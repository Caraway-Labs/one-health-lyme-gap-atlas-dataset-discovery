"""Explicit local DEV verification; importing and validating never connect.

Pricing evidence is supplied by the billing owner, not discovered or invented
by this runner. The parent enforces the process deadline independently of nodes.
"""

import argparse
import json
import multiprocessing
import os
import re
import subprocess
import uuid
from collections.abc import Callable, Mapping
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from langsmith import tracing_context
from pydantic import BaseModel, ConfigDict, Field

from .graph.budgets import RunProfile
from .graph.hosted import HostedConfig, build_hosted_graph
from .hosted_manual import bounded_input
from .observability import isolated_fixture_tracing

RUNTIME_CONNECTION = "ATLAS_DEV_DATASET_DISCOVERY_RUNTIME"
WAREHOUSE = "OH_LYME_DEV_INGEST_XS_WH"
DEADLINE_SECONDS = 300
STATEMENT_SECONDS = 30
STOP_SECONDS = 10
MODEL_RESERVE_USD = Decimal("0.12")


class PreflightBlocked(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CostEvidence(BaseModel):
    """Reviewed nonsecret billing evidence, never a credential/configuration file."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    account_locator: str = Field(pattern=r"^[A-Z0-9]{3,16}$")
    warehouse_hourly_usd: Decimal = Field(gt=0, allow_inf_nan=False)
    other_cost_reserve_usd: Decimal = Field(gt=0, allow_inf_nan=False)
    evidence_reference: str = Field(min_length=1, max_length=200)
    approved_total_usd: Decimal = Field(gt=0, le=1, allow_inf_nan=False)
    policy_verified_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def upper_exposure_usd(self) -> Decimal:
        # Includes shutdown grace, queued + running server statement ceilings,
        # auto-suspend tail and a conservative additional resume minimum.
        seconds = DEADLINE_SECONDS + STOP_SECONDS + 2 * STATEMENT_SECONDS + 60 + 60
        return (
            MODEL_RESERVE_USD
            + self.warehouse_hourly_usd * Decimal(seconds) / Decimal(3600)
            + self.other_cost_reserve_usd
        )

    def require_budget(self) -> None:
        reviewed = datetime.strptime(self.policy_verified_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        age = (datetime.now(UTC) - reviewed).total_seconds()
        if not 0 <= age <= 3600:
            raise PreflightBlocked("COST_EVIDENCE_REVIEW_EXPIRED")
        if self.upper_exposure_usd() > self.approved_total_usd:
            raise PreflightBlocked("ALL_IN_BUDGET_EXCEEDED")


def validate_local_configuration(values: Mapping[str, str]) -> HostedConfig:
    if not values.get("ATLAS_DD_DEV_OPENAI_API_KEY"):
        raise PreflightBlocked("EXISTING_MODEL_AUTH_UNAVAILABLE")
    if any(
        name.startswith(("OTEL_", "ARIZE_", "LANGSMITH_", "LANGCHAIN_")) and value
        for name, value in values.items()
    ):
        raise PreflightBlocked("EXPORTER_CONFIGURATION_PRESENT")
    config = HostedConfig.from_environment(values, named_runtime_pat=True)
    if not re.fullmatch(r"[A-Z0-9]{3,16}", config.snowflake_account.upper()):
        raise ValueError("local verification requires an explicit approved account locator")
    if config.profile != RunProfile.HOSTED_MANUAL:
        raise ValueError("local verification requires the bounded manual policy")
    if config.snowflake_warehouse != WAREHOUSE:
        raise ValueError("local verification requires the reviewed DEV warehouse")
    if config.snowflake_user != "OH_LYME_DEV_DATASET_DISCOVERY_SVC":
        raise ValueError("local verification requires the dedicated DEV service principal")
    return config


def verify_release_checkout(config: HostedConfig) -> None:
    root = Path(__file__).resolve().parents[2]
    prefix = ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root)]
    sha = subprocess.run(
        [*prefix, "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=5
    ).stdout.strip()
    dirty = subprocess.run(
        [*prefix, "status", "--porcelain"], capture_output=True, text=True, check=True, timeout=5
    ).stdout
    if sha != config.code_sha or dirty:
        raise PreflightBlocked("EXACT_CLEAN_RELEASE_CHECKOUT_REQUIRED")


def local_input(config: HostedConfig, run_id: str, trace_id: str) -> dict[str, Any]:
    state = bounded_input(
        config, run_id=run_id, trace_id=trace_id, host_session_id=f"sess_{trace_id}"
    )
    state["limits"] = state["limits"].model_copy(update={"retries_per_operation": 0})
    # Preserve reviewed graph profile while clearly attributing local execution.
    state["execution_key"] = f"local-verification:{run_id}"
    state["host_session_id"] = f"sess_local_{trace_id}"
    return dict(state)


def named_runtime_connect(config: HostedConfig) -> Any:
    import snowflake.connector

    connection = snowflake.connector.connect(
        connection_name=RUNTIME_CONNECTION,
        authenticator="PROGRAMMATIC_ACCESS_TOKEN",
        login_timeout=15,
        network_timeout=30,
        client_session_keep_alive=False,
        session_parameters={
            "STATEMENT_TIMEOUT_IN_SECONDS": STATEMENT_SECONDS,
            "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": STATEMENT_SECONDS,
            "ABORT_DETACHED_QUERY": True,
        },
    )
    try:
        # Metadata-only guard precedes the graph's identity check/business SQL.
        # No ALTER WAREHOUSE, grants, role switch or schema change.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT CURRENT_ACCOUNT(), CURRENT_USER(), CURRENT_ROLE(), "
                "CURRENT_DATABASE(), CURRENT_WAREHOUSE()",
                timeout=15,
            )
            identity = cursor.fetchone()
            if identity != (
                config.snowflake_account.upper(),
                config.snowflake_user,
                config.snowflake_role,
                config.snowflake_database,
                config.snowflake_warehouse,
            ):
                raise ValueError("runtime identity differs from reviewed DEV context")
            if cursor.fetchone() is not None:
                raise ValueError("ambiguous runtime identity")
            for parameter, expected in (
                ("STATEMENT_TIMEOUT_IN_SECONDS", str(STATEMENT_SECONDS)),
                ("STATEMENT_QUEUED_TIMEOUT_IN_SECONDS", str(STATEMENT_SECONDS)),
                ("ABORT_DETACHED_QUERY", "true"),
            ):
                cursor.execute(f"SHOW PARAMETERS LIKE '{parameter}' IN SESSION", timeout=15)
                setting = cursor.fetchone()
                if setting is None or str(setting[1]).lower() != expected:
                    raise ValueError("server timeout or detached-query guard unavailable")
            cursor.execute(f"SHOW WAREHOUSES LIKE '{WAREHOUSE}'", timeout=15)
            row = cursor.fetchone()
            if row is None or cursor.fetchone() is not None:
                raise ValueError("reviewed warehouse metadata unavailable")
            names = [str(column[0]).lower() for column in cursor.description]
            metadata = dict(zip(names, row, strict=True))
            if (
                metadata.get("name") != WAREHOUSE
                or metadata.get("size") != "X-Small"
                or metadata.get("resource_constraint") != "STANDARD_GEN_2"
                or int(metadata.get("auto_suspend", 0)) != 60
                or int(metadata.get("max_cluster_count", 0)) != 1
                or metadata.get("enable_query_acceleration") not in (False, "false", "FALSE")
            ):
                raise ValueError("warehouse policy differs from reviewed cost assumptions")
        return connection
    except BaseException:
        connection.close()
        raise


def _worker(send: Any, run_id: str, trace_id: str) -> None:
    try:
        config = validate_local_configuration(os.environ)
        verify_release_checkout(config)
        with (
            open(os.devnull, "w", encoding="utf-8") as discard,
            redirect_stdout(discard),
            redirect_stderr(discard),
            isolated_fixture_tracing(),
            tracing_context(enabled=False),
        ):
            result = build_hosted_graph(config, raw_connect=named_runtime_connect).invoke(
                local_input(config, run_id, trace_id), config={"recursion_limit": 100}
            )
        send.send(
            {
                "status": "FINISHED",
                "run_id": run_id,
                "code_sha": config.code_sha,
                "final_status": result.get("final_status"),
                "processed_count": result.get("processed_count", 0),
                "recommendation_version_ids": result.get(
                    "persisted_recommendation_version_ids", []
                ),
            }
        )
    except BaseException as error:
        send.send(
            {
                "status": "FAILED_UNKNOWN_DURABLE_STATUS",
                "run_id": run_id,
                "error_type": type(error).__name__,
            }
        )
    finally:
        send.close()


def _stop_worker(process: Any) -> None:
    process.terminate()
    process.join(STOP_SECONDS / 2)
    if process.is_alive():
        process.kill()
        process.join(STOP_SECONDS / 2)


def supervise(
    run_id: str,
    trace_id: str,
    *,
    deadline: float = DEADLINE_SECONDS,
    _worker_target: Callable[[Any, str, str], None] = _worker,
) -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_worker_target, args=(send, run_id, trace_id))
    try:
        process.start()
        send.close()
        process.join(deadline)
        if process.is_alive():
            _stop_worker(process)
            return {
                "status": "DEADLINE_UNKNOWN_DURABLE_STATUS",
                "run_id": run_id,
                "worker_stopped": not process.is_alive(),
            }
        try:
            if process.exitcode == 0 and receive.poll():
                return dict(receive.recv())
        except (EOFError, OSError):
            pass
        return {"status": "FAILED_UNKNOWN_DURABLE_STATUS", "run_id": run_id}
    finally:
        if process.pid is not None and process.is_alive():
            _stop_worker(process)
        receive.close()
        send.close()
        if process.pid is not None and not process.is_alive():
            process.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One explicitly authorized local DEV verification")
    parser.add_argument("--cost-evidence", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--no-export", action="store_true", required=True)
    parser.add_argument("--execute-authorized", action="store_true")
    args = parser.parse_args(argv)
    execution_started = False
    try:
        if not re.fullmatch(r"dd-hosted-manual-[0-9a-f]{32}", args.run_id):
            raise ValueError("invalid stable run identity")
        config = validate_local_configuration(os.environ)
        verify_release_checkout(config)
        try:
            cost = CostEvidence.model_validate_json(args.cost_evidence.read_text(encoding="utf-8"))
        except OSError as error:
            raise PreflightBlocked("COST_EVIDENCE_UNAVAILABLE") from error
        except ValueError as error:
            raise PreflightBlocked("COST_EVIDENCE_INVALID") from error
        cost.require_budget()
        if cost.account_locator != config.snowflake_account.upper():
            raise PreflightBlocked("BILLING_EVIDENCE_ACCOUNT_MISMATCH")
        if not args.execute_authorized:
            print(
                json.dumps(
                    {
                        "status": "OFFLINE_CONFIG_VALID",
                        "no_connections_opened": True,
                        "upper_exposure_usd": str(cost.upper_exposure_usd()),
                    }
                )
            )
            return 0
        execution_started = True
        result = supervise(args.run_id, uuid.uuid4().hex)
        print(json.dumps(result))
        return 0 if result.get("final_status") in {"COMPLETED", "BUDGET_STOPPED"} else 1
    except Exception as error:
        # Never print connector/provider messages, configuration or personal paths.
        if execution_started:
            print(json.dumps({"status": "FAILED_UNKNOWN_DURABLE_STATUS", "run_id": args.run_id}))
            return 1
        code = error.code if isinstance(error, PreflightBlocked) else "INVALID_LOCAL_CONFIGURATION"
        print(
            json.dumps({"status": "BLOCKED", "blocker": code, "error_type": type(error).__name__})
        )
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "INTERRUPTED_UNKNOWN_DURABLE_STATUS", "run_id": args.run_id}))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline enforcement of local deadline, authority, costs and recovery semantics."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langsmith import tracing_context
from langsmith.utils import tracing_is_enabled
from local_worker_fakes import abrupt_exit, blocking_operation, successful_worker
from test_hosted_graph import environment

from lyme_gap_atlas_dataset_discovery import local_verification as local
from lyme_gap_atlas_dataset_discovery.graph.hosted import HostedConfig, _snowflake_connect


def values() -> dict[str, str]:
    env = environment()
    env.pop("ATLAS_DD_DEV_SNOWFLAKE_PAT")
    env["SNOWFLAKE_USER"] = "OH_LYME_DEV_DATASET_DISCOVERY_SVC"
    env["SNOWFLAKE_ACCOUNT"] = "FIXTURE123"
    env["SNOWFLAKE_WAREHOUSE"] = local.WAREHOUSE
    return env


def evidence(**updates: Any) -> local.CostEvidence:
    return local.CostEvidence.model_validate(
        {
            "account_locator": "FIXTURE123",
            "warehouse_hourly_usd": "3",
            "other_cost_reserve_usd": "0.10",
            "evidence_reference": "test-only-billing-fixture",
            "approved_total_usd": "1",
            "policy_verified_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **updates,
        }
    )


def test_named_auth_does_not_require_or_capture_pat_and_hosted_stays_closed() -> None:
    config = local.validate_local_configuration(values())
    assert config.snowflake_pat == ""
    with pytest.raises(ValueError, match="required managed"):
        HostedConfig.from_environment(values())
    with pytest.raises(ValueError, match="PAT is unavailable"):
        _snowflake_connect(config)
    state = local.local_input(config, "dd-hosted-manual-" + "1" * 32, "2" * 32)
    assert state["limits"].retries_per_operation == 0
    assert state["limits"].model_calls == 4
    assert state["limits"].candidates == 1
    assert state["execution_key"].startswith("local-verification:")


@pytest.mark.parametrize(
    "change",
    [
        {"ATLAS_DD_DEV_OPENAI_API_KEY": ""},
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://example.invalid"},
        {"LANGSMITH_TRACING": "true"},
        {"SNOWFLAKE_ROLE": "ACCOUNTADMIN"},
        {"SNOWFLAKE_USER": "SOME_OTHER_SERVICE"},
        {"SNOWFLAKE_WAREHOUSE": "ANOTHER_WH"},
        {"SNOWFLAKE_ACCOUNT": "invalid-account"},
    ],
)
def test_missing_auth_export_or_changed_authority_fails_before_connect(
    change: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        local.validate_local_configuration({**values(), **change})


def test_cost_bound_includes_shutdown_queue_execution_idle_and_resume_tail() -> None:
    assert evidence().upper_exposure_usd() == Decimal("0.22") + Decimal(490) / Decimal(1200)
    evidence().require_budget()
    with pytest.raises(local.PreflightBlocked, match="BUDGET_EXCEEDED"):
        evidence(warehouse_hourly_usd="30").require_budget()
    old = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(local.PreflightBlocked, match="REVIEW_EXPIRED"):
        evidence(policy_verified_at=old).require_budget()
    for change in (
        {"warehouse_hourly_usd": None},
        {"warehouse_hourly_usd": "NaN"},
        {"other_cost_reserve_usd": "0"},
        {"approved_total_usd": "2"},
    ):
        with pytest.raises(ValueError):
            evidence(**change)


class Cursor:
    description = [
        (name,)
        for name in (
            "name",
            "size",
            "resource_constraint",
            "auto_suspend",
            "max_cluster_count",
            "enable_query_acceleration",
        )
    ]

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.rows: list[Any] = []

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.connection.cursor_closed = True

    def execute(self, sql: str, *, timeout: int) -> None:
        self.connection.executed.append(sql)
        assert timeout == 15
        if sql.startswith("SELECT CURRENT_ACCOUNT"):
            config = local.validate_local_configuration(values())
            self.rows = [
                (
                    config.snowflake_account.upper(),
                    config.snowflake_user,
                    config.snowflake_role,
                    config.snowflake_database,
                    config.snowflake_warehouse,
                )
            ]
            if self.connection.bad_identity:
                self.rows = [
                    (
                        "WRONG_ACCOUNT",
                        config.snowflake_user,
                        config.snowflake_role,
                        config.snowflake_database,
                        config.snowflake_warehouse,
                    )
                ]
        elif sql.startswith("SHOW PARAMETERS"):
            value = "true" if "ABORT_DETACHED" in sql else "30"
            self.rows = [("parameter", "0" if self.connection.bad_timeout else value)]
        else:
            self.rows = [
                (local.WAREHOUSE, "X-Small", "STANDARD_GEN_2", 60, 1, self.connection.bad_policy)
            ]

    def fetchone(self) -> Any:
        return self.rows.pop(0) if self.rows else None


class Connection:
    def __init__(
        self, *, bad_identity: bool = False, bad_timeout: bool = False, bad_policy: bool = False
    ) -> None:
        self.bad_identity = bad_identity
        self.bad_timeout = bad_timeout
        self.bad_policy = bad_policy
        self.closed = False
        self.cursor_closed = False
        self.executed: list[str] = []

    def cursor(self) -> Cursor:
        return Cursor(self)

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("failure", [None, "bad_identity", "bad_timeout", "bad_policy"])
def test_driver_named_profile_and_session_guards_fail_closed_with_cleanup(
    monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    connection = Connection(**({failure: True} if failure else {}))
    captured: dict[str, Any] = {}

    def connect(**kwargs: Any) -> Connection:
        captured.update(kwargs)
        return connection

    monkeypatch.setattr("snowflake.connector.connect", connect)
    config = local.validate_local_configuration(values())
    if failure:
        with pytest.raises(ValueError):
            local.named_runtime_connect(config)
        assert connection.closed
        if failure == "bad_identity":
            assert len(connection.executed) == 1
    else:
        assert local.named_runtime_connect(config) is connection
        assert not connection.closed
    assert connection.cursor_closed
    assert captured["connection_name"] == local.RUNTIME_CONNECTION
    assert captured["authenticator"] == "PROGRAMMATIC_ACCESS_TOKEN"
    assert "password" not in captured
    assert captured["session_parameters"]["STATEMENT_TIMEOUT_IN_SECONDS"] == 30
    assert captured["session_parameters"]["ABORT_DETACHED_QUERY"] is True


def test_cli_reports_precise_missing_auth_without_secret_or_connection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ATLAS_DD_DEV_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(local, "supervise", lambda *_args: pytest.fail("must not execute"))
    assert (
        local.main(
            [
                "--cost-evidence",
                "missing.json",
                "--run-id",
                "dd-hosted-manual-" + "1" * 32,
                "--no-export",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["blocker"] == "EXISTING_MODEL_AUTH_UNAVAILABLE"


def test_real_spawn_deadline_stops_blocked_operation_without_claiming_cancellation(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "started.txt"
    result = local.supervise(str(marker), "2" * 32, deadline=4, _worker_target=blocking_operation)
    assert marker.read_text(encoding="utf-8") == "entered blocking operation"
    assert result["status"] == "DEADLINE_UNKNOWN_DURABLE_STATUS"
    assert result["worker_stopped"] is True


def test_abrupt_worker_exit_reports_unknown_durable_status_with_stable_identity() -> None:
    run_id = "dd-hosted-manual-" + "1" * 32
    result = local.supervise(run_id, "2" * 32, deadline=10, _worker_target=abrupt_exit)
    assert result == {"status": "FAILED_UNKNOWN_DURABLE_STATUS", "run_id": run_id}


def test_successful_worker_returns_receipt_through_real_spawn_pipe() -> None:
    run_id = "dd-hosted-manual-" + "1" * 32
    result = local.supervise(run_id, "2" * 32, deadline=10, _worker_target=successful_worker)
    assert result == {"status": "FINISHED", "run_id": run_id, "final_status": "COMPLETED"}


def test_worker_masks_ambient_langsmith_and_returns_only_allowlisted_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = local.validate_local_configuration(values())
    receipts: list[dict[str, Any]] = []

    class FakeGraph:
        def invoke(self, state: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
            assert tracing_is_enabled() is False
            assert state["limits"].retries_per_operation == 0
            return {
                "final_status": "COMPLETED",
                "processed_count": 1,
                "private_candidate_payload": "NEVER_EXPORT_OR_REPORT",
            }

    class Sender:
        def send(self, receipt: dict[str, Any]) -> None:
            receipts.append(receipt)

        def close(self) -> None:
            pass

    monkeypatch.setattr(local, "validate_local_configuration", lambda _values: config)
    monkeypatch.setattr(local, "verify_release_checkout", lambda _config: None)
    monkeypatch.setattr(local, "build_hosted_graph", lambda *_args, **_kwargs: FakeGraph())
    with tracing_context(enabled=True):
        local._worker(Sender(), "dd-hosted-manual-" + "1" * 32, "2" * 32)
    assert receipts[0]["status"] == "FINISHED"
    assert "NEVER_EXPORT_OR_REPORT" not in json.dumps(receipts)


def test_operator_interrupt_stops_and_closes_worker_before_propagating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Process:
        pid: int | None = None
        alive = True
        joins = 0

        def start(self) -> None:
            self.pid = 1

        def join(self, _timeout: float) -> None:
            self.joins += 1
            if self.joins == 1:
                raise KeyboardInterrupt

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            events.append("terminate")

        def kill(self) -> None:
            events.append("kill")
            self.alive = False

        def close(self) -> None:
            events.append("close_process")

    class Pipe:
        def close(self) -> None:
            events.append("close_pipe")

    class Context:
        def Pipe(self, **_kwargs: Any) -> tuple[Pipe, Pipe]:
            return Pipe(), Pipe()

        def Process(self, **_kwargs: Any) -> Process:
            return Process()

    monkeypatch.setattr(local.multiprocessing, "get_context", lambda _method: Context())
    with pytest.raises(KeyboardInterrupt):
        local.supervise("dd-hosted-manual-" + "1" * 32, "2" * 32)
    assert events.index("terminate") < events.index("kill") < events.index("close_process")

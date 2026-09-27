"""One bounded, sequential SHADOW invocation inside Harness Runtime."""

import argparse
import json
import re
from typing import Any

from opentelemetry import trace

from lyme_gap_atlas_dataset_discovery.graph.budgets import PROFILE_DEFAULTS, RunProfile
from lyme_gap_atlas_dataset_discovery.graph.hosted import HostedConfig, build_hosted_graph
from lyme_gap_atlas_dataset_discovery.graph.state import DatasetDiscoveryState
from lyme_gap_atlas_dataset_discovery.model_policy import ModelPolicy
from lyme_gap_atlas_dataset_discovery.observability import (
    SERVICE_NAME,
    flush_dataset_discovery_tracing,
)

_RUN_ID = re.compile(r"^dd-shadow-[0-9a-f]{32}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_SESSION_ID = re.compile(
    r"^(?:sess_[A-Za-z0-9_-]{3,128}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def bounded_input(
    config: HostedConfig, *, run_id: str, trace_id: str, host_session_id: str
) -> DatasetDiscoveryState:
    """Pin a manually triggered three-candidate DEV shadow proof."""
    if config.profile != RunProfile.SHADOW:
        raise ValueError("shadow invocation requires SHADOW profile")
    if not _RUN_ID.fullmatch(run_id) or not _TRACE_ID.fullmatch(trace_id):
        raise ValueError("run or trace identity is invalid")
    if not _SESSION_ID.fullmatch(host_session_id):
        raise ValueError("host session identity is invalid")
    policy = ModelPolicy.luna_low_v1()
    limits = PROFILE_DEFAULTS[RunProfile.SHADOW].model_copy(
        update={
            "candidates": 3,
            "pages": 1,
            "graph_steps": 180,
            "model_calls": 12,
            "tool_calls": 60,
            "elapsed_seconds": 600,
            "input_tokens": 36_000,
            "output_tokens": 12_000,
            "evidence_bytes": 196_608,
            "retained_state_bytes": 262_144,
            "estimated_spend_cents": 36,
        }
    )
    return {
        "execution_key": f"shadow:{run_id}",
        "requested_run_id": run_id,
        "profile": RunProfile.SHADOW,
        "trigger_type": "MANUAL",
        "code_sha": config.code_sha,
        "spec_version": "dataset-discovery-v1",
        "graph_version": "dataset-discovery-sequential-v1",
        "config_fingerprint": policy.fingerprint,
        "search_fingerprint": config.search_fingerprint,
        "evidence_snapshot_id": config.snapshot_id,
        "model_provider": "OPENAI",
        "model_id": config.model_id,
        "model_fingerprint": config.model_fingerprint,
        "price_table_version": config.price_version,
        "prompt_versions": {"semantic": str(policy.document["prompt_version"])},
        "tool_versions": {},
        "eval_version": "dataset-discovery-domain-v1",
        "trace_id": trace_id,
        "host_session_id": host_session_id,
        "limits": limits,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one bounded hosted Dataset Discovery shadow")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--host-session-id", required=True)
    args = parser.parse_args(argv)
    try:
        config = HostedConfig.from_environment()
        state = bounded_input(
            config,
            run_id=args.run_id,
            trace_id=args.trace_id,
            host_session_id=args.host_session_id,
        )
        graph = build_hosted_graph(config)
        tracer = trace.get_tracer(SERVICE_NAME)
        with tracer.start_as_current_span(
            "dataset_discovery.run", record_exception=False, set_status_on_exception=False
        ) as span:
            span.set_attribute("atlas.discovery.requested_run_id", args.run_id)
            span.set_attribute("atlas.discovery.host_session_id", args.host_session_id)
            span.set_attribute("atlas.discovery.code_sha", config.code_sha)
            span.set_attribute("atlas.discovery.model_id", config.model_id)
            span.set_attribute("atlas.discovery.model_fingerprint", config.model_fingerprint)
            span.set_attribute("atlas.discovery.profile", RunProfile.SHADOW.value)
            span.set_attribute("atlas.discovery.environment", "DEV")
            actual_trace_id = f"{span.get_span_context().trace_id:032x}"
            result: dict[str, Any] = graph.invoke(state, config={"recursion_limit": 180})
            usage = result["usage"]
            for field in ("model_calls", "tool_calls", "input_tokens", "output_tokens"):
                span.set_attribute(f"atlas.discovery.{field}", getattr(usage, field))
            span.set_attribute("atlas.discovery.elapsed_seconds", usage.elapsed_seconds)
            span.set_attribute("atlas.discovery.processed_count", result.get("processed_count", 0))
            for field in ("final_status", "stop_reason"):
                value = result.get(field)
                if isinstance(value, str):
                    span.set_attribute(f"atlas.discovery.{field}", value)
        usage = result["usage"]
        print(
            json.dumps(
                {
                    "run_id": result.get("run_id", args.run_id),
                    "host_session_id": args.host_session_id,
                    "trace_id": args.trace_id,
                    "otel_trace_id": actual_trace_id,
                    "code_sha": config.code_sha,
                    "model_fingerprint": config.model_fingerprint,
                    "final_status": result.get("final_status"),
                    "stop_reason": result.get("stop_reason"),
                    "candidate_ids": result.get("seen_candidate_ids", ()),
                    "processed_count": result.get("processed_count", 0),
                    "outcomes": result.get("processed_candidate_outcomes", ()),
                    "recommendation_version_ids": result.get(
                        "persisted_recommendation_version_ids", ()
                    ),
                    "usage": usage.model_dump(mode="json"),
                    "bounded_error_types": result.get("bounded_errors", ()),
                }
            )
        )
        return 0 if result.get("final_status") not in {None, "FAILED", "CANCELLED"} else 1
    except Exception as error:
        print(json.dumps({"run_id": args.run_id, "error_type": type(error).__name__}))
        return 1
    finally:
        flush_dataset_discovery_tracing()


if __name__ == "__main__":
    raise SystemExit(main())

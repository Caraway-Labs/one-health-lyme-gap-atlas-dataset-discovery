"""Allowlisted graph telemetry; candidate text and model output never enter spans."""

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress

from lyme_gap_atlas_shared.observability import configure_tracing
from opentelemetry import trace

from .graph.state import DatasetDiscoveryState

SERVICE_NAME = "atlas-dataset-discovery"

_STRING_FIELDS = (
    "run_id",
    "requested_run_id",
    "code_sha",
    "spec_version",
    "graph_version",
    "config_fingerprint",
    "search_fingerprint",
    "evidence_snapshot_id",
    "model_provider",
    "model_id",
    "model_fingerprint",
    "price_table_version",
    "eval_version",
    "trace_id",
    "host_session_id",
    "stop_reason",
    "final_status",
    "candidate_outcome_reason",
)
_COUNT_FIELDS = ("pages_loaded", "processed_count")
_OPERATION_NAMES = {
    "tool": frozenset({"candidate_batch", "governed_status", "observations", "identity_links"}),
    "model": frozenset({"relationship", "classification", "rationale", "proposals"}),
    "persistence": frozenset(
        {"run_create", "recommendation_commit", "candidate_outcome", "run_finalize"}
    ),
    "review": frozenset({"list_pending", "show", "history", "decide"}),
    "handoff": frozenset({"submit", "status"}),
}


def configure_dataset_discovery_tracing() -> None:
    """Reuse the shared OTLP exporter with the configured hosted destination."""
    configure_tracing(SERVICE_NAME)


def flush_dataset_discovery_tracing() -> None:
    """Flush short-lived hosted spans with the pinned shared-python release."""
    with suppress(Exception):
        flush = getattr(trace.get_tracer_provider(), "force_flush", None)
        if callable(flush):
            flush()


@contextmanager
def traced_operation(kind: str, operation: str, phase: str, attempt: int) -> Iterator[None]:
    """Trace only fixed operation names and counters, never arguments or exception text."""
    if operation not in _OPERATION_NAMES.get(kind, ()):
        raise ValueError("unreviewed telemetry operation")
    allowed_phases = (
        {"send", "lookup"}
        if kind == "persistence"
        else {"request"}
        if kind in {"review", "handoff"}
        else {"attempt"}
    )
    if phase not in allowed_phases:
        raise ValueError("unreviewed telemetry phase")
    if attempt < 1:
        raise ValueError("telemetry attempt must be positive")
    tracer = trace.get_tracer(SERVICE_NAME)
    with tracer.start_as_current_span(
        f"dataset_discovery.{kind}.{operation}",
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("atlas.discovery.operation_kind", kind)
        span.set_attribute("atlas.discovery.operation_phase", phase)
        span.set_attribute("atlas.discovery.attempt", attempt)
        try:
            yield
        except Exception as error:
            span.set_attribute("atlas.discovery.outcome", "ERROR")
            span.set_attribute("atlas.discovery.error_type", type(error).__name__)
            raise
        else:
            span.set_attribute("atlas.discovery.outcome", "OK")


def traced_node(
    name: str, fn: Callable[[DatasetDiscoveryState], DatasetDiscoveryState]
) -> Callable[[DatasetDiscoveryState], DatasetDiscoveryState]:
    tracer = trace.get_tracer(SERVICE_NAME)

    def invoke(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        with tracer.start_as_current_span(
            f"dataset_discovery.{name}",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            for field in _STRING_FIELDS:
                value = state.get(field)
                if isinstance(value, str):
                    span.set_attribute(f"atlas.discovery.{field}", value)
            for versions_field in ("prompt_versions", "tool_versions"):
                versions = state.get(versions_field)
                if isinstance(versions, dict):
                    canonical = json.dumps(versions, sort_keys=True, separators=(",", ":"))
                    span.set_attribute(
                        f"atlas.discovery.{versions_field}_sha256",
                        hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                    )
            candidate_id = state.get("current_candidate_id")
            if isinstance(candidate_id, str):
                span.set_attribute(
                    "atlas.discovery.candidate_key_sha256",
                    hashlib.sha256(candidate_id.encode("utf-8")).hexdigest(),
                )
            for field in _COUNT_FIELDS:
                value = state.get(field)
                if isinstance(value, int):
                    span.set_attribute(f"atlas.discovery.{field}", value)
            profile = state.get("profile")
            if profile is not None:
                span.set_attribute("atlas.discovery.profile", profile.value)
            try:
                result = fn(state)
            except Exception as error:
                span.set_attribute("atlas.discovery.outcome", "ERROR")
                span.set_attribute("atlas.discovery.error_type", type(error).__name__)
                raise
            span.set_attribute("atlas.discovery.outcome", "OK")
            for field in ("stop_reason", "final_status", "candidate_outcome_reason"):
                value = result.get(field)
                if isinstance(value, str):
                    span.set_attribute(f"atlas.discovery.{field}", value)
            usage = result.get("usage")
            if usage is not None:
                for field in (
                    "graph_steps",
                    "model_calls",
                    "tool_calls",
                    "input_tokens",
                    "output_tokens",
                    "estimated_spend_cents",
                ):
                    span.set_attribute(f"atlas.discovery.{field}", getattr(usage, field))
            return result

    return invoke

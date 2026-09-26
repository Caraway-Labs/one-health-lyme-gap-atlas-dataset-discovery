"""Allowlisted graph telemetry; candidate text and model output never enter spans."""

from collections.abc import Callable

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
    "eval_version",
    "trace_id",
    "host_session_id",
    "stop_reason",
    "final_status",
    "candidate_outcome_reason",
)
_COUNT_FIELDS = ("pages_loaded", "processed_count")


def configure_dataset_discovery_tracing() -> None:
    """Reuse the shared OTLP exporter, including a Phoenix OTLP endpoint if configured."""
    configure_tracing(SERVICE_NAME)


def traced_node(
    name: str, fn: Callable[[DatasetDiscoveryState], DatasetDiscoveryState]
) -> Callable[[DatasetDiscoveryState], DatasetDiscoveryState]:
    tracer = trace.get_tracer(SERVICE_NAME)

    def invoke(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        with tracer.start_as_current_span(f"dataset_discovery.{name}") as span:
            for field in _STRING_FIELDS:
                value = state.get(field)
                if isinstance(value, str):
                    span.set_attribute(f"atlas.discovery.{field}", value)
            for field in _COUNT_FIELDS:
                value = state.get(field)
                if isinstance(value, int):
                    span.set_attribute(f"atlas.discovery.{field}", value)
            profile = state.get("profile")
            if profile is not None:
                span.set_attribute("atlas.discovery.profile", profile.value)
            result = fn(state)
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

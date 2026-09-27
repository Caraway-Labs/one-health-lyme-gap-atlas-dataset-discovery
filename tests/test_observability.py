"""Graph spans expose operational metadata only."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from lyme_gap_atlas_dataset_discovery.graph.budgets import BudgetUsage, RunProfile
from lyme_gap_atlas_dataset_discovery.graph.state import DatasetDiscoveryState
from lyme_gap_atlas_dataset_discovery.observability import traced_node, traced_operation


class CaptureSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, str | int] = {}

    def set_attribute(self, key: str, value: str | int) -> None:
        self.attributes[key] = value


class CaptureTracer:
    def __init__(self, span: CaptureSpan) -> None:
        self.span = span
        self.name: str | None = None
        self.options: dict[str, object] = {}

    @contextmanager
    def start_as_current_span(self, name: str, **options: object) -> Iterator[CaptureSpan]:
        self.name = name
        self.options = options
        yield self.span


def test_span_attributes_are_allowlisted(monkeypatch: Any) -> None:
    span = CaptureSpan()
    tracer = CaptureTracer(span)
    monkeypatch.setattr(
        "lyme_gap_atlas_dataset_discovery.observability.trace.get_tracer",
        lambda _: tracer,
    )
    state: DatasetDiscoveryState = {
        "run_id": "run-123",
        "profile": RunProfile.FIXTURE,
        "model_id": "model-version",
        "current_candidate_id": "private-candidate-id",
        "bounded_errors": ("private-error-payload",),
    }

    def node(_: DatasetDiscoveryState) -> DatasetDiscoveryState:
        return {
            "final_status": "BUDGET_STOPPED",
            "usage": BudgetUsage(model_calls=2, input_tokens=17),
        }

    traced_node("classify_and_score_candidate", node)(state)
    assert span.attributes["atlas.discovery.run_id"] == "run-123"
    assert span.attributes["atlas.discovery.final_status"] == "BUDGET_STOPPED"
    assert span.attributes["atlas.discovery.input_tokens"] == 17
    assert tracer.name == "dataset_discovery.classify_and_score_candidate"
    assert tracer.options == {"record_exception": False, "set_status_on_exception": False}
    assert "private-candidate-id" not in str(span.attributes)
    assert "private-error-payload" not in str(span.attributes)


def test_operation_spans_use_fixed_names_and_never_record_error_text(
    monkeypatch: Any,
) -> None:
    span = CaptureSpan()
    tracer = CaptureTracer(span)
    monkeypatch.setattr(
        "lyme_gap_atlas_dataset_discovery.observability.trace.get_tracer",
        lambda _: tracer,
    )
    with (
        pytest.raises(ValueError, match="sensitive candidate text"),
        traced_operation("model", "classification", "attempt", 2),
    ):
        raise ValueError("sensitive candidate text")
    assert tracer.name == "dataset_discovery.model.classification"
    assert tracer.options == {"record_exception": False, "set_status_on_exception": False}
    assert span.attributes["atlas.discovery.attempt"] == 2
    assert span.attributes["atlas.discovery.outcome"] == "ERROR"
    assert span.attributes["atlas.discovery.error_type"] == "ValueError"
    assert "sensitive candidate text" not in str(span.attributes)


def test_unreviewed_operation_name_is_rejected_before_span(monkeypatch: Any) -> None:
    span = CaptureSpan()
    tracer = CaptureTracer(span)
    monkeypatch.setattr(
        "lyme_gap_atlas_dataset_discovery.observability.trace.get_tracer",
        lambda _: tracer,
    )
    with (
        pytest.raises(ValueError, match="unreviewed telemetry operation"),
        traced_operation("tool", "candidate-secret", "attempt", 1),
    ):
        pass
    assert tracer.name is None


def test_node_failure_exports_error_type_without_message(monkeypatch: Any) -> None:
    span = CaptureSpan()
    tracer = CaptureTracer(span)
    monkeypatch.setattr(
        "lyme_gap_atlas_dataset_discovery.observability.trace.get_tracer",
        lambda _: tracer,
    )

    def fail(_: DatasetDiscoveryState) -> DatasetDiscoveryState:
        raise RuntimeError("private catalog content")

    with pytest.raises(RuntimeError, match="private catalog content"):
        traced_node("finalize_run", fail)({"run_id": "run-1"})
    assert span.attributes["atlas.discovery.outcome"] == "ERROR"
    assert span.attributes["atlas.discovery.error_type"] == "RuntimeError"
    assert "private catalog content" not in str(span.attributes)
    assert tracer.options == {"record_exception": False, "set_status_on_exception": False}

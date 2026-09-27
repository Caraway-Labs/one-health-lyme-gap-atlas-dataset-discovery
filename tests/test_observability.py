"""Graph spans expose operational metadata only."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from lyme_gap_atlas_dataset_discovery.graph.budgets import BudgetUsage, RunProfile
from lyme_gap_atlas_dataset_discovery.graph.state import DatasetDiscoveryState
from lyme_gap_atlas_dataset_discovery.observability import traced_node


class CaptureSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, str | int] = {}

    def set_attribute(self, key: str, value: str | int) -> None:
        self.attributes[key] = value


class CaptureTracer:
    def __init__(self, span: CaptureSpan) -> None:
        self.span = span

    @contextmanager
    def start_as_current_span(self, name: str) -> Iterator[CaptureSpan]:
        assert name == "dataset_discovery.classify_and_score_candidate"
        yield self.span


def test_span_attributes_are_allowlisted(monkeypatch: Any) -> None:
    span = CaptureSpan()
    monkeypatch.setattr(
        "lyme_gap_atlas_dataset_discovery.observability.trace.get_tracer",
        lambda _: CaptureTracer(span),
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
    assert "private-candidate-id" not in str(span.attributes)
    assert "private-error-payload" not in str(span.attributes)

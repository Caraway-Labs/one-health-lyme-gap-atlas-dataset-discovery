"""Independent offline gates; no credentials, exporter, model or database connection."""

import json
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from lyme_gap_atlas_dataset_discovery.domain.analysis import Classification
from lyme_gap_atlas_dataset_discovery.domain.handoff import HandoffFailureKind
from lyme_gap_atlas_dataset_discovery.evaluation import (
    evaluate_corpus,
    evaluate_receipt_case,
    load_corpus,
)
from lyme_gap_atlas_dataset_discovery.graph_evaluation import (
    TrajectoryCorpus,
)
from lyme_gap_atlas_dataset_discovery.graph_evaluation import (
    evaluate_case as evaluate_trajectory,
)
from lyme_gap_atlas_dataset_discovery.graph_evaluation import (
    evaluate_corpus as evaluate_trajectories,
)
from lyme_gap_atlas_dataset_discovery.handoff_evaluation import (
    evaluate_handoff_corpus,
    evaluate_recovery_case,
    load_handoff_corpus,
)
from lyme_gap_atlas_dataset_discovery.observability import traced_node

CORPORA = Path(__file__).resolve().parents[1] / "eval/corpora/v2"


def test_v2_receipt_gates_preserve_domain_cases_and_scope() -> None:
    corpus = load_corpus(CORPORA / "cases.json")
    report = evaluate_corpus(corpus)
    assert report.passed, report.model_dump_json(indent=2)
    assert len(report.case_results) == 27
    assert report.evaluation_scope == "DETERMINISTIC_FIXTURE"
    assert report.semantic_quality_accepted is False
    assert report.hosted_acceptance is False
    assert {case.phase for case in corpus.receipt_cases} == {"COMMIT", "LOOKUP"}
    assert corpus.receipt_request is not None
    invalid = next(case for case in corpus.receipt_cases if case.case_id == "commit-operation_key")
    mutation = invalid.model_copy(update={"expected_valid": True})
    assert (
        "receipt_validity_mismatch"
        in evaluate_receipt_case(mutation, corpus.receipt_request).failures
    )


def test_v2_classification_trajectory_gates_and_mutated_oracle() -> None:
    path = CORPORA / "graph_trajectories.json"
    report = evaluate_trajectories(path)
    assert report["passed"], report
    assert len(report["cases"]) == 21
    assert report["semantic_quality_accepted"] is False
    assert report["hosted_acceptance"] is False
    corpus = TrajectoryCorpus.model_validate_json(path.read_text())
    case = next(case for case in corpus.cases if case.id == "classification-blocked-then-valid")
    changed = case.model_copy(
        update={
            "candidates": (
                case.candidates[0].model_copy(
                    update={
                        "classification": Classification.RELEVANT,
                    }
                ),
                case.candidates[1],
            ),
        }
    )
    result = evaluate_trajectory(changed)
    assert result["passed"] is False
    assert {"nodes", "outcomes", "recommendations", "model_calls"} <= set(result["failures"])


def test_v2_handoff_recovery_oracles_reject_wrong_kind_status_and_write_count() -> None:
    corpus = load_handoff_corpus(CORPORA / "handoff.json")
    report = evaluate_handoff_corpus(corpus)
    assert report.passed, report.model_dump_json(indent=2)
    assert len(corpus.recovery_cases) == 6
    case = corpus.recovery_cases[0]
    for update, failure in [
        (
            {"expected_failure_kind": HandoffFailureKind.TERMINAL_FAILURE},
            "handoff_failure_kind_mismatch",
        ),
        ({"expected_status_present": False}, "handoff_recovery_status_mismatch"),
        ({"expected_write_calls": 2}, "handoff_write_count_mismatch"),
    ]:
        assert failure in evaluate_recovery_case(case.model_copy(update=update)).failures


def test_cross_family_duplicate_case_ids_are_rejected() -> None:
    corpus = load_corpus(CORPORA / "cases.json")
    collision = corpus.receipt_cases[0].model_copy(update={"case_id": corpus.cases[0].case_id})
    with pytest.raises(ValueError, match="duplicate evaluation"):
        evaluate_corpus(corpus.model_copy(update={"receipt_cases": (collision,)}))
    handoff = load_handoff_corpus(CORPORA / "handoff.json")
    collision = handoff.recovery_cases[0].model_copy(
        update={"case_id": handoff.handoff_cases[0].case_id}
    )
    with pytest.raises(ValueError, match="duplicate handoff"):
        evaluate_handoff_corpus(handoff.model_copy(update={"recovery_cases": (collision,)}))


def test_in_memory_graph_and_recovery_trace_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        "lyme_gap_atlas_dataset_discovery.observability.trace.get_tracer",
        provider.get_tracer,
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_dataset_discovery.observability.configure_dataset_discovery_tracing",
        lambda: None,
    )
    graph = TrajectoryCorpus.model_validate_json((CORPORA / "graph_trajectories.json").read_text())
    classification = next(
        case for case in graph.cases if case.id == "classification-blocked-then-valid"
    )
    lost_ack = next(case for case in graph.cases if case.id == "lost-ack-all-writes")
    recovery = load_handoff_corpus(CORPORA / "handoff.json").recovery_cases[0]
    with provider.get_tracer("offline-contract").start_as_current_span("offline.evaluation"):
        assert evaluate_trajectory(classification, corpus_version="v2")["passed"]
        assert evaluate_trajectory(lost_ack)["passed"]
        assert evaluate_recovery_case(recovery).passed
    spans = [span for span in exporter.get_finished_spans() if span.name != "offline.evaluation"]
    assert len({span.context.trace_id for span in spans}) == 1
    names = {span.name for span in spans}
    assert {
        "dataset_discovery.classify_and_score_candidate",
        "dataset_discovery.record_candidate_outcome",
        "dataset_discovery.persistence.recommendation_commit",
        "dataset_discovery.handoff.submit",
        "dataset_discovery.handoff.status",
    } <= names
    assert any(
        span.name == "dataset_discovery.persistence.recommendation_commit"
        and span.attributes.get("atlas.discovery.operation_phase") == "lookup"
        for span in spans
    )
    assert any(
        span.attributes.get("atlas.discovery.candidate_outcome_reason") == "BLOCKED"
        for span in spans
    )
    assert any(
        span.attributes.get("atlas.discovery.eval_version") == "graph-trajectories-v2"
        for span in spans
    )
    assert any(
        span.attributes.get("atlas.discovery.error_type") == "HandoffOperationError"
        for span in spans
    )
    assert all(not span.events for span in spans)
    serialized = json.dumps([dict(span.attributes or {}) for span in spans])
    for private in [
        "synthetic private transport marker",
        "Lyme surveillance",
        "Agency",
        "SYNTHETIC_REVIEWER",
        "fixture-semantic-v1",
        "fixture-reader-v1",
    ]:
        assert private not in serialized
    assert all(key.startswith("atlas.discovery.") for span in spans for key in span.attributes)
    provider.shutdown()


def test_trace_version_map_hashes_are_stable_and_values_are_not_exported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        "lyme_gap_atlas_dataset_discovery.observability.trace.get_tracer",
        provider.get_tracer,
    )
    node = traced_node("classify_and_score_candidate", lambda _: {})
    node(
        {
            "prompt_versions": {"second": "private-marker", "first": "v1"},
            "tool_versions": {"reader": "v1"},
        }
    )
    node(
        {
            "prompt_versions": {"first": "v1", "second": "private-marker"},
            "tool_versions": {"reader": "v1"},
        }
    )
    node(
        {
            "prompt_versions": {"first": "v2", "second": "private-marker"},
            "tool_versions": {"reader": "v2"},
        }
    )
    attributes = [dict(span.attributes or {}) for span in exporter.get_finished_spans()]
    assert attributes[0] == attributes[1]
    assert (
        attributes[0]["atlas.discovery.prompt_versions_sha256"]
        != attributes[2]["atlas.discovery.prompt_versions_sha256"]
    )
    assert (
        attributes[0]["atlas.discovery.tool_versions_sha256"]
        != attributes[2]["atlas.discovery.tool_versions_sha256"]
    )
    assert "private-marker" not in json.dumps(attributes)
    provider.shutdown()


def test_fixture_graph_never_configures_an_ambient_remote_exporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_configuration() -> None:
        raise AssertionError("offline evaluator configured remote tracing")

    monkeypatch.setattr(
        "lyme_gap_atlas_dataset_discovery.observability.configure_dataset_discovery_tracing",
        forbidden_configuration,
    )
    corpus = TrajectoryCorpus.model_validate_json((CORPORA / "graph_trajectories.json").read_text())
    assert evaluate_trajectory(corpus.cases[0])["passed"]

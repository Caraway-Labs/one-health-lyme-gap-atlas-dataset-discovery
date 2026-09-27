"""Corpus expectations are reviewed independently of evaluator code."""

from pathlib import Path

from lyme_gap_atlas_dataset_discovery.domain.ranking import rank_candidate
from lyme_gap_atlas_dataset_discovery.evaluation import evaluate_case, evaluate_corpus, load_corpus

CORPUS = Path(__file__).resolve().parents[1] / "eval/corpora/v1/cases.json"


def test_versioned_corpus_hard_gates() -> None:
    report = evaluate_corpus(load_corpus(CORPUS))
    assert report.passed, report.model_dump_json(indent=2)
    assert {case.slice for case in report.case_results} == {
        "priority_and_rights_ambiguity",
        "unsupported_observed_fact_hard_gate",
        "relationship",
        "high_priority_and_deterministic_order",
        "medium_priority_missing_penalty",
        "relationship_uncertainty_penalty",
        "priority_binding_hard_gate",
        "dimension_field_hard_gate",
        "observed_unknown_separation",
        "malicious_metadata_data_boundary",
        "mirror_priority_cap",
    }
    assert len(report.case_results) == 11


def test_hard_gate_expectation_mutations_are_detected() -> None:
    corpus = load_corpus(CORPUS)
    cases = {case.case_id: case for case in corpus.cases}
    binding = cases["ranking-cites-absent-fact"].model_copy(
        update={"expected_priority_binding_valid": True}
    )
    assert "priority_binding_mismatch" in evaluate_case(binding).failures
    dimension = cases["relevance-cites-only-publisher"].model_copy(
        update={"expected_dimension_valid": True}
    )
    assert "dimension_validity_mismatch" in evaluate_case(dimension).failures
    ordering = cases["fully-supported-high-priority"].model_copy(
        update={"expected_sort_key": (0, 0, 0, 0, "high", "v1")}
    )
    assert "priority_sort_key_mismatch" in evaluate_case(ordering).failures


def test_corpus_priority_order_is_deterministic_across_candidates() -> None:
    corpus = load_corpus(CORPUS)
    selected = {
        case.case_id: rank_candidate(case.priority_input)
        for case in corpus.cases
        if case.case_id
        in {
            "fully-supported-high-priority",
            "partially-supported-medium-priority",
            "mirror-capped-below-medium",
            "useful-unknown-rights",
            "unknown-relationship-penalty",
            "prompt-injection-is-catalog-data",
            "exact-duplicate-abstains",
        }
        and case.priority_input is not None
    }
    assert sorted(selected, key=lambda case_id: selected[case_id].sort_key) == [
        "fully-supported-high-priority",
        "partially-supported-medium-priority",
        "mirror-capped-below-medium",
        "useful-unknown-rights",
        "unknown-relationship-penalty",
        "prompt-injection-is-catalog-data",
        "exact-duplicate-abstains",
    ]

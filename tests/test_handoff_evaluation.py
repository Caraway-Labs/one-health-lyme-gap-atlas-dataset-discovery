"""The versioned handoff corpus exercises real fake review and handoff services."""

from pathlib import Path

import pytest

from lyme_gap_atlas_dataset_discovery.handoff_evaluation import (
    HandoffEvaluationCorpus,
    evaluate_handoff_corpus,
    load_handoff_corpus,
)

CORPUS = Path(__file__).resolve().parents[1] / "eval/corpora/v1/handoff.json"


def test_handoff_corpus_covers_hard_governance_slices() -> None:
    report = evaluate_handoff_corpus(load_handoff_corpus(CORPUS))
    assert report.passed, report.model_dump_json(indent=2)
    assert len(report.case_results) >= 10
    assert {
        "rights_unknown",
        "rights_ambiguity",
        "restricted_access",
        "controlled_access",
        "policy_prohibition",
        "relationship_and_existing_source",
        "review_authority",
        "evidence_integrity",
        "principal_authority",
    } <= {case.slice for case in report.case_results}


def test_handoff_corpus_rejects_duplicate_case_id() -> None:
    original = load_handoff_corpus(CORPUS)
    duplicate = HandoffEvaluationCorpus(
        corpus_version=original.corpus_version,
        handoff_cases=(original.handoff_cases[0], original.handoff_cases[0]),
    )
    with pytest.raises(ValueError, match="duplicate handoff"):
        evaluate_handoff_corpus(duplicate)

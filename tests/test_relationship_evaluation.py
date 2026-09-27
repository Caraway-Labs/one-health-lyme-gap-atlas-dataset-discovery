from pathlib import Path

import pytest

from lyme_gap_atlas_dataset_discovery.relationship_evaluation import (
    RelationshipCorpus,
    evaluate_corpus,
    load_corpus,
)

CORPUS = Path(__file__).resolve().parents[1] / "eval/corpora/v1/relationships.json"


def test_versioned_relationship_corpus() -> None:
    report = evaluate_corpus(load_corpus(CORPUS))
    assert report.passed, report.model_dump_json(indent=2)
    assert len(report.case_results) == 11
    assert {item.slice for item in report.case_results} >= {
        "governed_identity_precedence",
        "source_backed_version_link",
        "retained_content_link",
        "missing_link_evidence_hard_gate",
        "unknown_not_inferred",
    }


def test_duplicate_relationship_case_id_rejected() -> None:
    case = load_corpus(CORPUS).cases[0]
    with pytest.raises(ValueError, match="duplicate relationship case ID"):
        evaluate_corpus(RelationshipCorpus(corpus_version="test", cases=(case, case)))


def test_wrong_expected_relationship_fails() -> None:
    case = load_corpus(CORPUS).cases[0]
    bad = case.model_copy(update={"expected_relationship": "UNKNOWN"})
    report = evaluate_corpus(RelationshipCorpus(corpus_version="test", cases=(bad,)))
    assert not report.passed
    assert report.case_results[0].failures == ("relationship_mismatch",)

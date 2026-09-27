"""Corpus expectations are reviewed independently of evaluator code."""

from pathlib import Path

from lyme_gap_atlas_dataset_discovery.evaluation import evaluate_corpus, load_corpus

CORPUS = Path(__file__).resolve().parents[1] / "eval/corpora/v1/cases.json"


def test_versioned_corpus_hard_gates() -> None:
    report = evaluate_corpus(load_corpus(CORPUS))
    assert report.passed, report.model_dump_json(indent=2)
    assert {case.slice for case in report.case_results} == {
        "priority_and_rights_ambiguity",
        "unsupported_observed_fact_hard_gate",
        "relationship",
    }

"""Versioned, deterministic Dataset Discovery regression corpus runner."""

import json
import sys
from pathlib import Path

from pydantic import Field

from .domain.analysis import AvailableObservation, CandidateAnalysis, validate_analysis
from .domain.models import StrictModel
from .domain.ranking import PriorityBucket, PriorityInput, rank_candidate


class EvaluationCase(StrictModel):
    case_id: str = Field(min_length=1)
    slice: str = Field(min_length=1)
    analysis: CandidateAnalysis
    observations: tuple[AvailableObservation, ...]
    priority_input: PriorityInput | None = None
    expected_evidence_valid: bool
    expected_bucket: PriorityBucket | None = None
    expected_score: int | None = None
    expected_abstain_reason: str | None = None


class EvaluationCorpus(StrictModel):
    corpus_version: str = Field(min_length=1)
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)


class CaseResult(StrictModel):
    case_id: str
    slice: str
    passed: bool
    failures: tuple[str, ...]


class EvaluationReport(StrictModel):
    corpus_version: str
    passed: bool
    case_results: tuple[CaseResult, ...]


def load_corpus(path: Path) -> EvaluationCorpus:
    return EvaluationCorpus.model_validate(json.loads(path.read_text(encoding="utf-8")))


def evaluate_case(case: EvaluationCase) -> CaseResult:
    failures: list[str] = []
    try:
        validate_analysis(case.analysis, available_evidence=case.observations)
        evidence_valid = True
    except ValueError:
        evidence_valid = False
    if evidence_valid != case.expected_evidence_valid:
        failures.append("evidence_validity_mismatch")

    if case.priority_input is not None:
        if not evidence_valid:
            failures.append("ranking_attempted_without_valid_evidence")
        else:
            try:
                actual = rank_candidate(case.priority_input)
            except ValueError:
                failures.append("priority_input_invalid")
            else:
                if actual.bucket != case.expected_bucket:
                    failures.append("priority_bucket_mismatch")
                if actual.score != case.expected_score:
                    failures.append("priority_score_mismatch")
                if actual.abstain_reason != case.expected_abstain_reason:
                    failures.append("abstain_reason_mismatch")
    return CaseResult(
        case_id=case.case_id, slice=case.slice, passed=not failures, failures=tuple(failures)
    )


def evaluate_corpus(corpus: EvaluationCorpus) -> EvaluationReport:
    ids = [case.case_id for case in corpus.cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate evaluation case ID")
    results = tuple(evaluate_case(case) for case in corpus.cases)
    return EvaluationReport(
        corpus_version=corpus.corpus_version,
        passed=all(result.passed for result in results),
        case_results=results,
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m lyme_gap_atlas_dataset_discovery.evaluation CORPUS.json")
        return 2
    report = evaluate_corpus(load_corpus(Path(sys.argv[1])))
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

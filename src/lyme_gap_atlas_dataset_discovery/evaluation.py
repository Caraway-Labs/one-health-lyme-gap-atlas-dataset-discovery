"""Versioned, deterministic Dataset Discovery regression corpus runner."""

import json
import sys
from pathlib import Path

from pydantic import Field, model_validator

from .domain.analysis import AvailableObservation, CandidateAnalysis, validate_analysis
from .domain.models import StrictModel
from .domain.ranking import PriorityBucket, PriorityInput, rank_candidate
from .graph.planner import validate_dimension_evidence


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
    expected_priority_binding_valid: bool = True
    expected_dimension_valid: bool = True
    expected_sort_key: tuple[int, int, int, int, str, str] | None = None

    @model_validator(mode="after")
    def complete_expectations(self) -> "EvaluationCase":
        if self.priority_input is None:
            if (
                self.expected_bucket is not None
                or self.expected_score is not None
                or self.expected_abstain_reason is not None
                or self.expected_sort_key is not None
                or not self.expected_priority_binding_valid
                or not self.expected_dimension_valid
            ):
                raise ValueError("ranking expectation requires a priority input")
        elif (
            self.expected_priority_binding_valid
            and self.expected_dimension_valid
            and self.expected_evidence_valid
        ):
            if self.expected_bucket is None or self.expected_sort_key is None:
                raise ValueError("valid priority input requires bucket and deterministic sort key")
            if self.expected_bucket == PriorityBucket.ABSTAIN:
                if self.expected_abstain_reason is None or self.expected_score is not None:
                    raise ValueError("abstention needs reason and no score")
            elif self.expected_score is None or self.expected_abstain_reason is not None:
                raise ValueError("eligible priority needs score and no abstention reason")
        elif any(
            value is not None
            for value in (
                self.expected_bucket,
                self.expected_score,
                self.expected_abstain_reason,
                self.expected_sort_key,
            )
        ):
            raise ValueError("invalid evidence or binding cannot claim ranked output")
        return self


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
        observed_ids = {fact.evidence.observation_id for fact in case.analysis.observed_facts}
        binding_valid = (
            case.priority_input.resource_key == case.analysis.identity.resource_key
            and case.priority_input.observed_evidence_ids == observed_ids
        )
        if binding_valid != case.expected_priority_binding_valid:
            failures.append("priority_binding_mismatch")
        if evidence_valid and binding_valid:
            try:
                validate_dimension_evidence(case.analysis, case.priority_input.dimensions)
            except ValueError:
                dimension_valid = False
            else:
                dimension_valid = True
            if dimension_valid != case.expected_dimension_valid:
                failures.append("dimension_validity_mismatch")
            if dimension_valid:
                try:
                    actual = rank_candidate(case.priority_input)
                except ValueError:
                    failures.append("priority_input_invalid")
                    return CaseResult(
                        case_id=case.case_id,
                        slice=case.slice,
                        passed=False,
                        failures=tuple(failures),
                    )
                if actual.bucket != case.expected_bucket:
                    failures.append("priority_bucket_mismatch")
                if actual.score != case.expected_score:
                    failures.append("priority_score_mismatch")
                if actual.abstain_reason != case.expected_abstain_reason:
                    failures.append("abstain_reason_mismatch")
                if case.expected_sort_key is not None and actual.sort_key != case.expected_sort_key:
                    failures.append("priority_sort_key_mismatch")
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

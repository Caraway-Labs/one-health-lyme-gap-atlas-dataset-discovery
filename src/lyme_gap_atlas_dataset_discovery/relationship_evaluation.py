"""Versioned deterministic checks for source-backed relationship precedence."""

import json
import sys
from pathlib import Path

from pydantic import Field

from .domain.models import StrictModel
from .domain.ranking import Relationship
from .domain.relationships import RelationshipSignals, classify_relationship


class RelationshipCase(StrictModel):
    case_id: str = Field(min_length=1)
    slice: str = Field(min_length=1)
    signals: dict[str, object]
    expected_relationship: Relationship | None = None
    expected_basis: str | None = None
    expected_invalid: bool = False
    expected_error: str | None = None


class RelationshipCorpus(StrictModel):
    corpus_version: str = Field(min_length=1)
    cases: tuple[RelationshipCase, ...] = Field(min_length=1)


class RelationshipCaseResult(StrictModel):
    case_id: str
    slice: str
    passed: bool
    failures: tuple[str, ...]


class RelationshipReport(StrictModel):
    corpus_version: str
    passed: bool
    case_results: tuple[RelationshipCaseResult, ...]


def load_corpus(path: Path) -> RelationshipCorpus:
    return RelationshipCorpus.model_validate(json.loads(path.read_text(encoding="utf-8")))


def evaluate_corpus(corpus: RelationshipCorpus) -> RelationshipReport:
    ids = [case.case_id for case in corpus.cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate relationship case ID")
    results: list[RelationshipCaseResult] = []
    for case in corpus.cases:
        failures: list[str] = []
        try:
            actual = classify_relationship(RelationshipSignals.model_validate(case.signals))
        except ValueError as error:
            if not case.expected_invalid:
                failures.append("unexpected_invalid_signals")
            elif case.expected_error is not None and case.expected_error not in str(error):
                failures.append("wrong_invalid_reason")
        else:
            if case.expected_invalid:
                failures.append("invalid_signals_accepted")
            if actual.relationship != case.expected_relationship:
                failures.append("relationship_mismatch")
            if actual.basis != case.expected_basis:
                failures.append("basis_mismatch")
        results.append(
            RelationshipCaseResult(
                case_id=case.case_id,
                slice=case.slice,
                passed=not failures,
                failures=tuple(failures),
            )
        )
    return RelationshipReport(
        corpus_version=corpus.corpus_version,
        passed=all(result.passed for result in results),
        case_results=tuple(results),
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: python -m lyme_gap_atlas_dataset_discovery.relationship_evaluation CORPUS.json"
        )
        return 2
    report = evaluate_corpus(load_corpus(Path(sys.argv[1])))
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

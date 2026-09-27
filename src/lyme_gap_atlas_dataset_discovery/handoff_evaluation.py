"""Versioned, credential-free human review to governed handoff regression runner."""

import hashlib
import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .adapters.fake_handoff import FakeHumanHandoffClient
from .adapters.fake_review import FakeHumanReviewRepository
from .domain.handoff import AcquisitionBoundary, HandoffDisposition
from .domain.models import EvidenceRef, ObservedFact, StrictModel
from .domain.ranking import Dimension, PriorityBucket, RankingDimensions, Relationship
from .domain.review import ReviewDecision, ReviewDetail, ReviewEvidence, ReviewState
from .evaluation import CaseResult, EvaluationReport
from .handoff_service import HumanHandoffService
from .review_service import HumanReviewService


class HandoffEvaluationCase(StrictModel):
    case_id: str = Field(min_length=1)
    slice: str = Field(min_length=1)
    relationship: Relationship = Relationship.DISTINCT
    rights_assertion: Literal["RIGHTS_UNKNOWN", "RIGHTS_REVIEW_REQUIRED"] = "RIGHTS_UNKNOWN"
    reviewed_rights_state: str | None = None
    controlled_access: bool = False
    already_governed: bool = False
    review_decision: ReviewDecision = ReviewDecision.ACCEPT_FOR_INVESTIGATION
    use_stale_event: bool = False
    remove_evidence_after_review: bool = False
    handoff_principal_type: Literal["USER_PERSON", "USER_SERVICE", "TASK"] = "USER_PERSON"
    expected_disposition: HandoffDisposition | None = None
    expected_boundary: AcquisitionBoundary | None = None
    expected_error_type: Literal["PermissionError", "ValueError"] | None = None
    expected_error_contains: str | None = None

    @model_validator(mode="after")
    def exactly_one_expected_result(self) -> "HandoffEvaluationCase":
        success = self.expected_disposition is not None and self.expected_boundary is not None
        failure = self.expected_error_type is not None and bool(self.expected_error_contains)
        if success == failure:
            raise ValueError("handoff case needs exactly one success or failure expectation")
        return self


class HandoffEvaluationCorpus(StrictModel):
    corpus_version: str = Field(min_length=1)
    handoff_cases: tuple[HandoffEvaluationCase, ...] = Field(min_length=1)


def _detail(case: HandoffEvaluationCase, version_id: str) -> ReviewDetail:
    resource_key = f"synthetic:{case.case_id}"
    reference = EvidenceRef(
        observation_id=f"observation:{case.case_id}",
        catalog_dataset_id=f"dataset:{case.case_id}",
        catalog_resource_id=f"resource:{case.case_id}",
        observed_at="2026-01-01T00:00:00Z",
    )
    fact = ObservedFact(field="title", value="Synthetic candidate", evidence=reference)
    return ReviewDetail(
        recommendation_version_id=version_id,
        recommendation_id=hashlib.sha256(resource_key.encode()).hexdigest(),
        run_id="evaluation-run",
        resource_key=resource_key,
        catalog_dataset_id=reference.catalog_dataset_id,
        catalog_resource_id=reference.catalog_resource_id,
        evidence_snapshot_id="evaluation-snapshot",
        assertion_sha256="a" * 64,
        classification="RELEVANT",
        relationship_type=case.relationship,
        relationship_basis="synthetic reviewed fixture",
        rights_state=case.rights_assertion,
        observed_facts=(fact,),
        inferences=(),
        unknowns=(),
        dimensions=RankingDimensions(
            relevance=Dimension(value=2, supporting_observation_ids=(reference.observation_id,)),
            geography=Dimension(),
            variables=Dimension(),
            time=Dimension(),
            provenance=Dimension(),
            freshness=Dimension(),
            rights_clarity=Dimension(),
            complementarity=Dimension(),
        ),
        ranking_formula_version="recommendation-priority-v1",
        relationship_adjustment=0,
        missing_count=7,
        priority_score=0,
        priority_bucket=PriorityBucket.LOW,
        rank_in_run=1,
        rationale="Investigate this synthetic source",
        created_at="2026-01-01T00:00:00Z",
        review_state=ReviewState.PENDING,
        latest_review_event_id=None,
        evidence=(
            ReviewEvidence(
                recommendation_version_id=version_id,
                observation_id=reference.observation_id,
                catalog_dataset_id=reference.catalog_dataset_id,
                catalog_resource_id=reference.catalog_resource_id,
                field_name=fact.field,
                metadata_sha256=None,
                observed_at=reference.observed_at,
            ),
        ),
    )


def evaluate_handoff_case(case: HandoffEvaluationCase) -> CaseResult:
    failures: list[str] = []
    version_id = hashlib.sha256(f"handoff-eval-v1:{case.case_id}".encode()).hexdigest()
    detail = _detail(case, version_id)
    review = FakeHumanReviewRepository(details={version_id: detail})
    review_receipt = HumanReviewService(review).decide(
        version_id, case.review_decision, rationale="Corpus adjudication"
    )
    if case.remove_evidence_after_review:
        review.details[version_id] = detail.model_copy(update={"evidence": ()})
    review.principal_type = case.handoff_principal_type
    handoff = FakeHumanHandoffClient(
        review=review,
        controlled_access={detail.resource_key} if case.controlled_access else set(),
        already_governed={detail.resource_key} if case.already_governed else set(),
        reviewed_rights=(
            {detail.resource_key: case.reviewed_rights_state}
            if case.reviewed_rights_state is not None
            else {}
        ),
    )
    event_id = "f" * 64 if case.use_stale_event else review_receipt.review_event_id
    try:
        service = HumanHandoffService(handoff)
        receipt = service.submit(version_id, event_id)
    except (PermissionError, ValueError) as error:
        if case.expected_error_type != type(error).__name__ or (
            case.expected_error_contains is None or case.expected_error_contains not in str(error)
        ):
            failures.append("unexpected_handoff_rejection")
        if handoff.receipts:
            failures.append("rejected_handoff_created_receipt")
    else:
        if case.expected_disposition is None or case.expected_boundary is None:
            failures.append("unexpected_handoff_success")
        else:
            if receipt.disposition != case.expected_disposition:
                failures.append("handoff_disposition_mismatch")
            if receipt.acquisition_boundary != case.expected_boundary:
                failures.append("acquisition_boundary_mismatch")
            if receipt.relationship_type != case.relationship:
                failures.append("relationship_lost")
            if service.submit(version_id, event_id) != receipt or len(handoff.receipts) != 1:
                failures.append("handoff_replay_created_duplicate")
            status = service.status(version_id)
            if status is None or status.handoff_id != receipt.handoff_id:
                failures.append("handoff_status_mismatch")
    return CaseResult(
        case_id=case.case_id, slice=case.slice, passed=not failures, failures=tuple(failures)
    )


def load_handoff_corpus(path: Path) -> HandoffEvaluationCorpus:
    return HandoffEvaluationCorpus.model_validate(json.loads(path.read_text(encoding="utf-8")))


def evaluate_handoff_corpus(corpus: HandoffEvaluationCorpus) -> EvaluationReport:
    ids = [case.case_id for case in corpus.handoff_cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate handoff evaluation case ID")
    results = tuple(evaluate_handoff_case(case) for case in corpus.handoff_cases)
    return EvaluationReport(
        corpus_version=corpus.corpus_version,
        passed=all(result.passed for result in results),
        case_results=results,
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m lyme_gap_atlas_dataset_discovery.handoff_evaluation CORPUS.json")
        return 2
    report = evaluate_handoff_corpus(load_handoff_corpus(Path(sys.argv[1])))
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

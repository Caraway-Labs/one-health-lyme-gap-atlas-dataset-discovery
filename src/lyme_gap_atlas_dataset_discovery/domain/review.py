"""Human review of immutable recommendation versions, outside the graph."""

import hashlib
import json
from enum import StrEnum

from pydantic import Field, model_validator

from .models import Inference, ObservedFact, StrictModel, Unknown
from .ranking import PriorityBucket, RankingDimensions, Relationship


class ReviewDecision(StrEnum):
    ACCEPT_FOR_INVESTIGATION = "ACCEPT_FOR_INVESTIGATION"
    REJECT = "REJECT"
    MARK_DUPLICATE = "MARK_DUPLICATE"
    MARK_ALREADY_KNOWN = "MARK_ALREADY_KNOWN"
    REQUEST_MORE_INFORMATION = "REQUEST_MORE_INFORMATION"
    EXPIRE = "EXPIRE"


class ReviewState(StrEnum):
    PENDING = "PENDING"
    NEEDS_MORE_INFORMATION = "NEEDS_MORE_INFORMATION"
    ACCEPTED_FOR_INVESTIGATION = "ACCEPTED_FOR_INVESTIGATION"
    REJECTED = "REJECTED"
    DUPLICATE = "DUPLICATE"
    ALREADY_KNOWN = "ALREADY_KNOWN"
    EXPIRED = "EXPIRED"


DECISION_STATE = {
    ReviewDecision.ACCEPT_FOR_INVESTIGATION: ReviewState.ACCEPTED_FOR_INVESTIGATION,
    ReviewDecision.REJECT: ReviewState.REJECTED,
    ReviewDecision.MARK_DUPLICATE: ReviewState.DUPLICATE,
    ReviewDecision.MARK_ALREADY_KNOWN: ReviewState.ALREADY_KNOWN,
    ReviewDecision.REQUEST_MORE_INFORMATION: ReviewState.NEEDS_MORE_INFORMATION,
    ReviewDecision.EXPIRE: ReviewState.EXPIRED,
}


class ReviewCommand(StrictModel):
    command_key: str = Field(min_length=1, max_length=200)
    recommendation_version_id: str = Field(min_length=1, max_length=64)
    expected_prior_event_id: str | None = Field(default=None, max_length=64)
    decision: ReviewDecision
    rationale: str = Field(min_length=1, max_length=2000)
    conditions: tuple[str, ...] = Field(default=(), max_length=10)
    correction_of_event_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_conditions(self) -> "ReviewCommand":
        if any(not 1 <= len(condition) <= 300 for condition in self.conditions):
            raise ValueError("review conditions must be 1-300 characters")
        return self


def make_review_command(
    *,
    recommendation_version_id: str,
    decision: ReviewDecision,
    rationale: str,
    expected_prior_event_id: str | None = None,
    conditions: tuple[str, ...] = (),
    correction_of_event_id: str | None = None,
) -> ReviewCommand:
    """Same human command and prior version yield the same replay key."""
    payload = {
        "recommendation_version_id": recommendation_version_id,
        "expected_prior_event_id": expected_prior_event_id,
        "decision": decision.value,
        "rationale": rationale,
        "conditions": list(conditions),
        "correction_of_event_id": correction_of_event_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    command_key = "review:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ReviewCommand(
        command_key=command_key,
        recommendation_version_id=recommendation_version_id,
        expected_prior_event_id=expected_prior_event_id,
        decision=decision,
        rationale=rationale,
        conditions=conditions,
        correction_of_event_id=correction_of_event_id,
    )


class ReviewReceipt(StrictModel):
    review_event_id: str = Field(min_length=64, max_length=64)
    command_key: str
    recommendation_version_id: str
    prior_event_id: str | None
    prior_state: ReviewState
    new_state: ReviewState
    decision: ReviewDecision
    reviewer_user: str = Field(min_length=1)
    reviewer_role: str = Field(min_length=1)
    event_sequence: int = Field(ge=1)


class PendingRecommendation(StrictModel):
    recommendation_version_id: str
    recommendation_id: str
    run_id: str
    resource_key: str
    priority_bucket: PriorityBucket
    priority_score: int
    rank_in_run: int = Field(ge=1)
    rationale: str
    rights_state: str
    created_at: str
    review_state: ReviewState
    latest_review_event_id: str | None


class PendingPage(StrictModel):
    items: tuple[PendingRecommendation, ...]
    next_after_rank: int | None = None


class ReviewEvidence(StrictModel):
    recommendation_version_id: str
    observation_id: str
    catalog_dataset_id: str
    catalog_resource_id: str
    field_name: str
    metadata_sha256: str | None
    observed_at: str


class ReviewDetail(StrictModel):
    recommendation_version_id: str
    recommendation_id: str
    run_id: str
    resource_key: str
    catalog_dataset_id: str
    catalog_resource_id: str
    evidence_snapshot_id: str
    assertion_sha256: str
    classification: str
    relationship_type: Relationship
    relationship_basis: str
    rights_state: str
    observed_facts: tuple[ObservedFact, ...]
    inferences: tuple[Inference, ...]
    unknowns: tuple[Unknown, ...]
    dimensions: RankingDimensions
    ranking_formula_version: str
    relationship_adjustment: int
    missing_count: int
    priority_score: int
    priority_bucket: PriorityBucket
    rank_in_run: int
    rationale: str
    created_at: str
    review_state: ReviewState
    latest_review_event_id: str | None
    evidence: tuple[ReviewEvidence, ...] = ()


class ReviewHistoryEntry(StrictModel):
    review_event_id: str
    command_key: str
    event_sequence: int
    prior_event_id: str | None
    prior_state: ReviewState
    decision: ReviewDecision
    new_state: ReviewState
    rationale: str
    conditions: tuple[str, ...]
    reviewer_user: str
    reviewer_role: str
    reviewed_at: str
    correction_of_event_id: str | None


class ReviewHistoryPage(StrictModel):
    items: tuple[ReviewHistoryEntry, ...]
    next_after_sequence: int | None = None

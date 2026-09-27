"""Evidence-gated, deterministic v1 priority for investigation."""

from enum import StrEnum

from pydantic import Field, model_validator

from .models import StrictModel

FORMULA_VERSION = "recommendation-priority-v1"


class Relationship(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    ALREADY_KNOWN = "ALREADY_KNOWN"
    MIRROR = "MIRROR"
    ALTERNATE_DISTRIBUTION = "ALTERNATE_DISTRIBUTION"
    REVISION = "REVISION"
    SUPERSESSION = "SUPERSESSION"
    COMPLEMENTARY = "COMPLEMENTARY"
    DISTINCT = "DISTINCT"
    UNKNOWN = "UNKNOWN"


class PriorityBucket(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    ABSTAIN = "ABSTAIN"


class Dimension(StrictModel):
    value: int | None = Field(default=None, ge=0, le=2)
    supporting_observation_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def evidence_for_assertion(self) -> "Dimension":
        if self.value is not None and not self.supporting_observation_ids:
            raise ValueError("a scored dimension needs evidence")
        if self.value is None and self.supporting_observation_ids:
            raise ValueError("an unknown dimension cannot claim supporting evidence")
        return self


class RankingDimensions(StrictModel):
    relevance: Dimension
    geography: Dimension
    variables: Dimension
    time: Dimension
    provenance: Dimension
    freshness: Dimension
    rights_clarity: Dimension
    complementarity: Dimension


class PriorityInput(StrictModel):
    resource_key: str = Field(min_length=1)
    recommendation_version_id: str = Field(min_length=1)
    observed_evidence_ids: frozenset[str] = Field(min_length=1)
    relationship: Relationship
    dimensions: RankingDimensions
    identity_valid: bool = True
    evidence_sufficient: bool = True


class PriorityResult(StrictModel):
    formula_version: str = FORMULA_VERSION
    score: int | None
    bucket: PriorityBucket
    relationship_adjustment: int
    missing_count: int
    abstain_reason: str | None
    # For sorting eligible results ascending. Abstentions always follow eligible results.
    sort_key: tuple[int, int, int, int, str, str]


WEIGHTS = {
    "relevance": 5,
    "geography": 3,
    "variables": 4,
    "time": 2,
    "provenance": 3,
    "freshness": 1,
    "rights_clarity": 1,
    "complementarity": 2,
}


def rank_candidate(candidate: PriorityInput) -> PriorityResult:
    """Score validated evidence; this is never source approval or rights clearance."""
    dimensions = candidate.dimensions
    values = dimensions.model_dump()
    for dimension in values.values():
        if not set(dimension["supporting_observation_ids"]).issubset(
            candidate.observed_evidence_ids
        ):
            raise ValueError("dimension cites unavailable evidence")

    reason: str | None = None
    if not candidate.identity_valid:
        reason = "INVALID_IDENTITY"
    elif not candidate.evidence_sufficient or dimensions.relevance.value is None:
        reason = "INSUFFICIENT_EVIDENCE"
    elif candidate.relationship in {Relationship.EXACT_DUPLICATE, Relationship.ALREADY_KNOWN}:
        reason = candidate.relationship.value
    elif dimensions.relevance.value == 0:
        reason = "IRRELEVANT"

    if reason is not None:
        return PriorityResult(
            score=None,
            bucket=PriorityBucket.ABSTAIN,
            relationship_adjustment=0,
            missing_count=sum(item["value"] is None for item in values.values()),
            abstain_reason=reason,
            sort_key=(1, 3, 0, 0, candidate.resource_key, candidate.recommendation_version_id),
        )

    base = sum(WEIGHTS[name] * (dimension["value"] or 0) for name, dimension in values.items())
    missing_count = sum(dimension["value"] is None for dimension in values.values())
    adjustment = -2 if candidate.relationship == Relationship.UNKNOWN else 0
    score = max(0, base - 2 * missing_count + adjustment)
    bucket = (
        PriorityBucket.HIGH
        if score >= 30
        else PriorityBucket.MEDIUM
        if score >= 18
        else PriorityBucket.LOW
    )
    if candidate.relationship in {Relationship.MIRROR, Relationship.ALTERNATE_DISTRIBUTION}:
        bucket = PriorityBucket.LOW
    bucket_order = {
        PriorityBucket.HIGH: 0,
        PriorityBucket.MEDIUM: 1,
        PriorityBucket.LOW: 2,
    }[bucket]
    return PriorityResult(
        score=score,
        bucket=bucket,
        relationship_adjustment=adjustment,
        missing_count=missing_count,
        abstain_reason=None,
        sort_key=(
            0,
            bucket_order,
            -score,
            missing_count,
            candidate.resource_key,
            candidate.recommendation_version_id,
        ),
    )

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
    abstain_reason: str | None
    # For sorting eligible results ascending. Abstentions always follow eligible results.
    sort_key: tuple[int, int, int, int, int, int, str, str]


WEIGHTS = {
    "relevance": 5,
    "geography": 3,
    "variables": 3,
    "time": 2,
    "provenance": 2,
    "freshness": 1,
    "rights_clarity": 1,
    "complementarity": 2,
}

RELATIONSHIP_ADJUSTMENT = {
    Relationship.COMPLEMENTARY: 2,
    Relationship.REVISION: 1,
    Relationship.SUPERSESSION: 1,
    Relationship.DISTINCT: 0,
    Relationship.UNKNOWN: -2,
    Relationship.MIRROR: -4,
    Relationship.ALTERNATE_DISTRIBUTION: -4,
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
            abstain_reason=reason,
            sort_key=(
                1,
                0,
                0,
                0,
                0,
                0,
                candidate.resource_key,
                candidate.recommendation_version_id,
            ),
        )

    base = sum(WEIGHTS[name] * (dimension["value"] or 0) for name, dimension in values.items())
    adjustment = RELATIONSHIP_ADJUSTMENT[candidate.relationship]
    score = max(0, min(40, base + adjustment))
    bucket = (
        PriorityBucket.HIGH
        if score >= 28
        else PriorityBucket.MEDIUM
        if score >= 18
        else PriorityBucket.LOW
    )
    return PriorityResult(
        score=score,
        bucket=bucket,
        relationship_adjustment=adjustment,
        abstain_reason=None,
        sort_key=(
            0,
            -score,
            -(dimensions.relevance.value or 0),
            -(dimensions.geography.value or 0),
            -(dimensions.variables.value or 0),
            -(dimensions.time.value or 0),
            candidate.resource_key,
            candidate.recommendation_version_id,
        ),
    )

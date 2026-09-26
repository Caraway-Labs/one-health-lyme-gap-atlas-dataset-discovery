"""Atomic recommendation write contract, distinct from the durable receipt."""

from pydantic import Field, model_validator

from .analysis import CandidateAnalysis
from .models import RecommendationIdentity, StrictModel
from .ranking import PriorityInput, PriorityResult, rank_candidate
from .relationships import RelationshipResult


class RecommendationWrite(StrictModel):
    operation_key: str = Field(min_length=1)
    identity: RecommendationIdentity
    assertion_sha256: str = Field(min_length=64, max_length=64)
    analysis: CandidateAnalysis
    ranking_input: PriorityInput
    priority: PriorityResult
    relationship: RelationshipResult

    @model_validator(mode="after")
    def validate_bundle(self) -> "RecommendationWrite":
        if self.analysis.identity.resource_key != self.identity.resource_key:
            raise ValueError("recommendation bundle candidate identity mismatch")
        if self.ranking_input.resource_key != self.identity.resource_key:
            raise ValueError("ranking input candidate identity mismatch")
        if self.ranking_input.recommendation_version_id != self.identity.recommendation_version_id:
            raise ValueError("ranking input version identity mismatch")
        if self.ranking_input.relationship != self.relationship.relationship:
            raise ValueError("ranking relationship mismatch")
        if self.ranking_input.observed_evidence_ids != frozenset(self.evidence_observation_ids):
            raise ValueError("ranking evidence differs from validated observed facts")
        if not set(self.relationship.supporting_observation_ids).issubset(
            self.ranking_input.observed_evidence_ids
        ):
            raise ValueError("relationship cites unavailable observed evidence")
        if rank_candidate(self.ranking_input) != self.priority:
            raise ValueError("priority differs from the versioned deterministic formula")
        if self.priority.score is None:
            raise ValueError("abstaining candidate cannot be persisted as a recommendation")
        return self

    @property
    def evidence_observation_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({fact.evidence.observation_id for fact in self.analysis.observed_facts})
        )

    @property
    def proposal_ids(self) -> tuple[str, ...]:
        return tuple(
            f"{self.identity.recommendation_version_id}:proposal:{index}"
            for index, _ in enumerate(self.analysis.search_expansion_proposals)
        )

"""Atomic recommendation write contract, distinct from the durable receipt."""

import hashlib
import json
from enum import StrEnum

from pydantic import Field, model_validator

from .analysis import CandidateAnalysis, render_rationale
from .models import RecommendationIdentity, StrictModel
from .ranking import PriorityInput, PriorityResult, rank_candidate
from .relationships import RelationshipResult


class RightsEvidenceState(StrEnum):
    RIGHTS_UNKNOWN = "RIGHTS_UNKNOWN"
    RIGHTS_REVIEW_REQUIRED = "RIGHTS_REVIEW_REQUIRED"


def rights_evidence_state(analysis: CandidateAnalysis) -> RightsEvidenceState:
    """A metadata mention triggers investigation, never rights clearance."""
    return (
        RightsEvidenceState.RIGHTS_REVIEW_REQUIRED
        if any(fact.field in {"license", "access_level"} for fact in analysis.observed_facts)
        else RightsEvidenceState.RIGHTS_UNKNOWN
    )


def assertion_sha256(
    analysis: CandidateAnalysis,
    ranking_input: PriorityInput,
    priority: PriorityResult,
    relationship: RelationshipResult,
) -> str:
    ranking = ranking_input.model_dump(mode="json")
    ranking["observed_evidence_ids"] = sorted(ranking_input.observed_evidence_ids)
    payload = {
        "analysis": analysis.model_dump(mode="json"),
        "ranking_input": ranking,
        "priority": priority.model_dump(mode="json"),
        "relationship": relationship.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RecommendationWrite(StrictModel):
    operation_key: str = Field(min_length=1)
    identity: RecommendationIdentity
    evidence_snapshot_id: str = Field(min_length=1)
    rights_state: RightsEvidenceState
    assertion_sha256: str = Field(min_length=64, max_length=64)
    analysis: CandidateAnalysis
    ranking_input: PriorityInput
    priority: PriorityResult
    relationship: RelationshipResult
    rationale: str = Field(min_length=1, max_length=10000)

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
        if self.rights_state != rights_evidence_state(self.analysis):
            raise ValueError("rights evidence state is not derived from observed metadata")
        if self.assertion_sha256 != assertion_sha256(
            self.analysis, self.ranking_input, self.priority, self.relationship
        ):
            raise ValueError("assertion hash differs from canonical validated content")
        if self.rationale != render_rationale(self.analysis.rationale_claims):
            raise ValueError("rationale differs from validated structured claims")
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

"""Typed candidate analysis port used by separately testable graph nodes."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from lyme_gap_atlas_dataset_discovery.domain.analysis import (
    AvailableObservation,
    CandidateAnalysis,
    RationaleClaim,
    SearchExpansionProposal,
    validate_analysis,
)
from lyme_gap_atlas_dataset_discovery.domain.models import CandidateSummary, StrictModel
from lyme_gap_atlas_dataset_discovery.domain.ranking import RankingDimensions, Relationship
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult

_DIMENSION_FIELDS: dict[str, frozenset[str]] = {
    "relevance": frozenset({"title", "description"}),
    "geography": frozenset({"spatial", "description", "title"}),
    "variables": frozenset({"description", "title"}),
    "time": frozenset({"temporal", "issued", "modified", "description"}),
    "provenance": frozenset({"publisher", "description"}),
    "freshness": frozenset({"issued", "modified"}),
    "rights_clarity": frozenset({"license", "access_level"}),
    "complementarity": frozenset({"description", "title"}),
}


def validate_dimension_evidence(analysis: CandidateAnalysis, dimensions: RankingDimensions) -> None:
    """A semantic score must cite a validated fact in a relevant metadata field."""
    observed_fields_by_id: dict[str, set[str]] = {}
    for fact in analysis.observed_facts:
        observed_fields_by_id.setdefault(fact.evidence.observation_id, set()).add(fact.field)
    for name, dimension in dimensions.model_dump().items():
        citations = set(dimension["supporting_observation_ids"])
        if not citations.issubset(observed_fields_by_id):
            raise ValueError("semantic dimension cites no validated observed fact")
        if dimension["value"] is not None and not any(
            observed_fields_by_id[observation_id] & _DIMENSION_FIELDS[name]
            for observation_id in citations
        ):
            raise ValueError("semantic dimension cites unrelated metadata fields")


class ModelAllowance(StrictModel):
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_estimated_spend_cents: int = Field(ge=0)


class ModelUsage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    estimated_spend_cents: int = Field(default=0, ge=0)


class InvalidModelResponse(ValueError):
    """Provider billed tokens, but the semantic response cannot be accepted."""

    def __init__(
        self, usage: ModelUsage, reason: str = "model response failed strict content validation"
    ) -> None:
        super().__init__(reason)
        self.usage = usage


class UnmeteredModelResponse(RuntimeError):
    """A provider response without trustworthy usage cannot continue the run."""

    def __init__(self, usage: ModelUsage | None = None) -> None:
        super().__init__("model usage or identity is unavailable")
        self.usage = usage


@dataclass(frozen=True)
class PlannerResult[T]:
    value: T
    usage: ModelUsage = ModelUsage()


class CandidatePlanner(Protocol):
    def relationship(
        self,
        candidate: CandidateSummary,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[RelationshipResult]: ...

    def classify(
        self,
        candidate: CandidateSummary,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[tuple[CandidateAnalysis, RankingDimensions]]: ...

    def rationale(
        self,
        analysis: CandidateAnalysis,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[tuple[RationaleClaim, ...]]: ...

    def proposals(
        self,
        analysis: CandidateAnalysis,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[tuple[SearchExpansionProposal, ...]]: ...


@dataclass(frozen=True)
class FixturePlan:
    relationship: RelationshipResult
    analysis: CandidateAnalysis
    dimensions: RankingDimensions
    rationale: tuple[RationaleClaim, ...] = ()
    proposals: tuple[SearchExpansionProposal, ...] = ()


@dataclass
class FakeCandidatePlanner:
    """Explicit fixture answers; no title heuristics or network/model calls."""

    plans: dict[str, FixturePlan]

    def relationship(
        self,
        candidate: CandidateSummary,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[RelationshipResult]:
        return PlannerResult(self.plans[candidate.identity.resource_key].relationship)

    def classify(
        self,
        candidate: CandidateSummary,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[tuple[CandidateAnalysis, RankingDimensions]]:
        plan = self.plans[candidate.identity.resource_key]
        return PlannerResult((plan.analysis, plan.dimensions))

    def rationale(
        self,
        analysis: CandidateAnalysis,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[tuple[RationaleClaim, ...]]:
        return PlannerResult(self.plans[analysis.identity.resource_key].rationale)

    def proposals(
        self,
        analysis: CandidateAnalysis,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[tuple[SearchExpansionProposal, ...]]:
        return PlannerResult(self.plans[analysis.identity.resource_key].proposals)


@dataclass(frozen=True)
class ValidatedCandidatePlanner:
    """Constrain semantic proposals to evidence already supplied by the reader."""

    semantic: CandidatePlanner

    def relationship(
        self,
        candidate: CandidateSummary,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[RelationshipResult]:
        proposed = self.semantic.relationship(candidate, observations, allowance=allowance)
        result = proposed.value
        allowed = {Relationship.UNKNOWN, Relationship.DISTINCT, Relationship.COMPLEMENTARY}
        if result.relationship not in allowed:
            raise InvalidModelResponse(
                proposed.usage, "semantic model cannot assert an exact or governed relationship"
            )
        available = {item.reference.observation_id for item in observations}
        if not set(result.supporting_observation_ids).issubset(available):
            raise InvalidModelResponse(
                proposed.usage, "semantic relationship cites unavailable observation"
            )
        if (
            result.relationship == Relationship.COMPLEMENTARY
            and not result.supporting_observation_ids
        ):
            raise InvalidModelResponse(
                proposed.usage, "complementary relationship needs cited evidence"
            )
        safe = RelationshipResult(
            relationship=result.relationship,
            basis="SEMANTIC_INFERENCE",
            supporting_observation_ids=result.supporting_observation_ids,
        )
        return PlannerResult(safe, proposed.usage)

    def classify(
        self,
        candidate: CandidateSummary,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[tuple[CandidateAnalysis, RankingDimensions]]:
        proposed = self.semantic.classify(candidate, observations, allowance=allowance)
        analysis, dimensions = proposed.value
        try:
            if analysis.identity != candidate.identity:
                raise ValueError("semantic analysis changed canonical candidate identity")
            validate_analysis(analysis, available_evidence=observations)
            validate_dimension_evidence(analysis, dimensions)
        except ValueError as error:
            raise InvalidModelResponse(proposed.usage, str(error)) from None
        return proposed

    def rationale(
        self,
        analysis: CandidateAnalysis,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[tuple[RationaleClaim, ...]]:
        proposed = self.semantic.rationale(analysis, observations, allowance=allowance)
        try:
            validate_analysis(
                analysis.model_copy(update={"rationale_claims": proposed.value}),
                available_evidence=observations,
            )
        except ValueError as error:
            raise InvalidModelResponse(proposed.usage, str(error)) from None
        return proposed

    def proposals(
        self,
        analysis: CandidateAnalysis,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[tuple[SearchExpansionProposal, ...]]:
        proposed = self.semantic.proposals(analysis, observations, allowance=allowance)
        try:
            validate_analysis(
                analysis.model_copy(update={"search_expansion_proposals": proposed.value}),
                available_evidence=observations,
            )
        except ValueError as error:
            raise InvalidModelResponse(proposed.usage, str(error)) from None
        return proposed

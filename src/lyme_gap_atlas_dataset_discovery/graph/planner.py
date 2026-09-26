"""Typed candidate analysis port used by separately testable graph nodes."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from lyme_gap_atlas_dataset_discovery.domain.analysis import (
    AvailableObservation,
    CandidateAnalysis,
    RationaleClaim,
    SearchExpansionProposal,
)
from lyme_gap_atlas_dataset_discovery.domain.models import CandidateSummary, StrictModel
from lyme_gap_atlas_dataset_discovery.domain.ranking import RankingDimensions
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult


class ModelAllowance(StrictModel):
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_estimated_spend_cents: int = Field(ge=0)


class ModelUsage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_spend_cents: int = Field(default=0, ge=0)


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
        self, analysis: CandidateAnalysis, *, allowance: ModelAllowance
    ) -> PlannerResult[tuple[RationaleClaim, ...]]: ...

    def proposals(
        self, analysis: CandidateAnalysis, *, allowance: ModelAllowance
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
        self, analysis: CandidateAnalysis, *, allowance: ModelAllowance
    ) -> PlannerResult[tuple[RationaleClaim, ...]]:
        return PlannerResult(self.plans[analysis.identity.resource_key].rationale)

    def proposals(
        self, analysis: CandidateAnalysis, *, allowance: ModelAllowance
    ) -> PlannerResult[tuple[SearchExpansionProposal, ...]]:
        return PlannerResult(self.plans[analysis.identity.resource_key].proposals)

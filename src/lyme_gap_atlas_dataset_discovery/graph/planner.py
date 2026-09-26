"""Typed candidate analysis port used by separately testable graph nodes."""

from dataclasses import dataclass
from typing import Protocol

from lyme_gap_atlas_dataset_discovery.domain.analysis import (
    AvailableObservation,
    CandidateAnalysis,
    RationaleClaim,
    SearchExpansionProposal,
)
from lyme_gap_atlas_dataset_discovery.domain.models import CandidateSummary
from lyme_gap_atlas_dataset_discovery.domain.ranking import RankingDimensions
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult


class CandidatePlanner(Protocol):
    def relationship(
        self, candidate: CandidateSummary, observations: tuple[AvailableObservation, ...]
    ) -> RelationshipResult: ...

    def classify(
        self, candidate: CandidateSummary, observations: tuple[AvailableObservation, ...]
    ) -> tuple[CandidateAnalysis, RankingDimensions]: ...

    def rationale(self, analysis: CandidateAnalysis) -> tuple[RationaleClaim, ...]: ...

    def proposals(self, analysis: CandidateAnalysis) -> tuple[SearchExpansionProposal, ...]: ...


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
        self, candidate: CandidateSummary, observations: tuple[AvailableObservation, ...]
    ) -> RelationshipResult:
        return self.plans[candidate.identity.resource_key].relationship

    def classify(
        self, candidate: CandidateSummary, observations: tuple[AvailableObservation, ...]
    ) -> tuple[CandidateAnalysis, RankingDimensions]:
        plan = self.plans[candidate.identity.resource_key]
        return plan.analysis, plan.dimensions

    def rationale(self, analysis: CandidateAnalysis) -> tuple[RationaleClaim, ...]:
        return self.plans[analysis.identity.resource_key].rationale

    def proposals(self, analysis: CandidateAnalysis) -> tuple[SearchExpansionProposal, ...]:
        return self.plans[analysis.identity.resource_key].proposals

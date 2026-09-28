"""Typed candidate analysis port used by separately testable graph nodes."""

from dataclasses import dataclass, field, replace
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
    "relevance": frozenset({"title", "description", "keywords", "resource_title"}),
    "geography": frozenset({"spatial", "description", "title", "keywords"}),
    "variables": frozenset({"description", "title", "keywords"}),
    "time": frozenset({"temporal", "issued", "modified", "description"}),
    "provenance": frozenset({"publisher", "description"}),
    "freshness": frozenset({"issued", "modified"}),
    "rights_clarity": frozenset({"license", "access_level"}),
    "complementarity": frozenset({"description", "title", "resource_title"}),
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
    diagnostic: "ModelDiagnostic | None" = None


@dataclass(frozen=True)
class ModelDiagnostic:
    """Safe, bounded facts about one semantic invocation, never raw model content."""

    task_type: str
    model_call_attempted: bool
    model_call_succeeded_transport: bool
    structured_parse_succeeded: bool
    validation_stage: str
    validation_error_code: str | None
    validation_field: str | None
    validator_name: str
    validator_version: str
    response_schema_version: str
    response_fingerprint: str | None = None
    provider_response_status: str | None = None
    provider_incomplete_reason: str | None = None
    provider_error_code: str | None = None
    provider_response_id_hash: str | None = None
    parsed_analysis: CandidateAnalysis | None = field(default=None, repr=False)
    parsed_dimensions: RankingDimensions | None = field(default=None, repr=False)


class ModelTransportFailure(ConnectionError):
    """A semantic provider call was attempted but no response was received."""

    def __init__(self, diagnostic: ModelDiagnostic) -> None:
        super().__init__("semantic provider transport failed")
        self.diagnostic = diagnostic


class InvalidModelResponse(ValueError):
    """Provider billed tokens, but the semantic response cannot be accepted."""

    def __init__(
        self, usage: ModelUsage, reason: str = "model response failed strict content validation"
    ) -> None:
        super().__init__(reason)
        self.usage = usage
        self.diagnostic = usage.diagnostic


_EVIDENCE_ERRORS = {
    "relationship authority violation": "RELATIONSHIP_AUTHORITY_VIOLATION",
    "semantic relationship cites unavailable observation": "UNKNOWN_EVIDENCE_ID",
    "complementary relationship needs cited evidence": "MISSING_EVIDENCE_CITATION",
    "semantic analysis changed canonical candidate identity": "CANDIDATE_IDENTITY_MISMATCH",
    "ambiguous duplicate observation ID": "AMBIGUOUS_EVIDENCE_ID",
    "observed fact lacks an exact retained evidence reference": "UNKNOWN_EVIDENCE_ID",
    "observed fact value differs from retained metadata": "UNSUPPORTED_OBSERVED_FACT",
    "observed fact belongs to a different candidate": "CROSS_CANDIDATE_EVIDENCE",
    "field cannot be both observed and unknown": "CONFLICTING_EVIDENCE_STATE",
    "inference cites no observed fact": "MISSING_EVIDENCE_CITATION",
    "rationale assertion needs observed support": "MISSING_EVIDENCE_CITATION",
    "unknown claim cannot claim observation support": "UNSUPPORTED_RATIONALE_CLAIM",
    "unknown rationale differs from recorded unknown": "UNSUPPORTED_RATIONALE_CLAIM",
    "observed rationale differs from validated fact": "UNSUPPORTED_RATIONALE_CLAIM",
    "inferred rationale differs from recorded inference": "UNSUPPORTED_RATIONALE_CLAIM",
    "search proposal cites no observed fact": "MISSING_EVIDENCE_CITATION",
    "semantic dimension cites no validated observed fact": "UNKNOWN_EVIDENCE_ID",
    "semantic dimension cites unrelated metadata fields": "UNSUPPORTED_DIMENSION_EVIDENCE",
}


def _rejected_usage(
    usage: ModelUsage,
    error: ValueError,
    *,
    stage: str,
    analysis: CandidateAnalysis | None = None,
    dimensions: RankingDimensions | None = None,
) -> ModelUsage:
    diagnostic = usage.diagnostic
    if diagnostic is None:
        return usage
    return usage.model_copy(
        update={
            "diagnostic": replace(
                diagnostic,
                validation_stage=stage,
                validation_error_code=_EVIDENCE_ERRORS.get(str(error), "OTHER_VALIDATION_FAILURE"),
                validation_field=(
                    "dimensions"
                    if "dimension" in str(error)
                    else "rationale_claims"
                    if stage == "RATIONALE_VALIDATION"
                    else "search_expansion_proposals"
                    if stage == "PROPOSAL_VALIDATION"
                    else "observed_facts"
                    if "observed fact" in str(error)
                    else None
                ),
                validator_name="ValidatedCandidatePlanner",
                parsed_analysis=analysis,
                parsed_dimensions=dimensions,
            )
        }
    )


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
                _rejected_usage(
                    proposed.usage,
                    ValueError("relationship authority violation"),
                    stage="SEMANTIC_VALIDATION",
                ),
                "semantic model cannot assert an exact or governed relationship",
            )
        available = {item.reference.observation_id for item in observations}
        if not set(result.supporting_observation_ids).issubset(available):
            raise InvalidModelResponse(
                _rejected_usage(
                    proposed.usage,
                    ValueError("semantic relationship cites unavailable observation"),
                    stage="EVIDENCE_VALIDATION",
                ),
                "semantic relationship cites unavailable observation",
            )
        if (
            result.relationship == Relationship.COMPLEMENTARY
            and not result.supporting_observation_ids
        ):
            raise InvalidModelResponse(
                _rejected_usage(
                    proposed.usage,
                    ValueError("complementary relationship needs cited evidence"),
                    stage="EVIDENCE_VALIDATION",
                ),
                "complementary relationship needs cited evidence",
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
            raise InvalidModelResponse(
                _rejected_usage(
                    proposed.usage,
                    error,
                    stage="EVIDENCE_VALIDATION",
                    analysis=analysis,
                    dimensions=dimensions,
                ),
                str(error),
            ) from None
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
            raise InvalidModelResponse(
                _rejected_usage(
                    proposed.usage, error, stage="RATIONALE_VALIDATION", analysis=analysis
                ),
                str(error),
            ) from None
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
            raise InvalidModelResponse(
                _rejected_usage(
                    proposed.usage, error, stage="PROPOSAL_VALIDATION", analysis=analysis
                ),
                str(error),
            ) from None
        return proposed

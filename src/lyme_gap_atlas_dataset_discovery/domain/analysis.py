"""Validate candidate assertions against bounded, retained catalog evidence."""

from enum import StrEnum

from pydantic import Field

from .models import CandidateIdentity, EvidenceRef, Inference, ObservedFact, StrictModel, Unknown


class Classification(StrEnum):
    RELEVANT = "RELEVANT"
    POSSIBLY_RELEVANT = "POSSIBLY_RELEVANT"
    IRRELEVANT = "IRRELEVANT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    BLOCKED = "BLOCKED"


class RationaleClaim(StrictModel):
    field: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=500)
    kind: str = Field(pattern="^(OBSERVED|INFERRED|UNKNOWN)$")
    supporting_observation_ids: tuple[str, ...] = ()


class SearchExpansionProposal(StrictModel):
    proposed_term: str = Field(min_length=1, max_length=120)
    catalog_scope: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=500)
    supporting_observation_ids: tuple[str, ...] = Field(min_length=1)


class AvailableObservation(StrictModel):
    """Allowlisted, retained metadata fields supplied by a bounded reader."""

    reference: EvidenceRef
    field_values: dict[str, str]


class CandidateAnalysis(StrictModel):
    identity: CandidateIdentity
    classification: Classification
    observed_facts: tuple[ObservedFact, ...] = ()
    inferences: tuple[Inference, ...] = ()
    unknowns: tuple[Unknown, ...] = ()
    rationale_claims: tuple[RationaleClaim, ...] = ()
    search_expansion_proposals: tuple[SearchExpansionProposal, ...] = Field(
        default=(), max_length=10
    )


def validate_analysis(
    analysis: CandidateAnalysis, *, available_evidence: tuple[AvailableObservation, ...]
) -> None:
    """Fail closed on fabricated observations, unsupported claims, or conflicts."""
    available = {item.reference.observation_id: item for item in available_evidence}
    if len(available) != len(available_evidence):
        raise ValueError("ambiguous duplicate observation ID")

    observed_ids: set[str] = set()
    observed_fields: set[str] = set()
    observed_claims: set[tuple[str, str, str]] = set()
    for fact in analysis.observed_facts:
        observation = available.get(fact.evidence.observation_id)
        if observation is None or observation.reference != fact.evidence:
            raise ValueError("observed fact lacks an exact retained evidence reference")
        if observation.field_values.get(fact.field) != fact.value:
            raise ValueError("observed fact value differs from retained metadata")
        ref = observation.reference
        if (
            ref.catalog_dataset_id != analysis.identity.catalog_dataset_id
            or ref.catalog_resource_id != analysis.identity.catalog_resource_id
        ):
            raise ValueError("observed fact belongs to a different candidate")
        observed_ids.add(ref.observation_id)
        observed_fields.add(fact.field)
        observed_claims.add((fact.field, fact.value, ref.observation_id))

    unknown_fields = {item.field for item in analysis.unknowns}
    if observed_fields & unknown_fields:
        raise ValueError("field cannot be both observed and unknown")

    for inference in analysis.inferences:
        if not set(inference.supporting_observation_ids).issubset(observed_ids):
            raise ValueError("inference cites no observed fact")

    for claim in analysis.rationale_claims:
        citations = set(claim.supporting_observation_ids)
        if claim.kind == "UNKNOWN":
            if citations:
                raise ValueError("unknown claim cannot claim observation support")
            if not any(
                item.field == claim.field and item.reason == claim.text
                for item in analysis.unknowns
            ):
                raise ValueError("unknown rationale differs from recorded unknown")
        elif not citations or not citations.issubset(observed_ids):
            raise ValueError("rationale assertion needs observed support")
        elif claim.kind == "OBSERVED" and not all(
            (claim.field, claim.text, citation) in observed_claims for citation in citations
        ):
            raise ValueError("observed rationale differs from validated fact")
        elif claim.kind == "INFERRED" and not any(
            item.field == claim.field
            and item.value == claim.text
            and citations.issubset(item.supporting_observation_ids)
            for item in analysis.inferences
        ):
            raise ValueError("inferred rationale differs from recorded inference")

    for proposal in analysis.search_expansion_proposals:
        if not set(proposal.supporting_observation_ids).issubset(observed_ids):
            raise ValueError("search proposal cites no observed fact")


def render_rationale(claims: tuple[RationaleClaim, ...]) -> str:
    """Render validated structured claims without adding model-authored claims."""
    lines = []
    for claim in claims:
        refs = ", ".join(sorted(claim.supporting_observation_ids))
        citation = f" [observations: {refs}]" if refs else ""
        lines.append(f"- {claim.kind.lower()} {claim.field}: {claim.text}{citation}")
    return "\n".join(lines)

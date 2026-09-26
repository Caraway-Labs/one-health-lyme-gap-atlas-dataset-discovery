"""Versioned, source-attributable domain values for the v1 contract."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceKind(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class EvidenceRef(StrictModel):
    observation_id: str = Field(min_length=1)
    catalog_dataset_id: str = Field(min_length=1)
    catalog_resource_id: str = Field(min_length=1)
    metadata_sha256: str | None = None
    observed_at: str


class ObservedFact(StrictModel):
    field: str = Field(min_length=1)
    value: str = Field(min_length=1)
    evidence: EvidenceRef


class Inference(StrictModel):
    field: str = Field(min_length=1)
    value: str = Field(min_length=1)
    supporting_observation_ids: tuple[str, ...] = Field(min_length=1)
    uncertainty: str = Field(min_length=1)


class Unknown(StrictModel):
    field: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CandidateIdentity(StrictModel):
    resource_key: str = Field(min_length=1)
    catalog_dataset_id: str = Field(min_length=1)
    catalog_resource_id: str = Field(min_length=1)


class CandidateSummary(StrictModel):
    identity: CandidateIdentity
    title: str | None = None
    publisher: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()


class CandidatePage(StrictModel):
    candidates: tuple[CandidateSummary, ...]
    next_cursor: str | None = None


class DiscoveryContext(StrictModel):
    discovery_run_id: str = Field(min_length=1)
    search_fingerprint: str = Field(min_length=64, max_length=64)
    completed_at: str = Field(min_length=1)
    status: str = Field(pattern="^COMPLETED$")


class RunReceipt(StrictModel):
    run_id: str = Field(min_length=1)
    operation_key: str = Field(min_length=1)
    retry_of_run_id: str | None = None


class RecommendationIdentity(StrictModel):
    recommendation_id: str = Field(min_length=1)
    recommendation_version_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    resource_key: str = Field(min_length=1)
    equivalent_to_version_id: str | None = None

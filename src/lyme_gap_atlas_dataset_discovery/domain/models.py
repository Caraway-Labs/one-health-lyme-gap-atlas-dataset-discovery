"""Versioned, source-attributable domain values for the v1 contract."""

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class CandidatePriorAssessment(StrictModel):
    """Prior governed context; never a Dataset Discovery priority or approval."""

    identity: CandidateIdentity
    assessment_id: str = Field(min_length=1, max_length=200)
    assessment_status: str = Field(min_length=1, max_length=100)
    assessed_at: str = Field(min_length=1)


class CandidateArtifactMetadata(StrictModel):
    """Provenance metadata only; no URI or artifact retrieval capability."""

    identity: CandidateIdentity
    observation_id: str = Field(min_length=1, max_length=200)
    artifact_id: str = Field(min_length=1, max_length=200)
    artifact_type: str = Field(min_length=1, max_length=100)
    media_type: str | None = Field(default=None, max_length=200)
    byte_count: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    retention_class: str = Field(min_length=1, max_length=100)
    created_at: str = Field(min_length=1)


class DiscoveryContext(StrictModel):
    discovery_run_id: str = Field(min_length=1)
    search_fingerprint: str = Field(min_length=64, max_length=64)
    completed_at: str = Field(min_length=1)
    status: str = Field(pattern="^COMPLETED$")


class RunReceipt(StrictModel):
    run_id: str = Field(min_length=1)
    operation_key: str = Field(min_length=1)
    retry_of_run_id: str | None = None
    request_fingerprint: str | None = None


class RunCreateMetadata(StrictModel):
    """Immutable run request fields; creation time is assigned by Snowflake."""

    mode: str = Field(min_length=1)
    trigger_type: str = Field(min_length=1)
    code_sha: str = Field(min_length=40, max_length=40)
    spec_version: str = Field(min_length=1)
    graph_version: str = Field(min_length=1)
    config_fingerprint: str = Field(min_length=64, max_length=64)
    search_fingerprint: str = Field(min_length=64, max_length=64)
    evidence_snapshot_id: str = Field(min_length=1)
    provider: str | None = None
    model_id: str | None = None
    model_fingerprint: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    eval_version: str | None = None
    trace_id: str | None = None
    host_session_id: str | None = None

    @property
    def request_fingerprint(self) -> str:
        fields = self.model_dump(exclude={"trace_id", "host_session_id"})
        canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RecommendationIdentity(StrictModel):
    recommendation_id: str = Field(min_length=1)
    recommendation_version_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    resource_key: str = Field(min_length=1)
    equivalent_to_version_id: str | None = None


class DecisionDimension(StrictModel):
    value: int | None = Field(default=None, ge=0, le=2)
    cited_evidence_ids: tuple[str, ...] = ()


class CandidateDecisionRecord(StrictModel):
    """Bounded semantic audit, without prompts, observed values, or hidden reasoning."""

    model_id: str | None = Field(default=None, max_length=100)
    model_fingerprint: str | None = Field(default=None, max_length=64)
    config_fingerprint: str = Field(max_length=64)
    prompt_version: str | None = Field(default=None, max_length=120)
    task_type: str = Field(pattern="^(CLASSIFICATION|NOT_CALLED)$")
    classification: str | None = Field(default=None, max_length=80)
    relationship: str | None = Field(default=None, max_length=80)
    relationship_basis: str | None = Field(default=None, max_length=80)
    relevance: int | None = Field(default=None, ge=0, le=2)
    dimensions: dict[str, DecisionDimension] = Field(default_factory=dict)
    cited_evidence_ids: tuple[str, ...] = ()
    unknown_fields: tuple[str, ...] = ()
    validator_result: str = Field(max_length=80)
    normalized_reason: str = Field(max_length=80)
    final_outcome: str = Field(max_length=80)

    @field_validator("dimensions")
    @classmethod
    def reviewed_dimensions(
        cls, value: dict[str, DecisionDimension]
    ) -> dict[str, DecisionDimension]:
        allowed = {
            "relevance",
            "geography",
            "variables",
            "time",
            "provenance",
            "freshness",
            "rights_clarity",
            "complementarity",
        }
        if not set(value).issubset(allowed):
            raise ValueError("unreviewed decision dimension")
        return value

    @field_validator("cited_evidence_ids", "unknown_fields")
    @classmethod
    def bounded_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 25 or any(not item or len(item) > 200 for item in value):
            raise ValueError("decision audit list exceeds bound")
        return value


class CandidateOutcomeReceipt(StrictModel):
    operation_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    resource_key: str = Field(min_length=1)
    catalog_dataset_id: str = Field(min_length=1)
    catalog_resource_id: str = Field(min_length=1)
    evidence_snapshot_id: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    reason_code: str | None = None
    decision_record: CandidateDecisionRecord | None = None


class RecommendationWriteReceipt(StrictModel):
    operation_key: str = Field(min_length=1)
    identity: RecommendationIdentity
    assertion_sha256: str = Field(min_length=64, max_length=64)
    evidence_observation_ids: tuple[str, ...] = Field(min_length=1)
    proposal_ids: tuple[str, ...] = ()


class RunFinalizationReceipt(StrictModel):
    operation_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    processed_count: int = Field(ge=0)
    recommendation_count: int = Field(ge=0)
    budget_usage: dict[str, int] = Field(default_factory=dict)
    stop_reason: str | None = None

    @field_validator("budget_usage")
    @classmethod
    def bounded_usage(cls, value: dict[str, int]) -> dict[str, int]:
        allowed = {
            "candidates",
            "pages",
            "graph_steps",
            "model_calls",
            "tool_calls",
            "elapsed_seconds",
            "input_tokens",
            "output_tokens",
            "evidence_bytes",
            "retained_state_bytes",
            "estimated_spend_cents",
        }
        if set(value) - allowed or any(amount < 0 for amount in value.values()):
            raise ValueError("run usage counters must be bounded and nonnegative")
        return value

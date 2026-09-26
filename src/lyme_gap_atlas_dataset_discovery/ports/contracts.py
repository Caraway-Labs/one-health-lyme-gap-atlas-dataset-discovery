"""Closed application ports. None permits arbitrary SQL, URL, or shell access."""

from typing import Protocol

from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    CandidateOutcomeReceipt,
    CandidatePage,
    CandidateSummary,
    EvidenceRef,
    RecommendationWriteReceipt,
    RunFinalizationReceipt,
    RunReceipt,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import RecommendationWrite


class CandidateReader(Protocol):
    def list_batch(self, *, cursor: str | None, limit: int) -> CandidatePage: ...

    def get_summary(self, candidate_id: str) -> CandidateSummary: ...

    def get_identity(self, candidate_id: str) -> CandidateIdentity: ...

    def get_evidence_refs(self, candidate_id: str, *, limit: int) -> tuple[EvidenceRef, ...]: ...

    def get_governed_status(self, candidate_id: str) -> str: ...


class RecommendationRepository(Protocol):
    def create_run(
        self, *, operation_key: str, run_id: str, retry_of_run_id: str | None = None
    ) -> RunReceipt: ...

    def get_run(self, operation_key: str) -> RunReceipt | None: ...

    def record_candidate_outcome(
        self, receipt: CandidateOutcomeReceipt
    ) -> CandidateOutcomeReceipt: ...

    def save_recommendation(self, request: RecommendationWrite) -> RecommendationWriteReceipt: ...

    def finalize_run(self, receipt: RunFinalizationReceipt) -> RunFinalizationReceipt: ...


class ModelInterpreter(Protocol):
    def interpret_relevance(self, candidate: CandidateSummary) -> str: ...


class HandoffClient(Protocol):
    def get_status(self, recommendation_version_id: str) -> str: ...

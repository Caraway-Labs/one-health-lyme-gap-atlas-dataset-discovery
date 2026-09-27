"""Closed application ports. None permits arbitrary SQL, URL, or shell access."""

from typing import Protocol

from lyme_gap_atlas_dataset_discovery.domain.analysis import AvailableObservation
from lyme_gap_atlas_dataset_discovery.domain.handoff import HandoffReceipt, HandoffStatus
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    CandidateOutcomeReceipt,
    CandidatePage,
    CandidateSummary,
    DiscoveryContext,
    EvidenceRef,
    RecommendationWriteReceipt,
    RunCreateMetadata,
    RunFinalizationReceipt,
    RunReceipt,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import RecommendationWrite
from lyme_gap_atlas_dataset_discovery.domain.review import (
    PendingPage,
    ReviewCommand,
    ReviewDetail,
    ReviewHistoryPage,
    ReviewReceipt,
)


class DiscoveryContextReader(Protocol):
    def get_context(self, discovery_run_id: str) -> DiscoveryContext: ...


class CandidateReader(Protocol):
    def list_batch(self, *, cursor: str | None, limit: int) -> CandidatePage: ...

    def get_summary(self, candidate_id: str) -> CandidateSummary: ...

    def get_identity(self, candidate_id: str) -> CandidateIdentity: ...

    def get_evidence_refs(self, candidate_id: str, *, limit: int) -> tuple[EvidenceRef, ...]: ...

    def get_observations(
        self, candidate_id: str, *, limit: int
    ) -> tuple[AvailableObservation, ...]: ...

    def get_governed_status(self, candidate_id: str) -> str: ...


class RecommendationRepository(Protocol):
    def create_run(
        self,
        *,
        operation_key: str,
        run_id: str,
        metadata: RunCreateMetadata,
        retry_of_run_id: str | None = None,
    ) -> RunReceipt: ...

    def get_run(self, operation_key: str) -> RunReceipt | None: ...

    def record_candidate_outcome(
        self, receipt: CandidateOutcomeReceipt
    ) -> CandidateOutcomeReceipt: ...

    def get_candidate_outcome(self, operation_key: str) -> CandidateOutcomeReceipt | None: ...

    def save_recommendation(self, request: RecommendationWrite) -> RecommendationWriteReceipt: ...

    def get_recommendation(self, operation_key: str) -> RecommendationWriteReceipt | None: ...

    def finalize_run(self, receipt: RunFinalizationReceipt) -> RunFinalizationReceipt: ...

    def get_finalization(self, run_id: str) -> RunFinalizationReceipt | None: ...


class ModelInterpreter(Protocol):
    def interpret_relevance(self, candidate: CandidateSummary) -> str: ...


class HandoffClient(Protocol):
    """Human-only handoff boundary; excluded from graph dependencies."""

    def assert_human_session(self) -> None: ...

    def submit(self, recommendation_version_id: str, review_event_id: str) -> HandoffReceipt: ...

    def get_status(self, recommendation_version_id: str) -> HandoffStatus | None: ...


class HumanReviewRepository(Protocol):
    """Separate from the inference graph's recommendation repository."""

    def assert_human_session(self) -> None: ...

    def list_pending(self, run_id: str, *, after_rank: int, limit: int) -> PendingPage: ...

    def get_detail(self, recommendation_version_id: str) -> ReviewDetail: ...

    def get_history(
        self, recommendation_version_id: str, *, after_sequence: int, limit: int
    ) -> ReviewHistoryPage: ...

    def append_event(self, command: ReviewCommand) -> ReviewReceipt: ...

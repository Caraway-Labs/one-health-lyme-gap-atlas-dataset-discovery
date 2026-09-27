"""Bounded human-only review service; never imported by the inference graph."""

from lyme_gap_atlas_dataset_discovery.domain.review import (
    PendingPage,
    ReviewDecision,
    ReviewDetail,
    ReviewHistoryPage,
    ReviewReceipt,
    make_review_command,
)
from lyme_gap_atlas_dataset_discovery.observability import traced_operation
from lyme_gap_atlas_dataset_discovery.ports.contracts import HumanReviewRepository


class HumanReviewService:
    def __init__(self, repository: HumanReviewRepository) -> None:
        repository.assert_human_session()
        self._repository = repository

    def list_pending(self, run_id: str, *, after_rank: int = 0, limit: int = 25) -> PendingPage:
        with traced_operation("review", "list_pending", "request", 1):
            return self._repository.list_pending(run_id, after_rank=after_rank, limit=limit)

    def show(self, recommendation_version_id: str) -> ReviewDetail:
        with traced_operation("review", "show", "request", 1):
            return self._repository.get_detail(recommendation_version_id)

    def history(
        self, recommendation_version_id: str, *, after_sequence: int = 0, limit: int = 50
    ) -> ReviewHistoryPage:
        with traced_operation("review", "history", "request", 1):
            return self._repository.get_history(
                recommendation_version_id, after_sequence=after_sequence, limit=limit
            )

    def decide(
        self,
        recommendation_version_id: str,
        decision: ReviewDecision,
        *,
        rationale: str,
        expected_prior_event_id: str | None = None,
        conditions: tuple[str, ...] = (),
        correction_of_event_id: str | None = None,
    ) -> ReviewReceipt:
        command = make_review_command(
            recommendation_version_id=recommendation_version_id,
            decision=decision,
            rationale=rationale,
            expected_prior_event_id=expected_prior_event_id,
            conditions=conditions,
            correction_of_event_id=correction_of_event_id,
        )
        with traced_operation("review", "decide", "request", 1):
            return self._repository.append_event(command)

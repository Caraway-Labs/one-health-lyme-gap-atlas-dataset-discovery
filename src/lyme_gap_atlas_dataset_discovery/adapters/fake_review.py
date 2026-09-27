"""Deterministic human review fake with the same authority boundary as V109."""

import hashlib
from dataclasses import dataclass, field

from lyme_gap_atlas_dataset_discovery.domain.review import (
    DECISION_STATE,
    PendingPage,
    PendingRecommendation,
    ReviewCommand,
    ReviewDetail,
    ReviewHistoryEntry,
    ReviewHistoryPage,
    ReviewReceipt,
    ReviewState,
)


@dataclass
class FakeHumanReviewRepository:
    reviewer_user: str = "human-reviewer"
    reviewer_role: str = "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER"
    principal_type: str = "USER_PERSON"
    allowlisted: bool = True
    details: dict[str, ReviewDetail] = field(default_factory=dict)
    commands: dict[str, ReviewCommand] = field(default_factory=dict)
    receipts: dict[str, ReviewReceipt] = field(default_factory=dict)
    events: dict[str, list[ReviewHistoryEntry]] = field(default_factory=dict)

    def assert_human_session(self) -> None:
        if (
            self.principal_type != "USER_PERSON"
            or self.reviewer_role
            not in {
                "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER",
                "OH_LYME_PROD_DATASET_DISCOVERY_REVIEWER",
            }
            or not self.reviewer_user
            or not self.allowlisted
        ):
            raise PermissionError("individually authenticated reviewer required")

    def _current(self, version_id: str) -> tuple[ReviewState, str | None]:
        history = self.events.get(version_id, [])
        if not history:
            return ReviewState.PENDING, None
        latest = history[-1]
        return latest.new_state, latest.review_event_id

    def list_pending(self, run_id: str, *, after_rank: int, limit: int) -> PendingPage:
        self.assert_human_session()
        if (
            not run_id
            or type(after_rank) is not int
            or after_rank < 0
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise ValueError("invalid pending review page")
        candidates = sorted(
            (
                detail
                for detail in self.details.values()
                if detail.run_id == run_id
                and detail.rank_in_run > after_rank
                and self._current(detail.recommendation_version_id)[0]
                in {ReviewState.PENDING, ReviewState.NEEDS_MORE_INFORMATION}
            ),
            key=lambda detail: detail.rank_in_run,
        )
        page = candidates[:limit]
        items = tuple(
            PendingRecommendation(
                recommendation_version_id=detail.recommendation_version_id,
                recommendation_id=detail.recommendation_id,
                run_id=detail.run_id,
                resource_key=detail.resource_key,
                priority_bucket=detail.priority_bucket,
                priority_score=detail.priority_score,
                rank_in_run=detail.rank_in_run,
                rationale=detail.rationale,
                rights_state=detail.rights_state,
                created_at=detail.created_at,
                review_state=self._current(detail.recommendation_version_id)[0],
                latest_review_event_id=self._current(detail.recommendation_version_id)[1],
            )
            for detail in page
        )
        return PendingPage(
            items=items,
            next_after_rank=page[-1].rank_in_run if len(candidates) > limit else None,
        )

    def get_detail(self, recommendation_version_id: str) -> ReviewDetail:
        self.assert_human_session()
        detail = self.details[recommendation_version_id]
        state, event_id = self._current(recommendation_version_id)
        return detail.model_copy(update={"review_state": state, "latest_review_event_id": event_id})

    def get_history(
        self, recommendation_version_id: str, *, after_sequence: int, limit: int
    ) -> ReviewHistoryPage:
        self.assert_human_session()
        if (
            recommendation_version_id not in self.details
            or type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise ValueError("invalid review history request")
        events = [
            event
            for event in self.events.get(recommendation_version_id, [])
            if event.event_sequence > after_sequence
        ]
        page = events[:limit]
        return ReviewHistoryPage(
            items=tuple(page),
            next_after_sequence=page[-1].event_sequence if len(events) > limit else None,
        )

    def append_event(self, command: ReviewCommand) -> ReviewReceipt:
        self.assert_human_session()
        previous = self.receipts.get(command.command_key)
        if previous is not None:
            if self.commands[command.command_key] != command:
                raise ValueError("conflicting review replay")
            return previous
        detail = self.get_detail(command.recommendation_version_id)
        if not detail.evidence:
            raise ValueError("recommendation evidence missing")
        prior_state, prior_event_id = self._current(command.recommendation_version_id)
        if command.expected_prior_event_id != prior_event_id:
            raise ValueError("stale review state")
        if prior_state == ReviewState.ACCEPTED_FOR_INVESTIGATION:
            raise ValueError("accepted review is terminal")
        if prior_state in {ReviewState.PENDING, ReviewState.NEEDS_MORE_INFORMATION}:
            if command.correction_of_event_id is not None:
                raise ValueError("correction requires terminal state")
        elif command.correction_of_event_id != prior_event_id:
            raise ValueError("terminal review requires correction")
        event_id = hashlib.sha256(
            ("review-event-v1\x1f" + command.command_key).encode("utf-8")
        ).hexdigest()
        sequence = sum(len(items) for items in self.events.values()) + 1
        state = DECISION_STATE[command.decision]
        receipt = ReviewReceipt(
            review_event_id=event_id,
            command_key=command.command_key,
            recommendation_version_id=command.recommendation_version_id,
            prior_event_id=prior_event_id,
            prior_state=prior_state,
            new_state=state,
            decision=command.decision,
            reviewer_user=self.reviewer_user,
            reviewer_role=self.reviewer_role,
            event_sequence=sequence,
        )
        event = ReviewHistoryEntry(
            review_event_id=event_id,
            command_key=command.command_key,
            event_sequence=sequence,
            prior_event_id=prior_event_id,
            prior_state=prior_state,
            decision=command.decision,
            new_state=state,
            rationale=command.rationale,
            conditions=command.conditions,
            reviewer_user=self.reviewer_user,
            reviewer_role=self.reviewer_role,
            reviewed_at=f"fixture-sequence-{sequence}",
            correction_of_event_id=command.correction_of_event_id,
        )
        self.events.setdefault(command.recommendation_version_id, []).append(event)
        self.commands[command.command_key] = command
        self.receipts[command.command_key] = receipt
        return receipt

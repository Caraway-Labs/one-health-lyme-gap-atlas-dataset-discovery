"""Credential-free governed handoff fake for local end-to-end review tests."""

import hashlib
from dataclasses import dataclass, field

from lyme_gap_atlas_dataset_discovery.domain.handoff import (
    AcquisitionBoundary,
    HandoffDisposition,
    HandoffReceipt,
    HandoffStatus,
    InvestigationStatus,
)
from lyme_gap_atlas_dataset_discovery.domain.review import ReviewState

from .fake_review import FakeHumanReviewRepository


@dataclass
class FakeHumanHandoffClient:
    review: FakeHumanReviewRepository
    already_governed: set[str] = field(default_factory=set)
    controlled_access: set[str] = field(default_factory=set)
    reviewed_rights: dict[str, str] = field(default_factory=dict)
    receipts: dict[str, HandoffStatus] = field(default_factory=dict)

    def assert_human_session(self) -> None:
        self.review.assert_human_session()

    def submit(self, recommendation_version_id: str, review_event_id: str) -> HandoffReceipt:
        self.assert_human_session()
        old = self.receipts.get(recommendation_version_id)
        if old is not None:
            if old.review_event_id != review_event_id:
                raise ValueError("conflicting handoff replay")
            return HandoffReceipt.model_validate(old.model_dump(exclude={"created_at"}))
        detail = self.review.get_detail(recommendation_version_id)
        if (
            detail.review_state != ReviewState.ACCEPTED_FOR_INVESTIGATION
            or detail.latest_review_event_id != review_event_id
        ):
            raise ValueError("rejected or stale handoff")
        if not detail.evidence or not detail.catalog_dataset_id or not detail.catalog_resource_id:
            raise ValueError("missing handoff evidence or identity")
        finding = self.reviewed_rights.get(detail.resource_key)
        disposition = (
            HandoffDisposition.POLICY_BLOCKED
            if finding == "KNOWN_PROHIBITED"
            else HandoffDisposition.ALREADY_GOVERNED
            if detail.resource_key in self.already_governed
            else HandoffDisposition.HANDED_OFF
        )
        status = (
            InvestigationStatus.PENDING
            if disposition == HandoffDisposition.HANDED_OFF
            else InvestigationStatus(disposition.value)
        )
        boundary = (
            AcquisitionBoundary.NO_AUTOMATED_ACQUISITION
            if finding in {"KNOWN_RESTRICTED", "KNOWN_PROHIBITED"}
            or detail.resource_key in self.controlled_access
            else AcquisitionBoundary.INVESTIGATE_BEFORE_ACQUISITION
        )
        key = f"handoff-v1:{recommendation_version_id}"
        receipt = HandoffStatus(
            handoff_id=hashlib.sha256(key.encode()).hexdigest(),
            operation_key=key,
            recommendation_version_id=recommendation_version_id,
            review_event_id=review_event_id,
            relationship_type=detail.relationship_type,
            disposition=disposition,
            investigation_status=status,
            acquisition_boundary=boundary,
            created_at="2026-01-01T00:00:00Z",
        )
        self.receipts[recommendation_version_id] = receipt
        return HandoffReceipt.model_validate(receipt.model_dump(exclude={"created_at"}))

    def get_status(self, recommendation_version_id: str) -> HandoffStatus | None:
        self.assert_human_session()
        return self.receipts.get(recommendation_version_id)

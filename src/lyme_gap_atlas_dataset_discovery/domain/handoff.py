"""Typed governed investigation handoff receipts, outside the inference graph."""

from enum import StrEnum

from pydantic import Field

from .models import StrictModel
from .ranking import Relationship


class HandoffDisposition(StrEnum):
    HANDED_OFF = "HANDED_OFF"
    ALREADY_GOVERNED = "ALREADY_GOVERNED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class InvestigationStatus(StrEnum):
    PENDING = "PENDING"
    ALREADY_GOVERNED = "ALREADY_GOVERNED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class AcquisitionBoundary(StrEnum):
    INVESTIGATE_BEFORE_ACQUISITION = "INVESTIGATE_BEFORE_ACQUISITION"
    NO_AUTOMATED_ACQUISITION = "NO_AUTOMATED_ACQUISITION"


class HandoffReceipt(StrictModel):
    handoff_id: str = Field(min_length=64, max_length=64)
    operation_key: str = Field(min_length=1, max_length=75)
    recommendation_version_id: str = Field(min_length=64, max_length=64)
    review_event_id: str = Field(min_length=64, max_length=64)
    relationship_type: Relationship
    disposition: HandoffDisposition
    investigation_status: InvestigationStatus
    acquisition_boundary: AcquisitionBoundary


class HandoffStatus(HandoffReceipt):
    created_at: str

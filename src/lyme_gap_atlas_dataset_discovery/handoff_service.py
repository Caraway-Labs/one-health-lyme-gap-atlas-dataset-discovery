"""Human-initiated governed intake, deliberately outside LangGraph."""

from lyme_gap_atlas_dataset_discovery.domain.handoff import HandoffReceipt, HandoffStatus
from lyme_gap_atlas_dataset_discovery.observability import traced_operation
from lyme_gap_atlas_dataset_discovery.ports.contracts import HandoffClient


class HumanHandoffService:
    def __init__(self, client: HandoffClient) -> None:
        client.assert_human_session()
        self._client = client

    def submit(self, recommendation_version_id: str, review_event_id: str) -> HandoffReceipt:
        with traced_operation("handoff", "submit", "request", 1):
            return self._client.submit(recommendation_version_id, review_event_id)

    def status(self, recommendation_version_id: str) -> HandoffStatus | None:
        with traced_operation("handoff", "status", "request", 1):
            return self._client.get_status(recommendation_version_id)

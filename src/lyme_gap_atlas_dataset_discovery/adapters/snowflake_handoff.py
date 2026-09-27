"""Fixed, human-only client for the data-owned V110 investigation boundary."""

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Any

from lyme_gap_atlas_dataset_discovery.domain.handoff import HandoffReceipt, HandoffStatus

from .snowflake_repository import Connection
from .snowflake_review import SnowflakeHumanReviewRepository

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _key(version_id: str) -> str:
    if not _SHA256.fullmatch(version_id):
        raise ValueError("invalid recommendation version ID")
    return f"handoff-v1:{version_id}"


class SnowflakeHumanHandoffClient:
    """Accepts a separate authenticated reviewer connection, never graph runtime credentials."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._review = SnowflakeHumanReviewRepository(connection)

    def assert_human_session(self) -> None:
        self._review.assert_human_session()

    def _rows(
        self, sql: str, params: Sequence[object], *, maximum: int = 1
    ) -> list[tuple[Any, ...]]:
        cursor = self._connection.cursor()
        try:
            cursor.execute(sql, params, timeout=30)
            rows: list[tuple[Any, ...]] = []
            while len(rows) < maximum:
                row = cursor.fetchone()
                if row is None:
                    return rows
                if len(json.dumps(row, default=str, ensure_ascii=False).encode("utf-8")) > 4096:
                    raise ValueError("handoff receipt exceeded byte limit")
                rows.append(row)
            if cursor.fetchone() is not None:
                raise ValueError("ambiguous handoff receipt")
            return rows
        finally:
            cursor.close()

    def submit(self, recommendation_version_id: str, review_event_id: str) -> HandoffReceipt:
        self.assert_human_session()
        operation_key = _key(recommendation_version_id)
        if not _SHA256.fullmatch(review_event_id):
            raise ValueError("invalid review event ID")
        rows = self._rows(
            "CALL GOVERNANCE.SP_HANDOFF_DATASET_DISCOVERY_RECOMMENDATION(%s, %s)",
            (recommendation_version_id, review_event_id),
        )
        if len(rows) != 1 or len(rows[0]) != 1:
            raise ValueError("handoff procedure returned no receipt")
        payload = rows[0][0]
        receipt = HandoffReceipt.model_validate(
            json.loads(payload) if isinstance(payload, str) else payload
        )
        if (
            receipt.operation_key != operation_key
            or receipt.handoff_id != hashlib.sha256(operation_key.encode()).hexdigest()
            or receipt.recommendation_version_id != recommendation_version_id
            or receipt.review_event_id != review_event_id
        ):
            raise ValueError("handoff receipt differs from submitted version and review")
        return receipt

    def get_status(self, recommendation_version_id: str) -> HandoffStatus | None:
        self.assert_human_session()
        operation_key = _key(recommendation_version_id)
        rows = self._rows(
            "SELECT handoff_id, operation_key, recommendation_version_id, "
            "review_event_id, relationship_type, disposition, investigation_status, "
            "acquisition_boundary, created_at "
            "FROM DATASET_DISCOVERY.V_HANDOFF_RECEIPTS WHERE operation_key = %s",
            (operation_key,),
        )
        if not rows:
            return None
        row = rows[0]
        receipt = HandoffStatus(
            handoff_id=row[0],
            operation_key=row[1],
            recommendation_version_id=row[2],
            review_event_id=row[3],
            relationship_type=row[4],
            disposition=row[5],
            investigation_status=row[6],
            acquisition_boundary=row[7],
            created_at=str(row[8]),
        )
        if (
            receipt.handoff_id != hashlib.sha256(operation_key.encode()).hexdigest()
            or receipt.operation_key != operation_key
            or receipt.recommendation_version_id != recommendation_version_id
        ):
            raise ValueError("handoff status view returned another request")
        return receipt

"""Fixed Snowflake procedure and receipt adapter for the v1 runtime.

The connection is supplied by the host after authentication and role selection.
This module gives graph code no arbitrary SQL operation.
"""

import json
from collections.abc import Sequence
from typing import Any, Protocol

from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateOutcomeReceipt,
    RecommendationIdentity,
    RecommendationWriteReceipt,
    RunCreateMetadata,
    RunFinalizationReceipt,
    RunReceipt,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import RecommendationWrite


class Cursor(Protocol):
    def execute(self, sql: str, params: Sequence[object] = ()) -> "Cursor": ...

    def fetchone(self) -> tuple[Any, ...] | None: ...

    def close(self) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...


def _variant(value: object) -> dict[str, Any]:
    """Normalize connector VARIANT results without accepting scalar receipts."""
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("Snowflake receipt is not an object")
    return value


def _array(value: object) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("Snowflake receipt array is invalid")
    return value


class SnowflakeRecommendationRepository:
    """Only the reviewed V107/V108 procedures may write runtime state."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _one(self, sql: str, params: Sequence[object]) -> tuple[Any, ...] | None:
        cursor = self._connection.cursor()
        try:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            if row is not None and cursor.fetchone() is not None:
                raise ValueError("Snowflake receipt returned duplicate rows")
            return row
        finally:
            cursor.close()

    def _call(self, sql: str, params: Sequence[object]) -> dict[str, Any]:
        row = self._one(sql, params)
        if row is None or len(row) != 1:
            raise ValueError("Snowflake procedure did not return one receipt")
        return _variant(row[0])

    def create_run(
        self,
        *,
        operation_key: str,
        run_id: str,
        metadata: RunCreateMetadata,
        retry_of_run_id: str | None = None,
    ) -> RunReceipt:
        payload = metadata.model_dump(mode="json")
        payload["request_fingerprint"] = metadata.request_fingerprint
        result = self._call(
            "CALL DATASET_DISCOVERY.SP_CREATE_RUN(%s, %s, %s, %s)",
            (operation_key, run_id, retry_of_run_id, json.dumps(payload, ensure_ascii=False)),
        )
        return RunReceipt.model_validate(result)

    def get_run(self, operation_key: str) -> RunReceipt | None:
        row = self._one(
            "SELECT run_id, operation_key, retry_of_run_id, request_fingerprint "
            "FROM DATASET_DISCOVERY.V_RUN_RECEIPTS WHERE operation_key = %s",
            (operation_key,),
        )
        if row is None:
            return None
        return RunReceipt(
            run_id=row[0],
            operation_key=row[1],
            retry_of_run_id=row[2],
            request_fingerprint=row[3],
        )

    def record_candidate_outcome(self, receipt: CandidateOutcomeReceipt) -> CandidateOutcomeReceipt:
        result = self._call(
            "CALL DATASET_DISCOVERY.SP_RECORD_CANDIDATE_OUTCOME(%s)",
            (receipt.model_dump_json(),),
        )
        return CandidateOutcomeReceipt.model_validate(result)

    def get_candidate_outcome(self, operation_key: str) -> CandidateOutcomeReceipt | None:
        row = self._one(
            "SELECT operation_key, run_id, resource_key, catalog_dataset_id, "
            "catalog_resource_id, evidence_snapshot_id, outcome, reason_code "
            "FROM DATASET_DISCOVERY.V_CANDIDATE_OUTCOME_RECEIPTS WHERE operation_key = %s",
            (operation_key,),
        )
        if row is None:
            return None
        return CandidateOutcomeReceipt(
            operation_key=row[0],
            run_id=row[1],
            resource_key=row[2],
            catalog_dataset_id=row[3],
            catalog_resource_id=row[4],
            evidence_snapshot_id=row[5],
            outcome=row[6],
            reason_code=row[7],
        )

    def save_recommendation(self, request: RecommendationWrite) -> RecommendationWriteReceipt:
        validated = RecommendationWrite.model_validate(request.model_dump())
        result = self._call(
            "CALL DATASET_DISCOVERY.SP_COMMIT_RECOMMENDATION(%s)",
            (validated.model_dump_json(),),
        )
        return RecommendationWriteReceipt.model_validate(result)

    def get_recommendation(self, operation_key: str) -> RecommendationWriteReceipt | None:
        row = self._one(
            "SELECT operation_key, recommendation_id, recommendation_version_id, "
            "run_id, resource_key, equivalent_to_version_id, assertion_sha256, "
            "evidence_observation_ids, proposal_ids "
            "FROM DATASET_DISCOVERY.V_RECOMMENDATION_RECEIPTS WHERE operation_key = %s",
            (operation_key,),
        )
        if row is None:
            return None
        return RecommendationWriteReceipt(
            operation_key=row[0],
            identity=RecommendationIdentity(
                recommendation_id=row[1],
                recommendation_version_id=row[2],
                run_id=row[3],
                resource_key=row[4],
                equivalent_to_version_id=row[5],
            ),
            assertion_sha256=row[6],
            evidence_observation_ids=tuple(_array(row[7])),
            proposal_ids=tuple(_array(row[8])) if row[8] is not None else (),
        )

    def finalize_run(self, receipt: RunFinalizationReceipt) -> RunFinalizationReceipt:
        result = self._call(
            "CALL DATASET_DISCOVERY.SP_FINALIZE_RUN(%s)",
            (receipt.model_dump_json(),),
        )
        return RunFinalizationReceipt.model_validate(result)

    def get_finalization(self, run_id: str) -> RunFinalizationReceipt | None:
        row = self._one(
            "SELECT operation_key, run_id, status, processed_count, recommendation_count, "
            "budget_usage, stop_reason "
            "FROM DATASET_DISCOVERY.V_FINALIZATION_RECEIPTS WHERE run_id = %s",
            (run_id,),
        )
        if row is None:
            return None
        return RunFinalizationReceipt(
            operation_key=row[0],
            run_id=row[1],
            status=row[2],
            processed_count=row[3],
            recommendation_count=row[4],
            budget_usage=_variant(row[5]),
            stop_reason=row[6],
        )

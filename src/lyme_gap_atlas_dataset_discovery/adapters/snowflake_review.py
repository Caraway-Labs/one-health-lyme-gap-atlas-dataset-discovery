"""Human-only fixed Snowflake review adapter for the data-owned V109 boundary."""

import json
import re
from collections.abc import Sequence
from typing import Any

from lyme_gap_atlas_dataset_discovery.domain.review import (
    PendingPage,
    PendingRecommendation,
    ReviewCommand,
    ReviewDetail,
    ReviewEvidence,
    ReviewHistoryEntry,
    ReviewHistoryPage,
    ReviewReceipt,
)

from .snowflake_repository import Connection

_DATABASE = re.compile(r"^ONE_HEALTH_LYME_GAP_ATLAS_(DEV|PROD)$")


def _json(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _id(value: str, label: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError(f"invalid {label}")
    return value


class SnowflakeHumanReviewRepository:
    """Receives a separately authenticated reviewer connection, never runtime credentials."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _rows(
        self,
        sql: str,
        params: Sequence[object] = (),
        *,
        maximum: int = 1,
        timeout: int = 15,
        byte_limit: int = 262144,
    ) -> list[tuple[Any, ...]]:
        cursor = self._connection.cursor()
        try:
            cursor.execute(sql, params, timeout=timeout)
            rows: list[tuple[Any, ...]] = []
            used_bytes = 0
            while len(rows) < maximum:
                row = cursor.fetchone()
                if row is None:
                    return rows
                used_bytes += len(json.dumps(row, default=str, ensure_ascii=False).encode("utf-8"))
                if used_bytes > byte_limit:
                    raise ValueError("review read exceeded byte limit")
                rows.append(row)
            if cursor.fetchone() is not None:
                raise ValueError("review query exceeded row bound")
            return rows
        finally:
            cursor.close()

    def assert_human_session(self) -> None:
        rows = self._rows(
            "SELECT SYS_CONTEXT('SNOWFLAKE$SESSION', 'PRINCIPAL_NAME'), "
            "SYS_CONTEXT('SNOWFLAKE$SESSION', 'PRINCIPAL_TYPE'), "
            "SYS_CONTEXT('SNOWFLAKE$SESSION', 'ROLE'), "
            "CURRENT_DATABASE(), CURRENT_WAREHOUSE()",
            byte_limit=2048,
        )
        if len(rows) != 1:
            raise PermissionError("reviewer session identity unavailable")
        name, principal_type, role, database, warehouse = rows[0]
        match = _DATABASE.fullmatch(database) if isinstance(database, str) else None
        expected_role = f"OH_LYME_{match.group(1)}_DATASET_DISCOVERY_REVIEWER" if match else None
        if (
            not isinstance(name, str)
            or not name
            or principal_type != "USER_PERSON"
            or role != expected_role
            or not isinstance(warehouse, str)
            or not warehouse
        ):
            raise PermissionError("individually authenticated reviewer role required")

    def list_pending(self, run_id: str, *, after_rank: int, limit: int) -> PendingPage:
        self.assert_human_session()
        _id(run_id, "run ID")
        if (
            type(after_rank) is not int
            or after_rank < 0
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise ValueError("invalid pending review page")
        rows = self._rows(
            "SELECT recommendation_version_id, recommendation_id, run_id, "
            "resource_key, priority_bucket, priority_score, rank_in_run, "
            "rationale, rights_state, created_at, review_state, latest_review_event_id "
            "FROM DATASET_DISCOVERY.V_PENDING_RECOMMENDATIONS "
            "WHERE run_id = %s AND rank_in_run > %s "
            "ORDER BY rank_in_run, recommendation_version_id LIMIT %s",
            (run_id, after_rank, limit + 1),
            maximum=limit + 1,
        )
        items = tuple(
            PendingRecommendation(
                recommendation_version_id=row[0],
                recommendation_id=row[1],
                run_id=row[2],
                resource_key=row[3],
                priority_bucket=row[4],
                priority_score=row[5],
                rank_in_run=row[6],
                rationale=row[7],
                rights_state=row[8],
                created_at=str(row[9]),
                review_state=row[10],
                latest_review_event_id=row[11],
            )
            for row in rows[:limit]
        )
        if any(item.run_id != run_id for item in items):
            raise ValueError("review view returned another run")
        ranks = [item.rank_in_run for item in items]
        if ranks != sorted(set(ranks)) or any(rank <= after_rank for rank in ranks):
            raise ValueError("review view violated rank pagination")
        return PendingPage(
            items=items,
            next_after_rank=items[-1].rank_in_run if len(rows) > limit else None,
        )

    def get_detail(self, recommendation_version_id: str) -> ReviewDetail:
        self.assert_human_session()
        _id(recommendation_version_id, "recommendation version ID", 64)
        rows = self._rows(
            "SELECT recommendation_version_id, recommendation_id, run_id, resource_key, "
            "catalog_dataset_id, catalog_resource_id, evidence_snapshot_id, "
            "assertion_sha256, classification, relationship_type, relationship_basis, "
            "rights_state, observed_facts, inferences, unknowns, dimensions, "
            "ranking_formula_version, relationship_adjustment, missing_count, "
            "priority_score, priority_bucket, rank_in_run, rationale, created_at, "
            "review_state, latest_review_event_id "
            "FROM DATASET_DISCOVERY.V_REVIEW_RECOMMENDATION_DETAIL "
            "WHERE recommendation_version_id = %s",
            (recommendation_version_id,),
        )
        if not rows:
            raise KeyError(recommendation_version_id)
        row = rows[0]
        evidence_rows = self._rows(
            "SELECT recommendation_version_id, observation_id, catalog_dataset_id, "
            "catalog_resource_id, field_name, metadata_sha256, observed_at "
            "FROM DATASET_DISCOVERY.V_REVIEW_EVIDENCE "
            "WHERE recommendation_version_id = %s "
            "ORDER BY observation_id, field_name LIMIT 101",
            (recommendation_version_id,),
            maximum=101,
        )
        if len(evidence_rows) > 100:
            raise ValueError("review evidence exceeds v1 bound")
        evidence = tuple(
            ReviewEvidence(
                recommendation_version_id=item[0],
                observation_id=item[1],
                catalog_dataset_id=item[2],
                catalog_resource_id=item[3],
                field_name=item[4],
                metadata_sha256=item[5],
                observed_at=str(item[6]),
            )
            for item in evidence_rows
        )
        if any(item.recommendation_version_id != recommendation_version_id for item in evidence):
            raise ValueError("review evidence version mismatch")
        detail = ReviewDetail(
            recommendation_version_id=row[0],
            recommendation_id=row[1],
            run_id=row[2],
            resource_key=row[3],
            catalog_dataset_id=row[4],
            catalog_resource_id=row[5],
            evidence_snapshot_id=row[6],
            assertion_sha256=row[7],
            classification=row[8],
            relationship_type=row[9],
            relationship_basis=row[10],
            rights_state=row[11],
            observed_facts=_json(row[12]),
            inferences=_json(row[13]),
            unknowns=_json(row[14]),
            dimensions=_json(row[15]),
            ranking_formula_version=row[16],
            relationship_adjustment=row[17],
            missing_count=row[18],
            priority_score=row[19],
            priority_bucket=row[20],
            rank_in_run=row[21],
            rationale=row[22],
            created_at=str(row[23]),
            review_state=row[24],
            latest_review_event_id=row[25],
            evidence=evidence,
        )
        if detail.recommendation_version_id != recommendation_version_id:
            raise ValueError("review detail version mismatch")
        evidence_keys = [(item.observation_id, item.field_name) for item in evidence]
        fact_keys = [(fact.evidence.observation_id, fact.field) for fact in detail.observed_facts]
        if (
            len(set(evidence_keys)) != len(evidence_keys)
            or set(evidence_keys) != set(fact_keys)
            or any(
                item.catalog_dataset_id != detail.catalog_dataset_id
                or item.catalog_resource_id != detail.catalog_resource_id
                for item in evidence
            )
        ):
            raise ValueError("review evidence differs from immutable observed facts")
        return detail

    def get_history(
        self, recommendation_version_id: str, *, after_sequence: int, limit: int
    ) -> ReviewHistoryPage:
        self.assert_human_session()
        _id(recommendation_version_id, "recommendation version ID", 64)
        if (
            type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise ValueError("invalid review history page")
        rows = self._rows(
            "SELECT review_event_id, command_key, event_sequence, prior_event_id, "
            "prior_state, decision, new_state, rationale, conditions, reviewer_user, "
            "reviewer_role, reviewed_at, correction_of_event_id "
            "FROM DATASET_DISCOVERY.V_RECOMMENDATION_HISTORY "
            "WHERE recommendation_version_id = %s AND event_sequence > %s "
            "ORDER BY event_sequence LIMIT %s",
            (recommendation_version_id, after_sequence, limit + 1),
            maximum=limit + 1,
        )
        items = tuple(
            ReviewHistoryEntry(
                review_event_id=row[0],
                command_key=row[1],
                event_sequence=row[2],
                prior_event_id=row[3],
                prior_state=row[4],
                decision=row[5],
                new_state=row[6],
                rationale=row[7],
                conditions=_json(row[8]),
                reviewer_user=row[9],
                reviewer_role=row[10],
                reviewed_at=str(row[11]),
                correction_of_event_id=row[12],
            )
            for row in rows[:limit]
        )
        sequences = [item.event_sequence for item in items]
        if sequences != sorted(set(sequences)) or any(n <= after_sequence for n in sequences):
            raise ValueError("review history sequence is ambiguous")
        return ReviewHistoryPage(
            items=items,
            next_after_sequence=items[-1].event_sequence if len(rows) > limit else None,
        )

    def append_event(self, command: ReviewCommand) -> ReviewReceipt:
        self.assert_human_session()
        rows = self._rows(
            "CALL DATASET_DISCOVERY.SP_APPEND_REVIEW_EVENT(%s)",
            (command.model_dump_json(),),
            timeout=30,
            byte_limit=4096,
        )
        if not rows or len(rows[0]) != 1:
            raise ValueError("review procedure returned no receipt")
        receipt = ReviewReceipt.model_validate(_json(rows[0][0]))
        if (
            receipt.command_key != command.command_key
            or receipt.recommendation_version_id != command.recommendation_version_id
            or receipt.decision != command.decision
        ):
            raise ValueError("review receipt differs from submitted command")
        return receipt

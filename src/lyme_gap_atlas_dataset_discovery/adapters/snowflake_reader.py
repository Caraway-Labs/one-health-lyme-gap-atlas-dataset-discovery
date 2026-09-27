"""Fixed, snapshot-pinned reads over the data-owned Dataset Discovery views."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from lyme_gap_atlas_dataset_discovery.domain.analysis import AvailableObservation
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    CandidatePage,
    CandidateSummary,
    DiscoveryContext,
    EvidenceRef,
)
from lyme_gap_atlas_dataset_discovery.domain.relationships import IdentityLink

_SUMMARY = """SELECT resource_key, catalog_dataset_id, catalog_resource_id, title, publisher
FROM DATASET_DISCOVERY.V_CANDIDATE_SUMMARY
WHERE discovery_run_id = %s AND resource_key > %s
ORDER BY resource_key LIMIT %s"""
_ONE = """SELECT resource_key, catalog_dataset_id, catalog_resource_id, title, publisher
FROM DATASET_DISCOVERY.V_CANDIDATE_SUMMARY
WHERE discovery_run_id = %s AND resource_key = %s
ORDER BY resource_key LIMIT 2"""
_EVIDENCE = """SELECT observation_id, catalog_dataset_id, catalog_resource_id,
metadata_sha256, observed_at
FROM DATASET_DISCOVERY.V_CANDIDATE_EVIDENCE
WHERE discovery_run_id = %s AND resource_key = %s
AND catalog_dataset_id = %s AND catalog_resource_id = %s
ORDER BY observed_at DESC, observation_id LIMIT %s"""
_OBSERVATIONS = """SELECT observation_id, catalog_dataset_id, catalog_resource_id,
metadata_sha256, observed_at, field_values
FROM DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS
WHERE discovery_run_id = %s AND resource_key = %s
AND catalog_dataset_id = %s AND catalog_resource_id = %s
ORDER BY observed_at DESC, observation_id LIMIT %s"""
_STATUS = """SELECT already_governed FROM DATASET_DISCOVERY.V_CANDIDATE_GOVERNED_STATUS
WHERE resource_key = %s LIMIT 2"""
_IDENTITY_LINKS = """SELECT resource_key, catalog_dataset_id, catalog_resource_id,
linked_resource_key, linked_catalog_dataset_id, linked_catalog_resource_id,
relationship, relationship_basis
FROM DATASET_DISCOVERY.V_CANDIDATE_IDENTITY_LINKS
WHERE discovery_run_id = %s AND resource_key = %s
AND catalog_dataset_id = %s AND catalog_resource_id = %s
ORDER BY CASE relationship WHEN 'EXACT_DUPLICATE' THEN 0 ELSE 1 END,
linked_resource_key, linked_catalog_resource_id LIMIT 2"""
_CONTEXT = """SELECT discovery_run_id, search_fingerprint, completed_at, status
FROM DATASET_DISCOVERY.V_DISCOVERY_CONTEXT
WHERE discovery_run_id = %s LIMIT 2"""
_FIELDS = frozenset(
    {
        "title",
        "publisher",
        "description",
        "issued",
        "modified",
        "spatial",
        "temporal",
        "license",
        "access_level",
    }
)
_FIELD_LIMITS = {
    "title": 300,
    "publisher": 200,
    "description": 500,
    "issued": 100,
    "modified": 100,
    "spatial": 300,
    "temporal": 300,
    "license": 300,
    "access_level": 100,
}


def _timestamp(value: object) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _returned_id(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or "\x00" in value:
        raise ValueError(f"invalid {label} returned by governed view")
    return value


def _fetch_bounded(cursor: Any, *, max_rows: int, max_bytes: int) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    used_bytes = 0
    while len(rows) < max_rows:
        row = cursor.fetchone()
        if row is None:
            return rows
        used_bytes += len(json.dumps(row, default=str, ensure_ascii=False).encode("utf-8"))
        if used_bytes > max_bytes:
            raise ValueError("candidate read exceeded byte limit")
        rows.append(row)
    if cursor.fetchone() is not None:
        raise ValueError("governed view exceeded row limit")
    return rows


class SnowflakeCandidateReader:
    """Read only a registered discovery run; never accept SQL from graph state."""

    def __init__(self, *, discovery_run_id: str, connect: Callable[[], Any]) -> None:
        self.discovery_run_id = _returned_id(discovery_run_id, "discovery run ID", 200)
        self._connect = connect

    def _query(
        self, sql: str, params: tuple[object, ...], *, max_bytes: int, max_rows: int
    ) -> list[tuple[Any, ...]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params, timeout=15)
            return _fetch_bounded(cursor, max_rows=max_rows, max_bytes=max_bytes)

    @staticmethod
    def _candidate_id(candidate_id: str) -> str:
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or len(candidate_id) > 500
            or "\x00" in candidate_id
        ):
            raise ValueError("invalid candidate ID or cursor")
        return candidate_id

    @staticmethod
    def _limit(limit: int) -> int:
        if type(limit) is not int or not 1 <= limit <= 25:
            raise ValueError("candidate read limit outside v1 hard maximum")
        return limit

    @staticmethod
    def _summary(row: tuple[Any, ...]) -> CandidateSummary:
        for value, maximum in ((row[3], 300), (row[4], 200)):
            if value is not None and (not isinstance(value, str) or len(value) > maximum):
                raise ValueError("candidate summary exceeded reviewed field bound")
        return CandidateSummary(
            identity=CandidateIdentity(
                resource_key=_returned_id(row[0], "resource key", 500),
                catalog_dataset_id=_returned_id(row[1], "catalog dataset ID", 200),
                catalog_resource_id=_returned_id(row[2], "catalog resource ID", 200),
            ),
            title=row[3],
            publisher=row[4],
        )

    def list_batch(self, *, cursor: str | None, limit: int) -> CandidatePage:
        page_limit = self._limit(limit)
        key = self._candidate_id(cursor) if cursor is not None else ""
        rows = self._query(
            _SUMMARY,
            (self.discovery_run_id, key, page_limit + 1),
            max_bytes=65536,
            max_rows=page_limit + 1,
        )
        if len(rows) > page_limit + 1:
            raise ValueError("candidate view exceeded requested limit")
        candidates = tuple(self._summary(row) for row in rows[:page_limit])
        keys = [item.identity.resource_key for item in candidates]
        if any(candidate_key <= key for candidate_key in keys) or keys != sorted(set(keys)):
            raise ValueError("candidate view violated keyset order")
        return CandidatePage(
            candidates=candidates,
            next_cursor=candidates[-1].identity.resource_key if len(rows) > page_limit else None,
        )

    def get_summary(self, candidate_id: str) -> CandidateSummary:
        rows = self._query(
            _ONE,
            (self.discovery_run_id, self._candidate_id(candidate_id)),
            max_bytes=8192,
            max_rows=2,
        )
        if len(rows) != 1:
            raise KeyError(candidate_id) if not rows else ValueError("ambiguous candidate identity")
        return self._summary(rows[0])

    def get_identity(self, candidate_id: str) -> CandidateIdentity:
        return self.get_summary(candidate_id).identity

    def _evidence_rows(
        self, candidate_id: str, limit: int, *, observations: bool
    ) -> list[tuple[Any, ...]]:
        identity = self.get_identity(candidate_id)
        rows = self._query(
            _OBSERVATIONS if observations else _EVIDENCE,
            (
                self.discovery_run_id,
                identity.resource_key,
                identity.catalog_dataset_id,
                identity.catalog_resource_id,
                self._limit(limit) + 1,
            ),
            max_bytes=65536,
            max_rows=limit + 1,
        )
        if any(
            row[1] != identity.catalog_dataset_id or row[2] != identity.catalog_resource_id
            for row in rows
        ):
            raise ValueError("evidence view returned another candidate's identity")
        return rows

    @staticmethod
    def _ref(row: tuple[Any, ...]) -> EvidenceRef:
        return EvidenceRef(
            observation_id=_returned_id(row[0], "observation ID", 200),
            catalog_dataset_id=_returned_id(row[1], "catalog dataset ID", 200),
            catalog_resource_id=_returned_id(row[2], "catalog resource ID", 200),
            metadata_sha256=row[3],
            observed_at=_timestamp(row[4]),
        )

    def get_evidence_refs(self, candidate_id: str, *, limit: int) -> tuple[EvidenceRef, ...]:
        rows = self._evidence_rows(candidate_id, limit, observations=False)
        refs = tuple(self._ref(row) for row in rows[:limit])
        if len({ref.observation_id for ref in refs}) != len(refs):
            raise ValueError("ambiguous duplicate observation identity")
        return refs

    def get_observations(
        self, candidate_id: str, *, limit: int
    ) -> tuple[AvailableObservation, ...]:
        rows = self._evidence_rows(candidate_id, limit, observations=True)
        result = []
        for row in rows[:limit]:
            fields = json.loads(row[5]) if isinstance(row[5], str) else row[5]
            if not isinstance(fields, dict) or set(fields) != _FIELDS:
                raise ValueError("observation fields outside allowlist")
            if any(
                value is not None
                and (not isinstance(value, str) or len(value) > _FIELD_LIMITS[key])
                for key, value in fields.items()
            ):
                raise ValueError("observation field exceeded reviewed bound")
            values = {k: v for k, v in fields.items() if isinstance(v, str) and v}
            result.append(AvailableObservation(reference=self._ref(row), field_values=values))
        if len({item.reference.observation_id for item in result}) != len(result):
            raise ValueError("ambiguous duplicate observation identity")
        return tuple(result)

    def get_governed_status(self, candidate_id: str) -> str:
        self.get_identity(candidate_id)
        rows = self._query(_STATUS, (candidate_id,), max_bytes=1024, max_rows=2)
        if len(rows) > 1:
            raise ValueError("ambiguous governed status")
        if rows and rows[0][0] is not None and type(rows[0][0]) is not bool:
            raise ValueError("invalid governed status view result")
        return "ALREADY_GOVERNED" if rows and rows[0][0] is True else "UNKNOWN"

    def get_identity_links(self, candidate_id: str) -> tuple[IdentityLink, ...]:
        identity = self.get_identity(candidate_id)
        rows = self._query(
            _IDENTITY_LINKS,
            (
                self.discovery_run_id,
                identity.resource_key,
                identity.catalog_dataset_id,
                identity.catalog_resource_id,
            ),
            max_bytes=4096,
            max_rows=2,
        )
        links = tuple(
            IdentityLink(
                candidate=CandidateIdentity(
                    resource_key=_returned_id(row[0], "resource key", 500),
                    catalog_dataset_id=_returned_id(row[1], "catalog dataset ID", 200),
                    catalog_resource_id=_returned_id(row[2], "catalog resource ID", 200),
                ),
                linked_resource_key=_returned_id(row[3], "linked resource key", 500),
                linked_catalog_dataset_id=_returned_id(row[4], "linked dataset ID", 200),
                linked_catalog_resource_id=_returned_id(row[5], "linked resource ID", 200),
                relationship=row[6],
                basis=row[7],
            )
            for row in rows
        )
        if any(link.candidate != identity for link in links):
            raise ValueError("identity link view returned another candidate")
        return links


class SnowflakeDiscoveryContextReader:
    """Validate that the requested catalog snapshot actually completed."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def get_context(self, discovery_run_id: str) -> DiscoveryContext:
        discovery_run_id = _returned_id(discovery_run_id, "discovery run ID", 200)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(_CONTEXT, (discovery_run_id,), timeout=15)
            rows = _fetch_bounded(cursor, max_rows=2, max_bytes=2048)
        if len(rows) != 1:
            raise KeyError(discovery_run_id) if not rows else ValueError("ambiguous discovery run")
        row = rows[0]
        return DiscoveryContext(
            discovery_run_id=_returned_id(row[0], "discovery run ID", 200),
            search_fingerprint=str(row[1]),
            completed_at=_timestamp(row[2]),
            status=str(row[3]),
        )

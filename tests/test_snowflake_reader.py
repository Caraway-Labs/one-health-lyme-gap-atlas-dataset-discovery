"""Contract checks without credentials or a live Snowflake connection."""

from datetime import UTC, datetime
from typing import Any

import pytest

from lyme_gap_atlas_dataset_discovery.adapters.snowflake_reader import (
    SnowflakeCandidateReader,
    SnowflakeDiscoveryContextReader,
)


class Cursor:
    def __init__(self, connection: "Connection") -> None:
        self.connection = connection
        self.rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> "Cursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.connection.calls.append((sql, params))
        self.rows = self.connection.responses.pop(0)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class Connection:
    def __init__(self, *responses: list[tuple[Any, ...]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def cursor(self) -> Cursor:
        return Cursor(self)


def summary(key: str) -> tuple[str, str, str, str, str]:
    return key, "dataset-1", "resource-1", "Title", "Publisher"


def test_keyset_page_is_pinned_and_parameterized() -> None:
    db = Connection([summary("a"), summary("b"), summary("c")])
    reader = SnowflakeCandidateReader(discovery_run_id="snapshot-1", connect=lambda: db)
    page = reader.list_batch(cursor=None, limit=2)
    assert [item.identity.resource_key for item in page.candidates] == ["a", "b"]
    assert page.next_cursor == "b"
    sql, params = db.calls[0]
    assert "V_CANDIDATE_SUMMARY" in sql
    assert "discovery_run_id = %s" in sql
    assert "ORDER BY resource_key LIMIT %s" in sql
    assert params == ("snapshot-1", "", 3)


def test_evidence_query_pins_snapshot_and_exact_resource_identity() -> None:
    stamp = datetime(2026, 9, 26, tzinfo=UTC)
    evidence = ("observation-1", "dataset-1", "resource-1", "a" * 64, stamp)
    db = Connection([summary("key")], [evidence])
    reader = SnowflakeCandidateReader(discovery_run_id="snapshot-1", connect=lambda: db)
    refs = reader.get_evidence_refs("key", limit=2)
    assert refs[0].observation_id == "observation-1"
    sql, params = db.calls[-1]
    assert "V_CANDIDATE_EVIDENCE" in sql
    assert "catalog_dataset_id = %s AND catalog_resource_id = %s" in sql
    assert params == ("snapshot-1", "key", "dataset-1", "resource-1", 3)


def test_observation_rejects_unreviewed_field() -> None:
    stamp = datetime(2026, 9, 26, tzinfo=UTC)
    db = Connection(
        [summary("key")],
        [("obs", "dataset-1", "resource-1", None, stamp, {"private_payload": "secret"})],
    )
    reader = SnowflakeCandidateReader(discovery_run_id="snapshot-1", connect=lambda: db)
    with pytest.raises(ValueError, match="allowlist"):
        reader.get_observations("key", limit=1)


def test_invalid_cursor_fails_before_query() -> None:
    db = Connection()
    reader = SnowflakeCandidateReader(discovery_run_id="snapshot-1", connect=lambda: db)
    with pytest.raises(ValueError):
        reader.list_batch(cursor="x" * 513, limit=1)
    assert db.calls == []


def test_oversize_result_fails_closed() -> None:
    db = Connection([("key", "dataset-1", "resource-1", "x" * 9000, "publisher")])
    reader = SnowflakeCandidateReader(discovery_run_id="snapshot-1", connect=lambda: db)
    with pytest.raises(ValueError, match="byte limit"):
        reader.get_summary("key")


def test_discovery_context_is_fixed_snapshot_query_and_requires_completion() -> None:
    stamp = datetime(2026, 9, 26, tzinfo=UTC)
    db = Connection([("run-1", "a" * 64, stamp, "COMPLETED")])
    reader = SnowflakeDiscoveryContextReader(connect=lambda: db)
    context = reader.get_context("run-1")
    assert context.search_fingerprint == "a" * 64
    assert db.calls[0][1] == ("run-1",)
    assert "V_DISCOVERY_CONTEXT" in db.calls[0][0]

    incomplete = Connection([("run-1", "a" * 64, stamp, "RUNNING")])
    with pytest.raises(ValueError):
        SnowflakeDiscoveryContextReader(connect=lambda: incomplete).get_context("run-1")

"""Fixed SQL and receipt tests; no Snowflake credentials or network required."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from test_fake_persistence import recommendation

from lyme_gap_atlas_dataset_discovery.adapters.snowflake_repository import (
    SnowflakeRecommendationRepository,
)
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateOutcomeReceipt,
    RunCreateMetadata,
    RunFinalizationReceipt,
)


@dataclass
class StubConnection:
    responses: list[list[tuple[Any, ...]]]
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    closed_cursors: int = 0

    def cursor(self) -> "StubCursor":
        return StubCursor(self, self.responses.pop(0))


@dataclass
class StubCursor:
    connection: StubConnection
    rows: list[tuple[Any, ...]]

    def execute(self, sql: str, params: Sequence[object] = ()) -> "StubCursor":
        self.connection.calls.append((sql, tuple(params)))
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows.pop(0) if self.rows else None

    def close(self) -> None:
        self.connection.closed_cursors += 1


def metadata() -> RunCreateMetadata:
    return RunCreateMetadata(
        mode="DEV_MANUAL",
        trigger_type="MANUAL",
        code_sha="a" * 40,
        spec_version="v1",
        graph_version="v1",
        config_fingerprint="b" * 64,
        search_fingerprint="c" * 64,
        evidence_snapshot_id="snapshot-1",
    )


def test_create_run_calls_only_fixed_procedure_and_recovers_receipt() -> None:
    meta = metadata()
    receipt = {
        "operation_key": "run-key",
        "run_id": "run-1",
        "retry_of_run_id": None,
        "request_fingerprint": meta.request_fingerprint,
    }
    connection = StubConnection(
        [[((json.dumps(receipt)),)], [("run-1", "run-key", None, meta.request_fingerprint)]]
    )
    repository = SnowflakeRecommendationRepository(connection)

    assert (
        repository.create_run(operation_key="run-key", run_id="run-1", metadata=meta).run_id
        == "run-1"
    )
    recovered = repository.get_run("run-key")
    assert recovered is not None
    assert recovered.request_fingerprint == meta.request_fingerprint
    call, params = connection.calls[0]
    assert call == "CALL DATASET_DISCOVERY.SP_CREATE_RUN(%s, %s, %s, %s)"
    assert params[:3] == ("run-key", "run-1", None)
    assert json.loads(str(params[3]))["request_fingerprint"] == meta.request_fingerprint
    assert "V_RUN_RECEIPTS" in connection.calls[1][0]
    assert connection.closed_cursors == 2


def test_outcome_and_finalization_use_procedures_and_typed_receipts() -> None:
    outcome = CandidateOutcomeReceipt(
        operation_key="outcome:run-1:resource",
        run_id="run-1",
        resource_key="resource",
        catalog_dataset_id="dataset",
        catalog_resource_id="catalog-resource",
        evidence_snapshot_id="snapshot-1",
        outcome="INSUFFICIENT_EVIDENCE",
    )
    final = RunFinalizationReceipt(
        operation_key="finalize:run-1",
        run_id="run-1",
        status="PARTIAL",
        processed_count=1,
        recommendation_count=0,
        budget_usage={"candidates": 1},
    )
    connection = StubConnection(
        [
            [(outcome.model_dump(),)],
            [(final.model_dump(),)],
            [("finalize:run-1", "run-1", "PARTIAL", 1, 0, '{"candidates":1}', None)],
        ]
    )
    repository = SnowflakeRecommendationRepository(connection)
    assert repository.record_candidate_outcome(outcome) == outcome
    assert repository.finalize_run(final) == final
    assert repository.get_finalization("run-1") == final
    assert connection.calls[0][0] == "CALL DATASET_DISCOVERY.SP_RECORD_CANDIDATE_OUTCOME(%s)"
    assert connection.calls[1][0] == "CALL DATASET_DISCOVERY.SP_FINALIZE_RUN(%s)"
    assert "V_FINALIZATION_RECEIPTS" in connection.calls[2][0]


def test_recommendation_bundle_uses_atomic_procedure_and_receipt_view() -> None:
    request = recommendation("run-1", "version-1")
    expected = {
        "operation_key": request.operation_key,
        "identity": request.identity.model_dump(),
        "assertion_sha256": request.assertion_sha256,
        "evidence_observation_ids": ["obs-1"],
        "proposal_ids": [],
    }
    connection = StubConnection(
        [
            [(expected,)],
            [
                (
                    request.operation_key,
                    request.identity.recommendation_id,
                    request.identity.recommendation_version_id,
                    request.identity.run_id,
                    request.identity.resource_key,
                    None,
                    request.assertion_sha256,
                    '["obs-1"]',
                    None,
                )
            ],
        ]
    )
    repository = SnowflakeRecommendationRepository(connection)
    written = repository.save_recommendation(request)
    assert written == repository.get_recommendation(request.operation_key)
    assert connection.calls[0][0] == "CALL DATASET_DISCOVERY.SP_COMMIT_RECOMMENDATION(%s)"
    submitted = json.loads(str(connection.calls[0][1][0]))
    assert submitted["assertion_sha256"] == request.assertion_sha256
    assert submitted["evidence_snapshot_id"] == "fixture-snapshot"
    assert submitted["rationale"] == request.rationale
    assert "V_RECOMMENDATION_RECEIPTS" in connection.calls[1][0]


def test_duplicate_or_invalid_receipt_fails_closed() -> None:
    connection = StubConnection([[("run-1", "key", None, None), ("run-2", "key", None, None)]])
    with pytest.raises(ValueError, match="duplicate"):
        SnowflakeRecommendationRepository(connection).get_run("key")
    assert connection.closed_cursors == 1

    connection = StubConnection([[(["not-an-object"],)]])
    with pytest.raises(ValueError, match="not an object"):
        SnowflakeRecommendationRepository(connection).record_candidate_outcome(
            CandidateOutcomeReceipt(
                operation_key="o",
                run_id="r",
                resource_key="resource",
                catalog_dataset_id="dataset",
                catalog_resource_id="catalog-resource",
                evidence_snapshot_id="snapshot",
                outcome="INSUFFICIENT_EVIDENCE",
            )
        )

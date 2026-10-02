"""Failure/recovery uses original logical identities and no automatic write retry."""

from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from snowflake.connector.errorcode import ER_CONNECTION_IS_CLOSED, ER_CONNECTION_TIMEOUT
from snowflake.connector.errors import OperationalError, ProgrammingError
from test_handoff_client import EVENT, VERSION, fake_connection, receipt
from test_snowflake_repository import StubConnection, StubCursor
from test_snowflake_review import principal

from lyme_gap_atlas_dataset_discovery import review_cli
from lyme_gap_atlas_dataset_discovery.adapters.handoff_errors import classify_handoff_error
from lyme_gap_atlas_dataset_discovery.adapters.snowflake_handoff import SnowflakeHumanHandoffClient
from lyme_gap_atlas_dataset_discovery.domain.handoff import (
    HandoffFailureKind,
    HandoffOperationError,
)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("private provider text"),
        ConnectionResetError("private provider text"),
        OperationalError(msg="private provider text", errno=ER_CONNECTION_TIMEOUT),
        OperationalError(msg="private provider text", errno=ER_CONNECTION_IS_CLOSED),
        OperationalError(msg="private provider text", sqlstate="08006"),
        OperationalError(msg="private provider text", sqlstate="08007"),
        OperationalError(msg="private provider text", sqlstate="40001"),
    ],
)
def test_known_transport_failure_is_retryable_and_sanitized(error: Exception) -> None:
    assert isinstance(error, (OperationalError, TimeoutError, ConnectionError))
    classified = classify_handoff_error(error)
    assert classified.kind == HandoffFailureKind.RETRYABLE_FAILURE
    assert str(classified) == "RETRYABLE_FAILURE"


@pytest.mark.parametrize("sqlstate", ["42501", "28000", "P0001", "08004", None])
def test_authorization_business_and_unknown_errors_are_terminal(sqlstate: str | None) -> None:
    error = ProgrammingError(msg="private SQL and account details", sqlstate=sqlstate)
    classified = classify_handoff_error(error)
    assert classified.kind == HandoffFailureKind.TERMINAL_FAILURE
    assert str(classified) == "TERMINAL_FAILURE"


@dataclass
class LostAckCursor(StubCursor):
    def execute(
        self, sql: str, params: Sequence[object] = (), *, timeout: int | None = None
    ) -> StubCursor:
        result = super().execute(sql, params, timeout=timeout)
        if sql.startswith("CALL "):
            raise TimeoutError("private acknowledgement text")
        return result


class LostAckConnection(StubConnection):
    def cursor(self) -> StubCursor:
        return LostAckCursor(self, self.responses.pop(0))


def test_lost_ack_closes_cursor_and_recovers_without_second_write() -> None:
    payload = receipt()
    connection = LostAckConnection(
        [
            [principal()],
            [],  # Simulates a committed call whose acknowledgement is lost.
            [principal()],
            [tuple(payload.values()) + ("2026-09-28T00:00:00Z",)],
        ]
    )
    client = SnowflakeHumanHandoffClient(connection)
    with pytest.raises(HandoffOperationError) as caught:
        client.submit(VERSION, EVENT)
    assert caught.value.kind == HandoffFailureKind.RETRYABLE_FAILURE
    assert caught.value.__suppress_context__
    recovered = client.get_status(VERSION)
    assert recovered is not None
    assert recovered.review_event_id == EVENT
    assert recovered.handoff_id == payload["handoff_id"]
    writes = [call for call in connection.calls if call[0].startswith("CALL ")]
    assert len(writes) == 1
    assert writes[0][1] == (VERSION, EVENT)
    assert connection.closed_cursors == 4


@pytest.mark.parametrize(
    "kind,exit_code",
    [(HandoffFailureKind.RETRYABLE_FAILURE, 1), (HandoffFailureKind.TERMINAL_FAILURE, 2)],
)
def test_cli_classified_failure_is_safe_and_does_not_resubmit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: HandoffFailureKind,
    exit_code: int,
) -> None:
    calls: list[tuple[str, str]] = []

    class FailedService:
        def submit(self, version: str, event: str) -> None:
            calls.append((version, event))
            raise HandoffOperationError(kind)

    monkeypatch.setattr(review_cli, "_open_connection", fake_connection)
    monkeypatch.setattr(review_cli, "HumanReviewService", lambda _: object())
    monkeypatch.setattr(review_cli, "HumanHandoffService", lambda _: FailedService())
    result = review_cli.main(
        ["--connection", "TEST_REVIEWER", "handoff", VERSION, "--review-event-id", EVENT]
    )
    assert result == exit_code
    output = capsys.readouterr()
    assert output.out == ""
    assert kind.value in output.err
    assert "private" not in output.err
    assert calls == [(VERSION, EVENT)]

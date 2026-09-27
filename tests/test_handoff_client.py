"""Human-only governed handoff uses a fixed, version-pinned procedure."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from test_human_review import detail
from test_snowflake_repository import StubConnection
from test_snowflake_review import principal

from lyme_gap_atlas_dataset_discovery import review_cli
from lyme_gap_atlas_dataset_discovery.adapters.fake_handoff import FakeHumanHandoffClient
from lyme_gap_atlas_dataset_discovery.adapters.fake_review import FakeHumanReviewRepository
from lyme_gap_atlas_dataset_discovery.adapters.snowflake_handoff import (
    SnowflakeHumanHandoffClient,
)
from lyme_gap_atlas_dataset_discovery.domain.review import ReviewDecision
from lyme_gap_atlas_dataset_discovery.handoff_service import HumanHandoffService
from lyme_gap_atlas_dataset_discovery.review_service import HumanReviewService

VERSION = "a" * 64
EVENT = "b" * 64
KEY = f"handoff-v1:{VERSION}"
HANDOFF_ID = hashlib.sha256(KEY.encode()).hexdigest()


def receipt() -> dict[str, str]:
    return {
        "handoff_id": HANDOFF_ID,
        "operation_key": KEY,
        "recommendation_version_id": VERSION,
        "review_event_id": EVENT,
        "relationship_type": "DISTINCT",
        "disposition": "HANDED_OFF",
        "investigation_status": "PENDING",
        "acquisition_boundary": "NO_AUTOMATED_ACQUISITION",
    }


def test_handoff_uses_fixed_procedure_with_no_asserted_reviewer_or_rights() -> None:
    connection = StubConnection([[principal()], [((json.dumps(receipt())),)]])
    service = HumanHandoffService(SnowflakeHumanHandoffClient(connection))
    # Service construction and the call both verify the human session.
    connection.responses.insert(0, [principal()])
    result = service.submit(VERSION, EVENT)
    assert result.handoff_id == HANDOFF_ID
    assert connection.calls[-1][0] == (
        "CALL GOVERNANCE.SP_HANDOFF_DATASET_DISCOVERY_RECOMMENDATION(%s, %s)"
    )
    assert connection.calls[-1][1] == (VERSION, EVENT)
    assert connection.calls[-1][2] == 30


@pytest.mark.parametrize(
    "principal_type,role",
    [
        ("USER_SERVICE", "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER"),
        ("TASK", "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER"),
        ("USER_PERSON", "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME"),
    ],
)
def test_runtime_and_task_cannot_submit_handoff(principal_type: str, role: str) -> None:
    connection = StubConnection([[principal(principal_type=principal_type, role=role)]])
    with pytest.raises(PermissionError, match="reviewer role"):
        HumanHandoffService(SnowflakeHumanHandoffClient(connection))
    assert len(connection.calls) == 1


def test_status_reconciles_lost_ack_from_exact_logical_key() -> None:
    row = receipt()
    connection = StubConnection(
        [
            [principal()],
            [
                (
                    row["handoff_id"],
                    row["operation_key"],
                    row["recommendation_version_id"],
                    row["review_event_id"],
                    row["relationship_type"],
                    row["disposition"],
                    row["investigation_status"],
                    row["acquisition_boundary"],
                    "2026-09-26T00:00:00Z",
                )
            ],
        ]
    )
    result = SnowflakeHumanHandoffClient(connection).get_status(VERSION)
    assert result is not None and result.review_event_id == EVENT
    assert connection.calls[-1][0].endswith("WHERE operation_key = %s")
    assert connection.calls[-1][1] == (KEY,)


def test_conflicting_or_wrong_receipt_fails_closed() -> None:
    wrong = receipt() | {"review_event_id": "c" * 64}
    connection = StubConnection([[principal()], [((wrong),)]])
    with pytest.raises(ValueError, match="differs"):
        SnowflakeHumanHandoffClient(connection).submit(VERSION, EVENT)


def test_invalid_event_does_not_call_handoff_procedure() -> None:
    connection = StubConnection([[principal()]])
    with pytest.raises(ValueError, match="review event ID"):
        SnowflakeHumanHandoffClient(connection).submit(VERSION, "not-an-event")
    assert len(connection.calls) == 1


def test_fake_handoff_requires_exact_accepted_review_and_replays_once() -> None:
    review = FakeHumanReviewRepository(details={VERSION: detail(VERSION)})
    handoff = FakeHumanHandoffClient(review=review)
    service = HumanHandoffService(handoff)
    with pytest.raises(ValueError, match="rejected or stale"):
        service.submit(VERSION, EVENT)
    accepted = HumanReviewService(review).decide(
        VERSION, ReviewDecision.ACCEPT_FOR_INVESTIGATION, rationale="Investigate source"
    )
    first = service.submit(VERSION, accepted.review_event_id)
    assert first.disposition == "HANDED_OFF"
    assert service.submit(VERSION, accepted.review_event_id) == first
    assert len(handoff.receipts) == 1
    with pytest.raises(ValueError, match="conflicting"):
        service.submit(VERSION, EVENT)


@pytest.mark.parametrize(
    "finding,controlled,governed,expected,boundary",
    [
        (None, False, False, "HANDED_OFF", "INVESTIGATE_BEFORE_ACQUISITION"),
        ("RIGHTS_UNKNOWN", False, False, "HANDED_OFF", "INVESTIGATE_BEFORE_ACQUISITION"),
        ("KNOWN_RESTRICTED", False, False, "HANDED_OFF", "NO_AUTOMATED_ACQUISITION"),
        (None, True, False, "HANDED_OFF", "NO_AUTOMATED_ACQUISITION"),
        (None, False, True, "ALREADY_GOVERNED", "INVESTIGATE_BEFORE_ACQUISITION"),
        ("KNOWN_PROHIBITED", False, False, "POLICY_BLOCKED", "NO_AUTOMATED_ACQUISITION"),
    ],
)
def test_fake_rights_and_existing_source_classification(
    finding: str | None, controlled: bool, governed: bool, expected: str, boundary: str
) -> None:
    source = detail(VERSION)
    review = FakeHumanReviewRepository(details={VERSION: source})
    accepted = HumanReviewService(review).decide(
        VERSION, ReviewDecision.ACCEPT_FOR_INVESTIGATION, rationale="Investigate"
    )
    client = FakeHumanHandoffClient(
        review=review,
        reviewed_rights={source.resource_key: finding} if finding else {},
        controlled_access={source.resource_key} if controlled else set(),
        already_governed={source.resource_key} if governed else set(),
    )
    result = HumanHandoffService(client).submit(VERSION, accepted.review_event_id)
    assert result.disposition == expected
    assert result.acquisition_boundary == boundary


def test_fake_runtime_principal_cannot_impersonate_handoff_reviewer() -> None:
    review = FakeHumanReviewRepository(
        principal_type="USER_SERVICE", details={VERSION: detail(VERSION)}
    )
    with pytest.raises(PermissionError, match="reviewer"):
        HumanHandoffService(FakeHumanHandoffClient(review=review))


@contextmanager
def fake_connection(_: str) -> Iterator[object]:
    yield object()


def test_cli_handoff_sends_exact_version_and_event_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    review = FakeHumanReviewRepository(details={VERSION: detail(VERSION)})
    accepted = HumanReviewService(review).decide(
        VERSION, ReviewDecision.ACCEPT_FOR_INVESTIGATION, rationale="Investigate"
    )
    handoff = FakeHumanHandoffClient(review=review)
    monkeypatch.setattr(review_cli, "_open_connection", fake_connection)
    monkeypatch.setattr(review_cli, "SnowflakeHumanReviewRepository", lambda _: review)
    monkeypatch.setattr(review_cli, "SnowflakeHumanHandoffClient", lambda _: handoff)
    assert (
        review_cli.main(
            [
                "--connection",
                "review_pat",
                "handoff",
                VERSION,
                "--review-event-id",
                accepted.review_event_id,
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["disposition"] == "HANDED_OFF"
    assert len(handoff.receipts) == 1
    with pytest.raises(SystemExit):
        review_cli.build_parser().parse_args(
            ["--connection", "review_pat", "handoff", VERSION, "--reviewer", "alice"]
        )

"""Fixed review SQL boundary and CLI identity tests, without credentials."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from test_human_review import detail
from test_snowflake_repository import StubConnection

from lyme_gap_atlas_dataset_discovery import review_cli
from lyme_gap_atlas_dataset_discovery.adapters.fake_review import FakeHumanReviewRepository
from lyme_gap_atlas_dataset_discovery.adapters.snowflake_review import (
    SnowflakeHumanReviewRepository,
)
from lyme_gap_atlas_dataset_discovery.domain.review import (
    ReviewDecision,
    make_review_command,
)


def principal(
    *, principal_type: str = "USER_PERSON", role: str = "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER"
) -> tuple[str, str, str, str, str]:
    return (
        "ALICE",
        principal_type,
        role,
        "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        "REVIEW_WH",
    )


def test_review_write_uses_session_identity_and_no_asserted_reviewer() -> None:
    command = make_review_command(
        recommendation_version_id="version-1",
        decision=ReviewDecision.REJECT,
        rationale="Insufficient scope",
    )
    expected = {
        "review_event_id": "a" * 64,
        "command_key": command.command_key,
        "recommendation_version_id": "version-1",
        "prior_event_id": None,
        "prior_state": "PENDING",
        "new_state": "REJECTED",
        "decision": "REJECT",
        "reviewer_user": "ALICE",
        "reviewer_role": "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER",
        "event_sequence": 5,
    }
    connection = StubConnection([[principal()], [(expected,)]])
    repository = SnowflakeHumanReviewRepository(connection)
    assert repository.append_event(command).reviewer_user == "ALICE"
    assert "SNOWFLAKE$SESSION" in connection.calls[0][0]
    assert connection.calls[1][0] == "CALL DATASET_DISCOVERY.SP_APPEND_REVIEW_EVENT(%s)"
    submitted = json.loads(str(connection.calls[1][1][0]))
    assert submitted["recommendation_version_id"] == "version-1"
    assert "reviewer_user" not in submitted
    assert "reviewer_role" not in submitted
    assert connection.calls[1][2] == 30


@pytest.mark.parametrize(
    "principal_type,role",
    [
        ("USER_SERVICE", "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER"),
        ("TASK", "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER"),
        ("USER_PERSON", "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME"),
    ],
)
def test_review_adapter_rejects_runtime_or_service_before_procedure(
    principal_type: str, role: str
) -> None:
    connection = StubConnection([[principal(principal_type=principal_type, role=role)]])
    command = make_review_command(
        recommendation_version_id="version-1",
        decision=ReviewDecision.REJECT,
        rationale="No",
    )
    with pytest.raises(PermissionError, match="reviewer role"):
        SnowflakeHumanReviewRepository(connection).append_event(command)
    assert len(connection.calls) == 1


def test_review_detail_and_evidence_are_exact_version_reads() -> None:
    source = detail("version-1")
    row: tuple[Any, ...] = (
        source.recommendation_version_id,
        source.recommendation_id,
        source.run_id,
        source.resource_key,
        source.catalog_dataset_id,
        source.catalog_resource_id,
        source.evidence_snapshot_id,
        source.assertion_sha256,
        source.classification,
        source.relationship_type,
        source.relationship_basis,
        source.rights_state,
        json.dumps([fact.model_dump(mode="json") for fact in source.observed_facts]),
        [],
        [],
        source.dimensions.model_dump(mode="json"),
        source.ranking_formula_version,
        source.relationship_adjustment,
        source.missing_count,
        source.priority_score,
        source.priority_bucket,
        source.rank_in_run,
        source.rationale,
        source.created_at,
        source.review_state,
        None,
    )
    item = source.evidence[0]
    evidence_row = (
        item.recommendation_version_id,
        item.observation_id,
        item.catalog_dataset_id,
        item.catalog_resource_id,
        item.field_name,
        item.metadata_sha256,
        item.observed_at,
    )
    connection = StubConnection([[principal()], [row], [evidence_row]])
    recovered = SnowflakeHumanReviewRepository(connection).get_detail("version-1")
    assert recovered == source
    assert "V_REVIEW_RECOMMENDATION_DETAIL" in connection.calls[1][0]
    assert "V_REVIEW_EVIDENCE" in connection.calls[2][0]
    assert connection.calls[1][1] == ("version-1",)


def test_review_detail_rejects_wrong_candidate_evidence() -> None:
    source = detail("version-1")
    row: tuple[Any, ...] = (
        source.recommendation_version_id,
        source.recommendation_id,
        source.run_id,
        source.resource_key,
        source.catalog_dataset_id,
        source.catalog_resource_id,
        source.evidence_snapshot_id,
        source.assertion_sha256,
        source.classification,
        source.relationship_type,
        source.relationship_basis,
        source.rights_state,
        [fact.model_dump(mode="json") for fact in source.observed_facts],
        [],
        [],
        source.dimensions.model_dump(mode="json"),
        source.ranking_formula_version,
        source.relationship_adjustment,
        source.missing_count,
        source.priority_score,
        source.priority_bucket,
        source.rank_in_run,
        source.rationale,
        source.created_at,
        source.review_state,
        None,
    )
    item = source.evidence[0]
    evidence_row = (
        item.recommendation_version_id,
        item.observation_id,
        "another-dataset",
        item.catalog_resource_id,
        item.field_name,
        item.metadata_sha256,
        item.observed_at,
    )
    connection = StubConnection([[principal()], [row], [evidence_row]])
    with pytest.raises(ValueError, match="immutable observed facts"):
        SnowflakeHumanReviewRepository(connection).get_detail("version-1")


def test_pending_list_is_rank_paged() -> None:
    source = detail("version-1")
    row = (
        source.recommendation_version_id,
        source.recommendation_id,
        source.run_id,
        source.resource_key,
        source.priority_bucket,
        source.priority_score,
        source.rank_in_run,
        source.rationale,
        source.rights_state,
        source.created_at,
        source.review_state,
        None,
    )
    connection = StubConnection([[principal()], [row]])
    page = SnowflakeHumanReviewRepository(connection).list_pending("run-1", after_rank=0, limit=1)
    assert page.items[0].recommendation_version_id == "version-1"
    assert page.next_after_rank is None
    assert connection.calls[1][1] == ("run-1", 0, 2)


@contextmanager
def fake_connection(_: str) -> Iterator[object]:
    yield object()


def test_cli_has_no_reviewer_argument_and_uses_human_service(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FakeHumanReviewRepository(details={"version-1": detail("version-1")})
    monkeypatch.setattr(review_cli, "_open_connection", fake_connection)
    monkeypatch.setattr(review_cli, "SnowflakeHumanReviewRepository", lambda _: repository)
    assert (
        review_cli.main(
            [
                "--connection",
                "review_pat",
                "accept-for-investigation",
                "version-1",
                "--rationale",
                "Investigate rights",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["reviewer_user"] == "human-reviewer"
    assert output["new_state"] == "ACCEPTED_FOR_INVESTIGATION"
    with pytest.raises(SystemExit):
        review_cli.build_parser().parse_args(
            ["--connection", "review_pat", "show", "version-1", "--reviewer", "alice"]
        )


def test_cli_forces_named_pat_without_authentication_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import snowflake.connector

    captured: dict[str, object] = {}

    def connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(snowflake.connector, "connect", connect)
    review_cli._open_connection("human_pat")
    assert captured == {
        "connection_name": "human_pat",
        "authenticator": "PROGRAMMATIC_ACCESS_TOKEN",
        "login_timeout": 15,
        "network_timeout": 30,
    }

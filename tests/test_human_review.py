"""Human-only review lifecycle, exact version lineage, and replay tests."""

import pytest
from test_fake_persistence import recommendation

from lyme_gap_atlas_dataset_discovery.adapters.fake_review import FakeHumanReviewRepository
from lyme_gap_atlas_dataset_discovery.domain.review import (
    ReviewCommand,
    ReviewDecision,
    ReviewDetail,
    ReviewEvidence,
    ReviewState,
    make_review_command,
)
from lyme_gap_atlas_dataset_discovery.review_service import HumanReviewService


def detail(version_id: str, *, rank: int = 1) -> ReviewDetail:
    assertion = recommendation("run-1", version_id)
    fact = assertion.analysis.observed_facts[0]
    return ReviewDetail(
        recommendation_version_id=version_id,
        recommendation_id=assertion.identity.recommendation_id,
        run_id="run-1",
        resource_key=assertion.identity.resource_key,
        catalog_dataset_id=assertion.analysis.identity.catalog_dataset_id,
        catalog_resource_id=assertion.analysis.identity.catalog_resource_id,
        evidence_snapshot_id=assertion.evidence_snapshot_id,
        assertion_sha256=assertion.assertion_sha256,
        classification=assertion.analysis.classification,
        relationship_type=assertion.relationship.relationship,
        relationship_basis=assertion.relationship.basis,
        rights_state=assertion.rights_state,
        observed_facts=assertion.analysis.observed_facts,
        inferences=assertion.analysis.inferences,
        unknowns=assertion.analysis.unknowns,
        dimensions=assertion.ranking_input.dimensions,
        ranking_formula_version=assertion.priority.formula_version,
        relationship_adjustment=assertion.priority.relationship_adjustment,
        missing_count=assertion.priority.missing_count,
        priority_score=assertion.priority.score,
        priority_bucket=assertion.priority.bucket,
        rank_in_run=rank,
        rationale=assertion.rationale,
        created_at="fixture-created",
        review_state=ReviewState.PENDING,
        latest_review_event_id=None,
        evidence=(
            ReviewEvidence(
                recommendation_version_id=version_id,
                observation_id=fact.evidence.observation_id,
                catalog_dataset_id=fact.evidence.catalog_dataset_id,
                catalog_resource_id=fact.evidence.catalog_resource_id,
                field_name=fact.field,
                metadata_sha256=fact.evidence.metadata_sha256,
                observed_at=fact.evidence.observed_at,
            ),
        ),
    )


@pytest.mark.parametrize(
    "principal_type,role,allowlisted",
    [
        ("USER_SERVICE", "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER", True),
        ("TASK", "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER", True),
        ("USER_PERSON", "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME", True),
        ("USER_PERSON", "OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER", False),
    ],
)
def test_runtime_or_unauthorized_identity_cannot_be_reviewer(
    principal_type: str, role: str, allowlisted: bool
) -> None:
    repository = FakeHumanReviewRepository(
        principal_type=principal_type,
        reviewer_role=role,
        allowlisted=allowlisted,
        details={"version-1": detail("version-1")},
    )
    with pytest.raises(PermissionError, match="individually authenticated"):
        HumanReviewService(repository)
    command = make_review_command(
        recommendation_version_id="version-1",
        decision=ReviewDecision.REJECT,
        rationale="Not suitable",
    )
    with pytest.raises(PermissionError):
        repository.append_event(command)


def test_acceptance_is_exact_version_attributable_and_replay_safe() -> None:
    repository = FakeHumanReviewRepository(details={"version-1": detail("version-1")})
    service = HumanReviewService(repository)
    first = service.decide(
        "version-1",
        ReviewDecision.ACCEPT_FOR_INVESTIGATION,
        rationale="Investigate documentation and access",
    )
    replay = service.decide(
        "version-1",
        ReviewDecision.ACCEPT_FOR_INVESTIGATION,
        rationale="Investigate documentation and access",
    )
    assert replay == first
    assert first.recommendation_version_id == "version-1"
    assert first.reviewer_user == "human-reviewer"
    assert first.new_state == ReviewState.ACCEPTED_FOR_INVESTIGATION
    assert len(repository.events["version-1"]) == 1
    assert service.show("version-1").latest_review_event_id == first.review_event_id
    with pytest.raises(ValueError, match="terminal"):
        service.decide(
            "version-1",
            ReviewDecision.REJECT,
            rationale="Changed view",
            expected_prior_event_id=first.review_event_id,
        )


def test_more_information_then_accept_and_stale_command_rejected() -> None:
    repository = FakeHumanReviewRepository(details={"version-1": detail("version-1")})
    service = HumanReviewService(repository)
    request = service.decide(
        "version-1",
        ReviewDecision.REQUEST_MORE_INFORMATION,
        rationale="Need a data dictionary",
    )
    pending = service.list_pending("run-1")
    assert pending.items[0].review_state == ReviewState.NEEDS_MORE_INFORMATION
    with pytest.raises(ValueError, match="stale"):
        service.decide(
            "version-1",
            ReviewDecision.ACCEPT_FOR_INVESTIGATION,
            rationale="Now documented",
        )
    accepted = service.decide(
        "version-1",
        ReviewDecision.ACCEPT_FOR_INVESTIGATION,
        rationale="Now documented",
        expected_prior_event_id=request.review_event_id,
    )
    assert accepted.prior_event_id == request.review_event_id
    assert service.list_pending("run-1").items == ()
    first_page = service.history("version-1", limit=1)
    assert first_page.next_after_sequence == request.event_sequence
    second_page = service.history(
        "version-1", after_sequence=first_page.next_after_sequence, limit=1
    )
    assert second_page.items[0].review_event_id == accepted.review_event_id


def test_terminal_correction_is_explicit_and_append_only() -> None:
    repository = FakeHumanReviewRepository(details={"version-1": detail("version-1")})
    service = HumanReviewService(repository)
    rejected = service.decide("version-1", ReviewDecision.REJECT, rationale="Missing scope")
    with pytest.raises(ValueError, match="requires correction"):
        service.decide(
            "version-1",
            ReviewDecision.REQUEST_MORE_INFORMATION,
            rationale="Correction",
            expected_prior_event_id=rejected.review_event_id,
        )
    corrected = service.decide(
        "version-1",
        ReviewDecision.REQUEST_MORE_INFORMATION,
        rationale="Scope document found",
        expected_prior_event_id=rejected.review_event_id,
        correction_of_event_id=rejected.review_event_id,
    )
    assert corrected.prior_state == ReviewState.REJECTED
    assert [event.new_state for event in repository.events["version-1"]] == [
        ReviewState.REJECTED,
        ReviewState.NEEDS_MORE_INFORMATION,
    ]


def test_command_key_is_deterministic_and_cannot_carry_reviewer_identity() -> None:
    options = dict(
        recommendation_version_id="version-1",
        decision=ReviewDecision.MARK_DUPLICATE,
        rationale="Same resource",
        conditions=("Check alternate distribution",),
    )
    first = make_review_command(**options)
    assert make_review_command(**options) == first
    assert (
        make_review_command(**{**options, "recommendation_version_id": "version-2"}).command_key
        != first.command_key
    )
    assert "reviewer_user" not in ReviewCommand.model_fields
    assert "reviewer_role" not in ReviewCommand.model_fields


def test_missing_evidence_blocks_review() -> None:
    absent = detail("version-1").model_copy(update={"evidence": ()})
    repository = FakeHumanReviewRepository(details={"version-1": absent})
    with pytest.raises(ValueError, match="evidence missing"):
        HumanReviewService(repository).decide(
            "version-1",
            ReviewDecision.ACCEPT_FOR_INVESTIGATION,
            rationale="Investigate",
        )

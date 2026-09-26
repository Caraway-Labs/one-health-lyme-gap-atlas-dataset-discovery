"""Fake receipts model the reviewed lineage and replay semantics."""

import pytest

from lyme_gap_atlas_dataset_discovery.adapters.fake import FakeRecommendationRepository
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateOutcomeReceipt,
    RecommendationIdentity,
    RecommendationWriteReceipt,
    RunFinalizationReceipt,
)


def recommendation(run_id: str, version_id: str) -> RecommendationWriteReceipt:
    return RecommendationWriteReceipt(
        operation_key=f"recommendation:{run_id}:resource",
        identity=RecommendationIdentity(
            recommendation_id="stable-resource",
            recommendation_version_id=version_id,
            run_id=run_id,
            resource_key="resource",
        ),
        assertion_sha256="a" * 64,
        evidence_observation_ids=("obs-1",),
    )


def test_same_run_replay_and_new_run_version() -> None:
    repository = FakeRecommendationRepository()
    repository.create_run(operation_key="execution-a", run_id="run-a")
    first = recommendation("run-a", "version-a")
    assert repository.save_recommendation(first) == first
    assert repository.save_recommendation(first) == first

    repository.finalize_run(
        RunFinalizationReceipt(
            operation_key="finalize:run-a",
            run_id="run-a",
            status="PARTIAL",
            processed_count=1,
            recommendation_count=1,
        )
    )
    repository.create_run(operation_key="execution-b", run_id="run-b", retry_of_run_id="run-a")
    second = recommendation("run-b", "version-b")
    assert repository.save_recommendation(second) == second
    assert second.identity.recommendation_id == first.identity.recommendation_id
    assert second.identity.recommendation_version_id != first.identity.recommendation_version_id
    assert second.assertion_sha256 == first.assertion_sha256


def test_conflicting_replay_fails_closed() -> None:
    repository = FakeRecommendationRepository()
    repository.create_run(operation_key="execution-a", run_id="run-a")
    first = recommendation("run-a", "version-a")
    repository.save_recommendation(first)
    with pytest.raises(ValueError, match="conflicting payload"):
        repository.save_recommendation(first.model_copy(update={"assertion_sha256": "b" * 64}))
    with pytest.raises(ValueError, match="same-run candidate"):
        repository.save_recommendation(
            first.model_copy(
                update={
                    "operation_key": "other",
                    "identity": first.identity.model_copy(
                        update={"recommendation_version_id": "version-other"}
                    ),
                }
            )
        )


def test_finalization_recomputed_from_receipts_and_replay_safe() -> None:
    repository = FakeRecommendationRepository()
    repository.create_run(operation_key="execution-a", run_id="run-a")
    outcome = CandidateOutcomeReceipt(
        operation_key="outcome:run-a:bad",
        run_id="run-a",
        resource_key="bad",
        outcome="INSUFFICIENT_EVIDENCE",
    )
    assert repository.record_candidate_outcome(outcome) == outcome
    assert repository.record_candidate_outcome(outcome) == outcome
    repository.save_recommendation(recommendation("run-a", "version-a"))
    receipt = RunFinalizationReceipt(
        operation_key="finalize:run-a",
        run_id="run-a",
        status="SUCCEEDED_WITH_RECOMMENDATIONS",
        processed_count=2,
        recommendation_count=1,
    )
    assert repository.finalize_run(receipt) == receipt
    assert repository.finalize_run(receipt) == receipt
    with pytest.raises(ValueError, match="different receipt"):
        repository.finalize_run(receipt.model_copy(update={"status": "FAILED"}))
    with pytest.raises(ValueError, match="already terminal"):
        repository.record_candidate_outcome(
            CandidateOutcomeReceipt(
                operation_key="outcome:run-a:late",
                run_id="run-a",
                resource_key="late",
                outcome="INSUFFICIENT_EVIDENCE",
            )
        )
    with pytest.raises(ValueError, match="already terminal"):
        repository.save_recommendation(
            recommendation("run-a", "version-late").model_copy(update={"operation_key": "late"})
        )
    with pytest.raises(ValueError, match="retry-eligible"):
        repository.create_run(operation_key="execution-b", run_id="run-b", retry_of_run_id="run-a")

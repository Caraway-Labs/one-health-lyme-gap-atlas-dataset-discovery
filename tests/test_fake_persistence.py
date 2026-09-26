"""Fake receipts model the reviewed lineage and replay semantics."""

import pytest

from lyme_gap_atlas_dataset_discovery.adapters.fake import FakeRecommendationRepository
from lyme_gap_atlas_dataset_discovery.domain.analysis import CandidateAnalysis, Classification
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    CandidateOutcomeReceipt,
    EvidenceRef,
    ObservedFact,
    RecommendationIdentity,
    RunFinalizationReceipt,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import (
    RecommendationWrite,
    assertion_sha256,
    rights_evidence_state,
)
from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    Dimension,
    PriorityInput,
    RankingDimensions,
    Relationship,
    rank_candidate,
)
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult


def recommendation(run_id: str, version_id: str) -> RecommendationWrite:
    analysis = CandidateAnalysis(
        identity=CandidateIdentity(
            resource_key="resource",
            catalog_dataset_id="dataset",
            catalog_resource_id="catalog-resource",
        ),
        classification=Classification.RELEVANT,
        observed_facts=(
            ObservedFact(
                field="publisher",
                value="Agency",
                evidence=EvidenceRef(
                    observation_id="obs-1",
                    catalog_dataset_id="dataset",
                    catalog_resource_id="catalog-resource",
                    observed_at="2026-09-26T00:00:00Z",
                ),
            ),
        ),
    )
    ranking_input = PriorityInput(
        resource_key="resource",
        recommendation_version_id=version_id,
        observed_evidence_ids=frozenset({"obs-1"}),
        relationship=Relationship.DISTINCT,
        dimensions=RankingDimensions(
            relevance=Dimension(value=2, supporting_observation_ids=("obs-1",)),
            geography=Dimension(value=2, supporting_observation_ids=("obs-1",)),
            variables=Dimension(value=2, supporting_observation_ids=("obs-1",)),
            time=Dimension(value=2, supporting_observation_ids=("obs-1",)),
            provenance=Dimension(value=2, supporting_observation_ids=("obs-1",)),
            freshness=Dimension(value=2, supporting_observation_ids=("obs-1",)),
            rights_clarity=Dimension(value=None),
            complementarity=Dimension(value=2, supporting_observation_ids=("obs-1",)),
        ),
    )
    priority = rank_candidate(ranking_input)
    relationship = RelationshipResult(
        relationship=Relationship.DISTINCT,
        basis="FAKE_FIXTURE",
        supporting_observation_ids=("obs-1",),
    )
    return RecommendationWrite(
        operation_key=f"recommendation:{run_id}:resource",
        identity=RecommendationIdentity(
            recommendation_id="stable-resource",
            recommendation_version_id=version_id,
            run_id=run_id,
            resource_key="resource",
        ),
        evidence_snapshot_id="fixture-snapshot",
        rights_state=rights_evidence_state(analysis),
        assertion_sha256=assertion_sha256(analysis, ranking_input, priority, relationship),
        analysis=analysis,
        ranking_input=ranking_input,
        priority=priority,
        relationship=relationship,
    )


def test_same_run_replay_and_new_run_version() -> None:
    repository = FakeRecommendationRepository()
    repository.create_run(operation_key="execution-a", run_id="run-a")
    first = recommendation("run-a", "version-a")
    first_receipt = repository.save_recommendation(first)
    assert repository.save_recommendation(first) == first_receipt
    assert first_receipt.evidence_observation_ids == ("obs-1",)

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
    assert repository.save_recommendation(second).identity == second.identity
    assert second.identity.recommendation_id == first.identity.recommendation_id
    assert second.identity.recommendation_version_id != first.identity.recommendation_version_id
    assert second.assertion_sha256 != first.assertion_sha256


def test_conflicting_replay_fails_closed() -> None:
    repository = FakeRecommendationRepository()
    repository.create_run(operation_key="execution-a", run_id="run-a")
    first = recommendation("run-a", "version-a")
    repository.save_recommendation(first)
    changed_relationship = first.relationship.model_copy(update={"basis": "CHANGED_BASIS"})
    changed = first.model_copy(
        update={
            "relationship": changed_relationship,
            "assertion_sha256": assertion_sha256(
                first.analysis, first.ranking_input, first.priority, changed_relationship
            ),
        }
    )
    with pytest.raises(ValueError, match="conflicting payload"):
        repository.save_recommendation(changed)
    with pytest.raises(ValueError, match="same-run candidate"):
        repository.save_recommendation(
            recommendation("run-a", "version-other").model_copy(update={"operation_key": "other"})
        )


def test_finalization_recomputed_from_receipts_and_replay_safe() -> None:
    repository = FakeRecommendationRepository()
    repository.create_run(operation_key="execution-a", run_id="run-a")
    outcome = CandidateOutcomeReceipt(
        operation_key="outcome:run-a:bad",
        run_id="run-a",
        resource_key="bad",
        catalog_dataset_id="dataset-bad",
        catalog_resource_id="resource-bad",
        evidence_snapshot_id="snapshot-1",
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
                catalog_dataset_id="dataset-late",
                catalog_resource_id="resource-late",
                evidence_snapshot_id="snapshot-1",
                outcome="INSUFFICIENT_EVIDENCE",
            )
        )
    with pytest.raises(ValueError, match="already terminal"):
        repository.save_recommendation(
            recommendation("run-a", "version-late").model_copy(update={"operation_key": "late"})
        )
    with pytest.raises(ValueError, match="retry-eligible"):
        repository.create_run(operation_key="execution-b", run_id="run-b", retry_of_run_id="run-a")

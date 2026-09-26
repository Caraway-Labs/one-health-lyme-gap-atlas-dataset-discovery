import pytest

from lyme_gap_atlas_dataset_discovery.adapters.fake import (
    FakeCandidateReader,
    FakeRecommendationRepository,
)
from lyme_gap_atlas_dataset_discovery.domain.analysis import AvailableObservation
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    CandidateSummary,
    EvidenceRef,
    RunCreateMetadata,
    RunFinalizationReceipt,
)


def test_run_metadata_replay_ignores_new_transport_trace_but_rejects_new_config() -> None:
    metadata = RunCreateMetadata(
        mode="FIXTURE",
        trigger_type="MANUAL_FIXTURE",
        code_sha="a" * 40,
        spec_version="v1",
        graph_version="v1",
        config_fingerprint="b" * 64,
        search_fingerprint="c" * 64,
        evidence_snapshot_id="snapshot-1",
        trace_id="first-trace",
    )
    repository = FakeRecommendationRepository()
    first = repository.create_run(operation_key="execution-1", run_id="run-1", metadata=metadata)
    replay = repository.create_run(
        operation_key="execution-1",
        run_id="new-requested-id",
        metadata=metadata.model_copy(update={"trace_id": "second-trace"}),
    )
    assert replay == first
    with pytest.raises(ValueError, match="conflicting run metadata"):
        repository.create_run(
            operation_key="execution-1",
            run_id="new-requested-id",
            metadata=metadata.model_copy(update={"config_fingerprint": "d" * 64}),
        )


def test_fake_reader_pages_in_stable_order() -> None:
    candidates = tuple(
        CandidateSummary(
            identity=CandidateIdentity(
                resource_key=str(i), catalog_dataset_id="d", catalog_resource_id=str(i)
            )
        )
        for i in range(3)
    )
    reader = FakeCandidateReader(candidates)
    first = reader.list_batch(cursor=None, limit=2)
    assert [item.identity.resource_key for item in first.candidates] == ["0", "1"]
    assert first.next_cursor == "2"
    assert [
        item.identity.resource_key for item in reader.list_batch(cursor="2", limit=2).candidates
    ] == ["2"]


def test_fake_run_replay_and_explicit_retry_are_distinct() -> None:
    repository = FakeRecommendationRepository()
    first = repository.create_run(operation_key="delivery-a", run_id="run-a")
    assert repository.create_run(operation_key="delivery-a", run_id="ambiguous-redelivery") == first
    repository.finalize_run(
        RunFinalizationReceipt(
            operation_key="finalize:run-a",
            run_id="run-a",
            status="FAILED",
            processed_count=0,
            recommendation_count=0,
        )
    )
    retry = repository.create_run(
        operation_key="delivery-b", run_id="run-b", retry_of_run_id="run-a"
    )
    assert retry.run_id != first.run_id
    with pytest.raises(ValueError):
        repository.create_run(
            operation_key="delivery-a", run_id="run-c", retry_of_run_id="unexpected"
        )


def test_fake_observations_are_bounded_and_declared() -> None:
    ref = EvidenceRef(
        observation_id="observation-1",
        catalog_dataset_id="dataset",
        catalog_resource_id="resource",
        observed_at="2026-09-26T00:00:00Z",
    )
    candidate = CandidateSummary(
        identity=CandidateIdentity(
            resource_key="resource", catalog_dataset_id="dataset", catalog_resource_id="resource"
        ),
        evidence_refs=(ref,),
    )
    reader = FakeCandidateReader(
        candidates=(candidate,),
        observations={
            "resource": (AvailableObservation(reference=ref, field_values={"publisher": "Agency"}),)
        },
    )
    assert reader.get_observations("resource", limit=1)[0].field_values == {"publisher": "Agency"}
    with pytest.raises(ValueError, match="outside v1 hard maximum"):
        reader.get_observations("resource", limit=26)
    unknown = ref.model_copy(update={"observation_id": "unknown"})
    reader.observations["resource"] = (AvailableObservation(reference=unknown, field_values={}),)
    with pytest.raises(ValueError, match="not declared"):
        reader.get_observations("resource", limit=1)

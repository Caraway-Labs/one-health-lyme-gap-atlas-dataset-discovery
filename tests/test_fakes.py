import pytest

from lyme_gap_atlas_dataset_discovery.adapters.fake import (
    FakeCandidateReader,
    FakeRecommendationRepository,
)
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    CandidateSummary,
    RunFinalizationReceipt,
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

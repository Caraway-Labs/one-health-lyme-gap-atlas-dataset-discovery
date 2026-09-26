"""The compiled graph iterates candidates and persists final run outcomes."""

from lyme_gap_atlas_dataset_discovery.adapters.fake import (
    FakeCandidateReader,
    FakeRecommendationRepository,
)
from lyme_gap_atlas_dataset_discovery.domain.analysis import (
    AvailableObservation,
    CandidateAnalysis,
    Classification,
    RationaleClaim,
)
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    CandidateSummary,
    EvidenceRef,
    ObservedFact,
)
from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    Dimension,
    RankingDimensions,
    Relationship,
)
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult
from lyme_gap_atlas_dataset_discovery.graph.budgets import PROFILE_DEFAULTS, RunProfile
from lyme_gap_atlas_dataset_discovery.graph.planner import FakeCandidatePlanner, FixturePlan
from lyme_gap_atlas_dataset_discovery.graph.sequential import GraphDependencies, build_graph


def fixture(
    candidate_id: str, *, with_evidence: bool = True
) -> tuple[CandidateSummary, tuple[AvailableObservation, ...], FixturePlan]:
    identity = CandidateIdentity(
        resource_key=candidate_id,
        catalog_dataset_id=f"dataset-{candidate_id}",
        catalog_resource_id=f"catalog-resource-{candidate_id}",
    )
    ref = EvidenceRef(
        observation_id=f"observation-{candidate_id}",
        catalog_dataset_id=identity.catalog_dataset_id,
        catalog_resource_id=identity.catalog_resource_id,
        observed_at="2026-09-26T00:00:00Z",
    )
    summary = CandidateSummary(identity=identity, evidence_refs=(ref,) if with_evidence else ())
    observations = (
        (AvailableObservation(reference=ref, field_values={"publisher": "Agency"}),)
        if with_evidence
        else ()
    )
    analysis = CandidateAnalysis(
        identity=identity,
        classification=Classification.RELEVANT,
        observed_facts=(ObservedFact(field="publisher", value="Agency", evidence=ref),),
    )
    unknown = Dimension(value=None)
    plan = FixturePlan(
        relationship=RelationshipResult(
            relationship=Relationship.DISTINCT,
            basis="FIXTURE",
            supporting_observation_ids=(ref.observation_id,),
        ),
        analysis=analysis,
        dimensions=RankingDimensions(
            relevance=Dimension(value=2, supporting_observation_ids=(ref.observation_id,)),
            geography=unknown,
            variables=unknown,
            time=unknown,
            provenance=unknown,
            freshness=unknown,
            rights_clarity=unknown,
            complementarity=unknown,
        ),
        rationale=(
            RationaleClaim(
                field="publisher",
                text="Agency",
                kind="OBSERVED",
                supporting_observation_ids=(ref.observation_id,),
            ),
        ),
    )
    return summary, observations, plan


def input_state(*, run_id: str = "run-1", candidate_limit: int | None = None) -> dict[str, object]:
    limits = PROFILE_DEFAULTS[RunProfile.FIXTURE]
    if candidate_limit is not None:
        limits = limits.model_copy(update={"candidates": candidate_limit})
    return {
        "execution_key": f"execution:{run_id}",
        "requested_run_id": run_id,
        "profile": RunProfile.FIXTURE,
        "trigger_type": "MANUAL_FIXTURE",
        "code_sha": "a" * 40,
        "spec_version": "v1",
        "graph_version": "v1",
        "config_fingerprint": "b" * 64,
        "search_fingerprint": "c" * 64,
        "evidence_snapshot_id": "fixture-snapshot",
        "limits": limits,
    }


def test_valid_candidate_persists_and_finalizes() -> None:
    candidate, observations, plan = fixture("good")
    reader = FakeCandidateReader(candidates=(candidate,), observations={"good": observations})
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=reader, repository=repository, planner=FakeCandidatePlanner({"good": plan})
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "SUCCEEDED_WITH_RECOMMENDATIONS"
    assert result["processed_count"] == 1
    assert result["current_evidence"] == ()
    assert result["current_analysis"] is None
    assert result["remaining_run_budget"]["candidates"] == 4
    assert len(repository.recommendations) == 1
    assert repository.finalizations["run-1"].recommendation_count == 1


def test_insufficient_candidate_does_not_stop_next_candidate() -> None:
    bad, _, bad_plan = fixture("bad", with_evidence=False)
    good, observations, good_plan = fixture("good")
    reader = FakeCandidateReader(candidates=(bad, good), observations={"good": observations})
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=FakeCandidatePlanner({"bad": bad_plan, "good": good_plan}),
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["processed_count"] == 2
    assert result["processed_candidate_outcomes"] == ("INSUFFICIENT_EVIDENCE",)
    assert len(repository.recommendations) == 1
    assert repository.finalizations["run-1"].status == "SUCCEEDED_WITH_RECOMMENDATIONS"


def test_empty_run_is_durably_finalized() -> None:
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(),
            repository=repository,
            planner=FakeCandidatePlanner({}),
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "SUCCEEDED_NO_NEW_CANDIDATES"
    assert repository.finalizations["run-1"].processed_count == 0


def test_candidate_limit_stops_run_with_durable_status() -> None:
    first, first_observations, first_plan = fixture("first")
    second, second_observations, second_plan = fixture("second")
    reader = FakeCandidateReader(
        candidates=(first, second),
        observations={"first": first_observations, "second": second_observations},
    )
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=FakeCandidatePlanner({"first": first_plan, "second": second_plan}),
        )
    )
    result = graph.invoke(input_state(candidate_limit=1), config={"recursion_limit": 100})
    assert result["final_status"] == "BUDGET_STOPPED"
    assert result["processed_count"] == 1
    assert repository.finalizations["run-1"].status == "BUDGET_STOPPED"


def test_candidate_analysis_error_records_outcome_and_continues() -> None:
    bad, bad_observations, _ = fixture("bad")
    good, good_observations, good_plan = fixture("good")
    reader = FakeCandidateReader(
        candidates=(bad, good),
        observations={"bad": bad_observations, "good": good_observations},
    )
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=FakeCandidatePlanner({"good": good_plan}),
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["processed_candidate_outcomes"] == ("CANDIDATE_ANALYSIS_ERROR",)
    assert result["processed_count"] == 2
    assert len(repository.recommendations) == 1


def test_systemic_batch_reader_error_finalizes_failed_run() -> None:
    class BrokenReader(FakeCandidateReader):
        def list_batch(self, *, cursor: str | None, limit: int):  # type: ignore[no-untyped-def]
            raise ConnectionError("do not include details in persisted error")

    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=BrokenReader(), repository=repository, planner=FakeCandidatePlanner({})
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "FAILED"
    assert result["stop_reason"] == "load_candidate_batch:ConnectionError"
    assert repository.finalizations["run-1"].status == "FAILED"

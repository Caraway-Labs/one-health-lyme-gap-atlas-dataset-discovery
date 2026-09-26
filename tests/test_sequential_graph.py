"""The compiled graph iterates candidates and persists final run outcomes."""

from datetime import UTC, datetime

from lyme_gap_atlas_dataset_discovery.adapters.fake import (
    FakeCandidateReader,
    FakeDiscoveryContextReader,
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
    CandidateOutcomeReceipt,
    CandidateSummary,
    DiscoveryContext,
    EvidenceRef,
    ObservedFact,
    RecommendationWriteReceipt,
    RunFinalizationReceipt,
    RunReceipt,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import RecommendationWrite
from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    Dimension,
    RankingDimensions,
    Relationship,
)
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult
from lyme_gap_atlas_dataset_discovery.graph.budgets import PROFILE_DEFAULTS, RunProfile
from lyme_gap_atlas_dataset_discovery.graph.planner import FakeCandidatePlanner, FixturePlan
from lyme_gap_atlas_dataset_discovery.graph.sequential import (
    GraphDependencies,
    PolicyViolation,
    build_graph,
)


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


def fixture_context() -> FakeDiscoveryContextReader:
    return FakeDiscoveryContextReader(
        {
            "fixture-snapshot": DiscoveryContext(
                discovery_run_id="fixture-snapshot",
                search_fingerprint="c" * 64,
                completed_at="2026-09-26T00:00:00Z",
                status="COMPLETED",
            )
        }
    )


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


def test_cancellation_creates_and_finalizes_run() -> None:
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(),
            repository=repository,
            planner=FakeCandidatePlanner({}),
            cancellation_requested=lambda: True,
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "CANCELLED"
    assert repository.finalizations["run-1"].status == "CANCELLED"


def test_expired_deadline_durably_stops_run() -> None:
    calls = 0

    def advancing_clock() -> datetime:
        nonlocal calls
        calls += 1
        return datetime(2026, 9, 26, 0, 0, calls, tzinfo=UTC)

    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(),
            repository=repository,
            planner=FakeCandidatePlanner({}),
            clock=advancing_clock,
        )
    )
    state = input_state()
    state["deadline_at"] = "2026-09-26T00:00:01+00:00"
    result = graph.invoke(state, config={"recursion_limit": 100})
    assert result["final_status"] == "BUDGET_STOPPED"
    assert result["stop_reason"] == "DEADLINE_EXHAUSTED"
    assert repository.finalizations["run-1"].status == "BUDGET_STOPPED"


def test_lost_commit_acknowledgments_reconcile_all_business_writes() -> None:
    class LostAckRepository(FakeRecommendationRepository):
        def __init__(self) -> None:
            super().__init__()
            self.lost: set[str] = set()

        def create_run(
            self, *, operation_key: str, run_id: str, retry_of_run_id: str | None = None
        ) -> RunReceipt:
            result = super().create_run(
                operation_key=operation_key, run_id=run_id, retry_of_run_id=retry_of_run_id
            )
            if "run" not in self.lost:
                self.lost.add("run")
                raise ConnectionError("ack lost after run commit")
            return result

        def record_candidate_outcome(
            self, receipt: CandidateOutcomeReceipt
        ) -> CandidateOutcomeReceipt:
            result = super().record_candidate_outcome(receipt)
            if "outcome" not in self.lost:
                self.lost.add("outcome")
                raise ConnectionError("ack lost after outcome commit")
            return result

        def save_recommendation(self, request: RecommendationWrite) -> RecommendationWriteReceipt:
            result = super().save_recommendation(request)
            if "recommendation" not in self.lost:
                self.lost.add("recommendation")
                raise ConnectionError("ack lost after recommendation commit")
            return result

        def finalize_run(self, receipt: RunFinalizationReceipt) -> RunFinalizationReceipt:
            result = super().finalize_run(receipt)
            if "finalization" not in self.lost:
                self.lost.add("finalization")
                raise ConnectionError("ack lost after finalization commit")
            return result

    bad, _, bad_plan = fixture("bad", with_evidence=False)
    good, observations, good_plan = fixture("good")
    repository = LostAckRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(candidates=(bad, good), observations={"good": observations}),
            repository=repository,
            planner=FakeCandidatePlanner({"bad": bad_plan, "good": good_plan}),
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "SUCCEEDED_WITH_RECOMMENDATIONS"
    assert repository.lost == {"run", "outcome", "recommendation", "finalization"}
    assert len(repository.runs) == 1
    assert len(repository.outcomes) == 1
    assert len(repository.recommendations) == 1
    assert len(repository.finalizations) == 1


def test_evidence_reader_outage_is_systemic() -> None:
    candidate, _, plan = fixture("candidate")

    class BrokenEvidenceReader(FakeCandidateReader):
        def get_observations(self, candidate_id: str, *, limit: int):  # type: ignore[no-untyped-def]
            raise ConnectionError("provider unavailable")

    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=BrokenEvidenceReader(candidates=(candidate,)),
            repository=repository,
            planner=FakeCandidatePlanner({"candidate": plan}),
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "FAILED"
    assert result["stop_reason"] == "assess_evidence_sufficiency:ConnectionError"
    assert result["usage"].tool_calls == 2
    assert repository.finalizations["run-1"].status == "FAILED"


def test_policy_violation_stops_whole_run() -> None:
    candidate, observations, plan = fixture("candidate")

    class UnsafePlanner(FakeCandidatePlanner):
        def relationship(self, candidate, observations):  # type: ignore[no-untyped-def]
            raise PolicyViolation("catalog text attempted authority escalation")

    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(
                candidates=(candidate,), observations={"candidate": observations}
            ),
            repository=repository,
            planner=UnsafePlanner({"candidate": plan}),
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "FAILED"
    assert result["stop_reason"] == "analyze_candidate_relationship:PolicyViolation"
    assert repository.finalizations["run-1"].status == "FAILED"


def test_transient_reader_and_model_errors_retry_with_attempts_charged() -> None:
    candidate, observations, plan = fixture("candidate")

    class FlakyReader(FakeCandidateReader):
        attempts = 0

        def get_observations(self, candidate_id: str, *, limit: int):  # type: ignore[no-untyped-def]
            self.attempts += 1
            if self.attempts == 1:
                raise TimeoutError("temporary reader failure")
            return super().get_observations(candidate_id, limit=limit)

    class FlakyPlanner(FakeCandidatePlanner):
        attempts = 0

        def relationship(self, candidate, observations):  # type: ignore[no-untyped-def]
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("temporary model failure")
            return super().relationship(candidate, observations)

    reader = FlakyReader(candidates=(candidate,), observations={"candidate": observations})
    planner = FlakyPlanner({"candidate": plan})
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=planner,
            context_reader=fixture_context(),
            sleep=lambda _: None,
        )
    )
    state = input_state()
    state["profile"] = RunProfile.DEV_MANUAL
    state["limits"] = PROFILE_DEFAULTS[RunProfile.DEV_MANUAL]
    result = graph.invoke(state, config={"recursion_limit": 100})
    assert result["final_status"] == "SUCCEEDED_WITH_RECOMMENDATIONS"
    assert reader.attempts == 2
    assert planner.attempts == 2
    assert result["usage"].tool_calls == 3  # page plus two evidence attempts
    assert result["usage"].model_calls == 5  # relationship twice; remaining nodes once


def test_exhausted_model_retries_record_candidate_and_charge_attempts() -> None:
    candidate, observations, plan = fixture("candidate")

    class DownPlanner(FakeCandidatePlanner):
        def relationship(self, candidate, observations):  # type: ignore[no-untyped-def]
            raise TimeoutError("temporary provider outage")

    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(
                candidates=(candidate,), observations={"candidate": observations}
            ),
            repository=repository,
            planner=DownPlanner({"candidate": plan}),
            context_reader=fixture_context(),
            sleep=lambda _: None,
        )
    )
    state = input_state()
    state["profile"] = RunProfile.DEV_MANUAL
    state["limits"] = PROFILE_DEFAULTS[RunProfile.DEV_MANUAL]
    result = graph.invoke(state, config={"recursion_limit": 100})
    assert result["processed_candidate_outcomes"] == ("CANDIDATE_ANALYSIS_ERROR",)
    assert result["usage"].model_calls == 3
    assert repository.finalizations["run-1"].processed_count == 1


def test_nonfixture_run_requires_matching_governed_context() -> None:
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(discovery_run_id="other-snapshot"),
            repository=repository,
            planner=FakeCandidatePlanner({}),
            context_reader=fixture_context(),
        )
    )
    state = input_state()
    state["profile"] = RunProfile.DEV_MANUAL
    state["limits"] = PROFILE_DEFAULTS[RunProfile.DEV_MANUAL]
    result = graph.invoke(state, config={"recursion_limit": 100})
    assert result["final_status"] == "FAILED"
    assert result["stop_reason"] == "load_discovery_context:ValueError"
    assert repository.finalizations["run-1"].status == "FAILED"

    wrong_fingerprint = input_state(run_id="run-2")
    wrong_fingerprint["profile"] = RunProfile.DEV_MANUAL
    wrong_fingerprint["limits"] = PROFILE_DEFAULTS[RunProfile.DEV_MANUAL]
    wrong_fingerprint["search_fingerprint"] = "d" * 64
    reader = FakeCandidateReader()
    graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=FakeCandidatePlanner({}),
            context_reader=fixture_context(),
        )
    )
    mismatch = graph.invoke(wrong_fingerprint, config={"recursion_limit": 100})
    assert mismatch["final_status"] == "FAILED"
    assert repository.finalizations["run-2"].status == "FAILED"

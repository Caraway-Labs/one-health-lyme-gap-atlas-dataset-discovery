"""The compiled graph iterates candidates and persists final run outcomes."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

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
    RunCreateMetadata,
    RunFinalizationReceipt,
    RunReceipt,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import RecommendationWrite
from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    Dimension,
    RankingDimensions,
    Relationship,
)
from lyme_gap_atlas_dataset_discovery.domain.relationships import IdentityLink, RelationshipResult
from lyme_gap_atlas_dataset_discovery.graph.budgets import PROFILE_DEFAULTS, RunProfile
from lyme_gap_atlas_dataset_discovery.graph.planner import (
    FakeCandidatePlanner,
    FixturePlan,
    InvalidModelResponse,
    ModelUsage,
    PlannerResult,
    UnmeteredModelResponse,
)
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
        (
            AvailableObservation(
                reference=ref,
                field_values={"publisher": "Agency", "title": "Lyme surveillance"},
            ),
        )
        if with_evidence
        else ()
    )
    analysis = CandidateAnalysis(
        identity=identity,
        classification=Classification.RELEVANT,
        observed_facts=(
            ObservedFact(field="publisher", value="Agency", evidence=ref),
            ObservedFact(field="title", value="Lyme surveillance", evidence=ref),
        ),
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


def identity_link(
    candidate: CandidateSummary,
    *,
    linked_id: str = "related",
    relationship: Relationship = Relationship.EXACT_DUPLICATE,
) -> IdentityLink:
    return IdentityLink(
        candidate=candidate.identity,
        linked_resource_key=linked_id,
        linked_catalog_dataset_id=candidate.identity.catalog_dataset_id,
        linked_catalog_resource_id=f"resource-{linked_id}",
        relationship=relationship,
        basis=(
            "SAME_CATALOG_DATASET"
            if relationship == Relationship.ALTERNATE_DISTRIBUTION
            else "EXACT_CANONICAL_URL"
        ),
    )


def test_exact_identity_link_records_outcome_before_model_and_continues() -> None:
    duplicate, duplicate_observations, _ = fixture("duplicate")
    good, good_observations, good_plan = fixture("good")
    reader = FakeCandidateReader(
        candidates=(duplicate, good),
        observations={"duplicate": duplicate_observations, "good": good_observations},
        identity_links={"duplicate": (identity_link(duplicate),)},
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
    assert result["final_status"] == "SUCCEEDED_WITH_RECOMMENDATIONS"
    assert result["processed_candidate_outcomes"] == ("EXACT_DUPLICATE",)
    assert result["usage"].model_calls == 4
    assert len(repository.recommendations) == 1


def test_alternate_distribution_is_capped_low_without_model_relationship() -> None:
    candidate, observations, plan = fixture("alternate")
    reader = FakeCandidateReader(
        candidates=(candidate,),
        observations={"alternate": observations},
        identity_links={
            "alternate": (
                identity_link(candidate, relationship=Relationship.ALTERNATE_DISTRIBUTION),
            )
        },
    )
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=FakeCandidatePlanner({"alternate": plan}),
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    bundle = next(iter(repository.recommendation_bundles.values()))
    assert result["final_status"] == "SUCCEEDED_WITH_RECOMMENDATIONS"
    assert result["usage"].model_calls == 3
    assert bundle.relationship.relationship == Relationship.ALTERNATE_DISTRIBUTION
    assert bundle.priority.bucket.value == "LOW"


def test_forensic_usgs_digital_data_remains_low_eligible_with_unknown_options() -> None:
    candidate, observations, plan = fixture("usgs-digital-data")
    enriched = observations[0].model_copy(
        update={
            "field_values": {
                **observations[0].field_values,
                "description": (
                    "Blacklegged tick nymph density and Borrelia burgdorferi prevalence, 2014-2022"
                ),
                "resource_title": "Digital Data",
                "resource_role": "access",
                "resource_type": "API",
                "canonical_url": "https://doi.org/10.5066/P9LSI8K9",
                "spatial": "-80.0000, 37.6000, -71.0000, 41.3000",
                "access_level": "public",
            }
        }
    )
    reader = FakeCandidateReader(
        candidates=(candidate,),
        observations={"usgs-digital-data": (enriched,)},
        identity_links={
            "usgs-digital-data": (
                identity_link(candidate, relationship=Relationship.ALTERNATE_DISTRIBUTION),
            )
        },
    )
    repository = FakeRecommendationRepository()
    result = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=FakeCandidatePlanner({"usgs-digital-data": plan}),
        )
    ).invoke(input_state(), config={"recursion_limit": 100})
    bundle = next(iter(repository.recommendation_bundles.values()))
    assert result["final_status"] == "SUCCEEDED_WITH_RECOMMENDATIONS"
    assert bundle.priority.bucket.value == "LOW"
    assert bundle.ranking_input.dimensions.geography.value is None
    assert bundle.ranking_input.dimensions.rights_clarity.value is None


def test_forensic_usgs_original_metadata_is_supporting_evidence_not_new_source() -> None:
    candidate, observations, _ = fixture("usgs-metadata-xml")
    metadata = observations[0].model_copy(
        update={
            "field_values": {
                **observations[0].field_values,
                "resource_title": "Original Metadata",
                "resource_role": "download",
                "resource_type": "DATA",
                "distribution_media_type": "text/xml",
                "distribution_format": "XML",
                "canonical_url": "https://data.usgs.gov/datacatalog/metadata/USGS.637cfb9bd34ed907bf73c08c.xml",
            }
        }
    )
    repository = FakeRecommendationRepository()
    result = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(
                candidates=(candidate,),
                observations={"usgs-metadata-xml": (metadata,)},
                identity_links={
                    "usgs-metadata-xml": (
                        identity_link(candidate, relationship=Relationship.ALTERNATE_DISTRIBUTION),
                    )
                },
            ),
            repository=repository,
            planner=FakeCandidatePlanner({}),
        )
    ).invoke(input_state(), config={"recursion_limit": 100})
    assert result["usage"].model_calls == 0
    assert result["processed_candidate_outcomes"] == ("SUPPORTING_METADATA_DISTRIBUTION",)
    decision = next(iter(repository.outcomes.values())).decision_record
    assert decision is not None
    assert decision.relationship == "ALTERNATE_DISTRIBUTION"
    assert decision.task_type == "NOT_CALLED"
    assert not repository.recommendations


def test_forensic_nih_review_with_null_relevance_has_auditable_abstention() -> None:
    candidate, observations, plan = fixture("nih-literature")
    dimensions = plan.dimensions.model_copy(update={"relevance": Dimension(value=None)})
    conservative = replace(
        plan,
        analysis=plan.analysis.model_copy(
            update={"classification": Classification.INSUFFICIENT_EVIDENCE}
        ),
        dimensions=dimensions,
    )
    repository = FakeRecommendationRepository()
    result = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(
                candidates=(candidate,),
                observations={"nih-literature": observations},
                identity_links={
                    "nih-literature": (
                        identity_link(candidate, relationship=Relationship.ALTERNATE_DISTRIBUTION),
                    )
                },
            ),
            repository=repository,
            planner=FakeCandidatePlanner({"nih-literature": conservative}),
        )
    ).invoke(input_state(), config={"recursion_limit": 100})
    assert result["processed_candidate_outcomes"] == ("INSUFFICIENT_EVIDENCE",)
    decision = next(iter(repository.outcomes.values())).decision_record
    assert decision is not None
    assert decision.classification == "INSUFFICIENT_EVIDENCE"
    assert decision.relevance is None
    assert decision.validator_result == "PASSED_CLASSIFICATION"
    with pytest.raises(ValueError, match="candidate outcome key reused"):
        existing = next(iter(repository.outcomes.values()))
        repository.record_candidate_outcome(existing.model_copy(update={"decision_record": None}))


def test_multiple_identity_links_abstain_without_model_guess() -> None:
    candidate, observations, _ = fixture("ambiguous")
    reader = FakeCandidateReader(
        candidates=(candidate,),
        observations={"ambiguous": observations},
        identity_links={
            "ambiguous": (
                identity_link(candidate, linked_id="a"),
                identity_link(candidate, linked_id="b"),
            )
        },
    )
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(reader=reader, repository=repository, planner=FakeCandidatePlanner({}))
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["processed_candidate_outcomes"] == ("AMBIGUOUS_RELATIONSHIP",)
    assert result["usage"].model_calls == 0
    assert not repository.recommendations


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
    assert repository.finalizations["run-1"].budget_usage["candidates"] == 1
    metadata = repository.run_metadata["execution:run-1"]
    assert metadata.mode == "FIXTURE"
    assert metadata.evidence_snapshot_id == "fixture-snapshot"
    assert repository.runs["execution:run-1"].request_fingerprint == metadata.request_fingerprint


@pytest.mark.parametrize(
    "field,wrong_value",
    [
        ("code_sha", "b" * 40),
        ("code_sha", "not-a-commit"),
        ("evidence_snapshot_id", "another-snapshot"),
        ("price_table_version", "unreviewed-price"),
    ],
)
def test_deployment_pins_are_checked_before_run_creation(field: str, wrong_value: str) -> None:
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(),
            repository=repository,
            planner=FakeCandidatePlanner({}),
            deployed_code_sha="a" * 40,
            expected_snapshot_id="fixture-snapshot",
            approved_price_table_version="reviewed-price-v1",
        )
    )
    state = input_state()
    state["price_table_version"] = "reviewed-price-v1"
    state[field] = wrong_value
    with pytest.raises(ValueError, match="SHA|snapshot|price table"):
        graph.invoke(state, config={"recursion_limit": 100})
    assert repository.runs == {}


def test_matching_deployment_pins_allow_run() -> None:
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(),
            repository=repository,
            planner=FakeCandidatePlanner({}),
            deployed_code_sha="a" * 40,
            expected_snapshot_id="fixture-snapshot",
            approved_price_table_version="reviewed-price-v1",
        )
    )
    state = input_state()
    state["price_table_version"] = "reviewed-price-v1"
    result = graph.invoke(state, config={"recursion_limit": 100})
    assert result["final_status"] == "SUCCEEDED_NO_NEW_CANDIDATES"


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
    outcome = repository.outcomes["outcome:run-1:bad"]
    assert outcome.catalog_dataset_id == "dataset-bad"
    assert outcome.catalog_resource_id == "catalog-resource-bad"
    assert outcome.evidence_snapshot_id == "fixture-snapshot"
    assert len(repository.recommendations) == 1
    assert repository.finalizations["run-1"].status == "SUCCEEDED_WITH_RECOMMENDATIONS"


def test_already_governed_resource_records_outcome_without_model_or_evidence_read() -> None:
    known, _, _ = fixture("known", with_evidence=False)

    class NoEvidenceReader(FakeCandidateReader):
        def get_observations(self, candidate_id: str, *, limit: int):  # type: ignore[no-untyped-def]
            raise AssertionError("governed resource should not require candidate evidence")

    reader = NoEvidenceReader(candidates=(known,), governed_statuses={"known": "ALREADY_GOVERNED"})
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(reader=reader, repository=repository, planner=FakeCandidatePlanner({}))
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "SUCCEEDED_NO_NEW_CANDIDATES"
    assert result["processed_candidate_outcomes"] == ("ALREADY_KNOWN",)
    assert result["usage"].model_calls == 0
    assert result["usage"].tool_calls == 2  # batch plus governed-status view
    assert repository.outcomes["outcome:run-1:known"].reason_code == "ALREADY_KNOWN"
    assert not repository.recommendations


def test_unknown_governed_status_value_stops_run_before_model() -> None:
    candidate, _, _ = fixture("candidate")
    reader = FakeCandidateReader(
        candidates=(candidate,), governed_statuses={"candidate": "SOURCE_APPROVED"}
    )
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(reader=reader, repository=repository, planner=FakeCandidatePlanner({}))
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "FAILED"
    assert result["stop_reason"] == "assess_evidence_sufficiency:PolicyViolation"
    assert not repository.recommendations


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
            self,
            *,
            operation_key: str,
            run_id: str,
            metadata: RunCreateMetadata | None = None,
            retry_of_run_id: str | None = None,
        ) -> RunReceipt:
            result = super().create_run(
                operation_key=operation_key,
                run_id=run_id,
                metadata=metadata,
                retry_of_run_id=retry_of_run_id,
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
    assert result["usage"].tool_calls == 3
    assert repository.finalizations["run-1"].status == "FAILED"


def test_policy_violation_stops_whole_run() -> None:
    candidate, observations, plan = fixture("candidate")

    class UnsafePlanner(FakeCandidatePlanner):
        def relationship(self, candidate, observations, *, allowance):  # type: ignore[no-untyped-def]
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

        def relationship(self, candidate, observations, *, allowance):  # type: ignore[no-untyped-def]
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("temporary model failure")
            return super().relationship(candidate, observations, allowance=allowance)

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
    assert result["usage"].tool_calls == 5  # page, status, two evidence attempts, identity links
    assert result["usage"].model_calls == 5  # relationship twice; remaining nodes once


def test_exhausted_model_retries_record_candidate_and_charge_attempts() -> None:
    candidate, observations, plan = fixture("candidate")

    class DownPlanner(FakeCandidatePlanner):
        def relationship(self, candidate, observations, *, allowance):  # type: ignore[no-untyped-def]
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


def test_reported_model_usage_is_charged_and_overspend_stops_before_write() -> None:
    candidate, observations, plan = fixture("candidate")

    class MeteredPlanner(FakeCandidatePlanner):
        def relationship(self, candidate, observations, *, allowance):  # type: ignore[no-untyped-def]
            result = super().relationship(candidate, observations, allowance=allowance)
            return PlannerResult(
                result.value,
                ModelUsage(input_tokens=100, output_tokens=20, estimated_spend_cents=3),
            )

    reader = FakeCandidateReader(candidates=(candidate,), observations={"candidate": observations})
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=MeteredPlanner({"candidate": plan}),
            context_reader=fixture_context(),
        )
    )
    state = input_state()
    state["profile"] = RunProfile.DEV_MANUAL
    state["limits"] = PROFILE_DEFAULTS[RunProfile.DEV_MANUAL]
    result = graph.invoke(state, config={"recursion_limit": 100})
    assert result["final_status"] == "SUCCEEDED_WITH_RECOMMENDATIONS"
    assert result["usage"].input_tokens == 100
    assert result["usage"].output_tokens == 20
    assert result["usage"].estimated_spend_cents == 3

    fixture_repository = FakeRecommendationRepository()
    fixture_graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=fixture_repository,
            planner=MeteredPlanner({"candidate": plan}),
        )
    )
    stopped = fixture_graph.invoke(input_state(run_id="run-2"), config={"recursion_limit": 100})
    assert stopped["final_status"] == "BUDGET_STOPPED"
    assert stopped["usage"].estimated_spend_cents == 3
    assert fixture_repository.recommendations == {}


def test_invalid_model_content_charges_reported_usage_and_continues() -> None:
    bad, bad_observations, bad_plan = fixture("bad")
    good, good_observations, good_plan = fixture("good")

    class InvalidThenValidPlanner(FakeCandidatePlanner):
        def relationship(self, candidate, observations, *, allowance):  # type: ignore[no-untyped-def]
            if candidate.identity.resource_key == "bad":
                raise InvalidModelResponse(
                    ModelUsage(input_tokens=100, output_tokens=20, estimated_spend_cents=3)
                )
            return super().relationship(candidate, observations, allowance=allowance)

    reader = FakeCandidateReader(
        candidates=(bad, good),
        observations={"bad": bad_observations, "good": good_observations},
    )
    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=InvalidThenValidPlanner({"bad": bad_plan, "good": good_plan}),
            context_reader=fixture_context(),
        )
    )
    state = input_state()
    state["profile"] = RunProfile.DEV_MANUAL
    state["limits"] = PROFILE_DEFAULTS[RunProfile.DEV_MANUAL]
    result = graph.invoke(state, config={"recursion_limit": 100})
    assert result["final_status"] == "SUCCEEDED_WITH_RECOMMENDATIONS"
    assert result["usage"].input_tokens == 100
    assert result["usage"].output_tokens == 20
    assert result["usage"].estimated_spend_cents == 3
    assert result["usage"].model_calls == 5
    assert repository.outcomes["outcome:run-1:bad"].reason_code == "CANDIDATE_ANALYSIS_ERROR"
    assert len(repository.recommendations) == 1


def test_unmetered_model_response_fails_run_without_recommendation() -> None:
    candidate, observations, plan = fixture("candidate")

    class UnmeteredPlanner(FakeCandidatePlanner):
        def relationship(self, candidate, observations, *, allowance):  # type: ignore[no-untyped-def]
            raise UnmeteredModelResponse()

    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(
                candidates=(candidate,), observations={"candidate": observations}
            ),
            repository=repository,
            planner=UnmeteredPlanner({"candidate": plan}),
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "FAILED"
    assert result["stop_reason"] == "analyze_candidate_relationship:UnmeteredModelResponse"
    assert result["usage"].model_calls == 1
    assert not repository.recommendations


def test_invalid_model_response_over_budget_stops_with_measured_spend() -> None:
    candidate, observations, plan = fixture("candidate")

    class CostlyInvalidPlanner(FakeCandidatePlanner):
        def relationship(self, candidate, observations, *, allowance):  # type: ignore[no-untyped-def]
            raise InvalidModelResponse(
                ModelUsage(input_tokens=100, output_tokens=20, estimated_spend_cents=3)
            )

    repository = FakeRecommendationRepository()
    graph = build_graph(
        GraphDependencies(
            reader=FakeCandidateReader(
                candidates=(candidate,), observations={"candidate": observations}
            ),
            repository=repository,
            planner=CostlyInvalidPlanner({"candidate": plan}),
        )
    )
    result = graph.invoke(input_state(), config={"recursion_limit": 100})
    assert result["final_status"] == "BUDGET_STOPPED"
    assert result["stop_reason"] == "REPORTED_USAGE_EXCEEDED"
    assert result["usage"].estimated_spend_cents == 3
    assert repository.finalizations["run-1"].budget_usage["estimated_spend_cents"] == 3
    assert not repository.recommendations

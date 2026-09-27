"""Versioned, credential-free graph trajectory and durable receipt evaluation."""

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

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
    CandidateOutcomeReceipt,
    CandidatePage,
    CandidateSummary,
    EvidenceRef,
    ObservedFact,
    RecommendationWriteReceipt,
    RunCreateMetadata,
    RunFinalizationReceipt,
    RunReceipt,
    StrictModel,
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
    ModelAllowance,
    ModelUsage,
    PlannerResult,
    UnmeteredModelResponse,
)
from lyme_gap_atlas_dataset_discovery.graph.sequential import GraphDependencies, build_graph


class CandidateCase(StrictModel):
    id: str = Field(min_length=1)
    evidence: bool = True
    governed_status: Literal["UNKNOWN", "ALREADY_GOVERNED"] = "UNKNOWN"
    planner: Literal["NORMAL", "INVALID", "UNMETERED"] = "NORMAL"
    identity_link: Literal["NONE", "EXACT", "ALTERNATE", "AMBIGUOUS"] = "NONE"


class TrajectoryCase(StrictModel):
    id: str = Field(min_length=1)
    candidates: tuple[CandidateCase, ...]
    candidate_limit: int | None = Field(default=None, ge=1)
    nodes: tuple[str, ...]
    status: str
    outcomes: tuple[str, ...]
    processed: int = Field(ge=0)
    recommendations: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    replay: bool = False
    reader_fault: Literal["NONE", "EVIDENCE_ONCE", "EVIDENCE_ALWAYS", "BATCH_ALWAYS"] = "NONE"
    planner_fault: Literal["NONE", "RELATIONSHIP_ONCE", "RELATIONSHIP_ALWAYS"] = "NONE"
    lost_ack: tuple[Literal["RUN", "OUTCOME", "RECOMMENDATION", "FINALIZATION"], ...] = ()
    retries: int = Field(default=0, ge=0, le=2)
    cancelled: bool = False
    stop_reason: str | None = None
    expected_relationship: Relationship | None = None
    expected_priority_bucket: str | None = None


class TrajectoryCorpus(StrictModel):
    version: Literal["v1"]
    cases: tuple[TrajectoryCase, ...]


@dataclass
class ScenarioPlanner(FakeCandidatePlanner):
    behaviors: dict[str, str]
    fault: str = "NONE"
    relationship_attempts: int = 0

    def relationship(
        self,
        candidate: CandidateSummary,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[RelationshipResult]:
        self.relationship_attempts += 1
        if self.fault == "RELATIONSHIP_ALWAYS" or (
            self.fault == "RELATIONSHIP_ONCE" and self.relationship_attempts == 1
        ):
            raise TimeoutError("synthetic model transport outage")
        behavior = self.behaviors.get(candidate.identity.resource_key)
        if behavior == "INVALID":
            raise InvalidModelResponse(ModelUsage(input_tokens=1, output_tokens=1))
        if behavior == "UNMETERED":
            raise UnmeteredModelResponse()
        return super().relationship(candidate, observations, allowance=allowance)


@dataclass
class ScenarioReader(FakeCandidateReader):
    fault: str = "NONE"
    evidence_attempts: int = 0

    def list_batch(self, *, cursor: str | None, limit: int) -> CandidatePage:
        if self.fault == "BATCH_ALWAYS":
            raise ConnectionError("synthetic batch outage")
        return super().list_batch(cursor=cursor, limit=limit)

    def get_observations(
        self, candidate_id: str, *, limit: int
    ) -> tuple[AvailableObservation, ...]:
        self.evidence_attempts += 1
        if self.fault == "EVIDENCE_ALWAYS" or (
            self.fault == "EVIDENCE_ONCE" and self.evidence_attempts == 1
        ):
            raise TimeoutError("synthetic evidence outage")
        return super().get_observations(candidate_id, limit=limit)


@dataclass
class ScenarioRepository(FakeRecommendationRepository):
    lose_ack_for: tuple[str, ...] = ()
    lost: set[str] = field(default_factory=set)

    def _ack(self, operation: str) -> None:
        if operation in self.lose_ack_for and operation not in self.lost:
            self.lost.add(operation)
            raise TimeoutError("synthetic acknowledgment loss after commit")

    def create_run(
        self,
        *,
        operation_key: str,
        run_id: str,
        metadata: RunCreateMetadata | None = None,
        retry_of_run_id: str | None = None,
    ) -> RunReceipt:
        receipt = super().create_run(
            operation_key=operation_key,
            run_id=run_id,
            metadata=metadata,
            retry_of_run_id=retry_of_run_id,
        )
        self._ack("RUN")
        return receipt

    def record_candidate_outcome(self, receipt: CandidateOutcomeReceipt) -> CandidateOutcomeReceipt:
        committed = super().record_candidate_outcome(receipt)
        self._ack("OUTCOME")
        return committed

    def save_recommendation(self, request: RecommendationWrite) -> RecommendationWriteReceipt:
        receipt = super().save_recommendation(request)
        self._ack("RECOMMENDATION")
        return receipt

    def finalize_run(self, receipt: RunFinalizationReceipt) -> RunFinalizationReceipt:
        committed = super().finalize_run(receipt)
        self._ack("FINALIZATION")
        return committed


def _candidate(
    item: CandidateCase,
) -> tuple[CandidateSummary, tuple[AvailableObservation, ...], FixturePlan]:
    identity = CandidateIdentity(
        resource_key=item.id,
        catalog_dataset_id=f"dataset-{item.id}",
        catalog_resource_id=f"resource-{item.id}",
    )
    ref = EvidenceRef(
        observation_id=f"observation-{item.id}",
        catalog_dataset_id=identity.catalog_dataset_id,
        catalog_resource_id=identity.catalog_resource_id,
        observed_at="2026-09-26T00:00:00Z",
    )
    summary = CandidateSummary(identity=identity, evidence_refs=(ref,) if item.evidence else ())
    observations = (
        (
            AvailableObservation(
                reference=ref, field_values={"title": "Lyme surveillance", "publisher": "Agency"}
            ),
        )
        if item.evidence
        else ()
    )
    analysis = CandidateAnalysis(
        identity=identity,
        classification=Classification.RELEVANT,
        observed_facts=(
            ObservedFact(field="title", value="Lyme surveillance", evidence=ref),
            ObservedFact(field="publisher", value="Agency", evidence=ref),
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


def _identity_links(item: CandidateCase, identity: CandidateIdentity) -> tuple[IdentityLink, ...]:
    if item.identity_link == "NONE":
        return ()
    count = 2 if item.identity_link == "AMBIGUOUS" else 1
    return tuple(
        IdentityLink(
            candidate=identity,
            linked_resource_key=f"linked-{index}",
            linked_catalog_dataset_id=identity.catalog_dataset_id,
            linked_catalog_resource_id=f"linked-resource-{index}",
            relationship=(
                Relationship.ALTERNATE_DISTRIBUTION
                if item.identity_link == "ALTERNATE"
                else Relationship.EXACT_DUPLICATE
            ),
            basis=(
                "SAME_CATALOG_DATASET"
                if item.identity_link == "ALTERNATE"
                else "EXACT_CANONICAL_URL"
            ),
        )
        for index in range(count)
    )


def evaluate_case(case: TrajectoryCase) -> dict[str, object]:
    if len({item.id for item in case.candidates}) != len(case.candidates):
        raise ValueError("scenario candidate IDs must be unique")
    prepared = {item.id: _candidate(item) for item in case.candidates}
    reader = ScenarioReader(
        candidates=tuple(prepared[item.id][0] for item in case.candidates),
        observations={key: value[1] for key, value in prepared.items()},
        governed_statuses={item.id: item.governed_status for item in case.candidates},
        identity_links={
            item.id: _identity_links(item, prepared[item.id][0].identity)
            for item in case.candidates
        },
        fault=case.reader_fault,
    )
    repository = ScenarioRepository(lose_ack_for=case.lost_ack)
    planner = ScenarioPlanner(
        plans={key: value[2] for key, value in prepared.items()},
        behaviors={item.id: item.planner for item in case.candidates},
        fault=case.planner_fault,
    )
    graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=planner,
            clock=lambda: datetime(2026, 9, 26, tzinfo=UTC),
            cancellation_requested=lambda: case.cancelled,
            sleep=lambda _: None,
        )
    )
    limits = PROFILE_DEFAULTS[RunProfile.FIXTURE]
    limits = limits.model_copy(
        update={
            "candidates": case.candidate_limit or limits.candidates,
            "retries_per_operation": case.retries,
        }
    )
    initial: dict[str, Any] = {
        "execution_key": f"trajectory:{case.id}",
        "requested_run_id": f"run:{case.id}",
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

    def execute() -> tuple[tuple[str, ...], dict[str, Any]]:
        state = dict(initial)
        nodes: list[str] = []
        for event in graph.stream(initial, config={"recursion_limit": 100}, stream_mode="updates"):
            if len(event) != 1:
                raise ValueError("expected one sequential graph node per update")
            name, patch = next(iter(event.items()))
            if name == "__end__" and patch is None:
                continue
            nodes.append(name)
            if patch is not None:
                state.update(patch)
        return tuple(nodes), state

    nodes, state = execute()
    finalization = repository.finalizations.get(initial["requested_run_id"])
    errors: list[str] = []
    forbidden = {"review", "handoff", "source_approval", "ingest"}
    actual_outcomes = tuple(receipt.outcome for receipt in repository.outcomes.values())
    checks = {
        "nodes": (nodes, case.nodes),
        "status": (state.get("final_status"), case.status),
        "outcomes": (actual_outcomes, case.outcomes),
        "processed": (state.get("processed_count"), case.processed),
        "recommendations": (len(repository.recommendations), case.recommendations),
        "model_calls": (state["usage"].model_calls, case.model_calls),
        "tool_calls": (state["usage"].tool_calls, case.tool_calls),
        "run_receipts": (len(repository.runs), 1),
        "finalization_receipts": (len(repository.finalizations), 1),
        "durable_status": (finalization.status if finalization else None, case.status),
        "durable_processed": (
            finalization.processed_count if finalization else None,
            case.processed,
        ),
        "durable_recommendations": (
            finalization.recommendation_count if finalization else None,
            case.recommendations,
        ),
        "stop_reason": (state.get("stop_reason"), case.stop_reason),
        "lost_ack_reconciled": (tuple(sorted(repository.lost)), tuple(sorted(case.lost_ack))),
    }
    if case.expected_relationship is not None or case.expected_priority_bucket is not None:
        bundles = tuple(repository.recommendation_bundles.values())
        if len(bundles) != 1:
            errors.append("expected_one_ranked_relationship")
        else:
            if (
                case.expected_relationship is not None
                and bundles[0].relationship.relationship != case.expected_relationship
            ):
                errors.append("relationship")
            if (
                case.expected_priority_bucket is not None
                and bundles[0].priority.bucket.value != case.expected_priority_bucket
            ):
                errors.append("priority_bucket")
    errors.extend(key for key, (actual, expected) in checks.items() if actual != expected)
    if forbidden.intersection(nodes):
        errors.append("forbidden_authority_node")
    if state.get("current_candidate_id") is not None or state.get("current_evidence") != ():
        errors.append("candidate_state_not_cleared")
    if case.replay:
        replay_nodes, replay_state = execute()
        if replay_nodes != nodes or replay_state.get("final_status") != state.get("final_status"):
            errors.append("replay_trajectory")
        if (
            len(repository.runs),
            len(repository.outcomes),
            len(repository.recommendations),
            len(repository.finalizations),
        ) != (1, len(case.outcomes), case.recommendations, 1):
            errors.append("replay_duplicate_receipt")
    return {"id": case.id, "passed": not errors, "failures": errors, "nodes": nodes}


def evaluate_corpus(path: Path) -> dict[str, object]:
    corpus = TrajectoryCorpus.model_validate_json(path.read_text(encoding="utf-8"))
    if len({case.id for case in corpus.cases}) != len(corpus.cases):
        raise ValueError("trajectory case IDs must be unique")
    results = [evaluate_case(case) for case in corpus.cases]
    return {
        "version": corpus.version,
        "passed": all(item["passed"] for item in results),
        "cases": results,
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: python -m lyme_gap_atlas_dataset_discovery.graph_evaluation CORPUS.json"
        )
    report = evaluate_corpus(Path(sys.argv[1]))
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

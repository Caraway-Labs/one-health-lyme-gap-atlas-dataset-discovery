"""Versioned, credential-free graph trajectory and durable receipt evaluation."""

import json
import sys
from dataclasses import dataclass
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
    CandidateSummary,
    EvidenceRef,
    ObservedFact,
    StrictModel,
)
from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    Dimension,
    RankingDimensions,
    Relationship,
)
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult
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


class TrajectoryCorpus(StrictModel):
    version: Literal["v1"]
    cases: tuple[TrajectoryCase, ...]


@dataclass
class ScenarioPlanner(FakeCandidatePlanner):
    behaviors: dict[str, str]

    def relationship(
        self,
        candidate: CandidateSummary,
        observations: tuple[AvailableObservation, ...],
        *,
        allowance: ModelAllowance,
    ) -> PlannerResult[RelationshipResult]:
        behavior = self.behaviors.get(candidate.identity.resource_key)
        if behavior == "INVALID":
            raise InvalidModelResponse(ModelUsage(input_tokens=1, output_tokens=1))
        if behavior == "UNMETERED":
            raise UnmeteredModelResponse()
        return super().relationship(candidate, observations, allowance=allowance)


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


def evaluate_case(case: TrajectoryCase) -> dict[str, object]:
    if len({item.id for item in case.candidates}) != len(case.candidates):
        raise ValueError("scenario candidate IDs must be unique")
    prepared = {item.id: _candidate(item) for item in case.candidates}
    reader = FakeCandidateReader(
        candidates=tuple(prepared[item.id][0] for item in case.candidates),
        observations={key: value[1] for key, value in prepared.items()},
        governed_statuses={item.id: item.governed_status for item in case.candidates},
    )
    repository = FakeRecommendationRepository()
    planner = ScenarioPlanner(
        plans={key: value[2] for key, value in prepared.items()},
        behaviors={item.id: item.planner for item in case.candidates},
    )
    graph = build_graph(
        GraphDependencies(
            reader=reader,
            repository=repository,
            planner=planner,
            clock=lambda: datetime(2026, 9, 26, tzinfo=UTC),
        )
    )
    limits = PROFILE_DEFAULTS[RunProfile.FIXTURE]
    if case.candidate_limit is not None:
        limits = limits.model_copy(update={"candidates": case.candidate_limit})
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
    }
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

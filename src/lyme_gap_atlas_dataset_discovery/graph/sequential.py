"""Compiled, sequential Dataset Discovery workflow with injected closed ports."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from lyme_gap_atlas_dataset_discovery.domain.analysis import validate_analysis
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateOutcomeReceipt,
    RecommendationIdentity,
    RunFinalizationReceipt,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import RecommendationWrite
from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    PriorityInput,
    Relationship,
    rank_candidate,
)
from lyme_gap_atlas_dataset_discovery.ports.contracts import (
    CandidateReader,
    RecommendationRepository,
)

from .budgets import BudgetExceeded, BudgetUsage, RunBudgetConfig, charge_budget, remaining_budget
from .planner import CandidatePlanner
from .state import STATE_VERSION, DatasetDiscoveryState, clear_candidate_state


@dataclass(frozen=True)
class GraphDependencies:
    reader: CandidateReader
    repository: RecommendationRepository
    planner: CandidatePlanner


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _current(state: DatasetDiscoveryState) -> str:
    candidate_id = state.get("current_candidate_id")
    if candidate_id is None:
        raise ValueError("no current candidate")
    return candidate_id


def build_graph(deps: GraphDependencies) -> Any:
    """Compile one-candidate-at-a-time graph; production adapters are injected."""

    def initialize_run(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        required = (
            "execution_key",
            "requested_run_id",
            "profile",
            "trigger_type",
            "code_sha",
            "spec_version",
            "graph_version",
            "config_fingerprint",
            "search_fingerprint",
            "evidence_snapshot_id",
            "limits",
        )
        if any(not state.get(name) for name in required):
            raise ValueError("invalid run configuration: required identity missing")
        RunBudgetConfig(
            profile=state["profile"],
            limits=state["limits"],
            price_table_version=state.get("price_table_version"),
        )
        return {
            "state_version": STATE_VERSION,
            "usage": BudgetUsage(),
            "remaining_run_budget": remaining_budget(BudgetUsage(), state["limits"]),
            "candidate_queue": (),
            "current_candidate_index": -1,
            "next_page_cursor": None,
            "pages_loaded": 0,
            "processed_candidate_outcomes": (),
            "seen_candidate_ids": (),
            "skip_duplicate": False,
            "processed_count": 0,
            "persisted_recommendation_version_ids": (),
            "bounded_errors": (),
            "stop_reason": None,
            "final_status": None,
            **clear_candidate_state(),
        }

    def create_run(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        receipt = deps.repository.create_run(
            operation_key=state["execution_key"],
            run_id=state["requested_run_id"],
            retry_of_run_id=state.get("retry_of_run_id"),
        )
        return {"run_id": receipt.run_id}

    def load_discovery_context(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        if not state["search_fingerprint"] or not state["evidence_snapshot_id"]:
            raise ValueError("inaccessible discovery context")
        return {}

    def load_candidate_batch(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        remaining = state["limits"].candidates - state["processed_count"]
        if remaining <= 0:
            return {"stop_reason": "CANDIDATE_BUDGET", "final_status": "BUDGET_STOPPED"}
        usage = charge_budget(state["usage"], state["limits"], pages=1, tool_calls=1)
        page = deps.reader.list_batch(cursor=state["next_page_cursor"], limit=min(25, remaining))
        if not page.candidates and page.next_cursor is not None:
            raise ValueError("candidate reader returned an empty nonterminal page")
        return {
            "usage": usage,
            "pages_loaded": state["pages_loaded"] + 1,
            "candidate_queue": page.candidates,
            "current_candidate_index": -1,
            "next_page_cursor": page.next_cursor,
        }

    def select_next_candidate(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        next_index = state["current_candidate_index"] + 1
        result: DatasetDiscoveryState = {
            **clear_candidate_state(),
            "current_candidate_index": next_index,
        }
        if next_index < len(state["candidate_queue"]):
            candidate = state["candidate_queue"][next_index]
            candidate_id = candidate.identity.resource_key
            if candidate_id in state["seen_candidate_ids"]:
                result["skip_duplicate"] = True
                return result
            usage = charge_budget(state["usage"], state["limits"], candidates=1)
            result["usage"] = usage
            result["current_candidate_id"] = candidate_id
            result["current_candidate"] = candidate
            result["seen_candidate_ids"] = (*state["seen_candidate_ids"], candidate_id)
        return result

    def assess_evidence_sufficiency(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        candidate = state["current_candidate"]
        if candidate is None:
            raise ValueError("no candidate selected")
        usage = charge_budget(state["usage"], state["limits"], tool_calls=1)
        observations = deps.reader.get_observations(_current(state), limit=25)
        evidence_bytes = len(
            json.dumps(
                [item.model_dump(mode="json") for item in observations],
                sort_keys=True,
            ).encode("utf-8")
        )
        usage = charge_budget(usage, state["limits"], evidence_bytes=evidence_bytes)
        refs = tuple(item.reference for item in observations)
        if not observations:
            return {
                "usage": usage,
                "current_observations": (),
                "current_evidence": (),
                "candidate_outcome_reason": "INSUFFICIENT_EVIDENCE",
            }
        if any(
            ref.catalog_dataset_id != candidate.identity.catalog_dataset_id
            or ref.catalog_resource_id != candidate.identity.catalog_resource_id
            for ref in refs
        ):
            return {"usage": usage, "candidate_outcome_reason": "INVALID_EVIDENCE_IDENTITY"}
        return {"usage": usage, "current_observations": observations, "current_evidence": refs}

    def analyze_candidate_relationship(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        candidate = state["current_candidate"]
        if candidate is None:
            raise ValueError("no candidate selected")
        usage = charge_budget(state["usage"], state["limits"], model_calls=1)
        relationship = deps.planner.relationship(candidate, state["current_observations"])
        result: DatasetDiscoveryState = {"usage": usage, "current_relationship": relationship}
        if relationship.relationship in {Relationship.EXACT_DUPLICATE, Relationship.ALREADY_KNOWN}:
            result["candidate_outcome_reason"] = relationship.relationship.value
        return result

    def classify_and_score_candidate(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        candidate = state["current_candidate"]
        relation = state["current_relationship"]
        if candidate is None or relation is None:
            raise ValueError("candidate relationship missing")
        usage = charge_budget(state["usage"], state["limits"], model_calls=1)
        analysis, dimensions = deps.planner.classify(candidate, state["current_observations"])
        version_id = _stable_id("recommendation-version-v1", state["run_id"], _current(state))
        ranking_input = PriorityInput(
            resource_key=_current(state),
            recommendation_version_id=version_id,
            observed_evidence_ids=frozenset(
                fact.evidence.observation_id for fact in analysis.observed_facts
            ),
            relationship=relation.relationship,
            dimensions=dimensions,
        )
        priority = rank_candidate(ranking_input)
        result: DatasetDiscoveryState = {
            "usage": usage,
            "current_analysis": analysis,
            "current_ranking_input": ranking_input,
            "current_priority": priority,
        }
        if priority.score is None:
            result["candidate_outcome_reason"] = priority.abstain_reason or "ABSTAIN"
        return result

    def generate_recommendation_rationale(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        analysis = state["current_analysis"]
        if analysis is None:
            raise ValueError("candidate analysis missing")
        usage = charge_budget(state["usage"], state["limits"], model_calls=1)
        return {
            "usage": usage,
            "current_analysis": analysis.model_copy(
                update={"rationale_claims": deps.planner.rationale(analysis)}
            ),
        }

    def propose_search_expansions(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        analysis = state["current_analysis"]
        if analysis is None:
            raise ValueError("candidate analysis missing")
        usage = charge_budget(state["usage"], state["limits"], model_calls=1)
        proposals = deps.planner.proposals(analysis)
        return {
            "usage": usage,
            "current_proposals": proposals,
            "current_analysis": analysis.model_copy(
                update={"search_expansion_proposals": proposals}
            ),
        }

    def validate_candidate_result(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        analysis = state["current_analysis"]
        if analysis is None or state["current_priority"] is None:
            return {"candidate_outcome_reason": "MISSING_ANALYSIS"}
        try:
            validate_analysis(analysis, available_evidence=state["current_observations"])
        except ValueError:
            return {"candidate_outcome_reason": "INVALID_EVIDENCE_OR_CLAIM"}
        return {}

    def persist_recommendation(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        analysis = state["current_analysis"]
        ranking_input = state["current_ranking_input"]
        priority = state["current_priority"]
        relationship = state["current_relationship"]
        if not all((analysis, ranking_input, priority, relationship)):
            raise ValueError("validated recommendation bundle missing")
        assert analysis is not None and ranking_input is not None
        assert priority is not None and relationship is not None
        content = json.dumps(
            {
                "analysis": analysis.model_dump(mode="json"),
                "ranking_input": ranking_input.model_dump(mode="json"),
                "priority": priority.model_dump(mode="json"),
                "relationship": relationship.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        identity = RecommendationIdentity(
            recommendation_id=_stable_id("recommendation-v1", _current(state)),
            recommendation_version_id=ranking_input.recommendation_version_id,
            run_id=state["run_id"],
            resource_key=_current(state),
        )
        operation_key = f"recommendation:{state['run_id']}:{_current(state)}"
        receipt = deps.repository.save_recommendation(
            RecommendationWrite(
                operation_key=operation_key,
                identity=identity,
                assertion_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                analysis=analysis,
                ranking_input=ranking_input,
                priority=priority,
                relationship=relationship,
            )
        )
        return {
            "persistence_operation_key": receipt.operation_key,
            "persisted_recommendation_version_ids": (
                *state["persisted_recommendation_version_ids"],
                receipt.identity.recommendation_version_id,
            ),
            "processed_count": state["processed_count"] + 1,
        }

    def record_candidate_outcome(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        reason = state.get("candidate_outcome_reason") or "ABSTAIN"
        operation_key = f"outcome:{state['run_id']}:{_current(state)}"
        deps.repository.record_candidate_outcome(
            CandidateOutcomeReceipt(
                operation_key=operation_key,
                run_id=state["run_id"],
                resource_key=_current(state),
                outcome=reason,
                reason_code=reason,
            )
        )
        return {
            "processed_candidate_outcomes": (*state["processed_candidate_outcomes"], reason),
            "processed_count": state["processed_count"] + 1,
        }

    def build_run_summary(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        if state.get("final_status"):
            return {}
        if state["persisted_recommendation_version_ids"]:
            return {"final_status": "SUCCEEDED_WITH_RECOMMENDATIONS"}
        return {"final_status": "SUCCEEDED_NO_NEW_CANDIDATES"}

    def finalize_run(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        receipt = deps.repository.finalize_run(
            RunFinalizationReceipt(
                operation_key=f"finalize:{state['run_id']}",
                run_id=state["run_id"],
                status=state["final_status"] or "FAILED",
                processed_count=state["processed_count"],
                recommendation_count=len(state["persisted_recommendation_version_ids"]),
                stop_reason=state.get("stop_reason"),
            )
        )
        return {"final_status": receipt.status}

    candidate_analysis_nodes = {
        "assess_evidence_sufficiency",
        "analyze_candidate_relationship",
        "classify_and_score_candidate",
        "generate_recommendation_rationale",
        "propose_search_expansions",
        "validate_candidate_result",
    }

    def guard(
        name: str,
        fn: Callable[[DatasetDiscoveryState], DatasetDiscoveryState],
    ) -> Callable[[DatasetDiscoveryState], DatasetDiscoveryState]:
        def guarded(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
            try:
                usage = charge_budget(state["usage"], state["limits"], graph_steps=1)
                charged: DatasetDiscoveryState = {**state, "usage": usage}
                result: DatasetDiscoveryState = fn(charged)
                final_usage = result.get("usage", usage)
                result["usage"] = final_usage
                result["remaining_run_budget"] = remaining_budget(final_usage, state["limits"])
                return result
            except BudgetExceeded as error:
                return {"stop_reason": str(error), "final_status": "BUDGET_STOPPED"}
            except Exception as error:
                code = f"{name}:{type(error).__name__}"
                bounded_errors = (*state.get("bounded_errors", ()), code)[-10:]
                if name in candidate_analysis_nodes:
                    return {
                        "candidate_outcome_reason": "CANDIDATE_ANALYSIS_ERROR",
                        "bounded_errors": bounded_errors,
                    }
                return {
                    "stop_reason": code,
                    "final_status": "PARTIAL" if state.get("processed_count", 0) else "FAILED",
                    "bounded_errors": bounded_errors,
                }

        return guarded

    builder = StateGraph(DatasetDiscoveryState)
    handlers = {
        "initialize_run": initialize_run,
        "create_run": create_run,
        "load_discovery_context": load_discovery_context,
        "load_candidate_batch": load_candidate_batch,
        "select_next_candidate": select_next_candidate,
        "assess_evidence_sufficiency": assess_evidence_sufficiency,
        "analyze_candidate_relationship": analyze_candidate_relationship,
        "classify_and_score_candidate": classify_and_score_candidate,
        "generate_recommendation_rationale": generate_recommendation_rationale,
        "propose_search_expansions": propose_search_expansions,
        "validate_candidate_result": validate_candidate_result,
        "persist_recommendation": persist_recommendation,
        "record_candidate_outcome": record_candidate_outcome,
        "build_run_summary": build_run_summary,
        "finalize_run": finalize_run,
    }
    for name, handler in handlers.items():
        builder.add_node(
            name,
            cast(
                Any,
                handler
                if name in {"initialize_run", "build_run_summary", "finalize_run"}
                else guard(name, handler),
            ),
        )
    builder.add_edge(START, "initialize_run")
    builder.add_edge("initialize_run", "create_run")

    def route(next_node: str) -> Callable[[DatasetDiscoveryState], str]:
        def choose(state: DatasetDiscoveryState) -> str:
            if state.get("stop_reason"):
                return "build_run_summary" if state.get("run_id") else END
            return next_node

        return choose

    for source, target in (
        ("create_run", "load_discovery_context"),
        ("load_discovery_context", "load_candidate_batch"),
        ("load_candidate_batch", "select_next_candidate"),
        ("generate_recommendation_rationale", "propose_search_expansions"),
        ("propose_search_expansions", "validate_candidate_result"),
        ("record_candidate_outcome", "select_next_candidate"),
        ("persist_recommendation", "select_next_candidate"),
    ):
        builder.add_conditional_edges(source, route(target))

    def after_select(state: DatasetDiscoveryState) -> str:
        if state.get("stop_reason"):
            return "build_run_summary"
        if state.get("skip_duplicate"):
            return "select_next_candidate"
        if state.get("current_candidate_id"):
            return (
                "record_candidate_outcome"
                if state.get("candidate_outcome_reason")
                else "assess_evidence_sufficiency"
            )
        if state.get("next_page_cursor"):
            return "load_candidate_batch"
        return "build_run_summary"

    builder.add_conditional_edges("select_next_candidate", after_select)
    for node, success in (
        ("assess_evidence_sufficiency", "analyze_candidate_relationship"),
        ("analyze_candidate_relationship", "classify_and_score_candidate"),
        ("classify_and_score_candidate", "generate_recommendation_rationale"),
        ("validate_candidate_result", "persist_recommendation"),
    ):

        def choose(state: DatasetDiscoveryState, next_node: str = success) -> str:
            if state.get("stop_reason"):
                return "build_run_summary"
            return (
                "record_candidate_outcome" if state.get("candidate_outcome_reason") else next_node
            )

        builder.add_conditional_edges(node, choose)

    builder.add_edge("build_run_summary", "finalize_run")
    builder.add_edge("finalize_run", END)
    return builder.compile()

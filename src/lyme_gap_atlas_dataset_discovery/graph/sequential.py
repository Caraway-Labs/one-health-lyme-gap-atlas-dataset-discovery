"""Compiled, sequential Dataset Discovery workflow with injected closed ports."""

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from lyme_gap_atlas_dataset_discovery.domain.analysis import (
    CandidateAnalysis,
    render_rationale,
    validate_analysis,
)
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateDecisionRecord,
    CandidateOutcomeReceipt,
    DecisionDimension,
    DecisionTokenUsage,
    RecommendationIdentity,
    RunCreateMetadata,
    RunFinalizationReceipt,
    RunReceipt,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import (
    RecommendationWrite,
    assertion_sha256,
    rights_evidence_state,
)
from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    PriorityInput,
    Relationship,
    rank_candidate,
)
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult
from lyme_gap_atlas_dataset_discovery.observability import traced_operation
from lyme_gap_atlas_dataset_discovery.ports.contracts import (
    CandidateReader,
    DiscoveryContextReader,
    RecommendationRepository,
)

from .budgets import (
    BudgetExceeded,
    BudgetLimit,
    BudgetUsage,
    RunBudgetConfig,
    RunProfile,
    charge_budget,
    remaining_budget,
)
from .planner import (
    CandidatePlanner,
    ModelAllowance,
    ModelDiagnostic,
    ModelUsage,
    PlannerResult,
    UnmeteredModelResponse,
    ValidatedCandidatePlanner,
)
from .state import STATE_VERSION, DatasetDiscoveryState, clear_candidate_state


@dataclass(frozen=True)
class GraphDependencies:
    reader: CandidateReader
    repository: RecommendationRepository
    planner: CandidatePlanner
    context_reader: DiscoveryContextReader | None = None
    deployed_code_sha: str | None = None
    expected_snapshot_id: str | None = None
    approved_price_table_version: str | None = None
    required_profile: RunProfile | None = None
    expected_model_id: str | None = None
    expected_model_provider: str | None = None
    expected_model_fingerprint: str | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    cancellation_requested: Callable[[], bool] = lambda: False
    sleep: Callable[[float], None] = time.sleep


class PolicyViolation(RuntimeError):
    """Unrecoverable authority or security boundary failure."""


class RetryExhausted(RuntimeError):
    """Carry charged attempts when a transient call has no successful result."""

    def __init__(self, cause: ConnectionError | TimeoutError, usage: BudgetUsage) -> None:
        super().__init__(type(cause).__name__)
        self.cause = cause
        self.usage = usage


class ChargedCallFailure(RuntimeError):
    """Retain attempt and known billed usage when a nontransient call fails."""

    def __init__(self, cause: Exception, usage: BudgetUsage) -> None:
        super().__init__(type(cause).__name__)
        self.cause = cause
        self.usage = usage


class ReportedUsageExceeded(BudgetExceeded):
    """A model exceeded its allowance; retain measured usage in the run state."""

    def __init__(self, usage: BudgetUsage) -> None:
        super().__init__("model reported usage beyond per-call allowance")
        self.usage = usage


def _deliver_with_receipt_reconciliation[ReceiptT](
    *,
    operation: str,
    send: Callable[[], ReceiptT],
    lookup: Callable[[], ReceiptT | None],
    accepts: Callable[[ReceiptT], bool],
    retries: int,
    sleep: Callable[[float], None],
) -> ReceiptT:
    """Resolve a lost commit acknowledgment before resending an idempotent key."""
    for attempt in range(retries + 1):
        try:
            with traced_operation("persistence", operation, "send", attempt + 1):
                receipt = send()
                if not accepts(receipt):
                    raise ValueError("write returned a conflicting receipt")
            return receipt
        except (ConnectionError, TimeoutError):
            try:
                with traced_operation("persistence", operation, "lookup", attempt + 1):
                    committed = lookup()
            except (ConnectionError, TimeoutError):
                committed = None
            if committed is not None:
                if not accepts(committed):
                    raise ValueError(
                        "committed receipt conflicts with requested operation"
                    ) from None
                return committed
            if attempt == retries:
                raise
            sleep(min(0.25 * 2**attempt, 2.0))
    raise AssertionError("bounded retry loop unexpectedly exhausted")


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _safe_audit_name(value: str, fallback: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value) else fallback


def _bounded_call[ResultT](
    *,
    operation: str,
    call: Callable[[], ResultT],
    usage: BudgetUsage,
    limits: BudgetLimit,
    dimension: str,
    retries: int,
    sleep: Callable[[float], None],
) -> tuple[ResultT, BudgetUsage]:
    """Charge each read/model attempt and retry only transient transport failures."""
    if dimension not in {"tool_calls", "model_calls"}:
        raise ValueError("unsupported call budget dimension")
    current = usage
    for attempt in range(retries + 1):
        current = charge_budget(current, limits, **{dimension: 1})
        try:
            with traced_operation(
                "tool" if dimension == "tool_calls" else "model",
                operation,
                "attempt",
                attempt + 1,
            ):
                return call(), current
        except (ConnectionError, TimeoutError) as error:
            if attempt == retries:
                raise RetryExhausted(error, current) from error
            sleep(min(0.25 * 2**attempt, 2.0))
        except BudgetExceeded:
            raise
        except Exception as error:
            reported = getattr(error, "usage", None)
            if dimension == "model_calls" and isinstance(reported, ModelUsage):
                current = current.model_copy(
                    update={
                        "input_tokens": current.input_tokens + reported.input_tokens,
                        "output_tokens": current.output_tokens + reported.output_tokens,
                        "estimated_spend_cents": (
                            current.estimated_spend_cents + reported.estimated_spend_cents
                        ),
                    }
                )
            raise ChargedCallFailure(error, current) from error
    raise AssertionError("bounded retry loop unexpectedly exhausted")


def _current(state: DatasetDiscoveryState) -> str:
    candidate_id = state.get("current_candidate_id")
    if candidate_id is None:
        raise ValueError("no current candidate")
    return candidate_id


def _model_allowance(usage: BudgetUsage, limits: BudgetLimit) -> ModelAllowance:
    remaining = remaining_budget(usage, limits)
    return ModelAllowance(
        max_input_tokens=remaining["input_tokens"],
        max_output_tokens=remaining["output_tokens"],
        max_estimated_spend_cents=remaining["estimated_spend_cents"],
    )


def _charge_model_result[T](
    result: PlannerResult[T], usage: BudgetUsage, limits: BudgetLimit, allowance: ModelAllowance
) -> tuple[T, BudgetUsage]:
    report = result.usage
    measured = usage.model_copy(
        update={
            "input_tokens": usage.input_tokens + report.input_tokens,
            "output_tokens": usage.output_tokens + report.output_tokens,
            "estimated_spend_cents": (usage.estimated_spend_cents + report.estimated_spend_cents),
        }
    )
    if (
        report.input_tokens > allowance.max_input_tokens
        or report.output_tokens > allowance.max_output_tokens
        or report.estimated_spend_cents > allowance.max_estimated_spend_cents
    ):
        raise ReportedUsageExceeded(measured)
    charged = charge_budget(
        usage,
        limits,
        input_tokens=report.input_tokens,
        output_tokens=report.output_tokens,
        estimated_spend_cents=report.estimated_spend_cents,
    )
    return result.value, charged


def build_graph(deps: GraphDependencies) -> Any:
    """Compile one-candidate-at-a-time graph; production adapters are injected."""

    from lyme_gap_atlas_dataset_discovery.observability import (
        configure_dataset_discovery_tracing,
        traced_node,
    )

    configure_dataset_discovery_tracing()

    validated_planner = (
        deps.planner
        if isinstance(deps.planner, ValidatedCandidatePlanner)
        else ValidatedCandidatePlanner(deps.planner)
    )

    def planner_for(state: DatasetDiscoveryState) -> CandidatePlanner:
        return deps.planner if state["profile"] == RunProfile.FIXTURE else validated_planner

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
        if not re.fullmatch(r"[0-9a-f]{40}", state["code_sha"]):
            raise ValueError("run code SHA must be an exact lowercase commit ID")
        if deps.deployed_code_sha is not None and state["code_sha"] != deps.deployed_code_sha:
            raise ValueError("run code SHA differs from deployed graph")
        if deps.required_profile is not None and state["profile"] != deps.required_profile:
            raise ValueError("run profile differs from deployed graph")
        if (
            deps.required_profile in {RunProfile.HOSTED_MANUAL, RunProfile.SHADOW}
            and state["trigger_type"] != "MANUAL"
        ):
            raise ValueError("hosted run requires a manual trigger until scheduling is approved")
        if deps.expected_model_id is not None and state.get("model_id") != deps.expected_model_id:
            raise ValueError("run model differs from deployed graph")
        if (
            deps.expected_model_provider is not None
            and state.get("model_provider") != deps.expected_model_provider
        ):
            raise ValueError("run provider differs from deployed graph")
        if (
            deps.expected_model_fingerprint is not None
            and state.get("model_fingerprint") != deps.expected_model_fingerprint
        ):
            raise ValueError("run model configuration differs from deployed graph")
        if (
            deps.expected_snapshot_id is not None
            and state["evidence_snapshot_id"] != deps.expected_snapshot_id
        ):
            raise ValueError("run discovery snapshot differs from pinned reader")
        if (
            deps.approved_price_table_version is not None
            and state.get("price_table_version") != deps.approved_price_table_version
        ):
            raise ValueError("run price table differs from approved deployment")
        RunBudgetConfig(
            profile=state["profile"],
            limits=state["limits"],
            price_table_version=state.get("price_table_version"),
        )
        now = deps.clock()
        if now.tzinfo is None:
            raise ValueError("clock must be timezone aware")
        latest_deadline = now + timedelta(seconds=state["limits"].elapsed_seconds)
        requested_deadline = state.get("deadline_at")
        deadline = (
            datetime.fromisoformat(requested_deadline) if requested_deadline else latest_deadline
        )
        if deadline.tzinfo is None:
            raise ValueError("deadline must be timezone aware")
        deadline = min(deadline, latest_deadline)
        return {
            "state_version": STATE_VERSION,
            "started_at": now.isoformat(),
            "deadline_at": deadline.isoformat(),
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
        metadata = RunCreateMetadata(
            mode=state["profile"].value,
            trigger_type=state["trigger_type"],
            code_sha=state["code_sha"],
            spec_version=state["spec_version"],
            graph_version=state["graph_version"],
            config_fingerprint=state["config_fingerprint"],
            search_fingerprint=state["search_fingerprint"],
            evidence_snapshot_id=state["evidence_snapshot_id"],
            provider=state.get("model_provider"),
            model_id=state.get("model_id"),
            model_fingerprint=state.get("model_fingerprint"),
            prompt_versions=state.get("prompt_versions", {}),
            tool_versions=state.get("tool_versions", {}),
            eval_version=state.get("eval_version"),
            trace_id=state.get("trace_id"),
            host_session_id=state.get("host_session_id"),
        )
        receipt: RunReceipt = _deliver_with_receipt_reconciliation(
            operation="run_create",
            send=lambda: deps.repository.create_run(
                operation_key=state["execution_key"],
                run_id=state["requested_run_id"],
                metadata=metadata,
                retry_of_run_id=state.get("retry_of_run_id"),
            ),
            lookup=lambda: deps.repository.get_run(state["execution_key"]),
            accepts=lambda item: (
                item.operation_key == state["execution_key"]
                and item.retry_of_run_id == state.get("retry_of_run_id")
                and item.request_fingerprint == metadata.request_fingerprint
            ),
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
        )
        return {"run_id": receipt.run_id}

    def load_discovery_context(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        if not state["search_fingerprint"] or not state["evidence_snapshot_id"]:
            raise ValueError("inaccessible discovery context")
        if deps.context_reader is None:
            if state["profile"] != RunProfile.FIXTURE:
                raise ValueError("non-fixture run requires governed discovery context")
            return {}
        context = deps.context_reader.get_context(state["evidence_snapshot_id"])
        if (
            context.discovery_run_id != state["evidence_snapshot_id"]
            or context.search_fingerprint != state["search_fingerprint"]
        ):
            raise ValueError("discovery context differs from requested snapshot or search config")
        reader_snapshot = getattr(deps.reader, "discovery_run_id", None)
        if reader_snapshot != context.discovery_run_id:
            raise ValueError("candidate reader is pinned to a different discovery run")
        return {}

    def load_candidate_batch(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        remaining = state["limits"].candidates - state["processed_count"]
        if remaining <= 0:
            return {"stop_reason": "CANDIDATE_BUDGET", "final_status": "BUDGET_STOPPED"}
        usage = charge_budget(state["usage"], state["limits"], pages=1)
        page, usage = _bounded_call(
            operation="candidate_batch",
            call=lambda: deps.reader.list_batch(
                cursor=state["next_page_cursor"], limit=min(25, remaining)
            ),
            usage=usage,
            limits=state["limits"],
            dimension="tool_calls",
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
        )
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
        governed_status, usage = _bounded_call(
            operation="governed_status",
            call=lambda: deps.reader.get_governed_status(_current(state)),
            usage=state["usage"],
            limits=state["limits"],
            dimension="tool_calls",
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
        )
        if governed_status == "ALREADY_GOVERNED":
            return {
                "usage": usage,
                "current_relationship": RelationshipResult(
                    relationship=Relationship.ALREADY_KNOWN,
                    basis="GOVERNED_RESOURCE_KEY",
                    supporting_observation_ids=(),
                ),
                "candidate_outcome_reason": Relationship.ALREADY_KNOWN.value,
            }
        if governed_status != "UNKNOWN":
            raise PolicyViolation("governed status view returned an unknown policy value")
        observations, usage = _bounded_call(
            operation="observations",
            call=lambda: deps.reader.get_observations(_current(state), limit=25),
            usage=usage,
            limits=state["limits"],
            dimension="tool_calls",
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
        )
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
        links, usage = _bounded_call(
            operation="identity_links",
            call=lambda: deps.reader.get_identity_links(_current(state)),
            usage=state["usage"],
            limits=state["limits"],
            dimension="tool_calls",
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
        )
        if len(links) > 1:
            return {"usage": usage, "candidate_outcome_reason": "AMBIGUOUS_RELATIONSHIP"}
        if links:
            link = links[0]
            if link.candidate != candidate.identity:
                raise PolicyViolation("identity link belongs to another candidate")
            relationship = RelationshipResult(
                relationship=link.relationship,
                basis=link.basis,
                supporting_observation_ids=(),
            )
            deterministic_result: DatasetDiscoveryState = {
                "usage": usage,
                "current_relationship": relationship,
            }
            if link.relationship == Relationship.EXACT_DUPLICATE:
                deterministic_result["candidate_outcome_reason"] = (
                    Relationship.EXACT_DUPLICATE.value
                )
            elif link.relationship == Relationship.ALTERNATE_DISTRIBUTION and any(
                observation.field_values.get("resource_role") == "download"
                and observation.field_values.get("resource_title") == "Original Metadata"
                and observation.field_values.get("distribution_media_type") == "text/xml"
                and observation.field_values.get("distribution_format") == "XML"
                for observation in state["current_observations"]
            ):
                deterministic_result["candidate_outcome_reason"] = (
                    "SUPPORTING_METADATA_DISTRIBUTION"
                )
            return deterministic_result
        allowance = _model_allowance(usage, state["limits"])
        response, usage = _bounded_call(
            operation="relationship",
            call=lambda: planner_for(state).relationship(
                candidate, state["current_observations"], allowance=allowance
            ),
            usage=usage,
            limits=state["limits"],
            dimension="model_calls",
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
        )
        relationship, usage = _charge_model_result(response, usage, state["limits"], allowance)
        result: DatasetDiscoveryState = {"usage": usage, "current_relationship": relationship}
        result["current_model_diagnostic"] = response.usage.diagnostic
        result["current_model_usage"] = response.usage
        if relationship.relationship in {Relationship.EXACT_DUPLICATE, Relationship.ALREADY_KNOWN}:
            result["candidate_outcome_reason"] = relationship.relationship.value
        return result

    def classify_and_score_candidate(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        candidate = state["current_candidate"]
        relation = state["current_relationship"]
        if candidate is None or relation is None:
            raise ValueError("candidate relationship missing")
        allowance = _model_allowance(state["usage"], state["limits"])
        response, usage = _bounded_call(
            operation="classification",
            call=lambda: planner_for(state).classify(
                candidate, state["current_observations"], allowance=allowance
            ),
            usage=state["usage"],
            limits=state["limits"],
            dimension="model_calls",
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
        )
        (analysis, dimensions), usage = _charge_model_result(
            response, usage, state["limits"], allowance
        )
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
            "current_model_diagnostic": response.usage.diagnostic,
            "current_model_usage": response.usage,
        }
        if priority.score is None:
            result["candidate_outcome_reason"] = priority.abstain_reason or "ABSTAIN"
        return result

    def generate_recommendation_rationale(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        analysis = state["current_analysis"]
        if analysis is None:
            raise ValueError("candidate analysis missing")
        allowance = _model_allowance(state["usage"], state["limits"])
        response, usage = _bounded_call(
            operation="rationale",
            call=lambda: planner_for(state).rationale(
                analysis, state["current_observations"], allowance=allowance
            ),
            usage=state["usage"],
            limits=state["limits"],
            dimension="model_calls",
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
        )
        rationale, usage = _charge_model_result(response, usage, state["limits"], allowance)
        return {
            "usage": usage,
            "current_analysis": analysis.model_copy(update={"rationale_claims": rationale}),
            "current_model_diagnostic": response.usage.diagnostic,
            "current_model_usage": response.usage,
        }

    def propose_search_expansions(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        analysis = state["current_analysis"]
        if analysis is None:
            raise ValueError("candidate analysis missing")
        allowance = _model_allowance(state["usage"], state["limits"])
        response, usage = _bounded_call(
            operation="proposals",
            call=lambda: planner_for(state).proposals(
                analysis, state["current_observations"], allowance=allowance
            ),
            usage=state["usage"],
            limits=state["limits"],
            dimension="model_calls",
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
        )
        proposals, usage = _charge_model_result(response, usage, state["limits"], allowance)
        return {
            "usage": usage,
            "current_proposals": proposals,
            "current_analysis": analysis.model_copy(
                update={"search_expansion_proposals": proposals}
            ),
            "current_model_diagnostic": response.usage.diagnostic,
            "current_model_usage": response.usage,
        }

    def validate_candidate_result(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        analysis = state["current_analysis"]
        if analysis is None or state["current_priority"] is None:
            return {"candidate_outcome_reason": "MISSING_ANALYSIS"}
        try:
            CandidateAnalysis.model_validate(analysis.model_dump())
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
        identity = RecommendationIdentity(
            recommendation_id=_stable_id("recommendation-v1", _current(state)),
            recommendation_version_id=ranking_input.recommendation_version_id,
            run_id=state["run_id"],
            resource_key=_current(state),
        )
        operation_key = f"recommendation:{state['run_id']}:{_current(state)}"
        request = RecommendationWrite(
            operation_key=operation_key,
            identity=identity,
            evidence_snapshot_id=state["evidence_snapshot_id"],
            rights_state=rights_evidence_state(analysis),
            assertion_sha256=assertion_sha256(analysis, ranking_input, priority, relationship),
            analysis=analysis,
            ranking_input=ranking_input,
            priority=priority,
            relationship=relationship,
            rationale=render_rationale(analysis.rationale_claims),
        )
        receipt = _deliver_with_receipt_reconciliation(
            operation="recommendation_commit",
            send=lambda: deps.repository.save_recommendation(request),
            lookup=lambda: deps.repository.get_recommendation(operation_key),
            accepts=lambda item: (
                item.operation_key == request.operation_key
                and item.identity == request.identity
                and item.assertion_sha256 == request.assertion_sha256
                and item.evidence_observation_ids == request.evidence_observation_ids
                and item.proposal_ids == request.proposal_ids
            ),
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
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
        candidate = state["current_candidate"]
        if candidate is None:
            raise ValueError("candidate outcome lacks canonical identity")
        analysis = state.get("current_analysis")
        diagnostic = state.get("current_model_diagnostic")
        model_usage = state.get("current_model_usage")
        if analysis is None and diagnostic is not None:
            analysis = diagnostic.parsed_analysis
        ranking_input = state.get("current_ranking_input")
        relationship = state.get("current_relationship")
        dimensions = (
            {
                name: DecisionDimension(
                    value=dimension.value,
                    cited_evidence_ids=tuple(
                        sorted(
                            {
                                _safe_audit_name(item, "UNREVIEWED_EVIDENCE_ID")
                                for item in dimension.supporting_observation_ids
                            }
                        )
                    )[:25],
                )
                for name, dimension in ranking_input.dimensions.__dict__.items()
            }
            if ranking_input is not None
            else {
                name: DecisionDimension(
                    value=dimension.value,
                    cited_evidence_ids=tuple(
                        sorted(
                            {
                                _safe_audit_name(item, "UNREVIEWED_EVIDENCE_ID")
                                for item in dimension.supporting_observation_ids
                            }
                        )
                    )[:25],
                )
                for name, dimension in diagnostic.parsed_dimensions.__dict__.items()
            }
            if diagnostic is not None and diagnostic.parsed_dimensions is not None
            else {}
        )
        cited_ids = (
            set(fact.evidence.observation_id for fact in analysis.observed_facts)
            if analysis is not None
            else set()
        )
        for dimension in dimensions.values():
            cited_ids.update(dimension.cited_evidence_ids)
        if relationship is not None:
            cited_ids.update(relationship.supporting_observation_ids)
        decision = CandidateDecisionRecord(
            model_id=state.get("model_id"),
            provider=state.get("model_provider"),
            model_fingerprint=state.get("model_fingerprint"),
            config_fingerprint=state["config_fingerprint"],
            prompt_version=state.get("prompt_versions", {}).get("semantic"),
            task_type=(
                diagnostic.task_type
                if diagnostic is not None
                else "CLASSIFICATION"
                if analysis is not None
                else "NOT_CALLED"
            ),
            model_call_attempted=diagnostic.model_call_attempted if diagnostic else False,
            model_call_succeeded_transport=(
                diagnostic.model_call_succeeded_transport if diagnostic else False
            ),
            structured_parse_succeeded=(
                diagnostic.structured_parse_succeeded if diagnostic else False
            ),
            validation_stage=diagnostic.validation_stage if diagnostic else None,
            validation_error_code=diagnostic.validation_error_code if diagnostic else None,
            provider_response_status=diagnostic.provider_response_status if diagnostic else None,
            provider_incomplete_reason=diagnostic.provider_incomplete_reason
            if diagnostic
            else None,
            provider_error_code=diagnostic.provider_error_code if diagnostic else None,
            provider_response_id_hash=diagnostic.provider_response_id_hash if diagnostic else None,
            validation_field=diagnostic.validation_field if diagnostic else None,
            validator_name=diagnostic.validator_name if diagnostic else None,
            validator_version=diagnostic.validator_version if diagnostic else None,
            token_usage=(
                DecisionTokenUsage(
                    input_tokens=model_usage.input_tokens,
                    output_tokens=model_usage.output_tokens,
                    cached_input_tokens=model_usage.cached_input_tokens,
                    reasoning_tokens=model_usage.reasoning_tokens,
                    estimated_spend_cents=model_usage.estimated_spend_cents,
                )
                if model_usage is not None and model_usage.input_tokens > 0
                else None
            ),
            response_schema_version=diagnostic.response_schema_version if diagnostic else None,
            response_fingerprint=diagnostic.response_fingerprint if diagnostic else None,
            classification=analysis.classification.value if analysis is not None else None,
            relationship=relationship.relationship.value if relationship is not None else None,
            relationship_basis=relationship.basis if relationship is not None else None,
            relevance=(
                ranking_input.dimensions.relevance.value
                if ranking_input
                else diagnostic.parsed_dimensions.relevance.value
                if diagnostic is not None and diagnostic.parsed_dimensions is not None
                else None
            ),
            dimensions=dimensions,
            cited_evidence_ids=tuple(
                sorted({_safe_audit_name(item, "UNREVIEWED_EVIDENCE_ID") for item in cited_ids})
            )[:25],
            unknown_fields=(
                tuple(
                    sorted(
                        {
                            _safe_audit_name(item.field, "UNREVIEWED_FIELD")
                            for item in analysis.unknowns
                        }
                    )[:25]
                )
                if analysis is not None
                else ()
            ),
            validator_result=(
                "REJECTED_EVIDENCE_OR_CLAIM"
                if reason == "INVALID_EVIDENCE_OR_CLAIM"
                or diagnostic is not None
                and diagnostic.validation_error_code is not None
                and diagnostic.validation_stage
                in {"EVIDENCE_VALIDATION", "RATIONALE_VALIDATION", "PROPOSAL_VALIDATION"}
                else "PASSED_CLASSIFICATION"
                if analysis is not None
                and (diagnostic is None or diagnostic.validation_error_code is None)
                else "FAILED_CLASSIFICATION"
                if reason == "CANDIDATE_ANALYSIS_ERROR"
                else "NOT_REACHED"
            ),
            normalized_reason=reason,
            final_outcome=reason,
        )
        requested = CandidateOutcomeReceipt(
            operation_key=operation_key,
            run_id=state["run_id"],
            resource_key=_current(state),
            catalog_dataset_id=candidate.identity.catalog_dataset_id,
            catalog_resource_id=candidate.identity.catalog_resource_id,
            evidence_snapshot_id=state["evidence_snapshot_id"],
            outcome=reason,
            reason_code=reason,
            decision_record=decision,
        )
        _deliver_with_receipt_reconciliation(
            operation="candidate_outcome",
            send=lambda: deps.repository.record_candidate_outcome(requested),
            lookup=lambda: deps.repository.get_candidate_outcome(operation_key),
            accepts=lambda item: item == requested,
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
        )
        return {
            "processed_candidate_outcomes": (*state["processed_candidate_outcomes"], reason),
            "processed_count": state["processed_count"] + 1,
        }

    def build_run_summary(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        if state.get("final_status"):
            return clear_candidate_state()
        if state["persisted_recommendation_version_ids"]:
            return {**clear_candidate_state(), "final_status": "SUCCEEDED_WITH_RECOMMENDATIONS"}
        return {**clear_candidate_state(), "final_status": "SUCCEEDED_NO_NEW_CANDIDATES"}

    def finalize_run(state: DatasetDiscoveryState) -> DatasetDiscoveryState:
        requested = RunFinalizationReceipt(
            operation_key=f"finalize:{state['run_id']}",
            run_id=state["run_id"],
            status=state["final_status"] or "FAILED",
            processed_count=state["processed_count"],
            recommendation_count=len(state["persisted_recommendation_version_ids"]),
            budget_usage=state["usage"].model_dump(),
            stop_reason=state.get("stop_reason"),
        )
        receipt = _deliver_with_receipt_reconciliation(
            operation="run_finalize",
            send=lambda: deps.repository.finalize_run(requested),
            lookup=lambda: deps.repository.get_finalization(state["run_id"]),
            accepts=lambda item: item == requested,
            retries=state["limits"].retries_per_operation,
            sleep=deps.sleep,
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
                if state.get("run_id") and (
                    state.get("cancel_requested") or deps.cancellation_requested()
                ):
                    return {"stop_reason": "EXPLICIT_CANCELLATION", "final_status": "CANCELLED"}
                now = deps.clock()
                if state.get("run_id") and now >= datetime.fromisoformat(state["deadline_at"]):
                    return {"stop_reason": "DEADLINE_EXHAUSTED", "final_status": "BUDGET_STOPPED"}
                elapsed = max(
                    0,
                    int((now - datetime.fromisoformat(state["started_at"])).total_seconds()),
                )
                elapsed_increment = max(0, elapsed - state["usage"].elapsed_seconds)
                usage = charge_budget(
                    state["usage"],
                    state["limits"],
                    graph_steps=1,
                    elapsed_seconds=elapsed_increment,
                )
                charged: DatasetDiscoveryState = {**state, "usage": usage}
                result: DatasetDiscoveryState = fn(charged)
                final_usage = result.get("usage", usage)
                result["usage"] = final_usage
                result["remaining_run_budget"] = remaining_budget(final_usage, state["limits"])
                return result
            except BudgetExceeded as error:
                measured_usage = (
                    error.usage if isinstance(error, ReportedUsageExceeded) else state["usage"]
                )
                return {
                    "stop_reason": str(error),
                    "final_status": "BUDGET_STOPPED",
                    "usage": measured_usage,
                    "remaining_run_budget": remaining_budget(measured_usage, state["limits"]),
                }
            except Exception as error:
                cause = (
                    error.cause
                    if isinstance(error, (RetryExhausted, ChargedCallFailure))
                    else error
                )
                code = f"{name}:{type(cause).__name__}"
                bounded_errors = (*state.get("bounded_errors", ()), code)[-10:]
                systemic = isinstance(cause, (PolicyViolation, UnmeteredModelResponse)) or (
                    name == "assess_evidence_sufficiency"
                    and isinstance(cause, (ConnectionError, TimeoutError))
                )
                charged_usage = (
                    error.usage
                    if isinstance(error, (RetryExhausted, ChargedCallFailure))
                    else state["usage"]
                )
                reported_usage = getattr(cause, "usage", None)
                diagnostic: ModelDiagnostic | None = getattr(cause, "diagnostic", None)
                if diagnostic is None and isinstance(reported_usage, ModelUsage):
                    diagnostic = reported_usage.diagnostic
                diagnostic_state: DatasetDiscoveryState = (
                    {
                        "current_model_diagnostic": diagnostic,
                        "current_model_usage": reported_usage
                        if isinstance(reported_usage, ModelUsage)
                        else None,
                    }
                    if diagnostic is not None
                    else {}
                )
                if any(
                    getattr(charged_usage, dimension) > getattr(state["limits"], dimension)
                    for dimension in BudgetUsage.model_fields
                ):
                    return {
                        "stop_reason": "REPORTED_USAGE_EXCEEDED",
                        "final_status": "BUDGET_STOPPED",
                        "bounded_errors": bounded_errors,
                        "usage": charged_usage,
                        "remaining_run_budget": remaining_budget(charged_usage, state["limits"]),
                        **diagnostic_state,
                    }
                if name in candidate_analysis_nodes and not systemic:
                    return {
                        "candidate_outcome_reason": "CANDIDATE_ANALYSIS_ERROR",
                        "bounded_errors": bounded_errors,
                        "usage": charged_usage,
                        "remaining_run_budget": remaining_budget(charged_usage, state["limits"]),
                        **diagnostic_state,
                    }
                return {
                    "stop_reason": code,
                    "final_status": "PARTIAL" if state.get("processed_count", 0) else "FAILED",
                    "bounded_errors": bounded_errors,
                    "usage": charged_usage,
                    "remaining_run_budget": remaining_budget(charged_usage, state["limits"]),
                    **diagnostic_state,
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
                traced_node(
                    name,
                    handler
                    if name in {"initialize_run", "build_run_summary", "finalize_run"}
                    else guard(name, handler),
                ),
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

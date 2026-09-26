"""Versioned observable LangGraph state; no hidden model reasoning is retained."""

from typing import TypedDict

from lyme_gap_atlas_dataset_discovery.domain.analysis import (
    AvailableObservation,
    CandidateAnalysis,
    SearchExpansionProposal,
)
from lyme_gap_atlas_dataset_discovery.domain.models import CandidateSummary, EvidenceRef
from lyme_gap_atlas_dataset_discovery.domain.ranking import PriorityInput, PriorityResult
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult

from .budgets import BudgetLimit, BudgetUsage, RunProfile

STATE_VERSION = "dataset-discovery-state-v1"


class DatasetDiscoveryState(TypedDict, total=False):
    state_version: str
    execution_key: str
    requested_run_id: str
    retry_of_run_id: str | None
    run_id: str
    profile: RunProfile
    trigger_type: str
    started_at: str
    deadline_at: str
    code_sha: str
    spec_version: str
    graph_version: str
    config_fingerprint: str
    search_fingerprint: str
    evidence_snapshot_id: str
    model_provider: str
    model_id: str
    model_fingerprint: str
    price_table_version: str | None
    prompt_versions: dict[str, str]
    tool_versions: dict[str, str]
    eval_version: str
    trace_id: str
    host_session_id: str | None
    limits: BudgetLimit
    usage: BudgetUsage
    remaining_run_budget: dict[str, int]
    candidate_queue: tuple[CandidateSummary, ...]
    current_candidate_id: str | None
    current_candidate_index: int
    current_candidate: CandidateSummary | None
    current_evidence: tuple[EvidenceRef, ...]
    current_observations: tuple[AvailableObservation, ...]
    current_relationship: RelationshipResult | None
    current_analysis: CandidateAnalysis | None
    current_ranking_input: PriorityInput | None
    current_priority: PriorityResult | None
    current_proposals: tuple[SearchExpansionProposal, ...]
    next_page_cursor: str | None
    pages_loaded: int
    processed_candidate_outcomes: tuple[str, ...]
    seen_candidate_ids: tuple[str, ...]
    skip_duplicate: bool
    processed_count: int
    persisted_recommendation_version_ids: tuple[str, ...]
    persistence_operation_key: str | None
    bounded_errors: tuple[str, ...]
    candidate_outcome_reason: str | None
    stop_reason: str | None
    final_status: str | None


def clear_candidate_state() -> DatasetDiscoveryState:
    """Explicitly erase candidate-scoped values before the next selection."""
    return {
        "current_candidate_id": None,
        "current_candidate": None,
        "current_evidence": (),
        "current_observations": (),
        "current_relationship": None,
        "current_analysis": None,
        "current_ranking_input": None,
        "current_priority": None,
        "current_proposals": (),
        "candidate_outcome_reason": None,
        "skip_duplicate": False,
        "persistence_operation_key": None,
    }

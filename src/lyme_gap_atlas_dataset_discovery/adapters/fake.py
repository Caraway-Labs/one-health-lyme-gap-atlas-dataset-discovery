"""Deterministic in-memory adapters for local contract and graph development."""

from dataclasses import dataclass, field

from lyme_gap_atlas_dataset_discovery.domain.analysis import AvailableObservation
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    CandidateOutcomeReceipt,
    CandidatePage,
    CandidateSummary,
    EvidenceRef,
    RecommendationWriteReceipt,
    RunFinalizationReceipt,
    RunReceipt,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import RecommendationWrite


@dataclass
class FakeCandidateReader:
    candidates: tuple[CandidateSummary, ...] = ()
    observations: dict[str, tuple[AvailableObservation, ...]] = field(default_factory=dict)

    def list_batch(self, *, cursor: str | None, limit: int) -> CandidatePage:
        if not 1 <= limit <= 25:
            raise ValueError("candidate limit outside v1 hard maximum")
        offset = int(cursor) if cursor is not None else 0
        if offset < 0 or offset > len(self.candidates):
            raise ValueError("invalid cursor")
        chunk = self.candidates[offset : offset + limit]
        next_offset = offset + len(chunk)
        return CandidatePage(
            candidates=chunk,
            next_cursor=str(next_offset) if next_offset < len(self.candidates) else None,
        )

    def get_summary(self, candidate_id: str) -> CandidateSummary:
        return self._find(candidate_id)

    def get_identity(self, candidate_id: str) -> CandidateIdentity:
        return self._find(candidate_id).identity

    def get_evidence_refs(self, candidate_id: str, *, limit: int) -> tuple[EvidenceRef, ...]:
        if not 1 <= limit <= 25:
            raise ValueError("evidence limit outside v1 hard maximum")
        return self._find(candidate_id).evidence_refs[:limit]

    def get_observations(
        self, candidate_id: str, *, limit: int
    ) -> tuple[AvailableObservation, ...]:
        if not 1 <= limit <= 25:
            raise ValueError("observation limit outside v1 hard maximum")
        self._find(candidate_id)
        result = self.observations.get(candidate_id, ())[:limit]
        declared = {ref.observation_id for ref in self._find(candidate_id).evidence_refs}
        if any(item.reference.observation_id not in declared for item in result):
            raise ValueError("observation not declared by candidate evidence refs")
        return result

    def get_governed_status(self, candidate_id: str) -> str:
        self._find(candidate_id)
        return "UNKNOWN"

    def _find(self, candidate_id: str) -> CandidateSummary:
        for candidate in self.candidates:
            if candidate.identity.resource_key == candidate_id:
                return candidate
        raise KeyError(candidate_id)


@dataclass
class FakeRecommendationRepository:
    runs: dict[str, RunReceipt] = field(default_factory=dict)
    outcomes: dict[str, CandidateOutcomeReceipt] = field(default_factory=dict)
    recommendations: dict[str, RecommendationWriteReceipt] = field(default_factory=dict)
    recommendation_bundles: dict[str, RecommendationWrite] = field(default_factory=dict)
    finalizations: dict[str, RunFinalizationReceipt] = field(default_factory=dict)

    def create_run(
        self, *, operation_key: str, run_id: str, retry_of_run_id: str | None = None
    ) -> RunReceipt:
        existing = self.runs.get(operation_key)
        if existing is not None:
            if existing.retry_of_run_id != retry_of_run_id:
                raise ValueError("operation key reused with conflicting retry lineage")
            return existing
        if any(receipt.run_id == run_id for receipt in self.runs.values()):
            raise ValueError("run ID already exists under another operation key")
        if retry_of_run_id is not None:
            prior = self.finalizations.get(retry_of_run_id)
            if prior is None or prior.status not in {
                "FAILED",
                "PARTIAL",
                "BUDGET_STOPPED",
                "CANCELLED",
            }:
                raise ValueError("explicit retry requires a retry-eligible terminal prior run")
        receipt = RunReceipt(
            run_id=run_id, operation_key=operation_key, retry_of_run_id=retry_of_run_id
        )
        self.runs[operation_key] = receipt
        return receipt

    def get_run(self, operation_key: str) -> RunReceipt | None:
        return self.runs.get(operation_key)

    def record_candidate_outcome(self, receipt: CandidateOutcomeReceipt) -> CandidateOutcomeReceipt:
        self._require_run(receipt.run_id)
        previous = self.outcomes.get(receipt.operation_key)
        if previous is not None:
            if previous != receipt:
                raise ValueError("candidate outcome key reused with conflicting payload")
            return previous
        self._require_open_run(receipt.run_id)
        if any(
            item.run_id == receipt.run_id and item.resource_key == receipt.resource_key
            for item in self.outcomes.values()
        ):
            raise ValueError("candidate already has an outcome in this run")
        self.outcomes[receipt.operation_key] = receipt
        return receipt

    def get_candidate_outcome(self, operation_key: str) -> CandidateOutcomeReceipt | None:
        return self.outcomes.get(operation_key)

    def save_recommendation(self, request: RecommendationWrite) -> RecommendationWriteReceipt:
        request = RecommendationWrite.model_validate(request.model_dump())
        self._require_run(request.identity.run_id)
        if request.analysis.identity.resource_key != request.identity.resource_key:
            raise ValueError("recommendation bundle candidate identity mismatch")
        if request.priority.score is None:
            raise ValueError("abstaining candidate cannot be persisted as a recommendation")
        previous = self.recommendations.get(request.operation_key)
        if previous is not None:
            if self.recommendation_bundles[request.operation_key] != request:
                raise ValueError("recommendation key reused with conflicting payload")
            return previous
        self._require_open_run(request.identity.run_id)
        if any(
            item.identity.recommendation_version_id == request.identity.recommendation_version_id
            or (
                item.identity.run_id == request.identity.run_id
                and item.identity.resource_key == request.identity.resource_key
            )
            for item in self.recommendations.values()
        ):
            raise ValueError("recommendation version or same-run candidate already exists")
        receipt = RecommendationWriteReceipt(
            operation_key=request.operation_key,
            identity=request.identity,
            assertion_sha256=request.assertion_sha256,
            evidence_observation_ids=request.evidence_observation_ids,
            proposal_ids=request.proposal_ids,
        )
        self.recommendation_bundles[request.operation_key] = request
        self.recommendations[receipt.operation_key] = receipt
        return receipt

    def get_recommendation(self, operation_key: str) -> RecommendationWriteReceipt | None:
        return self.recommendations.get(operation_key)

    def finalize_run(self, receipt: RunFinalizationReceipt) -> RunFinalizationReceipt:
        self._require_run(receipt.run_id)
        previous = self.finalizations.get(receipt.run_id)
        if previous is not None:
            if previous != receipt:
                raise ValueError("run already finalized with a different receipt")
            return previous
        outcomes = sum(item.run_id == receipt.run_id for item in self.outcomes.values())
        recommendations = sum(
            item.identity.run_id == receipt.run_id for item in self.recommendations.values()
        )
        if receipt.processed_count != outcomes + recommendations:
            raise ValueError("processed count differs from durable candidate receipts")
        if receipt.recommendation_count != recommendations:
            raise ValueError("recommendation count differs from durable versions")
        self.finalizations[receipt.run_id] = receipt
        return receipt

    def get_finalization(self, run_id: str) -> RunFinalizationReceipt | None:
        return self.finalizations.get(run_id)

    def _require_run(self, run_id: str) -> None:
        if not any(item.run_id == run_id for item in self.runs.values()):
            raise ValueError("run has not been created")

    def _require_open_run(self, run_id: str) -> None:
        if run_id in self.finalizations:
            raise ValueError("run is already terminal")

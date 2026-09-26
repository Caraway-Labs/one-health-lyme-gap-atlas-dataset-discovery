"""Deterministic in-memory adapters for local contract and graph development."""

from dataclasses import dataclass, field

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


@dataclass
class FakeCandidateReader:
    candidates: tuple[CandidateSummary, ...] = ()

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

    def save_recommendation(
        self, receipt: RecommendationWriteReceipt
    ) -> RecommendationWriteReceipt:
        self._require_run(receipt.identity.run_id)
        previous = self.recommendations.get(receipt.operation_key)
        if previous is not None:
            if previous != receipt:
                raise ValueError("recommendation key reused with conflicting payload")
            return previous
        self._require_open_run(receipt.identity.run_id)
        if any(
            item.identity.recommendation_version_id == receipt.identity.recommendation_version_id
            or (
                item.identity.run_id == receipt.identity.run_id
                and item.identity.resource_key == receipt.identity.resource_key
            )
            for item in self.recommendations.values()
        ):
            raise ValueError("recommendation version or same-run candidate already exists")
        self.recommendations[receipt.operation_key] = receipt
        return receipt

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

    def _require_run(self, run_id: str) -> None:
        if not any(item.run_id == run_id for item in self.runs.values()):
            raise ValueError("run has not been created")

    def _require_open_run(self, run_id: str) -> None:
        if run_id in self.finalizations:
            raise ValueError("run is already terminal")

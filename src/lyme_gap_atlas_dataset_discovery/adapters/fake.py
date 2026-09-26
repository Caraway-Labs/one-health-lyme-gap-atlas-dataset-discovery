"""Deterministic in-memory adapters for local contract and graph development."""

from dataclasses import dataclass, field

from lyme_gap_atlas_dataset_discovery.domain.analysis import AvailableObservation
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    CandidatePage,
    CandidateSummary,
    EvidenceRef,
    RunReceipt,
)


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
        receipt = RunReceipt(
            run_id=run_id, operation_key=operation_key, retry_of_run_id=retry_of_run_id
        )
        self.runs[operation_key] = receipt
        return receipt

    def get_run(self, operation_key: str) -> RunReceipt | None:
        return self.runs.get(operation_key)

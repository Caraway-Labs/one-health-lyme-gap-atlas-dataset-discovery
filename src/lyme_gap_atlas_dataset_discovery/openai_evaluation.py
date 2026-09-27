"""Explicit, credential-file DEV semantic evaluation over the versioned corpus.

This command is never part of CI. It prints IDs and metrics, never candidate text,
prompts, model output, or credentials.
"""

import argparse
import json
from decimal import Decimal
from pathlib import Path
from statistics import mean, median

from lyme_gap_atlas_dataset_discovery.adapters.model_planner import ReviewedModelPrice
from lyme_gap_atlas_dataset_discovery.adapters.openai_responses import OpenAIResponsesPlanner
from lyme_gap_atlas_dataset_discovery.domain.analysis import AvailableObservation, validate_analysis
from lyme_gap_atlas_dataset_discovery.domain.models import CandidateSummary
from lyme_gap_atlas_dataset_discovery.domain.ranking import PriorityInput, rank_candidate
from lyme_gap_atlas_dataset_discovery.graph.planner import (
    InvalidModelResponse,
    ModelAllowance,
    UnmeteredModelResponse,
    validate_dimension_evidence,
)
from lyme_gap_atlas_dataset_discovery.model_policy import LunaPriceTable, ModelPolicy


def _metric(record: dict[str, object], name: str) -> int:
    value = record.get(name)
    return value if type(value) is int else 0


def evaluate(corpus: Path, key_file: Path) -> dict[str, object]:
    key = key_file.read_text(encoding="utf-8").strip()
    if not key or len(key) < 20:
        raise ValueError("local model credential is unavailable")
    table = LunaPriceTable.standard_v1()
    policy = ModelPolicy.luna_low_v1()
    planner = OpenAIResponsesPlanner(
        endpoint="https://api.openai.com/v1", model_id="gpt-6-luna", api_key=key,
        price=ReviewedModelPrice(table.version, "gpt-6-luna", Decimal("0.10"), Decimal("0.50")),
    )
    document = json.loads(corpus.read_text(encoding="utf-8"))
    results = []
    for item in document["cases"]:
        case_id = item["case_id"]
        observations = tuple(
            AvailableObservation.model_validate(value) for value in item["observations"]
        )
        identity = item["analysis"]["identity"]
        fields = observations[0].field_values if observations else {}
        candidate = CandidateSummary(
            identity=identity, title=fields.get("title"), publisher=fields.get("publisher")
        )
        record: dict[str, object] = {"case_id": case_id}
        try:
            answer = planner.classify(
                candidate, observations,
                allowance=ModelAllowance(
                    max_input_tokens=20000, max_output_tokens=1024,
                    max_estimated_spend_cents=10
                ),
            )
            analysis, dimensions = answer.value
            record.update(answer.usage.model_dump())
            try:
                if analysis.identity != candidate.identity:
                    raise ValueError("model changed canonical candidate identity")
                validate_analysis(analysis, available_evidence=observations)
                validate_dimension_evidence(analysis, dimensions)
            except ValueError:
                record["hard_gate"] = "REJECTED_UNSUPPORTED_ASSERTION"
            else:
                record["hard_gate"] = "PASSED"
                record["classification"] = analysis.classification.value
                if item.get("priority_input"):
                    expected = PriorityInput.model_validate(item["priority_input"])
                    observed_ids = frozenset(
                        fact.evidence.observation_id for fact in analysis.observed_facts
                    )
                    if observed_ids:
                        rank_input = expected.model_copy(
                            update={
                                "observed_evidence_ids": observed_ids,
                                "dimensions": dimensions,
                            }
                        )
                        try:
                            ranked = rank_candidate(rank_input)
                            record["bucket"] = ranked.bucket.value
                            record["bucket_matches_corpus"] = (
                                ranked.bucket.value == item.get("expected_bucket")
                            )
                        except ValueError:
                            record["hard_gate"] = "REJECTED_RANKING_EVIDENCE"
        except (InvalidModelResponse, UnmeteredModelResponse) as exc:
            if exc.usage is not None:
                record.update(exc.usage.model_dump())
            record["hard_gate"] = "MODEL_OR_SCHEMA_FAILURE"
            record["error_type"] = type(exc).__name__
        except Exception as exc:
            record["hard_gate"] = "MODEL_OR_SCHEMA_FAILURE"
            record["error_type"] = type(exc).__name__
        results.append(record)
    latencies = [_metric(item, "latency_ms") for item in results if "latency_ms" in item]
    return {
        "corpus_version": document["corpus_version"],
        "model": "gpt-6-luna",
        "reasoning_effort": "low",
        "model_policy_version": policy.document["model_policy_version"],
        "model_fingerprint": policy.fingerprint,
        "price_version": table.version,
        "price_fingerprint": table.fingerprint,
        "case_count": len(results),
        "hard_gate_counts": {
            status: sum(item["hard_gate"] == status for item in results)
            for status in sorted({str(item["hard_gate"]) for item in results})
        },
        "input_tokens": sum(_metric(item, "input_tokens") for item in results),
        "output_tokens": sum(_metric(item, "output_tokens") for item in results),
        "cached_input_tokens": sum(_metric(item, "cached_input_tokens") for item in results),
        "reasoning_tokens": sum(_metric(item, "reasoning_tokens") for item in results),
        "conservative_cost_cents": sum(
            _metric(item, "estimated_spend_cents") for item in results
        ),
        "mean_latency_ms": round(mean(latencies)) if latencies else None,
        "median_latency_ms": round(median(latencies)) if latencies else None,
        "cases": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.corpus, args.key_file), indent=2, default=str))


if __name__ == "__main__":
    main()

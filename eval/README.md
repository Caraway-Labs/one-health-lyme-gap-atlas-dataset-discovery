# Dataset Discovery evaluation corpus

`corpora/v1/cases.json` is a versioned set of reviewed, synthetic domain examples. Run:

```powershell
uv run python -m lyme_gap_atlas_dataset_discovery.evaluation eval/corpora/v1/cases.json
```

The command emits a JSON report and exits nonzero when any case fails. It checks retained-evidence fidelity before ranking, binds ranking citations to the analysis's validated observed facts, checks each scored dimension against relevant metadata fields, and compares deterministic bucket, score, abstention reason, and sort key to independently stated expectations. The v1 domain corpus covers high/medium/low priority, missing-evidence and unknown-relationship penalties, a mirror cap, duplicate abstention, fabricated facts, contradictory unknowns, absent citations, unrelated dimension fields, and catalog text containing a prompt injection. A rejected invalid case passes when its rejection is correctly observed. Unknown rights do not prevent a recommendation for investigation. The catalog-text case proves only the local evidence and ranking boundary; live model prompt-injection resistance still requires separate evaluation.

The separate `corpora/v1/handoff.json` corpus exercises the human review and
governed handoff fakes with exact event IDs and one logical receipt per replay:

```powershell
uv run python -m lyme_gap_atlas_dataset_discovery.handoff_evaluation eval/corpora/v1/handoff.json
```

Its cases cover unknown and reviewed restricted rights, controlled access,
reviewed hard prohibition, mirror/alternate distribution, already governed
sources, stale or rejected review, evidence loss, and a service-principal
impersonation attempt. These are credential-free domain gates. Data-owned V110
transaction, policy stewardship, grants and live DEV session identity still
need independent proof before hosted acceptance.

This is the first local domain slice for Story #10. It is not a semantic model evaluation, a hosted trace, a human-adjudicated quality baseline, or governed handoff proof. Expand v1 with graph trajectory, policy injection, outages, replay, handoff, measured cost/latency, and human labels before promotion. Shared Agent Evaluation Lab integration can consume this corpus and report contract when its runner stabilizes. Keep hard authority, evidence, schema, and security gates separate from averaged quality metrics.

Graph construction enables the shared Atlas OTLP exporter when `OTEL_EXPORTER_OTLP_ENDPOINT` is configured. An approved Arize/Phoenix OTLP endpoint can be used there; exporter authorization headers belong in managed secrets. Each graph node emits an allowlisted span containing run/config/model version IDs, status, and budget counters. Candidate titles, metadata values, rationale text, full prompts, hidden reasoning, and exception messages are excluded. Exporter availability alone is not evaluation evidence: hosted acceptance still needs inspected traces for an exact deployed and evaluated SHA.

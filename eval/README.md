# Dataset Discovery evaluation corpus

`corpora/v1/cases.json` is a versioned set of reviewed, synthetic domain examples. Run:

```powershell
uv run python -m lyme_gap_atlas_dataset_discovery.evaluation eval/corpora/v1/cases.json
```

The command emits a JSON report and exits nonzero when any case fails. It checks retained-evidence fidelity before ranking, binds ranking citations to the analysis's validated observed facts, checks each scored dimension against relevant metadata fields, and compares deterministic bucket, score, abstention reason, and sort key to independently stated expectations. The v1 domain corpus covers high/medium/low priority, missing-evidence and unknown-relationship penalties, a mirror cap, duplicate abstention, fabricated facts, contradictory unknowns, absent citations, unrelated dimension fields, and catalog text containing a prompt injection. A rejected invalid case passes when its rejection is correctly observed. Unknown rights do not prevent a recommendation for investigation. The catalog-text case proves only the local evidence and ranking boundary; live model prompt-injection resistance still requires separate evaluation.

`corpora/v1/relationships.json` pins deterministic relationship precedence,
including reviewed revision/supersession links and retained-content mirrors:

```powershell
uv run python -m lyme_gap_atlas_dataset_discovery.relationship_evaluation eval/corpora/v1/relationships.json
```

The invalid-link cases require retained evidence IDs for revision,
supersession, and mirror claims. They verify the domain rule, not the existence
of a live data-owned source-link feed. V111 currently exposes only exact
catalog identity and same-dataset alternate distributions; it does not infer
version or content links from metadata.

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

The `corpora/v1/graph_trajectories.json` corpus pins the exact sequential
LangGraph node path, terminal status and stop reason, budgeted model/tool
calls, candidate outcomes, and durable run/recommendation receipts. Its 16
cases cover no-candidate, valid, insufficient-evidence, already-governed,
invalid/unmetered model, exhausted batch/evidence/model outages, transient
read/model retries, candidate budget, cancellation, and lost commit
acknowledgments for all four business write families. It also checks an exact
identity link before the model, an alternate distribution's LOW priority cap,
and an ambiguous link that abstains without model guessing. Empty, successful, and
acknowledgment-loss runs are replayed with the same logical operation keys to
verify one durable result:

```powershell
uv run python -m lyme_gap_atlas_dataset_discovery.graph_evaluation eval/corpora/v1/graph_trajectories.json
```

Terminal paths clear candidate-local graph state. The trajectory gate uses a
fixed clock and fake adapters; it does not prove Snowflake concurrency or
provider metering in DEV.

These are local fixture gates for Story #10. They are not a semantic model evaluation, a hosted trace, a human-adjudicated quality baseline, or governed handoff proof. Expand v1 with hosted policy injection, measured cost/latency, and human labels before promotion. Shared Agent Evaluation Lab integration can consume these corpora and report contracts when its runner stabilizes. Keep hard authority, evidence, schema, and security gates separate from averaged quality metrics.

Graph construction enables the shared Atlas OTLP exporter when `OTEL_EXPORTER_OTLP_ENDPOINT` is configured. An approved Arize/Phoenix OTLP endpoint can be used there; exporter authorization headers belong in managed secrets. Each graph node emits an allowlisted span containing run/config/model version IDs, status, and budget counters. Candidate titles, metadata values, rationale text, full prompts, hidden reasoning, and exception messages are excluded. Exporter availability alone is not evaluation evidence: hosted acceptance still needs inspected traces for an exact deployed and evaluated SHA.

Bounded tool and model attempts and persistence send/receipt-lookup attempts
emit separate child spans with fixed operation names, attempt numbers and
outcome/error **type** only. Automatic OpenTelemetry exception recording is
disabled for these and node spans so catalog text or connector messages cannot
enter exported traces. Hosted acceptance must inspect actual traces and
correlate them with run/session IDs; fixture spans alone do not prove Phoenix
delivery.

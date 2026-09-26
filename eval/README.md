# Dataset Discovery evaluation corpus

`corpora/v1/cases.json` is a versioned set of reviewed, synthetic domain examples. Run:

```powershell
uv run python -m lyme_gap_atlas_dataset_discovery.evaluation eval/corpora/v1/cases.json
```

The command emits a JSON report and exits nonzero when any case fails. It checks retained-evidence fidelity before ranking and compares deterministic priority outputs to independently stated expectations. A fabricated observed fact is a hard failure in the application even though its corpus case passes when rejection is correctly observed. Unknown rights do not prevent a recommendation for investigation. Exact duplicates abstain.

This is the first local domain slice for Story #10. It is not a semantic model evaluation, a hosted trace, a human-adjudicated quality baseline, or governed handoff proof. Expand v1 with graph trajectory, policy injection, outages, replay, handoff, measured cost/latency, and human labels before promotion. Shared Agent Evaluation Lab integration can consume this corpus and report contract when its runner stabilizes. Keep hard authority, evidence, schema, and security gates separate from averaged quality metrics.

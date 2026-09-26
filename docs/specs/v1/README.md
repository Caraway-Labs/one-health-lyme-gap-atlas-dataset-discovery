# Dataset Discovery v1 implementation contract

**Status:** Reviewed implementation baseline. **Owner:** Dataset Discovery application; data-platform objects and grants remain owned by `one-health-lyme-gap-atlas-data`.

This contract implements accepted [ADR 0001](../../adr/0001-dataset-discovery-persistence-and-service-boundary.md) and Dataset Discovery stories #1, #6, #7–#12. The graph is a recommendation service over bounded governed catalog metadata. The inference graph has no human-review, approval, acquisition, ingestion, publication, arbitrary SQL/shell/URL, or active search-configuration tool. Catalog text is untrusted data. Snowflake is the v1 record; no second migration ledger or PostgreSQL store is introduced.

## Workflow and state

The foundation graph is deliberately a smoke entrypoint. Story #12 replaces it with a typed `DatasetDiscoveryState` and this sequential loop:

```text
initialize_run -> create_run -> load_discovery_context -> load_candidate_batch
  -> select_next_candidate
       candidate -> assess_evidence_sufficiency
         insufficient/blocked -> record_candidate_outcome -> select_next_candidate
         sufficient -> analyze_candidate_relationship -> classify_and_score_candidate
           -> generate_recommendation_rationale -> propose_search_expansions
           -> validate_candidate_result
                invalid/abstain -> record_candidate_outcome -> select_next_candidate
                valid -> persist_recommendation -> select_next_candidate
       queue empty + page allowed -> load_candidate_batch
       queue empty + no page -> build_run_summary -> finalize_run -> END
```

Run state contains run ID, mode/trigger, timestamps, code/spec/graph/config/search/model/prompt/tool/eval fingerprints, trace/session IDs, candidate queue/current ID/index, next cursor, pages loaded, current evidence, processed outcomes/count, remaining budget, bounded error records, stop reason and final status. Candidate-scoped evidence and draft fields are cleared when advancing. A single bad candidate normally records an outcome and continues. Invalid configuration, unavailable discovery context or persistence, cancellation, deadline/budget stop, or systemic security failure terminates the run.

`RUNS` is created before catalog reads. Candidate outcomes are committed individually. Successful runs finalize counters and one of `SUCCEEDED_WITH_RECOMMENDATIONS`, `SUCCEEDED_NO_NEW_CANDIDATES`, `PARTIAL`, `BUDGET_STOPPED`, `FAILED`, or `CANCELLED`. Progress heartbeat is optional; intermediate graph mutations need not be durable. Interrupted finalization is reconciled from committed outcomes and never silently marked successful.

## Evidence and identity

`ObservedFact` cites a stable catalog observation/evidence ID and immutable metadata hash when available. `Inference` cites observed fact IDs and records uncertainty. `Unknown` records a missing/blocked reason. Unknowns never become asserted facts. Store references rather than restricted raw payloads or hidden model reasoning.

`recommendation_id` is stable for the canonical candidate/resource. Every new run that generates a recommendation creates a new immutable `recommendation_version_id`, even for equivalent content; `equivalent_to_version_id` may link that equivalence. A same-run replay returns the prior version receipt. Human review cites the exact version. An explicit retry of a terminal run creates a new run ID with `retry_of_run_id`; an ambiguous replay of the same execution returns its original run ID.

## Classification and ranking

Categories: `RELEVANT`, `POSSIBLY_RELEVANT`, `IRRELEVANT`, `INSUFFICIENT_EVIDENCE`, `BLOCKED`. Relationships: exact duplicate, mirror/alternate distribution, revision, supersession, complementary, already known, distinct, unknown. Exact canonical IDs/URLs and retained version evidence outrank semantic guesses. Ambiguity remains unknown.

Eligibility requires canonical identity, one stable evidence ref, and evidence sufficient to judge Atlas relevance. Irrelevant, exact duplicate, and already-governed cases are recorded but not ranked. Each validated dimension is 0, 1, or 2, with unknown contributing zero and remaining explicitly unknown: relevance ×5; geography ×3; variables ×3; time ×2; provenance/documentation ×2; freshness ×1; rights clarity ×1; complementarity ×2. Base score ranges 0–38. Relationship adjustment: complement +2, revision/supersession +1, distinct 0, unknown −2, mirror/alternate distribution −4; clamp 0–40. Priority: high ≥28, medium 18–27, low 1–17; abstain for ineligible/zero-valid-evidence. Sort by score, relevance, geography, variables, time descending, then canonical key/version ascending. The formula is priority **for investigation**, not approval, scientific validity, rights clearance, or ingestion readiness. A model may propose semantic dimensions only with evidence; deterministic code validates and scores.

## Rights and human boundary

Human review occurs outside the graph using an individual Snowflake-authenticated session. The CLI never accepts a self-asserted reviewer name. A caller-rights procedure derives `CURRENT_USER()`, verifies the reviewer role/allowlist, and stores principal, decision, rationale, version and time in append-only `REVIEW_EVENTS`. Runtime identity cannot invoke this procedure.

Accepted means `ACCEPTED_FOR_INVESTIGATION`. `RIGHTS_UNKNOWN` and `RIGHTS_REVIEW_REQUIRED` can enter investigation; `KNOWN_RESTRICTED` goes to restricted investigation without automated acquisition; only a reviewed `KNOWN_PROHIBITED` policy blocks the appropriate onboarding request. Existing `CONTROLLED_ACCESS`/`NO_AUTOMATED_ACQUISITION` is not automatically a prohibition. Data #450 owns narrow handoff and existing documentation/rights/assessment/approval/ingestion remain authoritative.

## Persistence and authority

Data #449 owns tables/views/procedures, migration and grants. Standard Snowflake table primary-key declarations are not sufficient for concurrent uniqueness. Each mutating business procedure uses an explicit DML transaction and a tested serialized control row; after acquiring it, the procedure rereads operation key/current state, writes related records, then commits or rolls back. Operation keys reconcile client timeouts after commit. Atomic operations: create run; record candidate outcome; commit immutable recommendation version plus evidence/proposals; finalize run; append review event. Data #450 adds idempotent handoff. Genuinely concurrent DEV sessions must prove this protocol before hosted acceptance.

The proposed `OH_LYME_{ENV}_DATASET_DISCOVERY_RUNTIME` role selects only bounded views and calls only run/recommendation procedures. Individually assigned `OH_LYME_{ENV}_DATASET_DISCOVERY_REVIEWER` selects review views and calls only review/handoff procedures. Neither inherits ingestion runtime, OWNER, migration deployer, source approval, or publication rights. A new reviewed data-platform ADR must supersede ADR 0030's exhaustive inventory before role grants. V103/#454 recovery and protected migration health precede applying #449.

## Budgets, evaluation, and deployment

Profiles: `FIXTURE`, `DEV_MANUAL`, `HOSTED_MANUAL`, `SHADOW`, `SCHEDULED`. Initial manual/shadow defaults and hard maxima are recorded in the peer-reviewed plan; the implementation validates every field and checks limits before each call/edge. `SCHEDULED` defaults disabled and fails closed without approved cadence, per-run/monthly spend, safety gates, and a reviewed model price table.

Maintain a versioned local corpus for relevance, relationships, stale/missing evidence, rights, misleading metadata, injection, outages, retries, concurrency, and handoff. Zero-tolerance gates: unauthorized operations, unsupported observed facts, schema-invalid persisted recommendations, forbidden tool path, duplicate logical handoff. Shared Agent Evaluation Lab integration is optional until its contracts stabilize. OTLP and Arize/Phoenix telemetry uses redacted IDs/versions and never stores restricted bytes, secrets, full prompts, or hidden reasoning.

DigitalOcean Harness Runtime consumes root `langgraph.json`, a secret-free environment spec, managed credentials, and exact evaluated `FRAMEWORK_REPO_SHA`. #11 must record CLI version, confirm `doctl harness-runtime`, intended account, LangGraph support, private clone, spec, SHA, model and Snowflake connectivity before launch. Rollout is local → DEV → hosted manual → shadow → separate human handoff proof. Recurring schedule requires a later explicit owner decision.

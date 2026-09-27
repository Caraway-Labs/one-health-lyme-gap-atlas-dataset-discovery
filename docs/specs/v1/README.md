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

The create-run port sends typed, immutable run metadata matching the data-owned `RUNS` record: profile/trigger, code/spec/graph/config/search versions, evidence snapshot, and optional model/evaluation identifiers. The request fingerprint covers these identity fields while excluding transport trace and hosted session IDs, so a delivery retry with the same execution key can reconcile to its original run even after a new tracing session starts. Snowflake assigns creation time at first commit; a new explicit retry uses a new execution key and `retry_of_run_id`.

## Evidence and identity

`ObservedFact` cites a stable catalog observation/evidence ID and immutable metadata hash when available. `Inference` cites observed fact IDs and records uncertainty. `Unknown` records a missing/blocked reason. Unknowns never become asserted facts. Store references rather than restricted raw payloads or hidden model reasoning.

`recommendation_id` is stable for the canonical candidate/resource. Every new run that generates a recommendation creates a new immutable `recommendation_version_id`, even for equivalent content; `equivalent_to_version_id` may link that equivalence. A same-run replay returns the prior version receipt. Human review cites the exact version. An explicit retry of a terminal run creates a new run ID with `retry_of_run_id`; an ambiguous replay of the same execution returns its original run ID.

The atomic recommendation request includes its pinned discovery snapshot and an `assertion_sha256` over canonical validated analysis, ranking input/result, and relationship. The hash is version-specific because the ranking input contains the immutable version ID; equality across separate runs is not inferred from it. The runtime derives `RIGHTS_UNKNOWN` when no rights/access metadata is observed and `RIGHTS_REVIEW_REQUIRED` when such metadata exists. Neither state is rights clearance or a hard prohibition; reviewed restricted/prohibited findings belong to governed investigation and review evidence.

## Classification and ranking

Categories: `RELEVANT`, `POSSIBLY_RELEVANT`, `IRRELEVANT`, `INSUFFICIENT_EVIDENCE`, `BLOCKED`. Relationships: exact duplicate, mirror/alternate distribution, revision, supersession, complementary, already known, distinct, unknown. Exact canonical IDs/URLs and retained version evidence outrank semantic guesses. Ambiguity remains unknown.

Eligibility requires canonical identity, one stable evidence ref, and evidence sufficient to judge Atlas relevance. Irrelevant, exact duplicate, and already-governed cases are recorded but not ranked. Each validated dimension is 0, 1, or 2, with unknown contributing zero while remaining explicitly unknown: relevance ×5; geography ×3; variables ×4; time ×2; provenance/documentation ×3; freshness ×1; rights clarity ×1; complementarity ×2. Base score ranges 0–42. Subtract 2 for each unknown dimension and a further 2 for an unknown relationship, flooring at zero. A mirror or alternate distribution is capped at LOW unless its separate documented benefit supports a reviewed exception. Priority: HIGH ≥30, MEDIUM 18–29, LOW 0–17; ABSTAIN for ineligible candidates. Sort eligible recommendations by bucket, score descending, missing count ascending, then canonical key/version ascending. A new ranking-policy version is required to change weights, thresholds, or exception rules. The formula is priority **for investigation**, not approval, scientific validity, rights clearance, or ingestion readiness. A model may propose semantic dimensions only with evidence; deterministic code validates and scores.

The sequential graph checks the bounded governed-status view before loading
candidate observations or calling the model. An active governed version for the
same canonical resource produces an `ALREADY_KNOWN` candidate outcome. An
unrecognized status fails closed. The data-owned V111 identity-link view then
supports exact canonical key/URL duplicate detection and same-catalog-dataset
alternate distribution, bounded to two matches for the pinned snapshot. Two
matches produce `AMBIGUOUS_RELATIONSHIP`; neither the model nor the application
chooses a convenient target. A single alternate distribution bypasses model
relationship assertion and remains capped at LOW priority. Mirror, revision,
and supersession still lack independently retained link signals, so semantic
inference cannot invent those exact relationships. V111 and its runtime grant
remain draft pending ADR 0041 owner/security approval and protected migration.

The read-only candidate port also has one-result methods for prior governed
assessment status and exact catalog-observation artifact metadata through the
draft data-owned V112 views. Assessment status is context only: it cannot be
mapped to recommendation priority or source approval. Artifact metadata omits
object URI and bytes and cannot be used to fetch a private artifact. These
methods are available for bounded operator/evaluation context; the v1 graph
does not add model calls or authority based on them. V112 and SELECT grants
remain behind the same ADR 0041 and protected-migration gate.

## Rights and human boundary

Human review occurs outside the graph using an individual Snowflake-authenticated session. The CLI never accepts a self-asserted reviewer name. A caller-rights procedure would require direct reviewer table DML. Subject to owner/security approval in data ADR 0041, use an owner-rights procedure owned by a dedicated non-login write-owner role with narrowly granted `READ SESSION` on account. It derives the caller through `SYS_CONTEXT('SNOWFLAKE$SESSION', 'PRINCIPAL_NAME')` and `PRINCIPAL_TYPE`, verifies human reviewer role/allowlist, and stores the exact principal, decision, rationale, version and time in append-only `REVIEW_EVENTS`. The runtime identity cannot invoke it. If `READ SESSION` is not approved or the procedure cannot prove caller identity in DEV, review writes remain disabled pending a different reviewed boundary.

Accepted means `ACCEPTED_FOR_INVESTIGATION`. `RIGHTS_UNKNOWN` and `RIGHTS_REVIEW_REQUIRED` can enter investigation; `KNOWN_RESTRICTED` goes to restricted investigation without automated acquisition; only a reviewed `KNOWN_PROHIBITED` policy blocks the appropriate onboarding request. Existing `CONTROLLED_ACCESS`/`NO_AUTOMATED_ACQUISITION` is not automatically a prohibition. Data #450 owns narrow handoff and existing documentation/rights/assessment/approval/ingestion remain authoritative.

## Persistence and authority

Data #449 owns tables/views/procedures, migration and grants. Standard Snowflake table primary-key declarations are not sufficient for concurrent uniqueness. Each mutating business procedure uses an explicit DML transaction and a tested serialized control row; after acquiring it, the procedure rereads operation key/current state, writes related records, then commits or rolls back. Operation keys reconcile client timeouts after commit. Atomic operations: create run; record candidate outcome; commit immutable recommendation version plus evidence/proposals; finalize run; append review event. Data #450 adds idempotent handoff. Genuinely concurrent DEV sessions must prove this protocol before hosted acceptance.

The proposed `OH_LYME_{ENV}_DATASET_DISCOVERY_RUNTIME` role selects only bounded views and calls only run/recommendation procedures. Individually assigned `OH_LYME_{ENV}_DATASET_DISCOVERY_REVIEWER` selects review views and calls only review/handoff procedures. The dedicated non-login `OH_LYME_{ENV}_DATASET_DISCOVERY_WRITE_OWNER` owns only Dataset Discovery procedures/dependencies and the narrowly approved session-read privilege. Runtime and reviewer never inherit that owner. None inherits ingestion runtime, OWNER, migration deployer, source approval, or publication rights. A new reviewed data-platform ADR must supersede ADR 0030's exhaustive inventory before role grants. V103/#454 recovery and protected migration health precede applying #449.

## Budgets, evaluation, and deployment

Profiles: `FIXTURE`, `DEV_MANUAL`, `HOSTED_MANUAL`, `SHADOW`, `SCHEDULED`. Initial manual/shadow defaults and hard maxima are recorded in the peer-reviewed plan; the implementation validates every field and checks limits before each call/edge. `SCHEDULED` defaults disabled and fails closed without approved cadence, per-run/monthly spend, safety gates, and a reviewed model price table.

Maintain a versioned local corpus for relevance, relationships, stale/missing evidence, rights, misleading metadata, injection, outages, retries, concurrency, and handoff. Zero-tolerance gates: unauthorized operations, unsupported observed facts, schema-invalid persisted recommendations, forbidden tool path, duplicate logical handoff. Shared Agent Evaluation Lab integration is optional until its contracts stabilize. OTLP telemetry to Arize AX SaaS uses redacted IDs/versions and never stores restricted bytes, secrets, full prompts, or hidden reasoning.

DigitalOcean Harness Runtime consumes root `langgraph.json`, a secret-free environment spec, managed credentials, and exact evaluated `FRAMEWORK_REPO_SHA`. #11 must record CLI version, confirm `doctl harness-runtime`, intended account, LangGraph support, private clone, spec, SHA, model and Snowflake connectivity before launch. Rollout is local → DEV → hosted manual → shadow → separate human handoff proof. Recurring schedule requires a later explicit owner decision.

The hosted graph dependency assembly must pin its deployed code SHA, catalog
discovery snapshot ID, and reviewed price-table version. `initialize_run`
rejects mismatched input before creating `RUNS`; a caller-supplied value cannot
rewrite deployment identity or make the context reader and candidate reader
use different snapshots. Fixture dependencies may omit these pins, while a
hosted bootstrap must set all three from reviewed configuration.

The hosted entrypoint exports the full sequential graph and pins the
`HOSTED_MANUAL` profile, model ID, provider, exact commit SHA, snapshot, and
price-table version. The standalone foundation smoke graph remains available
for credential-free development but is not the hosted manifest target. The
first hosted composition is DEV-only. It opens a short PAT-backed Snowflake
connection for each bounded read/write and checks effective user, role,
database, and warehouse before any business SQL. Review events and handoffs
remain outside this unattended runtime.

The semantic planner adapter is a separate bounded port. It accepts only the
reader's allowlisted observations and canonical candidate/analysis values,
places catalog text in the user data message under fixed versioned system
instructions, and requests a strict Pydantic-derived JSON schema for each of
the four semantic steps. The initial candidate policy is the packaged,
non-secret `config/openai-gpt-6-luna-low-v1.json`: OpenAI `gpt-6-luna`,
Responses API, low reasoning, structured output, no hosted tools, and no
provider-side response storage. Its fingerprint includes the provider, model,
API, reasoning, capabilities, prompt version, processing mode, output cap, and
storage setting; credentials and environment-specific secret names are excluded.
The wrapper then checks citations and observed values against retained evidence;
deterministic ranking remains outside the model. A hosted bootstrap must supply
the approved environment-specific managed credential and exact policy/price
fingerprints. The packaged Standard price table includes cached input, cache
writes, and the >272K input-token long-context band. Unreported cache-write
usage is conservatively billed at the higher cache-write rate. No price or
model fallback is allowed. The adapter bounds request and
response bytes, output tokens, timeout, response shape, model identity, and
reported token usage. Before a call, request bytes plus a fixed envelope reserve
input allowance and reviewed maximum output cost; reported usage is returned
even when a provider exceeds its allowance so the graph can record measured
tokens and stop the run. It rounds estimated spend up to whole cents for budget
enforcement. Provider error bodies, prompt contents, and secrets are not logged.
If the provider reports usage but its content or citations fail validation, the
attempt and reported tokens/spend are retained before recording a candidate
outcome. A response without trustworthy usage or with a different model ID
stops the run, because the reviewed price cannot be applied. Reported usage
above the remaining allowance produces `BUDGET_STOPPED` with measured counters.

# ADR 0001 — Standalone Dataset Discovery service with Snowflake as the v1 system of record

- **Status:** Accepted
- **Date:** 2026-09-26
- **Deciders:** Atlas product / platform
- **Related:** data epic #80; data stories #448, #449, #450, #451, #85, #87

## Context

Atlas needs a Dataset Discovery Agent that recommends candidate datasets for investigation and hands accepted recommendations into the existing governed source-onboarding workflow. The agent must not approve sources, ingest payloads, or mutate authoritative governance tables.

## Decision

### 1. Standalone repository

Implement Dataset Discovery in:

`Caraway-Labs/one-health-lyme-gap-atlas-dataset-discovery`

This repository owns the Python/LangGraph application, agent state/orchestration, prompts, tool adapters, recommendation-domain models, persistence interfaces, agent-specific tests/evals, Docker/runtime packaging, and DigitalOcean deployment assets.

It does **not** own deterministic Atlas catalog ingestion, authoritative source governance, or the shared Snowflake migration framework.

### 2. Snowflake is the v1 system of record

Persist in Snowflake:

- agent run metadata
- recommendations and recommendation versions
- attributable evidence references
- human review/audit events
- search-expansion proposals
- downstream governed-handoff status
- model/prompt/tool/configuration/version identifiers required for audit and evaluation

Do **not** introduce PostgreSQL or another operational database for v1.

Rationale:

- Atlas already depends on Snowflake as the primary governed data platform
- expected write volume is modest and batch/workflow oriented
- recommendations are analytical/audit/provenance oriented
- Snowflake simplifies joins to authoritative catalog/source identities and later evaluation
- avoiding a second database reduces operating, synchronization, backup, security, and reconciliation complexity

### 3. Dedicated Snowflake namespace

Use environment-local schema `DATASET_DISCOVERY` with at least:

- `RUNS`
- `RECOMMENDATIONS`
- `RECOMMENDATION_EVIDENCE`
- `REVIEW_EVENTS`
- `SEARCH_EXPANSION_PROPOSALS`
- bounded read/review/handoff/history views

Keep these records distinct from authoritative governed source approval/version tables.

### 4. Persistence abstraction

The application depends on a typed domain interface (for example `RecommendationRepository`) with operations such as create_run, save_recommendation, append_review_event, list_pending_recommendations, and get_recommendation_history.

Snowflake is the initial implementation. LangGraph nodes must not embed scattered direct Snowflake SQL.

### 5. Migration ownership

`one-health-lyme-gap-atlas-data` remains the authoritative owner of Atlas shared Snowflake DDL, migrations, grants, and privilege-contract tests. This repository consumes those contracts through typed adapters and must not create a second migration ledger for the same Atlas database objects.

### 6. Least privilege

The Dataset Discovery runtime may:

- read only approved catalog/candidate/evidence surfaces
- write only approved Dataset Discovery runtime/recommendation/audit records

It may **not**:

- approve governed sources
- mutate authoritative source versions
- execute arbitrary SQL
- acquire unapproved source payloads
- publish releases
- mutate production search policy

Human review actions remain separately attributable.

### 7. Governed handoff semantics

"Accepted recommendation" means accepted for investigation, not source approved.

Flow:

1. Dataset Discovery recommendation
2. Human review
3. Accepted for investigation
4. Existing governed source-onboarding workflow
5. Rights / documentation / assessment / approval / ingestion controls

Stable recommendation/run/source/evidence identities must survive that handoff.

### 8. Reconsideration criteria

Revisit Snowflake-only persistence only if one or more of these appear:

- high-frequency interactive steward UX with transactional concurrency needs
- workflow latency that materially harms product behavior
- queue/session/locking semantics that become awkward or expensive in Snowflake
- demonstrated need for transactional application state not well served by the current abstraction
- material cost evidence favoring another store

Preferred evolution then: operational Postgres behind the existing repository interface, with Snowflake retained for analytical/audit history. Do not introduce the hybrid architecture preemptively.

## Alternatives considered

### A. Snowflake-only persistence (selected for v1)

- Benefits: one durable platform; strong joins to catalog/source identity; simpler ops; good auditability
- Drawbacks: not a conventional OLTP store; interactive review latency may become a limit later

### B. DigitalOcean Managed PostgreSQL (not selected for v1)

- Benefits: familiar transactional semantics for interactive apps
- Drawbacks: second database to operate/sync/secure; weaker immediate joins to Snowflake-governed identities; premature until interactive OLTP needs are proven

### C. Hybrid Postgres operational state + Snowflake analytical history (deferred)

- Benefits: OLTP where needed while keeping audit analytics in Snowflake
- Drawbacks: dual-write/sync complexity; only justified by the reconsideration criteria above

## Consequences

### Positive

- one primary durable data platform for v1
- easier source/recommendation/evaluation joins
- strong auditability and institutional memory
- fewer infrastructure components
- straightforward integration with existing governed onboarding

### Negative / accepted tradeoffs

- Snowflake is not a conventional OLTP application database
- very interactive review workflows may eventually expose latency/transactional limitations
- careful repository design is required to keep SQL out of graph nodes
- service-role boundary must be reconciled with the simplified Atlas role model

## References

- data#80 Dataset Discovery Agent epic
- data#448 standalone repository boundary
- data#449 Snowflake schema / least-privilege contract
- data#450 governed handoff
- data#451 this ADR story
- data#85 application persistence
- data#87 DigitalOcean deployment

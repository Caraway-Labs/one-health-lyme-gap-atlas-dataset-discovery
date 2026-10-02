# Typed persistence handoff

The existing `domain.persistence.RecommendationWrite` is the input contract for
classification/ranking output. `RecommendationRepository.save_recommendation`
returns `RecommendationWriteReceipt`; `get_recommendation(operation_key)` reads
the durable receipt after an uncertain acknowledgement. SQL stays in adapters.

The operation key is `recommendation:{run_id}:{resource_key}`. The graph's existing
canonical identity helper derives a stable recommendation ID and a per-run
version ID. The bundle contains the exact evidence snapshot, observed facts,
inferences, unknowns, structured rationale claims, ranking input/result,
relationship, rights evidence state, rendered rationale and canonical assertion
hash. `RecommendationWrite` validates their agreement before submission. Search
proposals remain inactive proposals, never active search-policy changes.

The Snowflake adapter checks the returned operation key, complete identity
(including explicit equivalence), assertion hash, sorted observation IDs and
proposal IDs against the submitted bundle. A structurally valid but mismatched
receipt fails closed. This does not undo a server commit: retain the original
operation key and reconcile through the bounded receipt view. Do not manufacture
a replacement recommendation or change its version to force acknowledgement.

The data-owned V108 procedure returns the supplied identity, sorted unique
observation IDs and version/index-derived proposal IDs. These checks preserve
that existing contract; no schema, grant or procedure change is required.

## Authority and acceptance

Construct the runtime repository only after the host verifies the environment's
service user, runtime role, database and warehouse. Use the existing shared
Snowflake/settings primitives and approved PAT connection; do not print or copy
credentials. Runtime writes use only fixed run/recommendation business procedures;
reads use bounded receipt views. Human review uses a separate authenticated
reviewer session outside the inference graph. Acceptance remains acceptance for
investigation, with no source-approval, acquisition, ingestion or publication
authority.

Data #449 and #450 are closed with reviewed DEV evidence in data PRs #502 and
#503. Their historical controlled persistence/rollback fixtures are explicitly
acceptance tests, not generated suitability findings. Data #450 additionally
records an attributable review and handoff of a hosted recommendation. This
establishes the data-owned contract and historical DEV evidence, not current
application runtime acceptance or PROD deployment authority.

Local receipt tests use mocks and require no Snowflake access. Read-only identity
or schema validation establishes only current visibility. New recommendation,
review or handoff writes require the actual authority and reviewed release gates;
never infer them from migration files or issue closure alone.

# one-health-lyme-gap-atlas-dataset-discovery

Dataset Discovery is the Atlas application that recommends candidate datasets for investigation, records attributable evidence and human review, and hands accepted recommendations into the governed source-onboarding workflow.

## Architecture

See [ADR 0001 — Standalone Dataset Discovery service with Snowflake as the v1 system of record](docs/adr/0001-dataset-discovery-persistence-and-service-boundary.md), the authoritative decision for this service boundary and v1 persistence.

This repository owns the Python/LangGraph application, agent orchestration, prompts, tool adapters, recommendation-domain models, persistence interfaces, agent-specific tests/evals, runtime packaging, and deployment assets. It does not own deterministic Atlas catalog ingestion, authoritative source governance, or the shared Snowflake migration framework; those remain with [`one-health-lyme-gap-atlas-data`](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data).

## Local foundation development

Requires Python 3.12 and `uv`. The package includes deterministic fake adapters, the sequential graph, and fixed Snowflake adapters. Local tests need no Snowflake, model, or DigitalOcean credential. The Snowflake adapters depend on the data-owned Dataset Discovery views and procedures in the reviewed V106–V108 migration sequence; their presence in this package does not establish a live DEV deployment or approved runtime grants.

`SnowflakeCandidateReader` and `SnowflakeDiscoveryContextReader` accept a host-supplied connection factory and expose only snapshot-pinned, parameterized reads. The reader's identity-link method depends on the data-owned V111 bounded view. Its prior-assessment and safe artifact-metadata methods depend on data-owned V112 bounded views. Absent protected migrations and reviewed `SELECT` grants, those reads fail closed. The recommendation repository accepts a host-supplied runtime connection and calls only fixed business procedures or receipt views. The host must establish and verify the approved least-privilege role before constructing these adapters. The agent graph cannot supply SQL or change the connection role.

```powershell
uv sync --extra dev --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
uv build
```

The reviewed [v1 implementation contract](docs/specs/v1/README.md) covers state, evidence, ranking, review, persistence, authority, evaluation, and rollout. Data #449 owns the Snowflake objects and role ADR; data #450 owns governed onboarding. Root `langgraph.json` exports the compiled graph. `deploy/digitalocean/` contains the secret-free hosted specs and preflight tools.

The [human review CLI](docs/operations/review-cli.md) runs separately from the inference graph and consumes the data-owned V109 review boundary. New live use requires the actual verified human session and reviewed release; historical DEV evidence is recorded separately in that guide.

The same human-only CLI has `handoff` and `handoff-status` commands backed by the
data-owned V110 investigation intake procedure and receipt view. The
typed client derives no rights or approval decision and sends only the exact
recommendation version and accepted review event. Its local fake supports
replay and rights-boundary tests without Snowflake credentials. Closed data #449/#450 record reviewed historical DEV contract evidence.
That does not authorize new review/handoff writes or establish current exact-SHA
application acceptance or PROD readiness.

The [DigitalOcean preflight](deploy/digitalocean/README.md) contains a
secret-free Harness Runtime templates, fully offline nonsecret configuration
checks and a separate credentialed exact-SHA/account/CLI dry-run path. The reviewed sequential graph is exported from `langgraph.json`.
The owner accepted the versioned OpenAI `gpt-6-luna` low configuration for
bounded `DEV_MANUAL` and `HOSTED_MANUAL` MVP operation. The current semantic
evaluation shows conservative over-abstention; all persisted recommendations
remain evidence-validated and require human review before governed handoff.
The first real DEV manual run persisted one insufficient-evidence candidate
outcome and finalized at its one-candidate budget. Scheduling remains disabled.
DigitalOcean HOSTED_MANUAL and three-candidate SHADOW runs have executed against
DEV Snowflake at exact recorded SHAs. Those historical records report paused sessions
and no triggers; they do not establish present account state for a newer revision.
Scheduling remains disabled in the application. The SHADOW operating spec routes redacted
OpenTelemetry spans to Arize AX SaaS through OTLP/HTTP. Remote receipt
was verified for the corrective SHADOW run by querying the Arize AX HTTPS trace
endpoint for the exact OTEL trace ID in the `atlas-dataset-discovery` project.

## Readiness and operation

The [readiness matrix](docs/operations/readiness.md) distinguishes merged code,
[offline evaluation](eval/README.md#offline-contract-corpus-v2), historical hosted
DEV receipts and unavailable PROD readiness. New hosted attempts require exact
reviewed code/configuration, secure managed credentials, approved budget and
operator monitoring. The [runbook](deploy/digitalocean/operations.md) requires an
explicit operator stop/cleanup deadline: idle timeout and per-run model budgets
are not total session lifetime or platform cost caps. No scheduler or automatic
session watchdog is enabled by these documents.

## Backlog migration

The authoritative Dataset Discovery implementation backlog is moving into this repository, with backlinks to [data#80](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/80) and [data#448](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/448), [data#449](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/449), [data#450](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/450), and [data#451](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/451).

Recommendations are accepted for investigation only; approval, rights, assessment, ingestion, and other governed source-onboarding controls remain in the existing workflow.

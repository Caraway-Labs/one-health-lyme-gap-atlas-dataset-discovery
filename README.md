# one-health-lyme-gap-atlas-dataset-discovery

Dataset Discovery is the Atlas application that recommends candidate datasets for investigation, records attributable evidence and human review, and hands accepted recommendations into the governed source-onboarding workflow.

## Architecture

See [ADR 0001 — Standalone Dataset Discovery service with Snowflake as the v1 system of record](docs/adr/0001-dataset-discovery-persistence-and-service-boundary.md), the authoritative decision for this service boundary and v1 persistence.

This repository owns the Python/LangGraph application, agent orchestration, prompts, tool adapters, recommendation-domain models, persistence interfaces, agent-specific tests/evals, runtime packaging, and deployment assets. It does not own deterministic Atlas catalog ingestion, authoritative source governance, or the shared Snowflake migration framework; those remain with [`one-health-lyme-gap-atlas-data`](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data).

## Local foundation development

Requires Python 3.12 and `uv`. The package includes deterministic fake adapters, the sequential graph, and fixed Snowflake adapters. Local tests need no Snowflake, model, or DigitalOcean credential. The Snowflake adapters depend on the data-owned Dataset Discovery views and procedures in the reviewed V106–V108 migration sequence; their presence in this package does not establish a live DEV deployment or approved runtime grants.

`SnowflakeCandidateReader` and `SnowflakeDiscoveryContextReader` accept a host-supplied connection factory and expose only snapshot-pinned, parameterized reads. The recommendation repository accepts a host-supplied runtime connection and calls only fixed business procedures or receipt views. The host must establish and verify the approved least-privilege role before constructing these adapters. The agent graph cannot supply SQL or change the connection role.

```powershell
uv sync --extra dev --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
uv build
```

The reviewed [v1 implementation contract](docs/specs/v1/README.md) covers state, evidence, ranking, review, persistence, authority, evaluation, and rollout. Data #449 owns the Snowflake objects and role ADR; data #450 owns governed onboarding. Root `langgraph.json` exports the compiled graph. `deploy/digitalocean/` is the future secret-free hosted spec home.

## Backlog migration

The authoritative Dataset Discovery implementation backlog is moving into this repository, with backlinks to [data#80](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/80) and [data#448](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/448), [data#449](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/449), [data#450](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/450), and [data#451](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/451).

Recommendations are accepted for investigation only; approval, rights, assessment, ingestion, and other governed source-onboarding controls remain in the existing workflow.

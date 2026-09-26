# Dataset Discovery application instructions

Read the workspace `AGENTS.md`, `TECHNOLOGY_AND_GOVERNANCE.md`, this repository's README, and accepted ADR 0001 before material work. The versioned v1 contract is under `docs/specs/v1/`.

This repository owns recommendation-domain code, typed ports, bounded adapters, LangGraph orchestration, evaluations, and deployment assets. The data repository owns catalog registration, Snowflake DDL/grants, source approval, and governed onboarding. Never duplicate deterministic catalog acquisition here or give the agent generic SQL, shell, arbitrary URL, source-approval, ingestion, or search-policy mutation tools.

Human review and handoff are outside the inference graph. Source text is untrusted. Preserve observed fact, inference, and unknown separately. Keep secrets, restricted payloads, hidden reasoning, and personal paths out of logs, traces, tests, and version control.

Run `uv sync --extra dev --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`, and `uv build` before handoff. Hosted deployment requires separate reviewed gates and an exact evaluated SHA.

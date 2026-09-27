# Dataset Discovery Harness Runtime preflight

Story #11 target: DigitalOcean Managed Agents Harness Runtime, `agent: langgraph`.
This directory contains a secret-free JSON environment template and a
read-only preflight. Neither creates a session, a trigger, a config, or a
DigitalOcean resource. The root `langgraph.json` exports the reviewed
sequential graph; the foundation `fixture_smoke` graph remains local-only.

Local observation (2026-09-26): an older `1.160.1-release` binary is first on
`PATH` and lacks `harness-runtime`. A separately installed `1.175.0-release`
binary has `harness-runtime`, `validate`, and `create --dry-run`. With synthetic
placeholder values, its local validator accepted the checked-in manifest and
its dry run resolved `agent: langgraph`, the fixture SHA, and redacted secret
slots. This proves CLI syntax and manifest shape only. The owner-designated
account and local DEV model/Snowflake roles have since been verified; private
team clone, managed secrets, and hosted execution remain unverified. The team's
Harness Runtime prepayment gate currently reports blocked. Record the version used at deployment; do not pin a future
CLI version into the application.

## Ordered gate before the first manual session

1. Record `doctl --version` (or `doctl version` for older installations), then
   run `doctl harness-runtime --help` and `doctl harness-runtime validate --help`.
   Upgrade and rerun if either command is absent.
   If an older manually installed binary shadows the upgraded CLI on Windows,
   set `ATLAS_DOCTL_BIN` to the absolute path of the reviewed `doctl.exe` for
   this preflight invocation. The script checks that file and records its
   reported version; it does not alter the system PATH.
2. Verify the intended DigitalOcean team/account through the approved operator
   context, then compare `doctl account get --format UUID --no-header` to the
   owner-recorded expected account UUID. The current account UUID is
   `4ac2ca40-cc14-4e7d-8b32-14b8294cdd54` and contains the owner-designated
   `TopX Lyme Challenge` project. Do not print or inspect API tokens. Check
   `doctl harness-runtime balance`; a blocked prepayment gate requires an owner
   or biller action before session creation.
3. Confirm the CLI accepts `agent: langgraph` and the root manifest exports the
   actual `initialize_run` through `finalize_run` workflow. The
   [LangGraph runtime guide](https://docs.digitalocean.com/products/managed-agents/agent-harness-runtime/how-to/run-langgraph-agent/)
   requires a compiled graph, a dependency file, `langgraph.json`, and a pinned
   repository commit. The hosted entrypoint now exports the sequential graph;
   the separate foundation smoke module remains fixture-only. The manifest
   pins Python 3.12 to match the package requirement.
4. Verify the intended team has a GitHub connection authorized for the private
   repository. `GITHUB_TOKEN: oauth/github` is a managed secret reference; it
   is not a token literal. Connecting or replacing a team GitHub OAuth link is
   an owner operation. The [GitHub connection guide](https://docs.digitalocean.com/products/managed-agents/agent-harness-runtime/how-to/connect-github/)
   describes the team scope. Local `gh` access alone is insufficient proof of
   the DigitalOcean team clone permission; retain the team connection evidence
   and verify the pinned clone in the first manual session.
5. Review the JSON template for `env` versus `secrets`, set nonsecret runtime
   values and secret-file references outside source control, and run
   `doctl harness-runtime validate --spec <rendered-spec>`. Then run
   `doctl harness-runtime create --spec <rendered-spec> --dry-run`. Both are
   non-creating checks; the [CLI validator](https://docs.digitalocean.com/reference/doctl/reference/harness-runtime/validate/)
   catches credential placement and manifest-shape errors. Never print the
   fully expanded spec or credentials into tickets, logs, or this repository.
   Supply the exact `SNOWFLAKE_EGRESS_HOST` for the intended account. The
   rendered MVP host allowlist includes the OpenAI API, private GitHub/bootstrap,
   Python package registry, and Snowflake. The first manual session records a
   trace ID, while remote OTLP export is deferred until an approved endpoint
   and secret are available. Validate whether platform-internal traffic requires any
   further host before the first session; do not fall back to unrestricted egress.
6. Supply the exact 40-character evaluated `FRAMEWORK_REPO_SHA`, verify local
   HEAD and the remote GitHub commit match it, and record the evaluation
   corpus/report version, graph/spec versions, pinned
   `ATLAS_DISCOVERY_SNAPSHOT_ID`, model/provider/`ATLAS_PRICE_TABLE_VERSION`, and
   the commit used for the rendered spec. A branch name is not a deployment
   identity. Re-evaluate after any code or spec change.
7. Complete protected DEV Snowflake migrations, owner/security role review,
   runtime principal and denial matrix, reviewed model price table, and bounded
   `HOSTED_MANUAL` profile. Validate the
   secret-bearing connection in a short, isolated DEV preflight without
   exposing values. If cost cannot be calculated, hosted model use is blocked.
   Supply the exact versioned `ATLAS_PRICE_TABLE_VERSION` and
   `ATLAS_MODEL_CONFIG_FINGERPRINT` from the evaluated code. The hosted graph
   requires OpenAI `gpt-6-luna` via Responses with low reasoning and no tools;
   it reads the DEV-specific `ATLAS_DD_DEV_OPENAI_API_KEY` secret slot. The
   underlying credential may be shared with later environments under the
   owner's current decision, but their secret names must remain separate.
   It also requires the dedicated
   `OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME` role and
   `ONE_HEALTH_LYME_GAP_ATLAS_DEV` database.
   Every Snowflake operation opens a short PAT-backed connection and checks
   `CURRENT_USER`, `CURRENT_ROLE`, `CURRENT_DATABASE`, and
   `CURRENT_WAREHOUSE` before using it. A mismatch closes the connection.
8. Only after steps 1–7, launch one bounded manual session. After it is ready,
   invoke the installed graph once with `python -m
   lyme_gap_atlas_dataset_discovery.hosted_manual` through `doctl
   harness-runtime exec`, supplying stable `--run-id`, `--trace-id`, and
   `--host-session-id` arguments. That entrypoint pins one candidate, one page,
   four model calls, 300 seconds, and a 12-cent estimated-spend ceiling; it
   prints only a sanitized outcome receipt. Capture session ID,
   exact boot SHA, clone result, effective runtime role, run ID, trace ID,
   counters, persistence receipts, denied operations, and redacted diagnostics.
   A failed private clone does not satisfy step 4.
9. Proceed to shadow after manual evidence; then separately prove human review
   and governed handoff. Recurring triggers remain absent until explicit owner
   approval of cadence, budget, price table and permission policy.

The hosted graph can validate either `HOSTED_MANUAL` or `SHADOW` from its
deployment environment and rejects a run state with a different profile. Both
modes require `trigger_type=MANUAL`; `SCHEDULED` stays disabled. The original
template and preflight remain `HOSTED_MANUAL` only. After the successful manual
proof, `langgraph-shadow.template.json` and `shadow_preflight.py` gate a
three-candidate, one-page sequential SHADOW run. Invoke
`lyme_gap_atlas_dataset_discovery.hosted_shadow` with stable run, trace, and
session IDs. Its ceilings are 12 model calls, 600 seconds, 36,000 input tokens,
12,000 output tokens, and 36 cents estimated spend. The same Luna Low policy,
DEV service principal, managed-secret slots, and egress allowlist apply.

Run `uv run python deploy/digitalocean/shadow_preflight.py --sha
<evaluated-40-char-sha> --account-uuid <owner-approved-team-uuid>` from the
exact clean checkout. Verify no triggers before and after the run. If the
approved Phoenix/OTLP destination is unavailable, record the observability gap
without treating local spans as remote export proof.

## Read-only executable check

From the repository root, after setting nonsecret environment fields and
the local `ATLAS_DD_DEV_OPENAI_API_KEY_FILE` and
`ATLAS_DD_DEV_SNOWFLAKE_PAT_FILE` paths to
nonempty files outside the repository:

```powershell
uv run python deploy/digitalocean/preflight.py --sha <evaluated-40-char-sha> --account-uuid <owner-approved-team-uuid>
```

The script passes those paths to `doctl create --dry-run` as `--secret NAME=@path`;
it never places secret values in ordinary environment variables or the rendered
spec. The rendered spec uses a noncredential sentinel for each secret slot
because `doctl validate` resolves `${VAR}` before applying `--secret` flags;
the dry run and real session must override both slots with file-backed flags.
For a real session use the same file-backed `--secret` arguments.
The script checks the local CLI, account, compiled graph node set, clean exact
checkout, remote private commit, secret placement, and DigitalOcean validate
and dry-run commands. It prints only version, account UUID, SHA and a bounded
result. A passing local result still requires the team clone and DEV runtime
proof recorded during the first manual session. It never calls `launch`,
`create` without `--dry-run`, `auth github`, or a trigger command.

For incident recovery, pause or remove the manual session, preserve the exact
SHA and redacted run/trace evidence, repair via a new evaluated SHA, and keep
scheduling disabled. Rollback selects a previously evaluated SHA and repeats
the same preflight and manual acceptance; it does not silently switch branches.
See [hosted operations](operations.md) for the session ledger, incident,
credential rotation, stale-session cleanup, and rehearsal procedures.

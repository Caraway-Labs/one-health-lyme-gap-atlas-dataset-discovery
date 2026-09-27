# Dataset Discovery Harness Runtime preflight

Story #11 target: DigitalOcean Managed Agents Harness Runtime, `agent: langgraph`.
This directory contains a secret-free JSON environment template and a
read-only preflight. Neither creates a session, a trigger, a config, or a
DigitalOcean resource. The root `langgraph.json` must export the reviewed
sequential graph before launch. As of 2026-09-26 it still exports the
foundation `fixture_smoke` graph; the preflight rejects it.

Current local observation (2026-09-26): `doctl --version` is unsupported;
`doctl version` reports `1.160.1-release`; `doctl harness-runtime --help`
reports an unknown command. The installed CLI therefore cannot pass preflight.
The [current doctl reference](https://docs.digitalocean.com/reference/doctl/reference/harness-runtime/)
documents `harness-runtime`; upgrade to a currently supported release before
continuing. Record the version actually used as deployment evidence. Do not
pin a future CLI version into the application.

## Ordered gate before the first manual session

1. Record `doctl --version` (or `doctl version` for older installations), then
   run `doctl harness-runtime --help` and `doctl harness-runtime validate --help`.
   Upgrade and rerun if either command is absent.
2. Re-authenticate the intended DigitalOcean team/account through the approved
   operator context, then compare `doctl account get --format UUID --no-header`
   to the owner-recorded expected account UUID. Do not print or inspect API
   tokens. The account currently shown locally has not been designated as the
   intended deployment team.
3. Confirm the CLI accepts `agent: langgraph` and the root manifest exports the
   actual `initialize_run` through `finalize_run` workflow. The
   [LangGraph runtime guide](https://docs.digitalocean.com/products/managed-agents/agent-harness-runtime/how-to/run-langgraph-agent/)
   requires a compiled graph, a dependency file, `langgraph.json`, and a pinned
   repository commit. The foundation smoke graph fails this step.
4. Verify the intended team has a GitHub connection authorized for the private
   repository. `GITHUB_TOKEN: oauth/github` is a managed secret reference; it
   is not a token literal. Connecting or replacing a team GitHub OAuth link is
   an owner operation. The [GitHub connection guide](https://docs.digitalocean.com/products/managed-agents/agent-harness-runtime/how-to/connect-github/)
   describes the team scope. Local `gh` access alone is insufficient proof of
   the DigitalOcean team clone permission; retain the team connection evidence
   and verify the pinned clone in the first manual session.
5. Review the JSON template for `env` versus `secrets`, set nonsecret runtime
   values and managed secret values outside source control, and run
   `doctl harness-runtime validate --spec <rendered-spec>`. Then run
   `doctl harness-runtime create --spec <rendered-spec> --dry-run`. Both are
   non-creating checks; the [CLI validator](https://docs.digitalocean.com/reference/doctl/reference/harness-runtime/validate/)
   catches credential placement and manifest-shape errors. Never print the
   fully expanded spec or credentials into tickets, logs, or this repository.
6. Supply the exact 40-character evaluated `FRAMEWORK_REPO_SHA`, verify local
   HEAD and the remote GitHub commit match it, and record the evaluation
   corpus/report version, graph/spec versions, model/provider/price table, and
   the commit used for the rendered spec. A branch name is not a deployment
   identity. Re-evaluate after any code or spec change.
7. Complete protected DEV Snowflake migrations, owner/security role review,
   runtime principal and denial matrix, reviewed model price table, redacted
   OTLP/Phoenix endpoint, and bounded `HOSTED_MANUAL` profile. Validate the
   secret-bearing connection in a short, isolated DEV preflight without
   exposing values. If cost cannot be calculated, hosted model use is blocked.
8. Only after steps 1–7, launch one bounded manual session. Capture session ID,
   exact boot SHA, clone result, effective runtime role, run ID, trace ID,
   counters, persistence receipts, denied operations, and redacted diagnostics.
   A failed private clone does not satisfy step 4.
9. Proceed to shadow after manual evidence; then separately prove human review
   and governed handoff. Recurring triggers remain absent until explicit owner
   approval of cadence, budget, price table and permission policy.

## Read-only executable check

From the repository root, after setting nonsecret environment fields and
managed secret variables in the operator's environment:

```powershell
uv run python deploy/digitalocean/preflight.py --sha <evaluated-40-char-sha> --account-uuid <owner-approved-team-uuid>
```

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

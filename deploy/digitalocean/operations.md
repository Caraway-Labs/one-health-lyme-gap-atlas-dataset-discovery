# Dataset Discovery hosted operations (v1)

This is the operator procedure for the reviewed, pinned LangGraph deployment.
The current deployment template and executable preflight permit only a bounded
`HOSTED_MANUAL` session. Shadow requires successful manual evidence and a
separately reviewed spec. Recurring triggers remain disabled until explicit
owner approval. All commands below refer to the owner-designated DigitalOcean
team; confirm `doctl account get --format UUID --no-header` before using them.

The command names were checked against `doctl version 1.175.0-release` on
2026-09-26. Recheck `doctl harness-runtime <command> --help` with the version
used for an actual operation; this document is not a CLI version pin.

## Session ledger and evidence

For each manual or shadow attempt, record the following in the restricted
operations record. Keep credentials, catalog payload, model prompt/output,
reviewer identity, and raw exception messages out of that record.

| Field | Evidence source |
| --- | --- |
| Team/account UUID, doctl version, operator, time | Account preflight and change record |
| Git commit SHA, manifest checksum, spec/graph/eval versions | Evaluated remote commit and rendered-spec review |
| Discovery snapshot, profile, limits, price table/model identity | Validated run request and deployment record |
| Session ID, status, exact boot SHA | `doctl harness-runtime show <session> -o json` and redacted startup evidence |
| Run ID, final status, stop reason, counters, persistence receipts | Dataset Discovery `RUNS` and bounded receipt views |
| OTEL trace ID and exporter receipt/trace reference | Approved Phoenix/OTLP inspection |
| Permission denials, clone/model/Snowflake outcome | Redacted session diagnostics and DEV privilege tests |
| Human adjudication and handoff, if performed | Exact review event and governed handoff receipt |

Never infer a successful run from a ready session, a green CI check, a local
preflight, or a recommendation row alone. Confirm `RUNS` finalization and its
candidate outcomes, then reconcile with trace and session IDs. A missing or
ambiguous receipt requires a read by the deterministic operation key before
any resend. Do not manually insert migration or business receipts.

## Manual launch and observation

1. Complete the ordered [preflight](README.md) and record its redacted output.
   Reconfirm the intended account, reviewed role/grants, owner-reviewed price
   table, exact evaluated SHA, private clone access, and managed secrets.
2. Use the reviewed rendered spec through `doctl harness-runtime create
   --spec <rendered-spec> -o json`. Do not use `--on-hitl approve` or
   `--resume-on-topoff`; unattended spending and approval are not authorized.
   Store the returned session ID in the operations record. Do not paste the
   expanded spec or secret values into the record.
3. Inspect `doctl harness-runtime show <session> -o json`. Inspect
   `doctl harness-runtime logs <session>` only in the restricted operator
   environment; redact before attaching excerpts. Verify clone, exact boot
   SHA, model/Snowflake context, graph execution, budget counters, run
   finalization, and Phoenix trace. Inspect the persisted run and operation
   receipts using the approved least-privilege DEV read path.
4. Treat an unavailable exporter or missing trace as missing observability
   proof. Do not promote the configuration to shadow or scheduling on the
   strength of application success alone.

## Stop and incident response

1. If a future trigger exists, identify its exact ID with `doctl
   harness-runtime triggers list -o json` and pause it with `doctl
   harness-runtime triggers pause <trigger-id>`. Record the returned state.
   There is no approved v1 trigger at present.
2. Pause an affected session with `doctl harness-runtime pause <session>`.
   Confirm its status with `show`. Pausing preserves the workspace; it does
   not undo a committed Snowflake write or guarantee an in-flight operation
   was not committed. Do not immediately resend a write.
3. Preserve the exact SHA, session ID, run ID, last known operation key,
   redacted logs, and trace reference. Query the corresponding receipt and
   finalized run state through the approved read surfaces. Classify the
   incident as clone/startup, principal/privilege, model, Snowflake,
   telemetry, budget, policy, or persistence ambiguity.
4. For a lost acknowledgment, reconcile by operation key. For a terminal
   failed/partial/budget-stopped run that must be retried, use a new run ID
   and `retry_of_run_id`; never reopen or rewrite the prior run. For a policy
   or security failure, stop until reviewed remediation is available.
5. Resume only an explicitly reviewed paused session with `doctl
   harness-runtime resume <session>`, after confirming its SHA, credentials,
   remaining budget and persisted receipts. Otherwise deploy a new evaluated
   SHA into a new manual session. Do not resume or schedule automatically.

## Redeploy, rollback and credentials

- **Redeploy:** fix code or spec in a focused PR, evaluate the exact remote
  commit, repeat preflight, then create a new bounded manual session. Record
  both old and new session/run identities and compare outcome, cost, and trace.
- **Rollback:** choose a previously evaluated and still permitted commit,
  revalidate its dependency and secret contract against the current platform,
  repeat preflight, and launch a new manual session pinned to that SHA. The CLI
  `rollback <session> <checkpoint-id>` rewinds a session workspace checkpoint;
  it is not evidence that an older Git SHA was deployed and it does not roll
  back Snowflake records. Do not use it as the application release rollback.
- **Credential rotation:** the owner rotates GitHub connection, model key,
  Snowflake PAT, or OTLP authorization through the approved provider and
  managed-secret paths. Do not display or copy token values. Validate the new
  principal and least-privilege role in DEV, then preflight and launch a new
  pinned manual session. Retire the old credential after the replacement has
  passed; if a credential was exposed, revoke it immediately and keep runs
  stopped until replacement validation succeeds.
- **Stale sessions:** list the intended team's sessions with `doctl
  harness-runtime list -o json`. Match exact session ID against the operations
  ledger and check for an active run, pending handoff evidence, or incident
  retention. Once the owner confirms the session is disposable and evidence is
  preserved, `doctl harness-runtime remove <session>` tears down its workspace.
  Never remove a session merely because its display name looks old.

## Rehearsal and promotion record

Before shadow, rehearse a manual-session pause, an ambiguous-acknowledgment
receipt lookup, an exporter outage, and a new-SHA rollback path in DEV.
Record observed behavior, commands, exact session/run IDs, and limits. Before
any recurring trigger, obtain explicit owner approval of cadence, per-run and
monthly spend, model price table, tool permissions, evaluation gates, and
human review results. Until those records exist, the trigger state is
**DISABLED**.

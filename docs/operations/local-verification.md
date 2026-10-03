# Bounded local DEV verification

Story #55 extends existing epic #5. This is an explicit operator invocation of
the reviewed graph with existing DEV persistence. It does not satisfy remote
Arize acceptance (#10), Harness Runtime acceptance (#11), human review, handoff,
or source approval. No scheduler or hosted resource is created.

## Authentication and release

Run only from a clean independently reviewed exact-SHA Git checkout. Supply the
existing nonsecret manual graph configuration documented in the hosted runbook,
including `FRAMEWORK_REPO_SHA`, pinned snapshot and model policy fingerprints.
The existing dedicated `ATLAS_DD_DEV_OPENAI_API_KEY` environment slot must already
be available through the approved application authentication provider. Missing
authentication reports `EXISTING_MODEL_AUTH_UNAVAILABLE` before connections.
The runner does not read key files, configure credentials, copy another app's
secret or introduce an alternate provider. An owner/operator must resolve this
setup gap through their supported secure application-authentication path.

Snowflake uses the existing `ATLAS_DEV_DATASET_DISCOVERY_RUNTIME` named driver
connection and forces PAT authentication. It never reads or exports a PAT to
application configuration. The driver performs its normal profile resolution.
The runtime principal, role, DEV database and warehouse must match the reviewed
configuration before metadata/business operations. Reviewer authentication is
separate; the runner performs no review or handoff.

## Budget evidence is mandatory

Pass a **nonsecret** JSON cost-evidence file with these fields:

- `account_locator`: the approved account locator matching the runtime's
  expected account, verified again using `CURRENT_ACCOUNT()` before operations.
- `warehouse_hourly_usd`: billing-owner verified dollar rate for this account's
  single-cluster X-Small Gen2 warehouse, including its actual consumption rate.
- `other_cost_reserve_usd`: positive conservative reserve covering attributable
  cloud services, retained audit storage and any other account charges.
- `evidence_reference`: nonsecret owner-reviewed billing evidence reference.
- `approved_total_usd`: explicit approval, at most 1 USD for this runner.
- `policy_verified_at`: UTC timestamp, reviewed within the last hour.

Unknown rates/reserves are blockers, not zero-cost assumptions. The evidence
file is an operator attestation; the application cannot verify account contract
prices or cloud/storage attribution. Independent review must establish those
inputs before executing. Do not place credentials, personal paths or private
billing documents in the file or public issue. No example price is a real rate.

The conservative exposure calculation reserves 0.12 USD for models plus
`warehouse_hourly_usd * 490 / 3600` plus the other-cost reserve. The 490 seconds
include a 300-second parent deadline, 10 seconds for forced stop, 30 seconds
queued plus 30 seconds executing after termination, 60 seconds idle tail, and
an additional 60-second resume minimum. Session query timeouts are verified;
warehouse metadata must show single-cluster X-Small Gen2, auto-suspend 60 seconds
and query acceleration disabled. Missing metadata fails closed. The runner
does not change warehouse settings, privileges or resource monitors.

This is a conservative estimate of **this run's attributable exposure**, not a
native Snowflake dollar cap or a bound on unrelated concurrent account activity.
If billing ownership cannot substantiate the calculation and reserve for the
shared warehouse, do not execute. The approved $1 alone does not establish it.

## Invocation and recovery

Use `python -m lyme_gap_atlas_dataset_discovery.local_verification --cost-evidence
<nonsecret-file> --run-id dd-hosted-manual-<32-hex> --no-export` for configuration
validation only. It makes no connection/model calls. After all evidence and
authority are established, the same command with `--execute-authorized` runs
once. Keep the stable run ID for receipt recovery; do not start a fresh run to
hide a partial write. One candidate, four model calls and **zero graph retries**
are enforced. The existing OpenAI client already has zero SDK retries.

No-export mode rejects ambient OTEL/Arize/LangSmith/LangChain variables, uses a
no-op OTEL provider and explicitly disables LangSmith tracing within the worker.
Worker stdout/stderr are discarded; only an allowlisted
summary returns to the parent. It never exports raw evidence, model output or
connector messages.

The parent terminates a worker after 300 seconds independently of graph checks,
then kills it if necessary. Each session requests and verifies 30-second server
statement/queue limits and detached-query abortion. Existing cursor execution
timeouts request best-effort connector cancellation; adapters close connections
on ordinary exits. A hard process kill cannot run Python cleanup or prove server
cancellation. Server statement timeout is the fallback bound, and forced stop
reports `DEADLINE_UNKNOWN_DURABLE_STATUS`, never rollback/zero-cost proof.
Recover exact run/recommendation receipts with the approved runtime read path
before any new execution. Preserve actual billed usage and receipt evidence
separately from the estimate; no local test establishes runtime acceptance.

# Dataset Discovery readiness and operating boundary

This page separates implementation and fixture results from deployment acceptance.
Dataset Discovery recommends investigation. It does not approve sources, clear
rights, acquire payloads, ingest or publish data, or change active search policy.

## Evidence layers

| Layer | What is established | What still needs evidence |
| --- | --- | --- |
| Merged application code | PRs #49–#52 implement classification/evidence gates, typed receipt integrity, review documentation and handoff failure/recovery behavior on main `bc49006ea90e49a2e8447344f9a49a95c2880182`. | A later revision must be reviewed, merged and tested at its own exact head. Code presence does not prove execution. |
| Offline configuration and fixtures | The versioned [evaluation report](../../eval/reports/offline-contracts-v2.md), in-memory trace checks and `--offline` preflight use synthetic inputs. | Independent fixture/rubric review and exact reviewed-commit gates. Neither a configuration check nor a passing fixture establishes semantic usefulness, remote export or a real transaction. |
| Historical hosted DEV and data contracts | [Discovery #11](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-dataset-discovery/issues/11) records older manual/SHADOW and remote Arize evidence. Closed [data #449](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/449) and [data #450](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/issues/450) record reviewed DEV persistence, attributable review, governed handoff and explicit owner-accepted contract-test substitutions. | Reconcile those historical SHAs/receipts with the selected application revision. A new exact-SHA run needs its own session, finalized run, evidence/receipt, remote trace, privilege and budget proof; review/handoff remains separately human initiated. |
| PROD and unattended readiness | The current hosted bootstrap and preflight accept dedicated DEV configuration only. There is no application PROD readiness or scheduling claim here. | Protected promotion review, environment-specific identities/grants/secrets, explicit operating authority and accepted quality/operational gates. Data migration readiness for promotion review is not deployment authorization. |

PR #53's offline extension and this operations reconciliation require independent
review; their fixtures cannot silently replace a live criterion. Historical
reports that sessions were paused and triggers empty are point-in-time evidence.
Inspect the intended account again before any later authorized operation.

## Modes and reproducibility

`FIXTURE` uses synthetic adapters locally. `DEV_MANUAL` is a real DEV write mode;
its name is not permission to run it. Hosted `HOSTED_MANUAL` and `SHADOW` accept
only manual triggers, the exact pinned SHA, the bounded completed discovery
snapshot/search fingerprint and the reviewed model/price fingerprints.
`SCHEDULED` remains disabled. Human review and governed handoff are outside the
inference graph and use an individually authenticated reviewer session.

The current manual baseline uses Luna Low semantic v2 with a 2048 output-token
cap per call. SHADOW selects the separately fingerprinted 4096-token Candidate B
variant. Both retain deterministic ranking, evidence validation and downstream
human authority. Selecting the variant is not a new quality acceptance; preserve
historical over-abstention and usefulness limitations. Do not broaden evidence,
relax relationship gates, tune ranking/model policy or select sources to force
an acceptance result.

Record the exact code/manifest/spec, graph/model/prompt/tool/evaluation versions,
source/snapshot identities, review event and operation keys required for replay.
Node spans hash prompt/tool version maps; full maps stay in run metadata.
Restricted content and credential values stay out of logs, public tickets,
evaluation artifacts and traces. Remote Arize receipt needs inspection of the
actual trace, not just an application correlation ID.

## Remaining owner/operator steps

1. Review and merge the offline changes, refresh main, and verify exact-head CI
   and the applicable deterministic corpus. Record the selected immutable SHA;
   later code/config changes need new evaluation. No hosted resource is needed
   for this step.
2. Decide the concrete DEV attempt: exact SHA/profile/snapshot or governed
   candidate IDs, allowed writes, budget and time window. Define separate
   overall platform/Snowflake/model exposure and a named monitoring operator.
   The configured model estimate ceiling is not authorization to spend.
3. Supply credentials through the approved secure owner/operator-to-provider
   managed-secret path. Do not paste keys/PATs/headers into chat or GitHub, or
   place them in the repository. The application does not authorize new
   credentials, expanded access or a different account. The intended team must
   have private clone access and the least-privilege DEV roles/grants.
4. After that handoff and paid-operation authorization, run the credentialed
   [preflight](../../deploy/digitalocean/README.md), including current CLI/account,
   exact clean checkout/remote commit and managed secret placement. `--dry-run`
   is not a guarantee that credentials stay local; the CLI receives the
   file-backed secret arguments. Complete local nonsecret checks first.
5. Under the agreed operator deadline, launch the approved bounded manual
   attempt, inspect exact boot SHA/principal, reconcile run/outcome/recommendation
   receipts and measured counters, and inspect remote trace delivery. Proceed
   to the separately approved SHADOW proof only after its prerequisites.
6. If a natural validated recommendation exists, an authorized human reviews
   its exact version and latest event before governed handoff. Reconcile lost
   acknowledgments by the original operation key; do not invent approval,
   replace events or manufacture a recommendation. Record any unavailable case
   or owner-approved substitution explicitly.
7. Verify pause/cleanup and incident/rollback rehearsals, retaining redacted
   evidence and actual session state. Keep scheduling and PROD blocked until
   their explicit release decisions and evidence exist.

These steps specify required decisions and evidence, not an approval to perform
paid operations, transmit credentials, create resources or issue business writes.
See the [operations runbook](../../deploy/digitalocean/operations.md) for lifetime,
cleanup and cost-control limitations.

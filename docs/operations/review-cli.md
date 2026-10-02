# Dataset Discovery human review CLI (v1)

This workflow is outside the inference graph. It requires data-owned V109, the
approved ADR 0041 role/grants, and an individually authenticated Snowflake
`USER_PERSON` session with the environment's Dataset Discovery reviewer role.
The procedure derives the caller's identity from `SNOWFLAKE$SESSION` and an
allowlist; no CLI option can assert a reviewer name. The CLI forces a named
programmatic access token connection and never starts browser or OAuth login.

Do not use the CLI against DEV or PROD until the protected migration, procedure
ownership, `READ SESSION` grant, role isolation, and live principal tests are
approved and verified. Keep the reviewer PAT out of this repository, shell
history, and logs. The unattended Dataset Discovery runtime uses a different
service identity and cannot call the review procedure.

```powershell
dataset-discovery-review --connection <human-review-pat-name> list --run-id <run-id>
dataset-discovery-review --connection <human-review-pat-name> show <recommendation-version-id>
dataset-discovery-review --connection <human-review-pat-name> history <recommendation-version-id>
dataset-discovery-review --connection <human-review-pat-name> accept-for-investigation <recommendation-version-id> --rationale "Investigate documentation and rights"
```

Other decisions are `reject`, `mark-duplicate`, `mark-already-known`,
`request-more-information`, and `expire`. Every decision requires a rationale.
Use `--condition` for a bounded condition, repeatable up to ten times. Read the
exact version with `show` before deciding. Pass its `latest_review_event_id` as
`--expected-event-id` when one exists. To correct a terminal rejected,
duplicate, already-known, or expired decision, also pass the same event ID as
`--correction-of-event-id`. An accepted version is terminal in v1.

`list` is scoped to one run and ordered by deterministic `rank_in_run`.
Use `--after-rank` with the returned `next_after_rank` for the next page.
`history` uses `--after-sequence` with `next_after_sequence`. A repeated command
with identical version, prior event, decision, rationale, conditions and
correction target derives the same command key. Retry those exact arguments
after an uncertain response. A changed prior event fails closed as stale;
inspect `show` and `history` before any new human decision.

`ACCEPTED_FOR_INVESTIGATION` creates no source approval, rights clearance,
payload acquisition, or ingestion. The separate data-owned handoff must be
explicitly invoked after review and preserves the exact review event.

After the data-owned V110 handoff boundary is approved and applied, use the
accepted version's exact `review_event_id` from `history`:

```powershell
dataset-discovery-review --connection <human-review-pat-name> handoff <recommendation-version-id> --review-event-id <accepted-review-event-id>
dataset-discovery-review --connection <human-review-pat-name> handoff-status <recommendation-version-id>
```

The handoff call is idempotent for the version and event. Retry the same call
after a lost response, or read `handoff-status`. Unknown rights still enter
investigation; controlled access has no automated acquisition. The governed
queue and policy findings remain data-owned. `POLICY_BLOCKED` requires a
separate reviewed hard prohibition. The reviewer connection cannot write the
policy finding, source decision, source version, or ingestion tables.

## Existing DEV lifecycle evidence and release gate

Data #449 and #450 are closed following reviewed data PRs #502 and #503. The
accepted ADR 0041 and protected DEV migrations establish separate runtime,
reviewer and non-login write-owner roles. Historical DEV evidence includes a
genuine hosted recommendation, individually authenticated acceptance, append-only
review attribution, exact/conflicting handoff replay, concurrent intake and
controlled rollback/retry. See the data-owned
`docs/operations/dataset-discovery-handoff-dev-acceptance-2026-09-28.md` for exact
identities and the explicitly owner-accepted contract-test substitutions. These
are prior acceptance receipts, not new execution by this application revision.

The existing typed input from #8 remains `RecommendationWrite`; #9 consumes its
immutable version through `HumanReviewRepository` and `HumanReviewService`.
The review detail retains observed facts, inferences, unknowns, evidence,
relationship, dimensions, formula, rationale and stable provenance identities.
`history` exports the bounded typed append-only events as JSON for evaluation.
Feedback is recorded as attributable decisions and conditions; it does not
change ranking weights, prompts, model policy or production search terms.

Before a new write, verify the actual human session, exact version and latest
review event, current protected DEV contract, and reviewed application release.
Do not infer live authority from this document or issue closure. Do not replay a
historical acceptance under a new event or invent a recommendation to prove
the lifecycle. New live review/handoff writes and PROD promotion remain separate
release gates.

## Handoff transport failures

The Snowflake handoff adapter raises a sanitized `HandoffOperationError` with
`RETRYABLE_FAILURE` for local connection/timeouts, documented connector closed-
connection/timeout codes and connection-failure, unknown-transaction or
serialization-failure SQLSTATEs. Other connector errors, including authorization,
validation, stale/conflicting state and unknown codes, are `TERMINAL_FAILURE`.
Classification never reads or emits connector message text, SQL or account data.
Domain validation and human-session denials continue to refuse the request.

These are client outcomes, not persisted handoff dispositions. The CLI returns
1 for a retryable failure and 2 for a terminal failure. There is no automatic
retry. After connection recovery, read `handoff-status` for the original version;
if no receipt exists, an authorized human may retry the same version and review
event. Never replace an event, change an operation key or manufacture a failed
row after an unknown outcome. Resolve a terminal governed cause and inspect
current review state before any resubmission.

Handoff commands initialize through the wrapped handoff human-session check.
The same classification covers connection opening and teardown. A teardown
failure can follow a committed receipt: the CLI does not claim rollback or
successful delivery and does not submit again. Read the original version's
status after recovery, including after a terminal teardown error, before any
further governed action.

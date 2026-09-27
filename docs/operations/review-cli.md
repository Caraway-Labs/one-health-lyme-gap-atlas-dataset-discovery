# Dataset Discovery human review CLI (v1 draft)

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

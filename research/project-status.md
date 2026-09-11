# Project status and session handoff

**Overall documentation update:** 2026-09-10 20:36:44 CDT

**Plan being measured:** [`research/project-plan.md`](project-plan.md)

**Implementation baseline:** `d828863` (`docs: record OAuth and controlled LA validation`)

This document is the current handoff record for a new session. The project plan remains the authority for intended behavior, while this file records what has actually been implemented, tested, and exercised against the live source and Calendar.

## Current repository state

- Branch: `main`
- Baseline at the time of this review: `d828863`, 21 commits ahead of `origin/main` before this documentation update
- Runtime: Python 3.13 in the repository-local `.venv`
- Deterministic verification: **56 tests passed** on 2026-09-10
- Credentials: the dedicated Desktop OAuth client JSON is ignored by Git; the refresh token and durable state belong under `~/Library/Application Support/techweek-etl/`
- Calendar tooling: `gog` is retained for read-only development inspection; the application uses its dedicated Desktop OAuth token and native Python client for inventory and writes
- Production state: ten selected LA events have been inserted into Candidate Events and an identical replay made zero additional writes
- Scheduler state: no LaunchAgent or CI workflow has been installed

Useful restart commands:

```sh
git status --short --branch
git log --oneline --decorate -25
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

Do not commit the OAuth client JSON, token, snapshots, raw Calendar inventories, SQLite database, caches, or runtime logs.

## Completion against the original plan

The implementation is approximately 65–70% complete by planned capability and 55–60% complete as an operational end-to-end rollout. Three milestones are substantially implemented, controlled writes are only partly live-validated, and operations remain open.

| Plan milestone | Status | Evidence and implementation commits | Remaining work |
|---|---|---|---|
| Foundation | Complete | Models, Pacific normalization, identity, SQLite state, and locking in `fda2365`; independent regressions in `a1549fc`; verification record in `838bd73` | None for the milestone |
| Source and Calendar reads | Partial | Calendar inventory/diff/execution foundations in `98ce6d7` and recovery fixes in `cf54140`; extraction and snapshots in `9ec3210`; live traversal fixes in `e599360`, `dc080b7`, and `0b8357c`; snapshot corrections in `8dcdda3` and `f7d8711`; redirect recovery/provenance in `5bdb20e` and `2769f5c` | LA is healthy; SF is blocked by two source rows outside Oct 5–11. Description enrichment is not implemented. Canonical redirect coverage remains limited by live rate limiting. |
| Integrated dry run | Complete | CLI orchestration in `e432711`; baseline protection in `ac5722d`; effective zero-write regression in `7901d42`; explicit reviewable identity selection in `1084cfe` | Historical redirect equivalence is supported by the pure diff API but is not passed through the normal CLI |
| Controlled writes and recovery | Partial | Calendar implementation in `98ce6d7` and `cf54140`; OAuth and the controlled ten-LA-event trial recorded in `d828863` | Live adoption, update, deletion/dismissal, ETag-conflict, interrupted-insert, and partial-failure exercises remain. Complete SF and LA separately. |
| Operations | Open | Runtime paths and intended workflow are documented | Verify refresh-token longevity and OAuth consent status; add CI; add, test, document, and install the user LaunchAgent only after full-city validation |

## Live state at handoff

Read-only inspection verified `zenmindai@gmail.com` as owner of Candidate Events, whose explicit Calendar ID and Pacific timezone are recorded in [`live-validation.md`](live-validation.md). The inventory before controlled writes contained 100 records, including protected week markers, two untagged candidate imports, cancelled records, and foreign sync-managed records.

The LA source snapshot is healthy: 756 displayed and normalized rows across all seven expected dates, with no rejected rows. Forty rows have canonical registration destinations; 716 have fallback identities and remain review items. Ten explicitly selected canonical events were inserted successfully. The same snapshot and selection then produced ten unchanged reports and no additional Calendar or SQLite writes.

The SF traversal found 1,599 source rows. Of these, 1,597 fall in the official October 5–11 window and two are under source sections for October 16 and October 28. “Out of window” means their event dates are outside the configured SF Tech Week date interval, not that they were fetched too early or too late. Both rows are retained as rejected-record evidence, and the whole SF city is unhealthy under the normalization-loss rule. SF Calendar writes and missing-source conclusions remain blocked until an explicit policy is implemented and verified.

## Known implementation gaps

1. The normal CLI calls `plan_sync` without the `resolved_links` mapping. Consequently, adoption across an older and a newer rotating Tech Week link is covered by the pure diff interface but is not wired end to end. Fix this before adopting `[Demoscene]` or `Science x AI Opening Breaskfast`.
2. Complete canonical resolution is not currently possible under observed rate limits. Only 40 of 756 LA records and 40 of the 1,597 retained SF records resolved canonically. Fallback events are withheld for review rather than inserted as probable duplicates.
3. Opportunistic source-description enrichment was planned but has not been implemented. Calendar descriptions currently contain the managed source/timing block rather than enriched host content.
4. Offline tests cover most update and recovery behavior, but dedicated end-to-end regression evidence is incomplete for interrupted insert recovery, ETag reread/recompute, and Calendar cancellation-to-dismissal handling.
5. No full-city import is complete. The ten-event LA run was a bounded production trial.
6. OAuth consent-screen Production/Testing status and refresh-token longevity must be verified before unattended scheduling.
7. No `.github` CI workflow or LaunchAgent template/install/remove procedure exists.

## Bugs and edge cases discovered after planning

The plan anticipated broad classes such as partial rendering, rotating links, health gates, and ambiguous matching. The following concrete failure modes were learned during implementation.

| Discovery | Effect and resolution | Commit evidence |
|---|---|---|
| Date-shaped event content could be mistaken for a day header | Header recognition now uses the page's structural day-header rows | `e599360`, `0b8357c` |
| JavaScript scrolling did not reliably render the full schedule | Traversal uses wheel-driven incremental rendering, readiness checks, and reload recovery | `e599360`, `dc080b7`, `0b8357c` |
| The page contained all expected day headers plus unexpected SF dates | Header completion accepts the expected set; normalization separately rejects and records out-of-window rows | `0b8357c`, `8dcdda3` |
| Snapshot serialization double-wrapped structured day evidence | Snapshot round trips preserve the original evidence shape | `8dcdda3` |
| A cityless rejection list could make an unrelated city unhealthy | Rejections carry city provenance; legacy cityless rejections fail closed | `8dcdda3` |
| Snapshot replay returned rows that had already been rejected | Replay now returns only retained normalized events while preserving rejection evidence | `8dcdda3` |
| The extraction deduplication key omitted the day | Similar occurrences on different dates no longer collapse | `8dcdda3` |
| Malformed snapshot evidence could crash or be silently coerced | Snapshot loading performs defensive type validation | `f7d8711` |
| Direct HTTP redirect resolution began returning 429s while Chromium still worked | The resolver uses bounded HTTP and Chromium transports with separate circuit breakers | `5bdb20e` |
| External destinations could return 404 for closed events but still carry stable identity | External destinations reached from Tech Week redirects remain usable; Tech Week hosts never become canonical | `5bdb20e` |
| Joining redirect results by shared URL overwrote occurrence-specific day/title/details | Redirect resolution now merges destination data positionally and preserves row provenance | `2769f5c` |
| Two identical-looking title/time rows could resolve to distinct registrations | Distinct resolved destinations remain distinct; mixed or uncertain collisions are deferred for review | `5bdb20e`, `2769f5c` |
| A failed, truncated, or health-rejected apply could replace a durable baseline | Baselines advance only for planner-approved healthy cities after complete successful execution | `ac5722d` |
| The original dry-run test planned no mutation and therefore proved little | The regression now plans a real insert and verifies zero Calendar and committed-state writes | `7901d42` |
| Global CLI options worked only before the subcommand although examples placed them after it | Runtime options are accepted in the documented positions | `e432711` |
| `--limit 10` selected arbitrary identities and reports lacked review detail | Repeatable `--identity` selection and title/time/source-rich output make a controlled apply reviewable | `1084cfe` |
| The dedicated `client_secret_*.json` name was not covered by the original ignore rule | OAuth client files matching that pattern are ignored by the committed configuration; the local file was separately restricted to owner access | `3e32fe5` |
| Routine identity-map refresh could erase a dismissal or prior successful payload | State upserts preserve dismissal and payload history | `fda2365`, verified by `a1549fc` and `838bd73` |
| Initial Calendar credential verification used an endpoint inconsistent with the intended scopes | Verification now uses calendar-list access with the configured read-only scope | `cf54140` |

## Recommended next work

1. Wire historical resolved-link mappings through the CLI and add an end-to-end adoption regression.
2. Define the SF out-of-window policy. Any accepted policy should retain explicit evidence and must not allow event filters to imply disappearance for the city.
3. Re-run SF and verify a healthy snapshot under that policy, then review/adopt the two existing untagged SF imports.
4. Decide which remaining LA review/insert candidates are useful and complete LA as a city before treating it as operationally complete.
5. Exercise update, manual deletion/dismissal, ETag conflict, interrupted insert, and partial failure against controlled Calendar fixtures or carefully selected live events.
6. Verify OAuth consent status and refresh-token longevity.
7. Add deterministic credential-free CI.
8. Add and verify the daily user LaunchAgent with absolute repository, virtual-environment, database, token, snapshot, and log paths; document unloading and removal.

Calendar writes must continue to require `sync --apply`. Use explicit identities and a mutation limit for controlled live work. Do not allow an unhealthy city to mutate Calendar entries or advance its healthy baseline.

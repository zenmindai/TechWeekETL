# Independent implementation verification

**Last updated:** 2026-09-10 20:36:44 CDT

**Authority:** [`research/project-plan.md`](project-plan.md)

**Handoff status:** [`research/project-status.md`](project-status.md)

## Current result

Independent verification against `main` at implementation baseline `d828863` ran:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

Result: **56 passed** under Python 3.13. The check was read-only and changed no repository files.

| Area | Verification status | Commit evidence |
|---|---|---|
| Foundation | Approved | `fda2365`, `a1549fc`, `838bd73` |
| Source extraction and snapshots | Offline regression coverage passes; LA live traversal verified; SF correctly fails closed | `9ec3210`, `e599360`, `dc080b7`, `0b8357c`, `8dcdda3`, `f7d8711`, `5bdb20e`, `2769f5c` |
| Calendar inventory and pure reconciliation | Offline regression coverage passes; complete live paginated inventory verified | `98ce6d7`, `cf54140` |
| Integrated dry run | Approved, including a healthy plan containing an insert with zero writes and no committed-state change | `e432711`, `ac5722d`, `7901d42`, `1084cfe` |
| Controlled writes | Ten LA inserts and identical-snapshot idempotence verified live | `d828863` |
| Operations | Not verified or implemented | No CI workflow or LaunchAgent exists |

## Acceptance evidence

- **Identity:** Tests cover recognized tracking removal, preservation of meaningful path/query values, rotating-link material-hash stability, Tech Week host rejection, collision review, and distinct resolved registrations.
- **Timing:** Tests cover explicit Pacific interpretation on a Chicago host, local midnight, exclusive all-day ends, date-only fallback, and default duration.
- **Health:** Tests cover missing days, count mismatches, unexpected dates, malformed/rejected records, snapshot evidence round trips, city-scoped rejection behavior, and the 80% healthy-baseline guard.
- **State:** Tests cover transactional rollback, read-only operation, lock overlap/release, preservation of dismissals and successful payloads, and guarded baseline persistence.
- **Calendar:** Tests cover paginated inventory, protected markers/foreign ownership, exact-link adoption, ambiguous review, deterministic IDs, field preservation, conditional execution paths, and bounded mutations.
- **Integration:** Tests cover snapshot replay, complete-plan-before-selection behavior, dry-run zero writes, explicit apply, and explicit reviewed identity selection.

## Verification still required

- Wire `resolved_links` through the CLI so adoption across different rotating Tech Week URLs works in the normal command path.
- Add focused end-to-end regressions for interrupted inserts, ETag reread/recompute, and cancellation/manual-deletion dismissal behavior.
- Resolve the SF October 16 and October 28 policy and obtain a healthy SF live run.
- Exercise adoption of the two known untagged SF events only after healthy canonical resolution.
- Complete SF and LA separately rather than treating the ten-event LA trial as a full import.
- Verify OAuth consent status and refresh-token longevity.
- Add and verify credential-free CI and user LaunchAgent operations, including absolute paths, noninteractive execution, logs, overlap locking, unloading, and removal.

## Historical foundation review

The first independent foundation review on 2026-09-09 found fail-open health checks, overly broad URL canonicalization, rotating Tech Week fallback identities, Pacific date fallback errors, and state-upsert loss of dismissal/payload data. The implementation and regressions in `fda2365` and `a1549fc` corrected those findings; `838bd73` recorded 24 passing foundation checks under Python 3.13. Later integration brought the deterministic suite to the 56 passing tests reported above.

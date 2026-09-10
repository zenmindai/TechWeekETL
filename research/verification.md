# Independent implementation verification

Authority: `research/project-plan.md` in the main worktree.

No implementation has been verified yet. Foundation `src/` and `tests/` were empty at initial inspection.

## Required evidence

- Identity: rotating Tech Week tokens resolve to one destination identity; recognized tracking removal preserves meaningful query values and paths; destination collisions between distinct occurrences require review; fingerprints exclude retrieval time and rotating direct links.
- Timing: Pacific interpretation under a Chicago host; local midnight; exclusive all-day end; DST boundary behavior; default duration and date-only fallback.
- Health: missing days, partial rendering, count mismatch, rejected normalization, or an 80% baseline collapse block affected-city writes and missing-source conclusions. Unhealthy runs retain healthy baselines.
- State: durable successful payloads and identity mappings; one lock shared across manual and scheduled commands; failure releases locks; dry runs preserve committed sync state.
- Calendar: complete paginated inventory; marker and foreign-owner protection; unique exact-link adoption; ambiguous matching becomes review; notes and user settings preserved; ETag reread/recompute; deterministic retry-safe insertion; dismissals persist; per-write recovery; bounded total mutations.
- Integration: identical snapshot replay and normal diff behavior; city filters cannot imply disappearance; default zero-write sync; explicit apply; deterministic credential-free checks.
- Operations: absolute scheduler paths, unattended authentication preflight, logging, overlap lock, and documented removal.

## Results

Pending implementation availability. No tests claimed passing.

### Foundation initial review (2026-09-09)

Executed independent unittest probes against `/private/tmp/techweek-foundation/src` using system Python 3.14.7; pinned Python 3.13 validation remains pending. Initial run: ten test methods, five passing methods, five failing methods (seven failed assertions including query subtests). Regression coverage lives in `tests/test_review_regressions.py`.

Confirmed findings sent directly to foundation builder and coordinator:

1. **P1 health fail-open:** `CityHealth('sf', 7, 1, 0, 5, 5, True).healthy` returns true despite six missing days. `displayed_count=None` also passes reconciliation.
2. **P1 identity collisions:** globally dropping `ref`, `source`, and `referrer` erases potentially meaningful registration selectors; dropping all fragments merges distinct hash-based event routes.
3. **P1 rotating fallback:** unresolved `https://www.tech-week.com/go/event/{token}` destinations receive canonical identities, violating token independence. Added an eleventh regression method after initial run.
4. **P2 Pacific date fallback:** `2026-06-02T01:00Z` with `has_time=False` becomes June 2 rather than Pacific June 1.

Passing probes: ordinary tracking removal, resolved rotating-link identity/material-hash stability, naive Pacific timed normalization, transactional rollback/read-only mutation guard with unchanged database bytes, overlapping lock rejection and release after exceptions.

Foundation integration remains withheld pending corrected regressions and its implementation test suite. Calendar/dismissal/payload recovery and source health integration are not yet reviewed.

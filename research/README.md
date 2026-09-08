# TechWeekETL Research and Planning

_Last updated: 2026-09-08_

## Project goal

Build a local macOS ETL that discovers San Francisco and Los Angeles Tech Week 2026 events from the official Tech Week calendars, normalizes event metadata, compares the source state with the Google Calendar named **Candidate Events**, and creates or updates only missing or materially changed events.

Primary event windows:

- San Francisco Tech Week: 2026-10-05 through 2026-10-11
- Los Angeles Tech Week: 2026-10-12 through 2026-10-18

The ETL should be safe to run repeatedly, avoid duplicate events, preserve manually changed availability where possible, and never automatically delete an event solely because it disappeared from the source on one run.

## Current source findings

### Official Tech Week calendars

The official Tech Week 2026 calendar states that San Francisco runs October 5-11 and Los Angeles runs October 12-18, with hundreds of events in each city. The city schedules expose event rows including start time, title, host, and in many cases neighborhood/location information.

Sources:

- https://www.tech-week.com/calendar
- https://www.tech-week.com/calendar/sf
- https://www.tech-week.com/calendar/la

The current calendar is dynamically rendered/paginated. A crawler or simple HTML request may expose only a subset of the visible schedule, so completeness must be verified rather than assumed.

### Event identity

Tech Week event rows expose event-specific links under the Tech Week domain, commonly using a `/go/event/...` path that redirects to an underlying registration/provider page.

Conclusion: use the Tech Week event URL as the canonical upstream identity whenever available. The registration URL can change independently and should be stored as secondary metadata rather than the primary identity.

Fallback identity when no event URL exists:

```text
city | local_date | local_start_time | normalized_title | normalized_host
```

Hash the canonical identity for compact storage, but retain the original source URL for auditability.

### Event detail extraction

The Tech Week listing is useful for discovery, but it may not expose a reliable end time. Do **not** infer an event end from the next listing row.

Preferred detail resolution order:

1. Structured JSON/JSON-LD from Tech Week if a stable endpoint is discovered.
2. JSON-LD `Event` data from the final registration page after resolving the Tech Week redirect.
3. Provider-specific extraction only when generic structured data is unavailable.
4. If a trustworthy end time cannot be obtained, mark the record unresolved for review rather than silently inventing one.

This avoids coupling the project to a single provider such as Partiful.

## Recommended extraction architecture

Use a layered extractor so the steady-state job is as simple and deterministic as possible.

### Layer A: plain HTTP

Use Python `httpx` or equivalent to fetch the Tech Week city pages and enumerate all event links and server-rendered pagination links.

Advantages:

- fast
- inexpensive
- easy to test with saved fixtures
- suitable for scheduled runs

### Layer B: Playwright fallback

Use Playwright/Chromium when the source is incomplete under plain HTTP. The browser layer should focus on making all event rows visible and extracting links/data, not on business logic.

Tasks for the Playwright discovery pass:

- load both city calendars
- record all `/go/event/...` links
- inspect pagination/infinite-scroll behavior
- record XHR/fetch responses whose payloads contain event data
- save a representative HTML snapshot and network notes for tests/debugging

If a stable internal JSON endpoint is discovered, move that endpoint into Layer A and keep Playwright only as a fallback/diagnostic tool.

### Layer C: registration-page resolution

Resolve each Tech Week event link with redirects enabled. Parse schema.org JSON-LD looking for objects whose `@type` includes `Event`.

Preferred normalized fields:

```text
source_url
registration_url
city
title
host
neighborhood
location
start
end
retrieved_at
```

Use `America/Los_Angeles` as the source event timezone unless the upstream structured data explicitly supplies a different timezone.

## Google Calendar loading strategy

Target calendar: **Candidate Events**.

Existing week-level all-day events such as `Tech Week, SF` and `Tech Week, LA` are intentional markers and must be preserved.

### Idempotency metadata

Google Calendar supports application-specific hidden key/value metadata through event `extendedProperties`, including private properties that belong to the specific calendar/event copy. The API also supports searching events by private extended properties.

Official documentation:

- Extended properties: https://developers.google.com/workspace/calendar/api/guides/extended-properties
- Events resource: https://developers.google.com/workspace/calendar/api/v3/reference/events

Recommended private metadata:

```json
{
  "tw_managed": "1",
  "tw_id": "<stable hash of canonical source identity>",
  "tw_source_url": "<official Tech Week event URL>",
  "tw_city": "SF|LA",
  "tw_payload_hash": "<hash of material normalized fields>"
}
```

Do not include `retrieved_at` in the material payload hash. Otherwise every run will make every event appear changed.

### Material-change hash

Hash only fields that should cause an update, for example:

```text
title
host
location
start
end
source_url
registration_url (optional; decide whether redirect-provider churn is material)
```

### Calendar lookup order

For each normalized source event:

1. Match by `tw_id` / canonical source URL.
2. If not found, attempt one conservative fallback match using city/date/start/title/host.
3. If exactly one fallback match is found, adopt that existing event by adding Tech Week metadata rather than creating a duplicate.
4. If fallback matching is ambiguous, do not guess; log it for review.

### Create policy

New imported Tech Week events should default to `transparency = transparent`, so they show as available/free and do not consume scheduling availability.

Google Calendar documents `transparent` as an event that does not block time:

- https://developers.google.com/workspace/calendar/api/v3/reference/events

Do not automatically add attendees or Google Meet links.

### Update policy

When an existing managed event changes materially:

- update source-controlled fields (title, start/end, source-derived location, managed description block, private metadata)
- do not overwrite transparency merely because the ETL normally creates transparent events
- preserve unrelated/manual fields unless the project explicitly decides they are source-owned

Google supports partial event changes using patch semantics; however the current Google Calendar Events documentation notes quota differences between `patch` and `get` + `update`, so implementation should choose deliberately rather than assuming patch is always cheaper.

Reference:

- https://developers.google.com/workspace/calendar/api/v3/reference/events

## Human-readable event description

Include an explicit managed block so ETL metadata is auditable while leaving room for manual notes.

Example:

```text
--- Tech Week sync ---
Tech Week city: San Francisco
Host: Example Company
Neighborhood: SOMA
Source: https://www.tech-week.com/go/event/...
Registration: https://...
Retrieved: 2026-09-08
--- /Tech Week sync ---
```

On updates, replace only the managed block when feasible instead of overwriting user-authored notes outside it.

## Disappearance policy

Never automatically delete an event just because it is absent from one extraction run.

Recommended safeguards:

1. Track source counts by city and compare against prior successful runs.
2. If source count falls sharply (candidate threshold: >20%), treat the extraction as unhealthy and suppress disappearance processing.
3. First missing observation: log only.
4. Missing on a second consecutive healthy run: report or annotate as `POSSIBLY REMOVED FROM SOURCE`.
5. Require manual review before deletion/cancellation behavior is introduced.

This prevents a frontend redesign, pagination bug, network failure, or anti-bot response from being interpreted as hundreds of canceled events.

## Local macOS implementation assumptions

The workstation has Python with `uv`, npm, Homebrew, browsers, Pi, and Codex available.

Recommended runtime stack:

- Python 3.12+
- `uv` for environment/dependency management
- `httpx` for HTTP
- `beautifulsoup4` + `lxml` for HTML parsing
- `playwright` for dynamic-browser fallback
- `python-dateutil` for date/time parsing
- `google-api-python-client`
- `google-auth-oauthlib`
- `google-auth-httplib2`

Keep Pi/Codex out of the unattended execution path. Use them for scraper maintenance, fixture analysis, and code changes when the upstream site changes.

## Authentication strategy

Use a Google OAuth Desktop client for local development. Store OAuth client configuration outside the repository and persist the refresh token locally with restrictive permissions.

Never commit:

```text
credentials.json
token.json
.env
browser profiles
raw secrets
```

A `.gitignore` should be added before authentication work begins.

## Proposed repository structure

```text
TechWeekETL/
  README.md
  pyproject.toml
  uv.lock
  .gitignore
  research/
    README.md
    source-discovery.md          # future network/DOM findings
  src/
    techweek_etl/
      __init__.py
      config.py
      models.py
      extract.py
      browser.py
      jsonld.py
      normalize.py
      calendar.py
      diff.py
      state.py
      cli.py
  tests/
    fixtures/
    test_extract.py
    test_jsonld.py
    test_diff.py
  snapshots/                    # ignored or sanitized fixtures only
```

## CLI design

Suggested commands/modes:

```bash
uv run techweek-etl extract
uv run techweek-etl sync --dry-run
uv run techweek-etl sync --apply
```

`extract` should produce a normalized local snapshot with **zero Google Calendar writes**.

`sync --dry-run` should report counts such as:

```text
SF source: 487
  new: 120
  changed: 4
  unchanged: 350
  unresolved: 13

LA source: 429
  new: 98
  changed: 2
  unchanged: 320
  unresolved: 9

calendar writes: 0 (dry run)
```

Only `--apply` should mutate Calendar.

## Scheduling on macOS

Prefer `launchd` over cron for a Mac that can sleep/wake. Use absolute paths because a launchd process does not inherit a normal interactive shell environment.

Suggested cadence:

- daily during early planning
- every 4-6 hours during the final 1-2 weeks before each Tech Week, if useful

Logs should be written to a predictable location such as `~/Library/Logs/techweek-etl/` and include source counts, unresolved count, creates, updates, skipped/deferred records, and failures.

## Validation and testing priorities

Before the first Calendar write:

- confirm the extracted event count appears complete for both cities
- save representative source fixtures
- verify one event with a Tech Week redirect and structured registration metadata end-to-end
- verify daylight/timezone handling
- verify payload hashes are stable across identical runs
- verify dry-run creates zero writes
- verify fallback duplicate matching is conservative
- verify existing `Tech Week, SF` and `Tech Week, LA` all-day markers are excluded from managed-child matching

Unit tests should cover:

- canonical identity generation
- title/host normalization
- JSON-LD traversal (single object, list, `@graph`)
- timezone normalization
- material hash stability
- new/changed/unchanged classification
- ambiguous fallback matches
- disappeared-source safety thresholds
- managed-description replacement without deleting manual notes

## Open research questions

1. Does the live 2026 Tech Week frontend expose a stable JSON/XHR endpoint for the complete schedule?
2. What exact pagination or infinite-scroll mechanism is used by the SF and LA pages today?
3. Are `/go/event/...` paths stable if an event changes registration providers?
4. What percentage of registration pages expose valid schema.org `Event` JSON-LD with `endDate`?
5. For unresolved end times, should the project skip Calendar creation entirely or create a separately labeled review item?
6. Should location changes be source-owned if a user manually edits an imported event's location?
7. Should the ETL use Google `patch`, or `get` + ETag-aware `update`, for the final write strategy?

## Immediate next implementation steps

1. Bootstrap the Python/uv project and `.gitignore`.
2. Add a discovery script that records all event URLs from SF and LA under plain HTTP.
3. Compare its counts against a Playwright-rendered browser pass.
4. Capture the browser network calls and identify any stable JSON schedule endpoint.
5. Implement generic JSON-LD event extraction and save a normalized source snapshot.
6. Implement Google Calendar OAuth and a read-only inventory of Candidate Events.
7. Implement deterministic diffing and `--dry-run` output.
8. Only after reviewing the dry run, implement `--apply`.
9. Add `launchd` scheduling after repeated idempotent runs succeed.

## Research conclusions

- The project should be deterministic Python, not an unattended LLM-agent workflow.
- The official Tech Week event URL should be the primary event identity.
- Browser automation is appropriate for source discovery/fallback, but should not become the business-logic layer.
- A discovered structured JSON endpoint is preferable to long-term DOM scraping.
- Google Calendar private extended properties provide a clean mechanism for managed identity and payload hashes.
- Imported Candidate Events should default to transparent/free.
- Existing transparency/manual state should not be reset on ordinary updates.
- Unknown end times should not be guessed silently.
- Source disappearance must be handled conservatively and never trigger immediate automatic deletion.
- Dry-run and source snapshots are required before enabling Calendar writes.

## Citation index

Official / primary sources used for this planning pass:

1. Tech Week 2026 official calendar: https://www.tech-week.com/calendar
2. SF Tech Week calendar: https://www.tech-week.com/calendar/sf
3. LA Tech Week calendar: https://www.tech-week.com/calendar/la
4. Google Calendar API - Extended properties: https://developers.google.com/workspace/calendar/api/guides/extended-properties
5. Google Calendar API - Events resource: https://developers.google.com/workspace/calendar/api/v3/reference/events

These sources should be rechecked during implementation because the Tech Week site is actively changing ahead of the October events.
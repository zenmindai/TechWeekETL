# TechWeekETL Project Plan — Candidate Events Discovery Sync

_Last updated: 2026-09-09_

## 1. Objective

Build a lightweight local macOS ETL that loads **all reasonably discoverable San Francisco and Los Angeles Tech Week 2026 events** into the Google Calendar named **Candidate Events**.

The calendar is a discovery and consideration tool, not an authoritative event schedule. The ETL should answer:

> What Tech Week events currently exist that I might want to attend?

The system should optimize in this order:

1. **Do not miss posted events.**
2. **Do not create duplicates.**
3. **Include a direct Tech Week source link.**
4. **Include enough descriptive content to evaluate the event.**
5. **Place the event approximately correctly on the calendar.**
6. **Preserve user-made Calendar decisions.**
7. Improve metadata precision only when it is cheap and reliable.

Target source windows:

- SF Tech Week: October 5–11, 2026
- LA Tech Week: October 12–18, 2026

Official source pages:

- https://www.tech-week.com/calendar
- https://www.tech-week.com/calendar/sf
- https://www.tech-week.com/calendar/la

> **Decision comment:** This plan deliberately prioritizes high recall over exact schedule fidelity. A useful approximate Candidate Event is better than silently omitting a real event because a duration, location, or organizer cannot be verified.

---

## 2. Scope

### In scope

For each posted Tech Week event, capture enough information to create a useful Candidate Event:

- event title;
- event date;
- start time when available;
- approximate end time when an authoritative end time is unavailable;
- direct Tech Week event URL when available;
- useful event description when reasonably obtainable;
- source city (`SF` or `LA`);
- retrieval date for auditability.

The ETL must also:

- discover the full SF and LA event sets;
- compare source state with Candidate Events;
- create missing events;
- update materially changed imported events;
- avoid duplicates;
- preserve existing all-day `Tech Week, SF` and `Tech Week, LA` week markers;
- create new imports as transparent/free;
- preserve later user changes such as marking an event busy;
- report source disappearances without automatically deleting events;
- support dry-run before Calendar mutation;
- run unattended from macOS once proven reliable.

### Explicitly out of scope for v1

The initial project does **not** need to solve:

- exact venue or address normalization;
- organizer/host prioritization;
- organizer-driven deduplication;
- authoritative RSVP state;
- attendee synchronization;
- Google Meet creation;
- exact duration for every event;
- generalized parsing for every registration provider;
- automatic cancellation or deletion;
- perfect replication of Tech Week's data model;
- AI-based event ranking or recommendation.

> **Decision comment:** Location and organizer may still be retained in raw/debug data when they are nearly free to extract, but they are not required for a successful import and should not drive material change detection.

---

## 3. Definition of success

The first production version is successful when:

1. essentially all posted SF and LA Tech Week events can be enumerated;
2. every imported event has a stable identity;
3. every imported event has a direct source link when the site provides one;
4. descriptions are included when reasonably obtainable;
5. known start times are imported;
6. unknown end times receive a documented approximate duration;
7. events with known date but no reliable time can still be represented rather than dropped;
8. newly imported events are transparent/free;
9. repeated runs do not create duplicates;
10. source title/time/description changes update the correct existing event;
11. user Calendar decisions such as busy/free state, color, reminders, and manual notes are preserved;
12. missing source events are reported but not automatically deleted;
13. incomplete scraping cannot trigger destructive behavior;
14. a dry-run mode produces the same diff as apply mode but performs zero writes;
15. the sync can run non-interactively on macOS.

---

## 4. Core event model

Keep the normalized model intentionally small:

```python
class TechWeekEvent:
    source_url: str | None
    city: str
    title: str
    date: date
    start: datetime | None
    end: datetime | None
    description: str | None
```

Additional diagnostic metadata may be carried internally without becoming part of the core Calendar contract:

```text
extraction_method
raw_source_hash
source_page
retrieved_at
approximate_time
all_day_fallback
```

### Minimum useful record

Preferred import record:

```text
title
date
start time
stable identity
```

If the page provides no usable event URL, create a conservative fallback identity using:

```text
city | date | start_time | normalized_title
```

If start time is also unavailable but the event clearly belongs to a specific date, fall back to:

```text
city | date | normalized_title
```

> **Decision comment:** Host/organizer is intentionally excluded from fallback identity. Content is the priority, and organizer text can change without representing a different event.

---

## 5. Time policy

Approximate timing is acceptable because Candidate Events is intended for discovery and planning.

### When start and end are both known

Use both authoritative values.

### When start is known but end is missing

Use a configurable default duration:

```text
DEFAULT_DURATION_MINUTES=60
```

Then:

```python
effective_end = start + timedelta(minutes=DEFAULT_DURATION_MINUTES)
```

Mark the time as approximate in the Calendar description.

### When date is known but start time is missing

Prefer preserving the event rather than dropping it.

Initial policy:

- create an all-day Candidate Event for that date;
- mark the time as unavailable/approximate in the description;
- keep the source link prominent.

> **Decision comment:** Missing end time is not an extraction failure. Missing start time is also no longer necessarily fatal if the event's date is known. This is a deliberate relaxation from the original research plan.

---

## 6. Extraction architecture

### 6.1 Playwright is the default discovery path

Use Playwright with Chromium as the expected production extractor for event enumeration.

The recent live checks showed that simple crawler/web representations can expose only a bounded first slice of the dynamically rendered schedule. Since the project prioritizes completeness, browser-rendered traversal should be the default rather than a fallback.

Playwright should:

- load each city calendar;
- wait for the page to render;
- traverse all pagination, load-more, or infinite-scroll behavior;
- enumerate every event row;
- collect every Tech Week event URL that the DOM exposes;
- capture title, day/date, start time, and visible description/content;
- track which calendar days were observed;
- optionally record relevant XHR/fetch endpoints for future optimization.

### 6.2 Plain HTTP remains a diagnostic/optimization path

Use `httpx`/HTML parsing to test whether the same data can be obtained more simply.

Plain HTTP is useful for:

- debugging;
- detecting server-rendered pagination;
- saving lightweight fixtures;
- future optimization if a stable structured endpoint is found.

It should not block the project if Playwright already provides complete results.

### 6.3 Hidden API discovery is optional

If Playwright network observation reveals a stable JSON endpoint containing the complete schedule, the project may later switch routine extraction to that endpoint.

Do not delay the initial implementation solely to reverse-engineer a cleaner API.

> **Decision comment:** The goal is a reliable local ETL, not an elegant scraper. A deterministic Playwright traversal is acceptable production behavior if it consistently finds the whole calendar.

---

## 7. Source completeness and health gate

Because partial dynamic rendering is a known failure mode, source health must be evaluated before any Calendar diff is trusted.

A city extraction is considered healthy only if all of the following are true:

1. traversal completed without an unhandled browser/navigation error;
2. all expected Tech Week dates for that city are represented, or the extractor has a documented reason a date has zero events;
3. the total event count is plausible relative to the previous healthy run;
4. the unique identity/link count is plausible;
5. there is no sudden duplicate explosion;
6. the result is not obviously limited to only the first visible page/day.

### Expected day coverage

SF should cover:

```text
2026-10-05
2026-10-06
2026-10-07
2026-10-08
2026-10-09
2026-10-10
2026-10-11
```

LA should cover:

```text
2026-10-12
2026-10-13
2026-10-14
2026-10-15
2026-10-16
2026-10-17
2026-10-18
```

### Count-collapse guard

Track the previous healthy count per city.

Candidate initial warning threshold:

```text
current_count < 80% of previous_healthy_count
```

This threshold is a secondary health check, not the sole criterion.

Example unhealthy run:

```text
SF extraction unhealthy
previous healthy count: 482
current count: 91
observed days: Oct 5 only

Calendar mutation suppressed for SF.
```

> **Decision comment:** Day coverage is more important than count alone. A first-page-only scrape can return a nontrivial number of events and still be badly incomplete.

---

## 8. Event description strategy

Content is more important than organizer or location, so description enrichment deserves limited effort.

Preferred description order:

1. description or event text visible directly on the Tech Week calendar/detail page;
2. text obtainable by opening the Tech Week event link;
3. simple generic metadata from the final linked registration page;
4. fallback to available Tech Week title/category/visible text.

Do **not** block import merely because a rich description is unavailable.

Do **not** build provider-specific parsers in the first milestone unless a major fraction of events is otherwise unusable.

### Recommended Calendar description

When timing is approximate:

```text
Tech Week Candidate Event

Approximate time: 10:00 AM–11:00 AM
Check the source for the latest schedule.

<best available event description>

Source:
https://www.tech-week.com/go/event/...

Source city: SF
Retrieved: 2026-09-09
```

When timing is authoritative:

```text
Tech Week Candidate Event

Time: 10:00 AM–12:00 PM

<best available event description>

Source:
https://www.tech-week.com/go/event/...

Source city: SF
Retrieved: 2026-09-09
```

When start time is unavailable:

```text
Tech Week Candidate Event

Time not available during extraction.
Check the source for the latest schedule.

<best available event description>

Source:
https://www.tech-week.com/go/event/...

Source city: SF
Retrieved: 2026-09-09
```

---

## 9. Calendar identity and deduplication

### Primary identity

Use the official Tech Week event URL whenever available.

Create a compact deterministic ID:

```text
tw_id = SHA256(canonical_source_url)
```

### Fallback identity

When no URL is available:

```text
city | date | start_time | normalized_title
```

If start time is unavailable:

```text
city | date | normalized_title
```

Fallback matching must remain conservative. If multiple existing events plausibly match, report ambiguity instead of guessing.

### Calendar private metadata

Recommended Google Calendar private extended properties:

```json
{
  "tw_managed": "1",
  "tw_id": "<stable identity hash>",
  "tw_source_url": "<official Tech Week URL when available>",
  "tw_city": "SF",
  "tw_payload_hash": "<material change hash>",
  "tw_schema_version": "1"
}
```

This supports safe repeated synchronization without exposing implementation metadata in the human-readable event title.

---

## 10. Material change detection

Only changes that affect usefulness in Candidate Events should trigger Calendar updates.

Initial material fields:

```text
title
date
start time
effective end time
description
source URL
```

Do not include:

```text
retrieval date
organizer/host
venue/location
registration provider
```

in the material payload hash.

If the only change is the retrieval date, perform no Calendar write.

> **Decision comment:** This keeps scheduled runs quiet and avoids unnecessary writes when nonessential metadata changes.

---

## 11. Calendar ownership model

### Source-owned fields

The ETL may update:

```text
title
start/end
all-day vs timed representation
managed description block
source URL/private identity metadata
```

### User-owned fields

The ETL should preserve:

```text
transparency after initial creation
color
manual notes outside the managed description block
reminders
```

### Never managed in v1

```text
attendees
Google Meet/conference data
user RSVP state
```

### New-event defaults

New Tech Week Candidate Events should be:

```text
transparency = transparent
```

with:

```text
no attendees
no Google Meet
```

If the user later marks an event busy, the ETL should not reset it to transparent on the next sync.

---

## 12. Existing Calendar records

Target calendar:

```text
Candidate Events
```

Preserve the existing all-day week markers:

```text
Tech Week, SF
Tech Week, LA
```

These are not event-level Tech Week imports and must not be adopted, modified, or deleted by child-event synchronization logic.

Other existing Candidate Events should only be adopted when a conservative fallback match identifies exactly one plausible corresponding Tech Week event.

---

## 13. Synchronization classifications

Every normalized source event should become one of:

### NEW

No matching managed or safely adoptable Candidate Event exists.

Action:

```text
create event
```

### CHANGED

Matching managed event exists but material payload changed.

Action:

```text
update source-owned fields only
```

### UNCHANGED

Matching managed event has the same material payload.

Action:

```text
no write
```

### ADOPT

No managed identity exists, but exactly one conservative existing Candidate Event match exists.

Action:

```text
attach Tech Week identity/managed metadata and update only clearly source-owned fields
```

### AMBIGUOUS

More than one plausible existing Candidate Event match exists.

Action:

```text
report for review; do not guess
```

### MISSING_FROM_SOURCE

A previously managed event is absent from a healthy current source extraction.

Action:

```text
report only
```

No automatic delete, cancel, or title modification in v1.

---

## 14. Project repository structure

Keep the initial codebase compact:

```text
TechWeekETL/
├── README.md
├── pyproject.toml
├── uv.lock
├── .gitignore
│
├── research/
│   ├── README.md
│   ├── project-plan.md
│   └── source-discovery.md
│
├── src/
│   └── techweek_etl/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── extract.py
│       ├── browser.py
│       ├── normalize.py
│       ├── calendar.py
│       ├── diff.py
│       └── state.py
│
├── tests/
│   ├── fixtures/
│   ├── test_extract.py
│   ├── test_identity.py
│   └── test_diff.py
│
└── snapshots/
```

Split modules further only when actual implementation complexity justifies it.

---

## 15. Local runtime stack

Assume the macOS development machine has:

- browsers;
- Python with `uv`;
- npm;
- Homebrew;
- Pi;
- Codex.

Recommended runtime dependencies:

```text
Python 3.12+
uv
playwright
httpx
beautifulsoup4
lxml
python-dateutil
google-api-python-client
google-auth-oauthlib
pytest
```

Pi and Codex are development/maintenance tools, not unattended runtime dependencies.

---

## 16. Phase 1 — Bootstrap

Create:

```text
pyproject.toml
.gitignore
package skeleton
CLI entrypoint
test runner
```

At minimum `.gitignore` should exclude:

```text
.env
credentials.json
token.json
.venv/
__pycache__/
.pytest_cache/
state.json
*.log
snapshots/*.json
snapshots/*.html
snapshots/*.har
```

Expected commands:

```bash
uv sync
uv run techweek-etl --help
uv run pytest
```

No Google Calendar write functionality is required in this phase.

---

## 17. Phase 2 — Complete browser discovery

Implement:

```bash
uv run techweek-etl discover
```

The command should run Playwright against both calendars and report:

```text
SF
  observed days: 7/7
  event rows: 482
  unique source URLs: 479
  rows without source URL: 3

LA
  observed days: 7/7
  event rows: 426
  unique source URLs: 424
  rows without source URL: 2
```

Also run a plain HTTP diagnostic and report its result, but HTTP completeness is not required.

Example:

```text
HTTP SF rows: 48
Browser SF rows: 482

HTTP LA rows: 52
Browser LA rows: 426
```

### Deliverable

Create/update:

```text
research/source-discovery.md
```

with actual observed pagination/render/network behavior.

### Review gate 1

Before moving on, answer:

> Can Playwright reproducibly enumerate essentially every posted event across all seven days for both cities?

If no, fix discovery before implementing Calendar writes.

---

## 18. Phase 3 — Normalized source snapshot

Implement:

```bash
uv run techweek-etl extract
```

Produce a normalized snapshot, for example:

```text
snapshots/latest.json
```

Report:

```text
SF
  events: 482
  timed: 475
  approximate-end: 121
  all-day fallback: 7
  descriptions available: 409

LA
  events: 426
  timed: 420
  approximate-end: 98
  all-day fallback: 6
  descriptions available: 361
```

### Snapshot purposes

Use source snapshots for:

- debugging;
- local development;
- repeatable diff tests;
- investigating site changes;
- avoiding unnecessary repeated source requests during Calendar development.

### Review gate 2

Sample events across multiple days and verify that each Candidate Event record is useful enough to decide whether to investigate/attend.

Focus review on:

- title;
- date;
- approximate placement;
- direct source URL;
- description.

Do not reject the milestone because location or organizer is incomplete.

---

## 19. Phase 4 — Read-only Candidate Events inventory

Implement Google OAuth Desktop authentication and:

```bash
uv run techweek-etl calendar-inventory
```

Read Candidate Events for October 5–18, 2026 and classify:

```text
Tech Week managed events
Tech Week week markers
other Candidate Events
```

Verify the correct calendar ID and account before write support exists.

### Review gate 3

Confirm:

- correct Candidate Events calendar;
- existing SF/LA week markers detected and excluded;
- current event inventory understood;
- zero writes performed.

---

## 20. Phase 5 — Diff and dry run

Implement:

```bash
uv run techweek-etl sync --dry-run
```

Example output:

```text
TechWeekETL DRY RUN

Source health
SF: healthy, 7/7 days, 482 events
LA: healthy, 7/7 days, 426 events

SF
new: 470
changed: 2
unchanged: 10
adopt: 0
ambiguous: 0

LA
new: 420
changed: 1
unchanged: 5
adopt: 0
ambiguous: 0

Missing previously imported: 3

Creates proposed: 890
Updates proposed: 3
Writes performed: 0
```

Dry-run must use the exact same extraction, normalization, identity, and diff logic as apply mode.

Only the mutation step changes.

### Review gate 4

Review proposed Calendar writes before enabling `--apply`.

Look specifically for:

- duplicate-looking titles/times;
- unexpected all-day fallbacks;
- malformed descriptions;
- missing source links;
- obviously wrong dates/timezones.

---

## 21. Phase 6 — Controlled write test

Do not begin with a full import.

Support one or both of:

```bash
uv run techweek-etl sync --apply --limit 10
```

and:

```bash
uv run techweek-etl sync --apply --source-url <event-url>
```

Validate a small batch in Candidate Events.

Then rerun the same exact source set.

Expected result:

```text
new: 0
changed: 0
unchanged: 10
writes: 0
```

This is the primary idempotency test.

### Review gate 5

Confirm:

- no duplicates;
- transparent/free default;
- no attendees;
- no Meet links;
- source links readable;
- approximate times clearly indicated;
- rerun performs zero writes.

---

## 22. Phase 7 — Full import

Import in two controlled stages:

```text
SF dry run
SF apply
SF rerun

LA dry run
LA apply
LA rerun
```

The immediate rerun should produce essentially zero writes unless the source changed during the import window.

This sequence makes any extraction or Calendar issue easier to isolate.

---

## 23. Phase 8 — Scheduled sync

Once repeated manual syncs are reliably idempotent, schedule with macOS `launchd`.

Initial cadence:

```text
once daily
```

Closer to Tech Week, optionally increase to:

```text
every 4–6 hours
```

Use absolute executable/project paths because `launchd` does not inherit a normal interactive shell environment.

Suggested log location:

```text
~/Library/Logs/techweek-etl/
```

Scheduled command:

```bash
uv run techweek-etl sync --apply
```

---

## 24. Run reporting

Every run should print and log a concise operational summary.

Example:

```text
TechWeekETL

Source health
SF: healthy, 7/7 days, 482 events
LA: healthy, 7/7 days, 426 events

Calendar
created: 6
updated: 3
unchanged: 894

Timing quality
approximate-duration events: 112
all-day fallback events: 4

Source warnings
missing from source: 2
ambiguous matches: 0

status: SUCCESS
```

Track at minimum:

```text
run ID
started_at
completed_at
source extraction method
per-city observed dates
per-city event count
unique source URL count
approximate-duration count
all-day fallback count
description coverage
new/changed/unchanged/adopt/ambiguous counts
missing-from-source count
Calendar creates
Calendar updates
errors
source health status
```

---

## 25. Missing-event policy

If a previously managed event is absent from a **healthy** current source extraction:

```text
report MISSING_FROM_SOURCE
```

Do not automatically:

```text
delete
cancel
rename
mark canceled
change availability
```

If the extraction itself is unhealthy, suppress missing-event conclusions entirely for that city.

> **Decision comment:** The Calendar is a candidate-event memory aid. Keeping a stale event temporarily is less harmful than deleting useful history because a dynamic scraper failed.

---

## 26. Error-handling policy

Failures should bias toward preserving existing Calendar state.

### Browser extraction failure

If SF extraction fails health checks:

- perform no SF Calendar writes;
- do not report hundreds of SF events as disappeared;
- LA may continue only if its extraction is independently healthy.

### Description enrichment failure

Still import/update the event if its core identity/title/date/time information is usable.

Description enrichment is best effort.

### Missing end time

Use the configured default duration.

### Missing start time

Use the all-day fallback if the date is known.

### Google authentication failure

Abort Calendar mutation.

### Mid-run Google write failure

Log successful writes and failed writes. The next idempotent run should safely resume rather than recreate successful events.

---

## 27. Testing priorities

Keep tests focused on high-value failure modes.

### Identity

```text
same source URL -> same tw_id
different source URL -> different tw_id
same fallback title/date/time -> same fallback identity
```

### Approximate time

```text
known start + no end -> start + 60 minutes
```

### Missing start

```text
known date + missing time -> all-day fallback
```

### Diff

Cover:

```text
new
unchanged
changed title
changed time
changed description
adopt
ambiguous
missing from source
```

### User-state preservation

Verify updates do not reset:

```text
transparency
color
manual notes
reminders
```

### Completeness guard

Simulate:

```text
previous healthy: 480 events, 7 days
current: 80 events, 1 day
```

Expected:

```text
source unhealthy
Calendar mutation suppressed
missing-event reporting suppressed
```

### Description ownership

If using a managed description block, verify user notes outside it survive updates.

---

## 28. Authentication and security

Use a Google OAuth Desktop client for local execution.

Never commit:

```text
credentials.json
token.json
.env
browser profiles/cookies
raw secrets
```

Prefer minimum necessary Google Calendar OAuth scope.

Public Tech Week source extraction should not require an authenticated persistent browser profile.

---

## 29. Development commands

Target final CLI:

### Discover source

```bash
uv run techweek-etl discover
```

### Extract snapshot

```bash
uv run techweek-etl extract
```

### Inspect Candidate Events

```bash
uv run techweek-etl calendar-inventory
```

### Compare without writes

```bash
uv run techweek-etl sync --dry-run
```

### Apply

```bash
uv run techweek-etl sync --apply
```

### Single city

```bash
uv run techweek-etl sync --dry-run --city SF
```

### Controlled test batch

```bash
uv run techweek-etl sync --apply --limit 10
```

### Single source event

```bash
uv run techweek-etl sync --dry-run --source-url <url>
```

Optional debugging flag:

```text
--save-debug-artifacts
```

---

## 30. Recommended implementation commits

Use small, reviewable commits:

```text
docs: add rescoped Candidate Events ETL project plan

chore: bootstrap uv Python project and tooling

feat: add Playwright Tech Week event discovery

docs: record live source discovery behavior

feat: normalize Tech Week Candidate Event records

test: cover identity and approximate time behavior

feat: add read-only Candidate Events inventory

feat: add deterministic Calendar diff and dry run

test: add completeness and duplicate safeguards

feat: add controlled Candidate Event creation

feat: update managed Candidate Events idempotently

feat: add source health and missing-event reporting

feat: add macOS launchd scheduling support

docs: add operations and troubleshooting guide
```

---

## 31. Review checkpoints

### Checkpoint 1 — Browser completeness

Question:

> Can the local Playwright extractor enumerate essentially all posted events and all expected days for both cities?

### Checkpoint 2 — Candidate usefulness

Question:

> Does the normalized snapshot contain enough title, approximate timing, source link, and descriptive content to decide which events are worth considering?

### Checkpoint 3 — Calendar dry run

Question:

> Would the proposed writes populate Candidate Events without obvious duplicate or date/time problems?

### Checkpoint 4 — Idempotent small batch

Question:

> Does importing 5–10 events and rerunning produce zero duplicate writes?

### Checkpoint 5 — Full import

Question:

> Are SF and LA now complete enough in Candidate Events to browse and prioritize?

### Checkpoint 6 — Automation

Question:

> Are repeated syncs reliable and quiet enough to run unattended?

---

## 32. First implementation milestone

The first development milestone should stop before Google Calendar mutation.

Scope:

1. bootstrap the `uv` project;
2. add `.gitignore` and test tooling;
3. implement Playwright discovery for SF and LA;
4. add plain HTTP extraction only as a diagnostic;
5. enumerate every unique event row/source link;
6. validate all seven dates for each city;
7. extract title, date, start time, source URL, and available description;
8. apply approximate one-hour end times when needed in normalization;
9. use all-day fallback for known-date/no-time records;
10. generate a normalized JSON snapshot;
11. document actual source traversal and completeness behavior.

Milestone success question:

> **How many events are currently posted for SF and LA, and can we create a useful Candidate Event record for essentially all of them?**

No Google Calendar write code is necessary until this question is answered confidently.

---

## 33. Deferred enhancements

Do not include these in v1 unless implementation evidence shows they are necessary:

- registration-provider-specific adapters;
- exact location normalization;
- organizer normalization;
- semantic event categories;
- AI relevance scoring;
- automated cleanup/deletion;
- notifications;
- hidden API reverse engineering when Playwright already works reliably.

Potential later features:

```text
topic tagging
AI/founder/investor scoring
shortlist generation
conflict clustering
travel-time planning
calendar views filtered by interest
```

---

## 34. Final project principles

The implementation should repeatedly favor these principles:

### Completeness over precision

A roughly timed real event is more useful than a perfectly normalized event that was never imported.

### Idempotency over cleverness

Every scheduled run should be safe to rerun.

### Source link over duplicated metadata

The Calendar entry should make it easy to jump to the current authoritative event page.

### Content over organizer/location

The event's subject matter determines whether it belongs in Candidate Events.

### Non-destructive behavior

When uncertain, preserve existing Calendar data and report the problem.

### Playwright is acceptable

A deterministic browser traversal is a valid production extractor when dynamic rendering is the simplest reliable path to completeness.

### Optimize later

If a stable JSON endpoint emerges, it can replace Playwright behind the same normalized event interface without redesigning the Calendar sync layer.

---

## References

Primary sources and technical references supporting this plan:

1. Tech Week official calendar: https://www.tech-week.com/calendar
2. SF Tech Week calendar: https://www.tech-week.com/calendar/sf
3. LA Tech Week calendar: https://www.tech-week.com/calendar/la
4. Google Calendar extended properties: https://developers.google.com/workspace/calendar/api/guides/extended-properties
5. Google Calendar Events resource: https://developers.google.com/workspace/calendar/api/v3/reference/events

The Tech Week source behavior should be revalidated during implementation because the calendar is actively changing ahead of the October 2026 events.

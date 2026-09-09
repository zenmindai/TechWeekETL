# TechWeekETL

Local macOS ETL for discovering **SF Tech Week** and **LA Tech Week 2026** events and loading them into a Google Calendar named **Candidate Events**.

> **Project status:** planning / pre-implementation as of **2026-09-09**. The research and project plan are committed; the Python package, CLI, Playwright extractor, and Google Calendar integration are the next implementation milestones.

## Why this project exists

`Candidate Events` is a discovery calendar: it holds events that may be worth attending, not a perfectly authoritative copy of every organizer's schedule.

The ETL is therefore intentionally optimized for **completeness over exact schedule fidelity**. A roughly timed real event with a direct source link is more useful than omitting an event because its exact duration, venue, or organizer cannot be normalized.

The project should answer:

> **What SF and LA Tech Week events currently exist that might be worth considering?**

### Priority order

1. Do not miss posted events.
2. Do not create duplicates.
3. Include a direct Tech Week source link.
4. Include enough descriptive content to evaluate the event.
5. Place the event approximately correctly on the calendar.
6. Preserve user-made Calendar decisions.
7. Improve metadata precision only when it is cheap and reliable.

## Target event weeks

- **SF Tech Week:** October 5–11, 2026
- **LA Tech Week:** October 12–18, 2026

Official source pages:

- https://www.tech-week.com/calendar
- https://www.tech-week.com/calendar/sf
- https://www.tech-week.com/calendar/la

## What gets imported

A useful Candidate Event should contain, when available:

- title;
- event date;
- start time;
- approximate or authoritative end time;
- direct Tech Week event URL;
- useful event description;
- source city (`SF` or `LA`);
- retrieval date.

The ETL does **not** require exact venue/location or normalized organizer/host information for v1.

### Approximate time policy

If Tech Week exposes a start time but no reliable end time, the current plan is to use a configurable default duration:

```text
DEFAULT_DURATION_MINUTES=60
```

If the date is known but the start time is unavailable, the event may be represented as an all-day Candidate Event rather than silently dropped.

Approximate timing should be clearly labeled in the Calendar description and the direct source link should remain prominent so the latest schedule can be checked quickly.

## High-level architecture

```text
Tech Week SF / LA
        |
        v
Playwright browser discovery
        |
        +--> optional HTTP/network diagnostics
        |
        v
Normalize Candidate Event records
        |
        v
Source completeness / health gate
        |
        v
Compare with Google Candidate Events
        |
   +----+---------+-------------+
   |              |             |
  NEW          CHANGED      UNCHANGED
   |              |             |
 create         update         no-op
   |
   v
transparent/free Candidate Event
```

### Why Playwright is the default extractor

Recent live checks showed that non-browser representations of the Tech Week calendar can expose only an initial dynamically loaded slice of the schedule. Since completeness is the primary goal, the project plan treats **Playwright/Chromium as the default discovery method**.

Plain HTTP remains useful for diagnostics, fixtures, and future optimization. If a stable structured JSON endpoint is discovered, it can later replace browser extraction behind the same normalized event interface.

## Completeness and safety

A successful HTTP response is **not** enough to consider an extraction healthy.

A city extraction should verify:

- browser traversal completed successfully;
- all expected event dates were observed, or zero-event dates are explicitly understood;
- event count is plausible relative to the previous healthy run;
- unique identity/source-link count is plausible;
- no duplicate explosion occurred;
- the result is not merely the first visible page/day.

An unhealthy source extraction should suppress Calendar mutations for the affected city.

The current candidate count-collapse warning threshold is:

```text
current_count < 80% of previous_healthy_count
```

Day coverage is considered more important than count alone.

## Google Calendar behavior

Target calendar:

```text
Candidate Events
```

Existing week-level markers must remain untouched:

```text
Tech Week, SF
Tech Week, LA
```

### New events

New imported events should default to:

```text
transparency = transparent
```

They should not add attendees or Google Meet links.

### User-owned Calendar state

After creation, the ETL should preserve user decisions such as:

- busy/free state;
- color;
- reminders;
- manual notes outside the ETL-managed description block.

For example, if an event is initially imported as transparent and later manually marked busy, a future sync should not reset it to transparent.

### Missing source events

If an imported event disappears from a **healthy** current Tech Week extraction, v1 should report it as `MISSING_FROM_SOURCE` but should not automatically delete, cancel, rename, or alter it.

## Identity and deduplication

Preferred identity:

```text
official Tech Week event URL
```

A compact stable ID can be derived as:

```text
tw_id = SHA256(canonical_source_url)
```

When no source URL is available, use a conservative fallback identity:

```text
city | date | start_time | normalized_title
```

or, when start time is unavailable:

```text
city | date | normalized_title
```

Recommended Google Calendar private extended properties:

```json
{
  "tw_managed": "1",
  "tw_id": "<stable identity hash>",
  "tw_source_url": "<Tech Week URL when available>",
  "tw_city": "SF",
  "tw_payload_hash": "<material change hash>",
  "tw_schema_version": "1"
}
```

Material change detection should focus on:

```text
title
date
start time
effective end time
description
source URL
```

Organizer, venue, retrieval timestamp, and registration provider should not independently trigger Calendar rewrites in v1.

## Repository structure

Current and planned layout:

```text
TechWeekETL/
├── README.md                     # project entry point (this file)
├── pyproject.toml                # planned Python/uv project metadata
├── uv.lock                       # planned locked dependencies
├── .gitignore                    # planned local secrets/runtime exclusions
│
├── research/
│   ├── README.md                 # original research and technical findings
│   ├── project-plan.md           # authoritative rescoped implementation plan
│   └── source-discovery.md       # planned live Playwright/source findings
│
├── src/
│   └── techweek_etl/             # planned application package
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
└── snapshots/                    # local/debug source snapshots; normally ignored
```

### Where to start reading

- [`research/project-plan.md`](research/project-plan.md) — **authoritative current implementation plan** and project decisions.
- [`research/README.md`](research/README.md) — earlier research, source findings, Google Calendar design notes, and background conclusions.
- `research/source-discovery.md` — will capture actual local Playwright behavior, event counts, pagination/infinite-scroll behavior, and any useful network endpoints discovered during implementation.

The original research document is intentionally retained as historical context; where it conflicts with `research/project-plan.md`, the rescoped project plan takes precedence.

## Planned local environment

The intended runtime is a local macOS workstation with:

- Python 3.12+;
- [`uv`](https://docs.astral.sh/uv/) for Python environments and dependency management;
- Chromium/Chrome-compatible browser;
- Playwright;
- Google OAuth Desktop credentials for Calendar access.

Development can also use locally available tools such as Homebrew, npm, Pi, or Codex, but none of those should be required by the unattended production sync unless the implementation later proves otherwise.

### Planned Python dependencies

Expected runtime dependencies:

```text
playwright
httpx
beautifulsoup4
lxml
python-dateutil
google-api-python-client
google-auth-oauthlib
```

Expected development/test dependency:

```text
pytest
```

The exact dependency list should be treated as provisional until `pyproject.toml` and `uv.lock` are committed.

## Installation

> The package has **not yet been bootstrapped**, so the commands below describe the intended setup after the first implementation milestone lands.

Expected workflow:

```bash
git clone https://github.com/zenmindai/TechWeekETL.git
cd TechWeekETL

uv sync
uv run playwright install chromium
```

Then verify the CLI and tests:

```bash
uv run techweek-etl --help
uv run pytest
```

If the repository is still in planning-only state, `uv sync` will not work until `pyproject.toml` has been added.

## Configuration and environment

Configuration should use environment variables or a local `.env` file that is **not committed**.

Likely configuration values:

```bash
TECHWEEK_SF_URL="https://www.tech-week.com/calendar/sf"
TECHWEEK_LA_URL="https://www.tech-week.com/calendar/la"

GOOGLE_CALENDAR_ID="<Candidate Events calendar id>"
GOOGLE_CREDENTIALS="./credentials.json"
GOOGLE_TOKEN="./token.json"

DEFAULT_DURATION_MINUTES="60"
```

Variable names may change during implementation; the committed `config.py` / sample environment file should become authoritative once they exist.

## Google OAuth setup

The planned Calendar integration uses a Google OAuth **Desktop application**.

Local secret material is expected to include:

```text
credentials.json
token.json
```

These files must never be committed.

The project should use the minimum Google Calendar OAuth scope needed for the read/write behavior it implements.

## Secrets and files that must stay out of Git

At minimum, `.gitignore` should exclude:

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
browser profiles/cookies
```

Sanitized source fixtures needed for deterministic tests may be committed under `tests/fixtures/`.

## Planned CLI

The intended command surface is:

### Discover source completeness

```bash
uv run techweek-etl discover
```

Expected responsibilities:

- run Playwright against SF and LA;
- report observed days;
- count event rows and unique event links;
- compare optional HTTP diagnostics;
- report source health.

### Extract normalized source snapshot

```bash
uv run techweek-etl extract
```

### Inventory Candidate Events without writes

```bash
uv run techweek-etl calendar-inventory
```

### Compare source and Calendar without mutation

```bash
uv run techweek-etl sync --dry-run
```

### Apply approved sync behavior

```bash
uv run techweek-etl sync --apply
```

Useful controlled modes are planned:

```bash
uv run techweek-etl sync --dry-run --city SF
uv run techweek-etl sync --apply --limit 10
uv run techweek-etl sync --dry-run --source-url <url>
```

## Development workflow

Implementation should proceed through explicit review gates rather than immediately enabling hundreds of Calendar writes.

### Milestone 1 — source discovery

- bootstrap the `uv` project;
- implement Playwright extraction;
- enumerate SF and LA across all expected dates;
- save normalized source snapshots;
- document actual source behavior in `research/source-discovery.md`.

No Google Calendar write code is required for this milestone.

### Milestone 2 — read-only Calendar integration

- authenticate to Google Calendar;
- inventory Candidate Events;
- identify existing Tech Week markers and candidate matches;
- implement deterministic identity and diff logic;
- implement `--dry-run`.

### Milestone 3 — controlled writes

- import one event or a small batch;
- rerun and verify zero duplicates/zero unnecessary writes;
- confirm transparent/free defaults and preservation of user state.

### Milestone 4 — full sync

- SF dry run → apply → rerun;
- LA dry run → apply → rerun;
- verify idempotency.

### Milestone 5 — unattended operation

Once repeated manual runs are reliable, schedule the sync with macOS `launchd`.

Initial cadence is expected to be daily, optionally increasing to every 4–6 hours closer to Tech Week.

## Testing priorities

The project should focus tests on high-value failure modes rather than maximizing test count.

Important cases include:

- stable identity generation;
- approximate one-hour end times;
- all-day fallback when start time is missing;
- new / changed / unchanged / ambiguous / missing classifications;
- duplicate prevention;
- preservation of user-owned Calendar state;
- preservation of manual description notes;
- source count/day-coverage collapse causing mutation suppression.

A key safety test is:

```text
previous healthy: ~480 events across 7 days
current extraction: ~80 events across 1 day
```

Expected result:

```text
source unhealthy
Calendar mutation suppressed
missing-event reporting suppressed
```

## Scheduling on macOS

The planned scheduler is `launchd`, not cron, because the workstation may sleep/wake and `launchd` is the native macOS scheduling mechanism.

Scheduled execution should use absolute paths and write structured logs somewhere predictable, for example:

```text
~/Library/Logs/techweek-etl/
```

Expected scheduled command:

```bash
uv run techweek-etl sync --apply
```

## Operational principles

### Completeness over precision

A roughly timed real event is more useful than a perfectly normalized event that never appears in Candidate Events.

### Idempotency over cleverness

Every sync should be safe to rerun.

### Source link over duplicated metadata

The Calendar event should make the authoritative/current source easy to open.

### Content over organizer/location

Event subject matter is more important to this project's use case than venue or host metadata.

### Non-destructive behavior

When extraction is uncertain, preserve existing Calendar data and report the problem.

### Browser extraction is acceptable

A deterministic Playwright traversal is an acceptable production extractor if it is the simplest reliable way to obtain the complete dynamic schedule.

### Optimize later

If a stable structured endpoint is discovered, replace the extraction implementation without redesigning normalization or Calendar synchronization.

## Current roadmap

The next implementation task is the first milestone from the project plan:

1. bootstrap the Python/`uv` project;
2. add `.gitignore` and test tooling;
3. implement Playwright discovery for SF and LA;
4. validate all seven dates for each city;
5. extract title, date, start time, source link, and available description;
6. generate a normalized JSON snapshot;
7. document actual source-discovery behavior.

The milestone should answer:

> **How many events are currently posted for SF and LA, and can we create a useful Candidate Event record for essentially all of them?**

## Documentation

Detailed planning and research live under [`research/`](research/):

- [`research/project-plan.md`](research/project-plan.md) — current authoritative plan.
- [`research/README.md`](research/README.md) — initial research and background architecture.

Primary external references used in planning:

- Tech Week official calendar: https://www.tech-week.com/calendar
- SF Tech Week: https://www.tech-week.com/calendar/sf
- LA Tech Week: https://www.tech-week.com/calendar/la
- Google Calendar extended properties: https://developers.google.com/workspace/calendar/api/guides/extended-properties
- Google Calendar Events resource: https://developers.google.com/workspace/calendar/api/v3/reference/events

Because the Tech Week calendar is actively changing ahead of the October 2026 events, source behavior should be revalidated during implementation rather than treated as static.

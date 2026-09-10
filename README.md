# TechWeekETL

Local macOS ETL for discovering SF and LA Tech Week 2026 events and importing useful candidates into Google Calendar. Completeness, duplicate prevention, source links, approximate Pacific scheduling, and preservation of user decisions take priority.

Implementation is in progress. The authoritative [project plan](research/project-plan.md) defines acceptance gates; [original research](research/README.md) is historical and may contain superseded assumptions.

## Identity and safety

Tech Week `/go/event/...` links rotate. Identity v1 uses **year + city + canonical registration destination**, removing recognized tracking parameters only. Direct Tech Week links remain available in descriptions but their rotating tokens and retrieval timestamps do not trigger updates. Unresolved identities and ambiguous rematches are held for review.

Each city must complete all seven dates, reconcile displayed counts, account for zero-event dates, validate normalized records, and retain at least 80% of its previous healthy count. An unhealthy city cannot trigger Calendar writes or missing-source conclusions, or replace its healthy baseline.

SF runs October 5–11, 2026; LA runs October 12–18. Dates and times use `America/Los_Angeles`, including on a Chicago host. Missing duration defaults to 60 minutes; known dates without a time use all-day events with exclusive end dates.

Calendar sync defaults to dry-run. Managed events use deterministic Google IDs. Adoption requires a unique exact source-link or resolved-destination match. Week markers and foreign-managed events are protected. Updates preserve manual notes outside the managed block, busy/free settings, reminders, color, and unrelated metadata. Confirmed manual deletions remain dismissed; source disappearances are report-only.

## Development workflow

Use Python 3.13, a repository-local `.venv`, an ignored local uv cache, and committed `uv.lock`. Install the Chromium revision matching the locked Playwright package. Offline CI needs no Google credentials.

The coordinator establishes shared interfaces and integrates verified changes. At most two `gpt-5.6-terra` build agents and one `gpt-6-astra` verifier (low reasoning effort) work in isolated Git worktrees with explicit ownership. Terra implements fixes; Astra independently verifies the revisions. No nested agents.

Milestones: foundation → source extraction and Calendar reads → integrated snapshot dry-run → controlled writes and recovery → operations. Live validation starts with extraction and snapshots, then adoption and at most ten new candidates, followed by an identical-snapshot rerun. Full SF and LA imports run separately. Enable scheduling only after successful idempotent runs and OAuth longevity verification.

## Runtime configuration

Credentials and durable SQLite state belong in `~/Library/Application Support/techweek-etl/`. Raw snapshots, caches, OAuth files, and runtime logs are ignored. Google Calendar access uses an explicit calendar ID and Desktop OAuth through an explicit `auth` command; unattended sync must never open an authentication browser.

Target account: `zenmindai@gmail.com`. Target calendar: `Candidate Events`, with Pacific timezone. Setup must verify this identity instead of choosing a calendar by display name alone.

The CLI provides `doctor`, `auth`, `discover`, `extract`, `calendar-inventory`, and `sync`. Sync supports `--snapshot FILE`, defaults to dry-run, and requires `--apply` for writes. `--limit` caps all mutations, including adoption and updates. Source/event filters never imply city-wide disappearance.

## Commands

All commands accept explicit `--app-dir`, `--database`, `--lock`, `--token`, `--client`, `--account`, and `--calendar-id` paths/identifiers when the defaults are unsuitable. The default app directory is `~/Library/Application Support/techweek-etl/`.

```sh
uv run techweek-etl doctor
uv run techweek-etl auth --client /secure/client_secret.json --token /secure/token.json
uv run techweek-etl discover --city sf
uv run techweek-etl extract --city sf --output /secure/sf-snapshot.json
uv run techweek-etl calendar-inventory --output /secure/calendar.json
uv run techweek-etl sync --snapshot /secure/sf-snapshot.json          # dry-run
uv run techweek-etl sync --snapshot /secure/sf-snapshot.json --apply --limit 10
```

`auth` is the only command that opens a browser. Every command takes the same application lock. A saved snapshot is replayed through the same reconciliation path as a live extraction.

Network access, Playwright browser launches, macOS Keychain access through `gog`, and writes outside the workspace may require elevated execution. Deterministic tests and snapshot replay can use workspace-local paths. A daily LaunchAgent must use absolute paths and the installed virtual-environment executable.

Installation and command examples will be finalized with the implemented CLI and operational checks. No production sync or scheduler has been enabled yet.

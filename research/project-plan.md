# TechWeekETL development plan with Terra build agents and Astra verification

## 1. Plan persistence and agent workflow

First execution step: save this revised plan as Markdown in `research/project-plan.md`. Align the root README with its corrected identity strategy and development workflow; preserve `research/README.md` as historical research.

| Role | Model | Responsibility |
|---|---|---|
| Coordinator | Parent agent | Own interfaces, assign bounded tasks, integrate changes, and report progress |
| Build agents | `gpt-5.6-terra` | Implement application code, fixtures, and relevant unit tests |
| Verification agent | `gpt-6-astra`, reasoning effort `low` | Independently review changes, run checks, exercise failure scenarios, and identify missing regression coverage |

“Astra light” means Astra with low reasoning effort. Run at most two Terra agents and one Astra verification agent alongside the coordinator. Give each agent an isolated Git worktree, explicit file ownership, acceptance criteria, and a bounded task; no nested agents. Pass explicit context with model overrides. Establish shared models and interfaces before parallel implementation; shared interface changes go through the coordinator. Terra implements fixes; Astra checks revisions; integrate only after applicable verification passes. Agents may inspect live sources and make authorized read-only Calendar checks. Coordinator owns production Calendar writes and scheduler installation.

## 2. Goal and environment

Build a local macOS ETL that comprehensively discovers SF and LA Tech Week 2026 events and imports useful candidates into Google Calendar. Prioritize completeness, duplicate prevention, useful descriptions and source links, approximate scheduling, and user decisions.

Verified planning environment: clean main containing planning documents; Apple Silicon macOS 27.0; Python 3.12–3.14, uv, Homebrew, Git, GitHub CLI, Node/npm, gog; Chrome and cached Chromium; working GitHub authentication outside sandbox; Candidate Events accessible through zenmindai@gmail.com with owner access and Pacific timezone.

Pin Python 3.13, repository-local virtual environment and ignored uv cache, committed uv.lock. Install Chromium matching locked Playwright. Start with Playwright, httpx, Beautiful Soup, pytest, argparse, dataclasses, zoneinfo, SQLite; add Google clients for Calendar integration. Credentials and durable state live under `~/Library/Application Support/techweek-etl/`. Ignore caches, raw snapshots, credentials, runtime files. Document elevated execution for Keychain, browser, network, outside-workspace operations. Offline tests run within workspace.

## 3. Extraction, normalization, and identity

Tech Week `/go/event/...` URLs rotate after reload while resolving to the same registration event; never use these as primary identities.

- Playwright traverses every date in both cities with search/topic filters cleared and closed events included.
- Wait for selected dates, displayed counts, rendered rows to agree; accumulate incremental rendering; deduplicate desktop/mobile links.
- Reconcile displayed counts and explicitly account for zero-event days. Historical SF 1,545 matches and ~48 initial rows are examples, not targets. Source: https://www.tech-week.com/calendar/sf
- Health requires completed traversal, count reconciliation, validation, and at least 80% of previous healthy count. Unhealthy runs cannot replace healthy baselines, mutate affected-city Calendar entries, or draw missing-source conclusions.
- Resolve redirects with bounded concurrency/timeouts. Identity v1 = year, city, canonical registration destination; retain direct Tech Week URL separately.
- Preserve meaningful URL paths/query parameters; remove only recognized tracking parameters. Conflicting occurrences sharing a destination require review.
- Fallback identity uses title/date/time with confidence marked. Defer uncertain rematches instead of probable duplicate creation.
- Exclude retrieval timestamps and rotating redirect tokens from material changes; preserve source links on otherwise unchanged Calendar events.
- Normalize in America/Los_Angeles regardless of host timezone. Default duration 60 minutes; known date/no time gets all-day fallback.
- Opportunistic enrichment failures must not erase useful descriptions or block usable events.
- Versioned snapshots include normalized events, identity confidence, timing quality, city health, rejected-record reasons.

## 4. Calendar behavior and recovery

- Explicit Candidate Events calendar ID through verified account; native Python Google client unattended, gog for inspection.
- Desktop OAuth scopes: Calendar events and read-only calendar list. Authentication only via explicit setup command. Verify refresh-token longevity before scheduling; Testing external OAuth apps may get seven-day tokens: https://developers.google.com/identity/protocols/oauth2
- Inventory all pages, managed entries independently of source-date window.
- Preserve Tech Week, SF and Tech Week, LA markers and foreign-managed records.
- Adopt untagged entries only by unique exact source-link match, including rotating redirects resolving to same destination. Title/time-only matches suppress creation as review items. Validate existing [Demoscene] and Science x AI Opening Breaskfast imports.
- Deterministic Google event IDs, transparent availability, no attendees/conference creation. Safe retry after uncertain inserts: https://developers.google.com/workspace/calendar/api/guides/create-events
- Conditional PATCH source-owned fields; preserve availability/reminders/color/unrelated metadata and notes outside delimited managed description. Re-read/recompute after ETag conflict: https://developers.google.com/workspace/calendar/api/guides/version-resources
- SQLite identity mappings, successful payloads, healthy baselines, outcomes, dismissals; one application lock for manual/scheduled runs.
- Confirmed manual deletions become DISMISSED. Missing imported records withheld pending investigation.
- Source disappearance report-only. Bounded transient retries; persist each successful write immediately.

## 5. Build sequence and acceptance

| Milestone | Terra implementation | Astra verification |
|---|---|---|
| Foundation | One agent: package, configuration, models, identity, normalization, state interfaces | Interfaces, identity stability, timezone, state |
| Source and Calendar reads | Two agents: extraction/snapshots and inventory/diff | Subsystem review and offline checks |
| Integrated dry run | CLI orchestration/reporting | Snapshot replay, classifications, health gates, zero writes |
| Controlled writes | Creation/adoption/conditional updates/recovery | Retries/conflicts/user-state/deletion |
| Operations | LaunchAgent template and docs | Absolute paths/noninteractive/locking/logs/removal |

Coordinator integrates milestones and conducts authorized live validation.

CLI: discover, extract, calendar-inventory, sync, doctor, auth, sync --snapshot FILE. Sync defaults dry-run, --apply required for writes. Separate extraction, pure diffing, execution with identical replay logic. --limit caps total mutations. Event filters must not imply city-wide disappearance.

Acceptance scenarios:
- Rotating links produce one identity and no token-only update.
- Partial rendering, missing days, collapse, normalization losses block city writes.
- Pacific time under Chicago host, including midnight/exclusive all-day end.
- Adoption retains Calendar IDs; ambiguous/marker/foreign entries untouched.
- Notes/availability/reminders/color survive.
- Deleted imports stay deleted.
- Interrupted inserts, ETag conflicts, partial failures, overlapping runs recover without duplicates.
- Dry-run has zero Calendar writes and leaves committed sync state unchanged.

Begin extraction/snapshots without Calendar writes. Then adopt verified imports, create at most ten candidates, rerun same snapshot with zero unnecessary writes. Complete SF and LA separately before enabling daily user LaunchAgent with absolute paths and installed venv executable. Deterministic CI without Google credentials; live checks explicit/local. Defer cloud, provider-specific parsers, AI ranking, automatic deletion.

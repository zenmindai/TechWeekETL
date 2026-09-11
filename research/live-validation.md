# Local live validation

These observations are local checks, not offline-test fixtures or proof that the full import has completed.

## Calendar reads

Read-only `gog` inspection through `zenmindai@gmail.com` verified:

- Calendar: Candidate Events
- ID: `1cc8e5965d1ae7526d61b8d9828b5b7448900d410affd1e0c59e943678b6d053@group.calendar.google.com`
- Access role: owner
- Timezone: America/Los_Angeles
- Existing protected markers: Tech Week, SF; Tech Week, LA
- Existing untagged candidates: `[Demoscene]` and `Science x AI Opening Breaskfast`
- Other entries include Notion/cron Calendar synchronization metadata, which must remain untouched.

The initial October read used `--all-pages`. A later native-client inventory read every Calendar page without a date window and included cancelled records. Before controlled writes it found 100 records: 83 confirmed and 17 cancelled. Raw Calendar data is retained only in temporary or ignored local files, not committed.

Both existing candidate descriptions contain older rotating Tech Week `/go/event/...` links. Direct HTTP requests returned 429 without resolving to external registration destinations. Those responses do **not** establish canonical identity or authorize adoption. Exact destination adoption remains pending successful resolution; title/time resemblance alone should produce review and suppress creation.

## Native OAuth and operations

Desktop OAuth now uses a dedicated installed-application client. The application successfully authenticated `zenmindai@gmail.com`, verified the exact Candidate Events calendar ID, and stored an owner-only refresh token with Calendar event access and read-only calendar-list access. The OAuth consent screen's Production/Testing status still needs verification before unattended scheduling.

## Source snapshots and dry runs

The 2026-09-10 LA snapshot reconciled 756 displayed and normalized events across all seven expected days, with no rejected rows. Forty events had canonical registration destinations; 716 retained fallback identities and were held for review. The live dry run classified 40 as `INSERT` and 716 as `REVIEW`, made no Calendar writes, and created no SQLite state.

The separate SF traversal reconciled all seven expected day sections but exposed 1,599 source rows: 1,597 within October 5–11 plus real source sections on October 16 and October 28. Those two rows are recorded as `unexpected_source_day`; SF remains unhealthy and blocked from writes under the normalization-loss rule. Its dry run reported all 1,597 retained events without mutations.

## Controlled LA write

Ten explicit canonical LA identities were selected from the complete snapshot plan. The selected dry run produced exactly ten `INSERT` actions. The controlled `--apply --limit 10` run created all ten with no failures and persisted ten deterministic mappings. Replaying the identical snapshot and identities produced ten `REPORT: unchanged` results and no further Calendar or SQLite writes.

A fresh native inventory found 110 total records and exactly ten `techweek_etl`-managed LA events. All ten are transparent, use Pacific event timing, contain the delimited managed description block, and have no attendees or conference data. Both protected Tech Week markers and all 47 detected foreign sync-managed records remain present. Explicit partial selection did not advance a city-wide healthy baseline.

No LaunchAgent has been installed. Remaining live gates are: resolve or explicitly retain the SF out-of-window block; validate adoption of the two known untagged SF imports after SF becomes healthy; complete any further user-selected LA import; verify OAuth refresh-token longevity; and only then enable daily scheduling.

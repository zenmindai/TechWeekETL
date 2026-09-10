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

The October read used `--all-pages`. This was a development inspection, not the application's full-history managed-event inventory. Raw Calendar data is retained only in a temporary local file, not committed.

Both existing candidate descriptions contain older rotating Tech Week `/go/event/...` links. Direct HTTP requests returned 429 without resolving to external registration destinations. Those responses do **not** establish canonical identity or authorize adoption. Exact destination adoption remains pending successful resolution; title/time resemblance alone should produce review and suppress creation.

## Native OAuth and operations

The dedicated `~/Library/Application Support/techweek-etl/` directory did not exist at initial inspection. `gog` has an existing Keychain-backed client; that is distinct from configuring the native Python client's Desktop OAuth setup. The Desktop client file and consent-screen Production/Testing status remain to be established.

No production Calendar writes or LaunchAgent installation have been performed. Required live gates remain: complete healthy snapshots for both cities; native Calendar authentication and target verification; controlled adoption and at most ten new candidates; identical-snapshot zero-write replay; separate full-city imports; OAuth longevity verification before daily scheduling.

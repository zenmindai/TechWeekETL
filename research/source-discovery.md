# Source discovery notes

The live calendar pages are `https://www.tech-week.com/calendar/sf` and `/la`.
SF exposes date controls for October 5–11, 2026; LA exposes October 12–18.
The event table uses `tr` rows, `.event-title` carries the title, the first `td`
contains the start time, and the registration link is a `/go/event/…` anchor with
an `aria-label`. Responsive markup can expose duplicate anchors for one row.

Extraction clears filters and disables an active “Hide closed events” control,
then visits every expected date and records both selected-date and row-count
evidence. The total display is reconciled with the aggregate of per-day rows.
Counts observed in the live site are diagnostic evidence rather than fixed test
targets because the program changes over time.

`/go/event` links are rotating redirects. Redirect resolution is best effort,
bounded and circuit-breaks after a 429; unresolved links stay fallback identities.

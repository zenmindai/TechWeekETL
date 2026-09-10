"""Browser-backed collection of the Tech Week calendar.

The calendar is client-rendered and its ``/go/event`` links are deliberately
ephemeral, so this module keeps the browser work isolated from normalization.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
import re
import time
from typing import Iterable
from urllib.parse import urljoin, urlsplit

import httpx
from playwright.sync_api import Browser, Page, sync_playwright

CITY_DATES = {
    "sf": tuple(date(2026, 10, day) for day in range(5, 12)),
    "la": tuple(date(2026, 10, day) for day in range(12, 19)),
}
CITY_URLS = {city: f"https://www.tech-week.com/calendar/{city}" for city in CITY_DATES}


@dataclass(frozen=True, slots=True)
class RawEvent:
    city: str
    day: date
    title: str
    time_text: str
    source_url: str
    registration_url: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class DayEvidence:
    day: date
    displayed_count: int | None
    confirmed: bool
    selected_label: str = ""


@dataclass(frozen=True, slots=True)
class CityTraversal:
    city: str
    raw_events: tuple[RawEvent, ...]
    expected_days: tuple[date, ...]
    day_evidence: tuple[DayEvidence, ...]
    displayed_count: int | None
    traversal_complete: bool
    issues: tuple[str, ...] = ()


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _scan_schedule(page: Page, city: str) -> tuple[list[RawEvent], set[date], int]:
    """Parse every currently appended row and associate it with its day header."""
    rows = page.locator("tr").evaluate_all(
        """rows => rows.map(row => {
            const first = (row.innerText || '').split('\\n')[0].trim();
            const link = row.querySelector('a[href^="/go/event/"][aria-label], a[href*="tech-week.com/go/event/"][aria-label]');
            const title = row.querySelector('.event-title')?.textContent?.trim() || '';
            const time = row.querySelector('td')?.innerText?.trim() || '';
            return {first, href: link?.getAttribute('href') || '', title, time};
        })"""
    )
    current_day: date | None = None
    headers: set[date] = set()
    events: dict[tuple[date, str, str, str], RawEvent] = {}
    rendered_event_rows = 0
    for row in rows:
        header = _clean_text(row.get("first"))
        if re.match(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), Oct \d{1,2}$", header):
            current_day = date(2026, 10, int(header.rsplit(" ", 1)[1]))
            headers.add(current_day)
            continue
        href = str(row.get("href") or "")
        if not href:
            continue
        rendered_event_rows += 1
        if current_day is None:
            continue
        source_url = urljoin(CITY_URLS[city], href)
        title = _clean_text(row.get("title"))
        time_text = _clean_text(row.get("time"))
        if title:
            key = (current_day, source_url, title, time_text)
            events.setdefault(key, RawEvent(city, current_day, title, time_text, source_url))
    return list(events.values()), headers, rendered_event_rows


def _displayed_count(page: Page) -> int | None:
    # The app has used both "1,234 events" and bare event-count labels.
    text = _clean_text(page.locator("body").inner_text())
    matches = re.findall(r"(?:^|\s)([\d,]+)\s+(?:(?:matching\s+)?events?|results?)(?:\s|$)", text, re.I)
    if not matches:
        return None
    return max(int(value.replace(",", "")) for value in matches)


def _clear_filters(page: Page) -> None:
    controls = page.get_by_text(re.compile(r"clear all filters", re.I))
    if controls.count() and controls.first.is_enabled():
        controls.first.click()
        deadline = time.monotonic() + 10
        while controls.first.is_enabled() and time.monotonic() < deadline:
            page.wait_for_timeout(200)
        if controls.first.is_enabled():
            raise RuntimeError("filters did not clear")


def collect_city(city: str, *, headless: bool = True, timeout_ms: int = 240_000) -> CityTraversal:
    """Traverse each advertised day and capture rendered-row/count evidence."""
    city = city.lower()
    if city not in CITY_DATES:
        raise ValueError(f"unsupported city: {city}")
    expected = CITY_DATES[city]
    issues: list[str] = []
    evidence: list[DayEvidence] = []
    all_events: list[RawEvent] = []
    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=headless)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            page.goto(CITY_URLS[city], wait_until="networkidle", timeout=timeout_ms)
            _clear_filters(page)
            # The live control is a switch. aria-checked=false means closed
            # events are included; turn filtering off if it was left on.
            hide_closed = page.get_by_role("switch", name=re.compile(r"hide closed events", re.I))
            if hide_closed.count() and hide_closed.first.get_attribute("aria-checked") == "true":
                hide_closed.first.click()
                page.wait_for_timeout(350)
            aggregate = _displayed_count(page)
            if aggregate is None:
                issues.append("missing city-wide displayed event count")
            deadline = time.monotonic() + timeout_ms / 1000
            stable_rounds = 0
            previous_count = -1
            headers: set[date] = set()
            rendered_count = 0
            while time.monotonic() < deadline:
                all_events, headers, rendered_count = _scan_schedule(page, city)
                current_displayed = _displayed_count(page)
                if current_displayed is not None:
                    aggregate = current_displayed
                if aggregate is not None and rendered_count == aggregate and headers == set(expected):
                    break
                stable_rounds = stable_rounds + 1 if rendered_count == previous_count else 0
                previous_count = rendered_count
                if stable_rounds >= 30:
                    issues.append("incremental schedule rendering stopped before count reconciliation")
                    break
                page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                page.wait_for_timeout(500)
            else:
                issues.append("schedule traversal timed out")
            counts: dict[date, int] = {day: 0 for day in expected}
            for event in all_events:
                counts[event.day] = counts.get(event.day, 0) + 1
            for day in expected:
                confirmed = day in headers
                evidence.append(DayEvidence(day, counts[day] if confirmed else None, confirmed, day.strftime("%A, %b %-d")))
                if not confirmed:
                    issues.append(f"missing rendered day header {day.isoformat()}")
            if aggregate != rendered_count:
                issues.append(f"rendered row mismatch: displayed {aggregate}, rendered {rendered_count}")
        finally:
            browser.close()
    # Source URLs can appear twice in responsive markup; preserve one occurrence.
    unique: dict[tuple[date, str, str, str], RawEvent] = {}
    for event in all_events:
        unique.setdefault((event.day, event.source_url, event.title, event.time_text), event)
    return CityTraversal(city, tuple(unique.values()), expected, tuple(evidence), aggregate,
                         len(evidence) == len(expected) and not issues, tuple(issues))


def resolve_redirects(events: Iterable[RawEvent], *, concurrency: int = 8, timeout: float = 15.0,
                      rate_limit_pause: float = 0.0) -> tuple[RawEvent, ...]:
    """Best-effort resolve all redirect links, stopping new work after a 429.

    A redirect that remains on Tech Week or errors is deliberately left unresolved;
    it must not become a false canonical destination.
    """
    values = tuple(events)
    if not values:
        return values
    stopped = False
    client = httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})

    def resolve(raw: RawEvent) -> tuple[RawEvent, bool]:
        try:
            response = client.get(raw.source_url)
            if response.status_code == 429:
                return raw, True
            final = str(response.url)
            parsed = urlsplit(final)
            host = (parsed.hostname or "").lower()
            # Do not bless an HTTP error endpoint or a still-rotating URL.
            if response.is_error or parsed.scheme not in {"http", "https"} or not host:
                return raw, False
            if (host == "tech-week.com" or host.endswith(".tech-week.com")) and parsed.path.startswith("/go/event/"):
                return raw, False
            return RawEvent(raw.city, raw.day, raw.title, raw.time_text, raw.source_url, final, raw.description), False
        except httpx.HTTPError:
            return raw, False

    result = list(values)
    width = max(1, concurrency)
    try:
        for offset in range(0, len(values), width):
            if stopped:
                break
            batch = values[offset:offset + width]
            with ThreadPoolExecutor(max_workers=width) as pool:
                pending = {pool.submit(resolve, raw): offset + index for index, raw in enumerate(batch)}
                for future in as_completed(pending):
                    resolved, limited = future.result()
                    result[pending[future]] = resolved
                    stopped = stopped or limited
            if stopped and rate_limit_pause > 0:
                time.sleep(rate_limit_pause)
    finally:
        client.close()
    return tuple(result)

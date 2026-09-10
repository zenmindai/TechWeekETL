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


def _row_events(page: Page, city: str, day: date) -> list[RawEvent]:
    """Read table rows, retaining one link per event row (desktop/mobile duplicate)."""
    rows = page.locator("tr").all()
    found: list[RawEvent] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        anchors = row.locator("a[href^='/go/event/'], a[href*='tech-week.com/go/event/']").all()
        if not anchors:
            continue
        anchor = anchors[0]
        href = anchor.get_attribute("href") or ""
        source_url = urljoin(CITY_URLS[city], href)
        title_node = row.locator(".event-title").first
        title = _clean_text(title_node.get_attribute("title") if title_node.count() else "")
        if not title:
            title = _clean_text(anchor.get_attribute("aria-label") or anchor.inner_text())
        cells = row.locator("td").all()
        time_text = _clean_text(cells[0].inner_text() if cells else "")
        key = (source_url, title, time_text)
        if not title or key in seen:
            continue
        seen.add(key)
        found.append(RawEvent(city, day, title, time_text, source_url))
    return found


def _settled_row_events(page: Page, city: str, day: date) -> list[RawEvent]:
    """Scroll the table to trigger incremental rendering, until the row set settles."""
    previous: set[tuple[str, str, str]] | None = None
    stable = 0
    result: list[RawEvent] = []
    for _ in range(18):
        result = _row_events(page, city, day)
        current = {(item.source_url, item.title, item.time_text) for item in result}
        stable = stable + 1 if current == previous else 0
        if stable >= 2:
            break
        previous = current
        page.mouse.wheel(0, 1100)
        page.wait_for_timeout(300)
    page.evaluate("window.scrollTo(0, 0)")
    return result


def _displayed_count(page: Page) -> int | None:
    # The app has used both "1,234 events" and bare event-count labels.
    text = _clean_text(page.locator("body").inner_text())
    matches = re.findall(r"(?:^|\s)([\d,]+)\s+(?:events?|results?)(?:\s|$)", text, re.I)
    if not matches:
        return None
    return max(int(value.replace(",", "")) for value in matches)


def _clear_filters(page: Page) -> None:
    controls = page.get_by_text(re.compile(r"clear all filters", re.I))
    if controls.count():
        controls.first.click()
        page.wait_for_timeout(500)


def _date_button(page: Page, day: date):
    label = day.strftime("%a, %b ") + str(day.day)
    buttons = page.get_by_role("button", name=re.compile(re.escape(label), re.I))
    return buttons.first if buttons.count() else None


def collect_city(city: str, *, headless: bool = True, timeout_ms: int = 30_000) -> CityTraversal:
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
            # "Hide closed events" means the checked state hides them. Verify it
            # and turn it off when present so closed events remain included.
            hide_closed = page.get_by_text(re.compile(r"hide closed events", re.I))
            if hide_closed.count():
                checkbox = hide_closed.first.locator("xpath=ancestor::*[@role='checkbox' or self::label][1]")
                if checkbox.count() and checkbox.get_attribute("aria-checked") == "true":
                    checkbox.click()
                    page.wait_for_timeout(350)
            aggregate = _displayed_count(page)
            for day in expected:
                button = _date_button(page, day)
                if button is None:
                    issues.append(f"missing date control {day.isoformat()}")
                    evidence.append(DayEvidence(day, None, False))
                    continue
                button.click()
                page.wait_for_timeout(650)
                # Ensure the calendar has settled around the selected day.
                classes = button.get_attribute("class") or ""
                selected = (button.get_attribute("aria-pressed") == "true" or
                            button.get_attribute("data-state") in {"active", "selected"} or
                            bool(re.search(r"(?<!un)selected", classes, re.I)))
                events = _settled_row_events(page, city, day)
                # A selected empty day is valid; do not require table rows.
                count = len(events)
                evidence.append(DayEvidence(day, count, selected, _clean_text(button.inner_text())))
                if not selected:
                    issues.append(f"unconfirmed selected day {day.isoformat()}")
                all_events.extend(events)
        finally:
            browser.close()
    # Source URLs can appear twice in responsive markup; preserve one occurrence.
    unique: dict[tuple[str, str, str], RawEvent] = {}
    for event in all_events:
        unique.setdefault((event.source_url, event.title, event.time_text), event)
    return CityTraversal(city, tuple(unique.values()), expected, tuple(evidence), aggregate,
                         len(evidence) == len(expected) and not issues, tuple(issues))


def resolve_redirects(events: Iterable[RawEvent], *, concurrency: int = 8, timeout: float = 15.0,
                      rate_limit_pause: float = 8.0) -> tuple[RawEvent, ...]:
    """Best-effort resolve all redirect links, stopping new work after a 429.

    A redirect that remains on Tech Week or errors is deliberately left unresolved;
    it must not become a false canonical destination.
    """
    values = tuple(events)
    if not values:
        return values
    stopped = False
    def resolve(raw: RawEvent) -> RawEvent:
        nonlocal stopped
        if stopped:
            return raw
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as client:
                response = client.get(raw.source_url)
            if response.status_code == 429:
                stopped = True
                time.sleep(rate_limit_pause)
                return raw
            final = str(response.url)
            # Do not bless an HTTP error endpoint or a still-rotating URL.
            if response.is_error or urlsplit(final).path.startswith("/go/event/") and "tech-week.com" in urlsplit(final).netloc:
                return raw
            return RawEvent(raw.city, raw.day, raw.title, raw.time_text, raw.source_url, final, raw.description)
        except httpx.HTTPError:
            return raw
    result: list[RawEvent | None] = [None] * len(values)
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        pending = {pool.submit(resolve, raw): index for index, raw in enumerate(values)}
        for future in as_completed(pending):
            result[pending[future]] = future.result()
    return tuple(item for item in result if item is not None)

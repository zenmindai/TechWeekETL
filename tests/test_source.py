import asyncio
from datetime import date

from techweek_etl import browser, extract


class Locator:
    def __init__(self, rows=None, text=""):
        self.rows = rows or []
        self.text = text

    def evaluate_all(self, script):
        return self.rows

    def inner_text(self):
        return self.text


class Page:
    def __init__(self, rows=None, text=""):
        self.rows = rows or []
        self.text = text

    def locator(self, selector):
        return Locator(self.rows if selector == "tr" else None, self.text)


def test_schedule_scan_assigns_rows_to_day_headers_and_counts_malformed_rows():
    rows = [
        {"first": "Monday, Oct 5", "href": "", "title": "", "time": "", "isHeader": True},
        {"first": "12:00am", "href": "/go/event/a", "title": "One", "time": "12:00am"},
        {"first": "1:00am", "href": "/go/event/b", "title": "", "time": "1:00am"},
        {"first": "Tuesday, Oct 6", "href": "", "title": "", "time": "", "isHeader": True},
        {"first": "6:15am", "href": "/go/event/c", "title": "Two", "time": "6:15am"},
    ]
    events, headers, rendered = browser._scan_schedule(Page(rows), "sf")
    assert rendered == 3
    assert headers == {date(2026, 10, 5), date(2026, 10, 6)}
    assert [(event.day, event.title) for event in events] == [
        (date(2026, 10, 5), "One"),
        (date(2026, 10, 6), "Two"),
    ]


def test_schedule_scan_does_not_treat_date_shaped_event_title_as_header():
    rows = [
        {"first": "Monday, Oct 5", "href": "", "title": "", "time": "", "isHeader": True},
        {
            "first": "Friday, Oct 16",
            "href": "/go/event/date-title",
            "title": "Friday, Oct 16",
            "time": "9:00am",
            "isHeader": False,
        },
        {"first": "Tuesday, Oct 6", "href": "", "title": "", "time": "", "isHeader": True},
    ]

    events, headers, rendered = browser._scan_schedule(Page(rows), "sf")

    assert rendered == 1
    assert headers == {date(2026, 10, 5), date(2026, 10, 6)}
    assert events[0].day == date(2026, 10, 5)


def test_matching_event_count_is_parsed():
    assert browser._displayed_count(Page(text="Filters 1,563 matching events")) == 1563


def test_redirect_resolution_stops_submitting_batches_after_rate_limit(monkeypatch):
    calls = []

    class Response:
        def __init__(self, status, url):
            self.status_code = status
            self.url = url
            self.is_error = status >= 400

    class Client:
        def __init__(self, **kwargs):
            pass

        def get(self, url):
            calls.append(url)
            if url.endswith("/c"):
                return Response(429, url)
            return Response(200, "https://tickets.example/" + url.rsplit("/", 1)[1])

        def close(self):
            pass

    monkeypatch.setattr(browser.httpx, "Client", Client)
    raw = tuple(
        browser.RawEvent("sf", date(2026, 10, 5), name, "9:00am", f"https://tech-week.com/go/event/{name}")
        for name in ("a", "b", "c", "d", "e", "f")
    )
    resolved = browser.resolve_redirects(raw, concurrency=2, browser_fallback=lambda values, **_: tuple(values))
    assert len(calls) <= 4
    assert resolved[0].registration_url == "https://tickets.example/a"
    assert resolved[-1].registration_url == ""


def test_external_error_is_canonical_but_techweek_final_is_not(monkeypatch):
    responses = iter([
        type("Response", (), {"status_code": 404, "url": "https://tickets.example/missing", "is_error": True})(),
        type("Response", (), {"status_code": 200, "url": "https://www.tech-week.com/calendar/la", "is_error": False})(),
    ])

    class Client:
        def __init__(self, **kwargs):
            pass

        def get(self, url):
            return next(responses)

        def close(self):
            pass

    monkeypatch.setattr(browser.httpx, "Client", Client)
    raw = tuple(
        browser.RawEvent("sf", date(2026, 10, 5), str(index), "9:00am", f"https://tech-week.com/go/event/{index}")
        for index in range(2)
    )
    resolved = browser.resolve_redirects(raw, concurrency=1, browser_fallback=lambda values, **_: tuple(values))
    assert resolved[0].registration_url == "https://tickets.example/missing"
    assert not resolved[1].registration_url


def test_browser_fallback_recovers_only_unresolved_techweek_links(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass

        def get(self, url):
            return type("Response", (), {"status_code": 200, "url": url})()

        def close(self):
            pass

    seen = {}

    def fallback(values, *, concurrency, timeout_ms):
        seen["sources"] = [item.source_url for item in values]
        seen["concurrency"] = concurrency
        seen["timeout_ms"] = timeout_ms
        return tuple(
            browser.RawEvent(item.city, item.day, item.title, item.time_text, item.source_url,
                             f"https://partiful.example/{index}", item.description)
            for index, item in enumerate(values)
        )

    monkeypatch.setattr(browser.httpx, "Client", Client)
    raw = (
        browser.RawEvent("sf", date(2026, 10, 5), "Browser", "9:00am", "https://tech-week.com/go/event/browser"),
        browser.RawEvent("sf", date(2026, 10, 5), "Direct", "10:00am", "https://tickets.example/direct",
                         "https://tickets.example/existing"),
    )

    resolved = browser.resolve_redirects(raw, browser_concurrency=3, browser_timeout_ms=4_000,
                                         browser_fallback=fallback)

    assert seen == {"sources": [raw[0].source_url], "concurrency": 3, "timeout_ms": 4_000}
    assert resolved[0].registration_url == "https://partiful.example/0"
    assert resolved[1].registration_url == "https://tickets.example/existing"


def test_browser_fallback_retains_external_404_and_stops_after_429(monkeypatch):
    calls = []
    active = 0
    max_active = 0
    release_closed = asyncio.Event()

    class Page:
        url = ""

        def set_default_navigation_timeout(self, timeout):
            assert timeout == 500

        async def goto(self, url, **kwargs):
            nonlocal active, max_active
            calls.append(url)
            active += 1
            max_active = max(max_active, active)
            if url.endswith("/closed"):
                await release_closed.wait()
            else:
                release_closed.set()
            active -= 1
            self.url = "https://partiful.example/closed" if url.endswith("/closed") else url
            return type("Response", (), {"status": 404 if url.endswith("/closed") else 429})()

        async def close(self):
            pass

    class Browser:
        async def new_page(self):
            return Page()

        async def close(self):
            pass

    class Chromium:
        async def launch(self, **kwargs):
            return Browser()

    class Playwright:
        chromium = Chromium()

    class Context:
        async def __aenter__(self):
            return Playwright()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(browser, "async_playwright", lambda: Context())
    raw = tuple(
        browser.RawEvent("sf", date(2026, 10, 5), title, "9:00am", f"https://tech-week.com/go/event/{title}")
        for title in ("closed", "limited", "after-limit")
    )

    resolved = browser.resolve_redirects_in_browser(raw, concurrency=2, timeout_ms=500)

    assert resolved[0].registration_url == "https://partiful.example/closed"
    assert max_active == 2
    assert set(calls) == {raw[0].source_url, raw[1].source_url}


def test_same_canonical_occurrence_on_different_days_is_rejected():
    expected = browser.CITY_DATES["sf"]
    raw = tuple(
        browser.RawEvent(
            "sf",
            day,
            "Repeated event",
            "9:00am",
            "https://www.tech-week.com/go/event/rotating",
            "https://tickets.example/events/repeated",
        )
        for day in expected[:2]
    )
    evidence = tuple(
        browser.DayEvidence(day, 1 if day in expected[:2] else 0, True)
        for day in expected
    )
    traversal = browser.CityTraversal("sf", raw, expected, evidence, 2, True)

    events, _, rejected = extract.normalize_city_traversal(traversal)

    assert events == ()
    assert [record.reason for record in rejected] == ["conflicting_destination_occurrence"]
    assert rejected[0].city == "sf"


def test_ambiguous_unresolved_title_and_time_are_deferred():
    expected = browser.CITY_DATES["sf"]
    raw = tuple(
        browser.RawEvent("sf", expected[0], "Same title", "9:00am", f"https://tech-week.com/go/event/{token}")
        for token in ("one", "two")
    )
    evidence = tuple(browser.DayEvidence(day, 2 if day == expected[0] else 0, True) for day in expected)
    traversal = browser.CityTraversal("sf", raw, expected, evidence, 2, True)

    events, health, rejected = extract.normalize_city_traversal(traversal)

    assert events == ()
    assert not health.healthy
    assert [record.reason for record in rejected] == ["ambiguous_unresolved_occurrence"]


def test_mixed_resolved_and_unresolved_title_and_time_are_deferred():
    expected = browser.CITY_DATES["sf"]
    raw = (
        browser.RawEvent("sf", expected[0], "Same title", "9:00am", "https://tech-week.com/go/event/one",
                         "https://partiful.example/resolved"),
        browser.RawEvent("sf", expected[0], "Same title", "9:00am", "https://tech-week.com/go/event/two"),
    )
    evidence = tuple(browser.DayEvidence(day, 2 if day == expected[0] else 0, True) for day in expected)
    traversal = browser.CityTraversal("sf", raw, expected, evidence, 2, True)

    events, health, rejected = extract.normalize_city_traversal(traversal)

    assert events == ()
    assert not health.healthy
    assert [record.reason for record in rejected] == ["ambiguous_unresolved_occurrence"]

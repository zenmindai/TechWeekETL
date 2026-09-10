from datetime import date

from techweek_etl import browser


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
        {"first": "Monday, Oct 5", "href": "", "title": "", "time": ""},
        {"first": "12:00am", "href": "/go/event/a", "title": "One", "time": "12:00am"},
        {"first": "1:00am", "href": "/go/event/b", "title": "", "time": "1:00am"},
        {"first": "Tuesday, Oct 6", "href": "", "title": "", "time": ""},
        {"first": "6:15am", "href": "/go/event/c", "title": "Two", "time": "6:15am"},
    ]
    events, headers, rendered = browser._scan_schedule(Page(rows), "sf")
    assert rendered == 3
    assert headers == {date(2026, 10, 5), date(2026, 10, 6)}
    assert [(event.day, event.title) for event in events] == [
        (date(2026, 10, 5), "One"),
        (date(2026, 10, 6), "Two"),
    ]


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
    resolved = browser.resolve_redirects(raw, concurrency=2)
    assert len(calls) <= 4
    assert resolved[0].registration_url == "https://tickets.example/a"
    assert resolved[-1].registration_url == ""


def test_external_error_and_techweek_final_are_not_canonical(monkeypatch):
    responses = iter([
        type("Response", (), {"status_code": 404, "url": "https://tickets.example/missing", "is_error": True})(),
        type("Response", (), {"status_code": 200, "url": "https://www.tech-week.com/go/event/new", "is_error": False})(),
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
    assert all(not item.registration_url for item in browser.resolve_redirects(raw, concurrency=1))

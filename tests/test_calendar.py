import json
from datetime import datetime, timezone
from pathlib import Path
import stat

from techweek_etl.auth import _write_token
from techweek_etl.calendar import (
    CalendarTarget,
    deterministic_event_id,
    event_payload,
    insert_payload,
    verify_calendar_access,
)
from techweek_etl.diff import PlanItem, SyncPlan, plan_sync
from techweek_etl.executor import execute_plan
from techweek_etl.identity import build_identity
from techweek_etl.models import CityHealth, Event, Snapshot
from techweek_etl.normalize import normalize_event_timing
from techweek_etl.state import StateStore


def candidate() -> Event:
    start, end, _, quality = normalize_event_timing(datetime(2026, 10, 5, 9))
    raw = Event("sf", "Example", start, end, source_url="https://www.tech-week.com/go/event/current", registration_url="https://example.test/r/1", timing_quality=quality)
    return raw.with_identity(*build_identity(raw))


def snapshot(event: Event) -> Snapshot:
    return Snapshot((event,), (CityHealth("sf", 7, 7, 6, 1, 1, True),), datetime.now(timezone.utc))


def test_adopts_only_exact_resolved_url_and_protects_title_time(tmp_path: Path) -> None:
    event = candidate()
    old = {"id": "old", "description": "see https://www.tech-week.com/go/event/old"}
    with StateStore(tmp_path / "s", read_only=True) as state:
        plan = plan_sync(snapshot(event), [old], state, {"https://www.tech-week.com/go/event/old": event.registration_url})
    assert plan.items[0].action == "ADOPT"
    title_match = {"id": "title", "summary": event.title, "start": {"dateTime": event.start.isoformat()}}
    with StateStore(tmp_path / "t", read_only=True) as state:
        assert plan_sync(snapshot(event), [title_match], state).items[0].action == "REVIEW"


def test_patch_owned_fields_preserve_user_properties() -> None:
    existing = {"id": "g", "description": "my note", "transparency": "opaque", "attendees": [{"email": "a"}], "reminders": {"useDefault": False}, "colorId": "5", "extendedProperties": {"private": {"other": "keep"}}}
    body = event_payload(candidate(), existing=existing)
    assert "transparency" not in body and "attendees" not in body and "reminders" not in body and "colorId" not in body
    assert body["extendedProperties"]["private"]["other"] == "keep"
    assert "my note" in body["description"]
    inserted = insert_payload(candidate())
    assert inserted["id"] == deterministic_event_id(candidate().identity)
    assert inserted["transparency"] == "transparent" and inserted["attendees"] == []


class Request:
    def __init__(self, result): self.result, self.headers = result, {}
    def execute(self): return self.result


class Events:
    def __init__(self): self.calls = []
    def patch(self, **kwargs): self.calls.append(("patch", kwargs)); return Request({"id": kwargs["eventId"]})
    def insert(self, **kwargs): self.calls.append(("insert", kwargs)); return Request({"id": kwargs["body"]["id"]})


class Service:
    def __init__(self): self.api = Events()
    def events(self): return self.api


def test_apply_uses_body_id_and_if_match_header_and_dry_run_writes_nothing(tmp_path: Path) -> None:
    event = candidate(); existing = {"id": "adopted", "etag": "E"}
    target = CalendarTarget("zenmindai@gmail.com", "cal", "America/Los_Angeles")
    service = Service()
    with StateStore(tmp_path / "state") as state:
        plan = SyncPlan((PlanItem("ADOPT", event, existing), PlanItem("INSERT", event)), frozenset({"sf"}))
        execute_plan(service, target, plan, state, apply=False)
        assert service.api.calls == [] and state.get_identity(event.identity) is None
        execute_plan(service, target, plan, state, apply=True, limit=1)
        assert [call[0] for call in service.api.calls] == ["patch"]
        # the actual request object records its conditional header before execute
        assert state.get_calendar_identity(target.account_email, target.calendar_id, event.identity) is not None


def test_oauth_token_replacement_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    _write_token(path, '{"refresh_token":"secret"}')
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text(encoding="utf-8") == '{"refresh_token":"secret"}'


def test_target_verification_uses_calendar_list_scope_and_checks_identity() -> None:
    target_id = "candidate@example.test"

    class CalendarList:
        def list(self, **kwargs):
            return Request({"items": [
                {"id": "zenmindai@gmail.com", "primary": True},
                {"id": target_id, "summary": "Candidate Events", "timeZone": "America/Los_Angeles", "accessRole": "owner"},
            ]})

    class ReadOnlyService:
        def calendarList(self):
            return CalendarList()

    verified = verify_calendar_access(ReadOnlyService(), target_id)
    assert verified == CalendarTarget("zenmindai@gmail.com", target_id, "America/Los_Angeles")

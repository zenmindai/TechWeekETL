from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from techweek_etl import cli
from techweek_etl.calendar import CalendarTarget
from techweek_etl.diff import PlanItem
from techweek_etl.identity import build_identity
from techweek_etl.models import CityHealth, Event, Snapshot
from techweek_etl.normalize import normalize_event_timing
from techweek_etl.snapshots import write_snapshot
from techweek_etl.state import AppLock, StateStore


def _snapshot(*, second: bool = False) -> Snapshot:
    start, end, _, quality = normalize_event_timing(datetime(2026, 10, 5, 9))
    event = Event("sf", "CLI fixture", start, end, source_url="https://www.tech-week.com/go/event/a",
                  registration_url="https://example.test/event/a", timing_quality=quality)
    event = event.with_identity(*build_identity(event))
    events = [event]
    if second:
        other = Event("sf", "Second CLI fixture", start, end, source_url="https://www.tech-week.com/go/event/b",
                      registration_url="https://example.test/event/b", timing_quality=quality)
        events.append(other.with_identity(*build_identity(other)))
    health = CityHealth("sf", 7, 7, 6, len(events), len(events), True)
    evidence = {"sf": {
        date(2026, 10, day).isoformat(): {"displayed_count": len(events) if day == 5 else 0, "confirmed": True}
        for day in range(5, 12)
    }}
    return Snapshot(tuple(events), (health,), datetime.now(timezone.utc), version=2, day_evidence=evidence)


class _Events:
    def __init__(self) -> None:
        self.writes: list[tuple[str, dict]] = []

    def insert(self, **kwargs):
        self.writes.append(("insert", kwargs))
        return _Request({"id": kwargs["body"]["id"]})

    def patch(self, **kwargs):
        self.writes.append(("patch", kwargs))
        return _Request({"id": kwargs["eventId"]})


class _Request:
    def __init__(self, value): self.value = value; self.headers = {}
    def execute(self): return self.value


class _Service:
    def __init__(self): self.api = _Events()
    def events(self): return self.api


def _patch_calendar(monkeypatch, service: _Service) -> None:
    monkeypatch.setattr(cli, "build_calendar_service", lambda _: service)
    monkeypatch.setattr(cli, "verify_calendar_access", lambda *args, **kwargs: CalendarTarget("a@example.test", "cal", "America/Los_Angeles"))
    monkeypatch.setattr(cli, "inventory_events", lambda *args: [])


def _arguments(tmp_path: Path, *extra: str) -> list[str]:
    return ["--app-dir", str(tmp_path / "app"), "--account", "a@example.test", "--calendar-id", "cal", *extra]


def test_snapshot_dry_run_replays_reader_with_no_calendar_or_sqlite_writes(tmp_path: Path, monkeypatch, capsys) -> None:
    snapshot_path = tmp_path / "source.json"; write_snapshot(snapshot_path, _snapshot())
    database = tmp_path / "app" / "state.sqlite"
    database.parent.mkdir()
    with StateStore(database) as state:
        with state.transaction():
            state.set_baseline("sf", 1)
    committed = database.read_bytes()
    service = _Service(); _patch_calendar(monkeypatch, service)
    calls: list[Path] = []
    original = cli.read_snapshot
    monkeypatch.setattr(cli, "read_snapshot", lambda path: (calls.append(Path(path)) or original(path)))

    assert cli.main(["--json", *_arguments(tmp_path, "sync", "--snapshot", str(snapshot_path))]) == 0
    report = json.loads(capsys.readouterr().out)
    assert calls == [snapshot_path]
    assert report["actions"] == {"INSERT": 1}
    assert report["items"][0] == {
        "action": "INSERT", "identity": _snapshot().events[0].identity, "city": "sf", "title": "CLI fixture",
        "start": _snapshot().events[0].start.isoformat(), "end": _snapshot().events[0].end.isoformat(),
        "registration_url": "https://example.test/event/a", "source_url": "https://www.tech-week.com/go/event/a",
        "calendar_event_id": None, "reason": "new canonical event",
    }
    assert service.api.writes == []
    assert database.read_bytes() == committed


def test_apply_and_limit_are_passed_to_execution(tmp_path: Path, monkeypatch) -> None:
    snapshot_path = tmp_path / "source.json"; write_snapshot(snapshot_path, _snapshot())
    service = _Service(); _patch_calendar(monkeypatch, service)
    recorded = {}

    def execute(service_arg, target, plan, state, *, apply, limit):
        recorded.update(apply=apply, limit=limit)
        return list(plan.items)

    monkeypatch.setattr(cli, "execute_plan", execute)
    assert cli.main(_arguments(tmp_path, "sync", "--snapshot", str(snapshot_path), "--apply", "--limit", "1")) == 0
    assert recorded == {"apply": True, "limit": 1}


def test_cli_lock_rejects_overlapping_manual_command(tmp_path: Path) -> None:
    lock = tmp_path / "app" / "techweek-etl.lock"
    with AppLock(lock):
        with pytest.raises(RuntimeError, match="application lock"):
            cli.main(_arguments(tmp_path, "doctor"))


def test_snapshot_rejects_city_filter_that_would_hide_source_evidence(tmp_path: Path, monkeypatch) -> None:
    snapshot_path = tmp_path / "source.json"; write_snapshot(snapshot_path, _snapshot())
    service = _Service(); _patch_calendar(monkeypatch, service)
    with pytest.raises(SystemExit, match="cannot be combined"):
        cli.main(_arguments(tmp_path, "sync", "--snapshot", str(snapshot_path), "--city", "sf"))


def test_apply_cannot_lower_durable_baseline_when_plan_health_gate_rejects_city(tmp_path: Path, monkeypatch) -> None:
    snapshot_path = tmp_path / "source.json"; write_snapshot(snapshot_path, _snapshot())
    database = tmp_path / "app" / "state.sqlite"; database.parent.mkdir()
    with StateStore(database) as state:
        with state.transaction():
            state.set_baseline("sf", 100)
    service = _Service(); _patch_calendar(monkeypatch, service)

    assert cli.main(_arguments(tmp_path, "sync", "--snapshot", str(snapshot_path), "--apply")) == 0
    with StateStore(database, read_only=True) as state:
        assert state.get_baseline("sf") == 100


@pytest.mark.parametrize("reason", ["write failed: service unavailable", "mutation limit reached"])
def test_incomplete_apply_does_not_advance_baseline(tmp_path: Path, monkeypatch, reason: str) -> None:
    snapshot_path = tmp_path / "source.json"; write_snapshot(snapshot_path, _snapshot())
    service = _Service(); _patch_calendar(monkeypatch, service)

    def incomplete(_service, _target, plan, _state, *, apply, limit):
        assert apply is True
        return [PlanItem("REVIEW", plan.items[0].event, reason=reason)]

    monkeypatch.setattr(cli, "execute_plan", incomplete)
    assert cli.main(_arguments(tmp_path, "sync", "--snapshot", str(snapshot_path), "--apply")) == 0
    with StateStore(tmp_path / "app" / "state.sqlite", read_only=True) as state:
        assert state.get_baseline("sf") is None


def test_identity_selection_plans_complete_snapshot_then_applies_selected_item(tmp_path: Path, monkeypatch) -> None:
    snapshot = _snapshot(second=True); snapshot_path = tmp_path / "source.json"; write_snapshot(snapshot_path, snapshot)
    service = _Service(); _patch_calendar(monkeypatch, service)
    observed = {}

    def full_plan(source, _inventory, _state):
        observed["source_identities"] = [event.identity for event in source.events]
        return cli.SyncPlan(tuple(PlanItem("INSERT", event, reason="fixture") for event in source.events), frozenset({"sf"}))

    def execute(_service, _target, plan, _state, *, apply, limit):
        observed["executed"] = plan.items
        observed["apply"] = apply
        return list(plan.items)

    monkeypatch.setattr(cli, "plan_sync", full_plan)
    monkeypatch.setattr(cli, "execute_plan", execute)
    chosen = snapshot.events[1].identity
    assert cli.main(_arguments(tmp_path, "sync", "--snapshot", str(snapshot_path), "--identity", chosen, "--apply")) == 0
    assert observed["source_identities"] == [event.identity for event in snapshot.events]
    assert [item.event.identity for item in observed["executed"]] == [chosen]
    assert observed["apply"] is True


def test_identity_selection_rejects_unknown_and_ambiguous_identity(tmp_path: Path, monkeypatch) -> None:
    snapshot = _snapshot(); snapshot_path = tmp_path / "source.json"; write_snapshot(snapshot_path, snapshot)
    service = _Service(); _patch_calendar(monkeypatch, service)
    with pytest.raises(SystemExit, match="absent"):
        cli.main(_arguments(tmp_path, "sync", "--snapshot", str(snapshot_path), "--identity", "unknown"))

    event = snapshot.events[0]
    monkeypatch.setattr(cli, "plan_sync", lambda *_: cli.SyncPlan((PlanItem("INSERT", event), PlanItem("REVIEW", event)), frozenset({"sf"})))
    with pytest.raises(SystemExit, match="ambiguous"):
        cli.main(_arguments(tmp_path, "sync", "--snapshot", str(snapshot_path), "--identity", event.identity))

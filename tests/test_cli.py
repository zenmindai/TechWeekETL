from datetime import datetime, timezone
from pathlib import Path

import pytest

from techweek_etl import cli
from techweek_etl.calendar import CalendarTarget
from techweek_etl.identity import build_identity
from techweek_etl.models import CityHealth, Event, Snapshot
from techweek_etl.normalize import normalize_event_timing
from techweek_etl.snapshots import write_snapshot
from techweek_etl.state import AppLock, StateStore


def _snapshot() -> Snapshot:
    start, end, _, quality = normalize_event_timing(datetime(2026, 10, 5, 9))
    event = Event("sf", "CLI fixture", start, end, source_url="https://www.tech-week.com/go/event/a",
                  registration_url="https://example.test/event/a", timing_quality=quality)
    event = event.with_identity(*build_identity(event))
    health = CityHealth("sf", 7, 7, 6, 1, 1, True)
    return Snapshot((event,), (health,), datetime.now(timezone.utc), version=2)


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


def test_snapshot_dry_run_replays_reader_with_no_calendar_or_sqlite_writes(tmp_path: Path, monkeypatch) -> None:
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
    assert calls == [snapshot_path]
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

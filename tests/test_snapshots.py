"""Regression coverage for versioned source snapshot replay."""
from datetime import date, datetime, timezone
from dataclasses import replace
import json

from techweek_etl.browser import CITY_DATES
from techweek_etl.models import CityHealth, Event, RejectedRecord, Snapshot, TimingQuality
from techweek_etl.snapshots import read_snapshot, write_snapshot


def _snapshot(*, rejected=()):
    events = []
    evidence = {}
    health = []
    for city, days in CITY_DATES.items():
        events.extend(
            Event(city, f"{city} event {day.day}", day, date.fromordinal(day.toordinal() + 1), True,
                  source_url=f"https://source.example/{city}/{day.day}", timing_quality=TimingQuality.ALL_DAY)
            for day in days
        )
        evidence[city] = {
            day.isoformat(): {"displayed_count": 1, "confirmed": True, "selected_label": day.strftime("%A, %b %-d")}
            for day in days
        }
        health.append(CityHealth(city, len(days), len(days), 0, len(days), len(days), True))
    return Snapshot(tuple(events), tuple(health), datetime(2026, 1, 1, tzinfo=timezone.utc),
                    version=2, rejected=tuple(rejected), day_evidence=evidence)


def test_structured_day_evidence_round_trips_without_nesting(tmp_path):
    path = tmp_path / "snapshot.json"
    snapshot = _snapshot()

    write_snapshot(path, snapshot)

    payload = json.loads(path.read_text())
    assert payload["day_evidence"]["sf"]["2026-10-05"] == {
        "displayed_count": 1, "confirmed": True, "selected_label": "Monday, Oct 5"
    }
    assert read_snapshot(path).day_evidence == snapshot.day_evidence


def test_city_scoped_serialized_rejection_does_not_poison_other_city(tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, _snapshot(rejected=(RejectedRecord("normalization_error", city="sf"),)))

    replayed = read_snapshot(path)

    assert not replayed.health_for("sf").healthy
    assert replayed.health_for("la").healthy


def test_legacy_cityless_rejection_still_fails_closed_for_every_city(tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, _snapshot(rejected=(RejectedRecord("normalization_error"),)))

    replayed = read_snapshot(path)

    assert not replayed.health_for("sf").healthy
    assert not replayed.health_for("la").healthy


def test_replay_withholds_event_from_unexpected_source_day(tmp_path):
    path = tmp_path / "snapshot.json"
    snapshot = _snapshot()
    # The same rotating link and title may occur in a valid row; its day must
    # still be part of replay matching so this out-of-range row is withheld.
    unexpected = Event("sf", "sf event 5", date(2026, 9, 1), date(2026, 9, 2), True,
                       source_url="https://source.example/sf/5", timing_quality=TimingQuality.ALL_DAY)
    write_snapshot(path, replace(snapshot, events=snapshot.events + (unexpected,)))

    replayed = read_snapshot(path)

    assert all(event.start != date(2026, 9, 1) for event in replayed.events)
    assert not replayed.health_for("sf").healthy


def test_malformed_day_evidence_value_fails_closed_without_crashing(tmp_path):
    path = tmp_path / "snapshot.json"
    write_snapshot(path, _snapshot())
    payload = json.loads(path.read_text())
    payload["day_evidence"]["sf"]["2026-10-05"] = ["not", "an", "object"]
    path.write_text(json.dumps(payload))

    replayed = read_snapshot(path)

    assert not replayed.health_for("sf").healthy
    assert replayed.health_for("la").healthy

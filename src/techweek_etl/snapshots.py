"""Versioned, defensive JSON snapshots for source replay."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timezone
import json
from pathlib import Path

from .browser import CITY_DATES, CityTraversal, DayEvidence, RawEvent
from .extract import normalize_city_traversal
from .identity import build_identity
from .models import CityHealth, Event, IdentityConfidence, RejectedRecord, Snapshot, TimingQuality

SNAPSHOT_VERSION = 2

def _event_json(event: Event) -> dict:
    return {"city": event.city, "title": event.title, "start": event.start.isoformat(), "end": event.end.isoformat(),
            "all_day": event.all_day, "description": event.description, "source_url": event.source_url,
            "registration_url": event.registration_url, "identity": event.identity,
            "identity_confidence": event.identity_confidence.value, "timing_quality": event.timing_quality.value,
            "source_urls": list(event.source_urls), "metadata": event.metadata}

def _health_json(health: CityHealth) -> dict:
    value = asdict(health); value["issues"] = list(health.issues); return value

def write_snapshot(path: Path | str, snapshot: Snapshot, *, day_evidence: dict[str, dict[str, int] | tuple[DayEvidence, ...]] | None = None) -> None:
    """Persist event data plus date/count evidence needed to independently replay health."""
    supplied = day_evidence or snapshot.day_evidence or {}
    evidence: dict[str, dict[str, dict]] = {}
    for health in snapshot.city_health:
        city = health.city
        source = supplied.get(city, {})
        if isinstance(source, dict):
            evidence[city] = {str(day): {"displayed_count": count, "confirmed": True} for day, count in source.items()}
        else:
            evidence[city] = {entry.day.isoformat(): {"displayed_count": entry.displayed_count, "confirmed": entry.confirmed,
                                                       "selected_label": entry.selected_label} for entry in source}
    payload = {"version": SNAPSHOT_VERSION, "created_at": snapshot.created_at.astimezone(timezone.utc).isoformat(),
               "events": [_event_json(event) for event in snapshot.events], "city_health": [_health_json(item) for item in snapshot.city_health],
               "rejected": [asdict(item) for item in snapshot.rejected], "day_evidence": evidence}
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def _parse_event(value: dict) -> Event:
    all_day = bool(value["all_day"])
    start = date.fromisoformat(value["start"]) if all_day else datetime.fromisoformat(value["start"])
    end = date.fromisoformat(value["end"]) if all_day else datetime.fromisoformat(value["end"])
    event = Event(value["city"], value["title"], start, end, all_day, value.get("description", ""), value.get("source_url", ""),
                  value.get("registration_url", ""), timing_quality=TimingQuality(value.get("timing_quality", "exact")),
                  source_urls=tuple(value.get("source_urls", ())), metadata=value.get("metadata", {}))
    identity, confidence = build_identity(event)
    return event.with_identity(identity, confidence)

def read_snapshot(path: Path | str) -> Snapshot:
    """Read and independently recompute identities, counts, and city health.

    Stored healthy flags are evidence only and never trusted on replay.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("version") != SNAPSHOT_VERSION:
        raise ValueError(f"unsupported snapshot version: {payload.get('version')!r}")
    events = tuple(_parse_event(value) for value in payload.get("events", ()))
    prior = {item["city"].lower(): item for item in payload.get("city_health", ())}
    evidence_payload = payload.get("day_evidence", {})
    health: list[CityHealth] = []; rejected: list[RejectedRecord] = [RejectedRecord(**item) for item in payload.get("rejected", ())]
    for city in sorted({event.city for event in events} | set(prior)):
        expected = CITY_DATES.get(city)
        if not expected:
            continue
        day_data = evidence_payload.get(city, {})
        evidence: list[DayEvidence] = []
        malformed = False
        for raw_day, value in day_data.items():
            try:
                evidence.append(DayEvidence(date.fromisoformat(raw_day), value.get("displayed_count"), bool(value.get("confirmed")), value.get("selected_label", "")))
            except (TypeError, ValueError):
                malformed = True
        raw_rows = []
        for event in events:
            if event.city != city:
                continue
            day = event.start if event.all_day else event.start.date()
            raw_rows.append(RawEvent(city, day, event.title, "" if event.all_day else event.start.strftime("%-I:%M%p"), event.source_url, event.registration_url, event.description))
        previous_count = prior.get(city, {}).get("previous_healthy_count")
        stored = prior.get(city, {})
        stored_issues = tuple(stored.get("issues", ()))
        traversal = CityTraversal(city, tuple(raw_rows), expected, tuple(evidence),
                                  stored.get("displayed_count"), bool(stored.get("traversal_complete", False)),
                                  stored_issues + (("malformed day evidence",) if malformed else ()))
        _, recomputed, local_rejected = normalize_city_traversal(traversal, previous_healthy_count=previous_count)
        # Replay must retain serialized all-day/default timing exactly; use its
        # validation and count evidence, while preserving parsed events above.
        # Any serialized rejection or failed validation is a permanent reason to
        # fail closed on replay, even if present rows happen to reconcile.
        if rejected or not stored.get("validation_complete", True):
            recomputed = CityHealth(recomputed.city, recomputed.expected_days, recomputed.traversed_days,
                                    recomputed.zero_event_days, recomputed.displayed_count, recomputed.collected_count,
                                    recomputed.traversal_complete, False, recomputed.previous_healthy_count,
                                    tuple(dict.fromkeys(recomputed.issues + ("serialized rejected/invalid records",))))
        health.append(recomputed); rejected.extend(local_rejected)
    created = datetime.fromisoformat(payload["created_at"])
    return Snapshot(events, tuple(health), created, version=SNAPSHOT_VERSION, rejected=tuple(rejected), day_evidence=evidence_payload)

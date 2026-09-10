"""Pure source normalization and the CLI-facing snapshot extraction API."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import re
from typing import Callable, Iterable

from .browser import CITY_DATES, CityTraversal, RawEvent, collect_city, resolve_redirects
from .identity import build_identity, canonical_registration_url
from .models import CityHealth, Event, RejectedRecord, Snapshot
from .normalize import normalize_event_timing


def _time_from_text(value: str):
    match = re.search(r"\b(\d{1,2}:\d{2}\s*[ap]m|\d{1,2}\s*[ap]m)\b", value, re.I)
    if not match:
        return None
    normalized = match.group(1).replace(" ", "").upper()
    for pattern in ("%I:%M%p", "%I%p"):
        try:
            return datetime.strptime(normalized, pattern).time()
        except ValueError:
            pass
    return None


def normalize_city_traversal(traversal: CityTraversal, *, previous_healthy_count: int | None = None):
    """Normalize one traversal and fail city health closed on evidence/data loss."""
    city = traversal.city.lower()
    expected = tuple(CITY_DATES.get(city, traversal.expected_days))
    rejected: list[RejectedRecord] = []
    events: list[Event] = []
    seen_source: set[tuple[object, str, str, str]] = set()
    for raw in traversal.raw_events:
        if raw.city.lower() != city or raw.day not in expected:
            rejected.append(RejectedRecord("unexpected_source_day", raw.source_url, raw.day.isoformat(), city))
            continue
        key = (raw.day, raw.source_url, raw.title.strip().casefold(), raw.time_text.strip().casefold())
        if key in seen_source:
            continue
        seen_source.add(key)
        try:
            clock = _time_from_text(raw.time_text)
            if clock is None:
                start, end, all_day, quality = normalize_event_timing(raw.day, has_time=False)
            else:
                start, end, all_day, quality = normalize_event_timing(datetime.combine(raw.day, clock))
            event = Event(city, raw.title.strip(), start, end, all_day, raw.description.strip(), raw.source_url,
                          raw.registration_url, timing_quality=quality, source_urls=(raw.source_url,))
            identity, confidence = build_identity(event)
            events.append(event.with_identity(identity, confidence))
        except (TypeError, ValueError) as exc:
            rejected.append(RejectedRecord("normalization_error", raw.source_url, str(exc), city))
    # A destination is one registration event. Multiple distinct occurrences with
    # one canonical destination are ambiguous and therefore withheld for review.
    canonical_occurrences: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for event in events:
        if event.identity_confidence.value == "canonical":
            canonical_occurrences[event.identity or ""].add((event.title.casefold(), event.start.isoformat(), event.end.isoformat()))
    conflicts = {identity for identity, occurrences in canonical_occurrences.items() if len(occurrences) > 1}
    if conflicts:
        rejected.extend(RejectedRecord("conflicting_destination_occurrence", "", identity, city)
                        for identity in sorted(conflicts))
        events = [event for event in events if event.identity not in conflicts]
    # Multiple rotating source links for precisely the same occurrence become one
    # normalized event, retaining every source link for descriptions/review.
    merged: dict[str, Event] = {}
    for event in events:
        old = merged.get(event.identity or "")
        if old is None:
            merged[event.identity or ""] = event
        else:
            merged[event.identity or ""] = replace(old, source_urls=tuple(dict.fromkeys(old.source_urls + event.source_urls)))
    events = list(merged.values())
    evidence_by_day = {item.day: item for item in traversal.day_evidence}
    evidence_valid = len(evidence_by_day) == len(expected) and set(evidence_by_day) == set(expected)
    issues = list(traversal.issues)
    if not evidence_valid:
        issues.append("day evidence does not exactly cover expected dates")
    counts = Counter(event.start if event.all_day else event.start.date() for event in events)
    for day in expected:
        item = evidence_by_day.get(day)
        if item is None or not item.confirmed:
            issues.append(f"unconfirmed day {day.isoformat()}")
        elif item.displayed_count is None:
            issues.append(f"missing count {day.isoformat()}")
        elif item.displayed_count != counts[day]:
            issues.append(f"day count mismatch {day.isoformat()}: displayed {item.displayed_count}, collected {counts[day]}")
    aggregate = traversal.displayed_count
    if aggregate is None:
        # Per-day evidence is an equally authoritative aggregate when every day is confirmed.
        aggregate = sum(item.displayed_count or 0 for item in evidence_by_day.values()) if evidence_valid else None
    if aggregate != len(events):
        issues.append(f"aggregate count mismatch: displayed {aggregate}, collected {len(events)}")
    if rejected:
        issues.append("rejected or conflicting source records")
    health = CityHealth(city, len(expected), len(set(evidence_by_day) & set(expected)),
                        sum(1 for item in evidence_by_day.values() if item.displayed_count == 0), aggregate,
                        len(events), traversal.traversal_complete, not rejected, previous_healthy_count,
                        tuple(dict.fromkeys(issues)))
    return tuple(events), health, tuple(rejected)


def extract_snapshot(cities: Iterable[str] = ("sf", "la"), previous_counts: dict[str, int] | None = None,
                     *, collector: Callable[[str], CityTraversal] = collect_city,
                     redirect_resolver: Callable[[Iterable[RawEvent]], tuple[RawEvent, ...]] = resolve_redirects) -> Snapshot:
    """Collect, resolve, normalize, and health-gate the requested cities.

    Dependency injection keeps fixture tests and snapshot replay free of a browser.
    """
    previous_counts = previous_counts or {}
    events: list[Event] = []
    health: list[CityHealth] = []
    rejected: list[RejectedRecord] = []
    evidence: dict[str, dict[str, dict[str, object]]] = {}
    for requested in cities:
        city = requested.lower()
        traversal = collector(city)
        resolved = redirect_resolver(traversal.raw_events)
        traversal = replace(traversal, raw_events=tuple(resolved))
        evidence[city] = {entry.day.isoformat(): {"displayed_count": entry.displayed_count,
                                                   "confirmed": entry.confirmed,
                                                   "selected_label": entry.selected_label}
                          for entry in traversal.day_evidence}
        normalized, city_health, city_rejected = normalize_city_traversal(
            traversal, previous_healthy_count=previous_counts.get(city))
        events.extend(normalized); health.append(city_health); rejected.extend(city_rejected)
    return Snapshot(tuple(events), tuple(health), datetime.now(timezone.utc), version=2,
                    rejected=tuple(rejected), day_evidence=evidence)

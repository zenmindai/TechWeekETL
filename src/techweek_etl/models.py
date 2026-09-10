"""Stable data contracts shared by discovery, planning, and calendar layers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class IdentityConfidence(StrEnum):
    CANONICAL = "canonical"
    FALLBACK = "fallback"


class TimingQuality(StrEnum):
    EXACT = "exact"
    DEFAULT_DURATION = "default_duration"
    ALL_DAY = "all_day"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Event:
    city: str
    title: str
    start: datetime | date
    end: datetime | date
    all_day: bool = False
    description: str = ""
    source_url: str = ""
    registration_url: str = ""
    identity: str | None = None
    identity_confidence: IdentityConfidence = IdentityConfidence.FALLBACK
    timing_quality: TimingQuality = TimingQuality.EXACT
    source_urls: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False, hash=False, repr=False)

    def __post_init__(self) -> None:
        city = self.city.strip().lower()
        if city not in {"sf", "la"}:
            raise ValueError("city must be 'sf' or 'la'")
        if not self.title.strip():
            raise ValueError("event title is required")
        if self.all_day:
            if not isinstance(self.start, date) or isinstance(self.start, datetime):
                raise ValueError("all-day events use date start/end values")
            if not isinstance(self.end, date) or isinstance(self.end, datetime):
                raise ValueError("all-day events use date start/end values")
        elif not isinstance(self.start, datetime) or not isinstance(self.end, datetime):
            raise ValueError("timed events use datetime start/end values")
        elif self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("timed events must use timezone-aware datetimes")
        if self.end <= self.start:
            raise ValueError("event end must be after start")
        object.__setattr__(self, "city", city)

    def with_identity(self, identity: str, confidence: IdentityConfidence) -> "Event":
        return replace(self, identity=identity, identity_confidence=confidence)


@dataclass(frozen=True, slots=True)
class CityHealth:
    city: str
    expected_days: int
    traversed_days: int
    zero_event_days: int
    displayed_count: int | None
    collected_count: int
    traversal_complete: bool
    validation_complete: bool = True
    previous_healthy_count: int | None = None
    issues: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        count_floor = self.previous_healthy_count is None or self.collected_count >= self.previous_healthy_count * 0.8
        reconciled = self.displayed_count is not None and self.displayed_count == self.collected_count
        all_days_traversed = self.expected_days > 0 and self.expected_days == self.traversed_days
        return self.traversal_complete and self.validation_complete and all_days_traversed and count_floor and reconciled and not self.issues


@dataclass(frozen=True, slots=True)
class RejectedRecord:
    reason: str
    source_url: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Snapshot:
    events: tuple[Event, ...]
    city_health: tuple[CityHealth, ...]
    created_at: datetime
    version: int = 1
    rejected: tuple[RejectedRecord, ...] = ()
    # Raw date/count evidence is retained so a normal extraction can be replayed
    # without trusting the previous health verdict.
    day_evidence: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict, compare=False, hash=False, repr=False)

    def health_for(self, city: str) -> CityHealth | None:
        return next((health for health in self.city_health if health.city == city.lower()), None)

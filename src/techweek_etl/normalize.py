"""Timezone-safe normalization for incomplete source timing."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .config import PACIFIC
from .models import TimingQuality


def pacific_datetime(value: datetime) -> datetime:
    """Interpret naive source values as Pacific and convert aware values to Pacific."""
    return value.replace(tzinfo=PACIFIC) if value.tzinfo is None else value.astimezone(PACIFIC)


def normalize_event_timing(
    start: date | datetime,
    end: date | datetime | None = None,
    *,
    has_time: bool = True,
    default_duration: timedelta = timedelta(hours=1),
) -> tuple[date | datetime, date | datetime, bool, TimingQuality]:
    """Return normalized start/end, all_day flag, and confidence in supplied timing."""
    if not has_time or (isinstance(start, date) and not isinstance(start, datetime)):
        start_date = pacific_datetime(start).date() if isinstance(start, datetime) else start
        if isinstance(end, datetime):
            end_date = pacific_datetime(end).date()
        elif isinstance(end, date):
            end_date = end
        else:
            end_date = start_date
        # Google all-day end dates are exclusive.
        return start_date, end_date + timedelta(days=1), True, TimingQuality.ALL_DAY
    if not isinstance(start, datetime):
        start = datetime.combine(start, time.min)
    normalized_start = pacific_datetime(start)
    if end is None:
        return normalized_start, normalized_start + default_duration, False, TimingQuality.DEFAULT_DURATION
    if not isinstance(end, datetime):
        end = datetime.combine(end, time.min)
    normalized_end = pacific_datetime(end)
    if normalized_end <= normalized_start:
        normalized_end = normalized_start + default_duration
        return normalized_start, normalized_end, False, TimingQuality.DEFAULT_DURATION
    return normalized_start, normalized_end, False, TimingQuality.EXACT

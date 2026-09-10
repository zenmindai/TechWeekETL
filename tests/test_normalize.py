from datetime import date, datetime, timedelta

from techweek_etl.config import PACIFIC
from techweek_etl.models import TimingQuality
from techweek_etl.normalize import normalize_event_timing


def test_naive_time_is_pacific_even_when_host_timezone_differs() -> None:
    start, end, all_day, quality = normalize_event_timing(datetime(2026, 10, 12, 23, 30))
    assert start == datetime(2026, 10, 12, 23, 30, tzinfo=PACIFIC)
    assert end == datetime(2026, 10, 13, 0, 30, tzinfo=PACIFIC)
    assert not all_day
    assert quality == TimingQuality.DEFAULT_DURATION


def test_all_day_end_is_exclusive() -> None:
    start, end, all_day, quality = normalize_event_timing(date(2026, 10, 12), has_time=False)
    assert (start, end, all_day, quality) == (date(2026, 10, 12), date(2026, 10, 13), True, TimingQuality.ALL_DAY)


def test_midnight_end_defaults_to_an_hour_when_source_end_is_not_after_start() -> None:
    start, end, all_day, quality = normalize_event_timing(datetime(2026, 10, 12), datetime(2026, 10, 12))
    assert end - start == timedelta(hours=1)
    assert not all_day
    assert quality == TimingQuality.DEFAULT_DURATION

"""Independent acceptance probes; imports production code through PYTHONPATH."""
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from techweek_etl.identity import canonical_registration_url, build_identity, event_material_hash
from techweek_etl.models import CityHealth, Event, IdentityConfidence
from techweek_etl.normalize import normalize_event_timing
from techweek_etl.state import AppLock, StateStore


class ReviewRegressions(unittest.TestCase):
    def test_incomplete_days_fail_closed(self):
        self.assertFalse(CityHealth('sf', 7, 1, 0, 5, 5, True).healthy)

    def test_missing_counts_fail_closed(self):
        self.assertFalse(CityHealth('sf', 7, 7, 0, None, 5, True).healthy)

    def test_meaningful_query_preserved(self):
        for key in ('ref', 'source', 'referrer', 'event_id'):
            with self.subTest(key=key):
                self.assertNotEqual(canonical_registration_url(f'https://example.com/register?{key}=a'),
                                    canonical_registration_url(f'https://example.com/register?{key}=b'))

    def test_hash_routes_preserved(self):
        self.assertNotEqual(canonical_registration_url('https://example.com/#/event/a'),
                            canonical_registration_url('https://example.com/#/event/b'))

    def test_tracking_removed(self):
        self.assertEqual(canonical_registration_url('https://example.com/register?id=a&utm_source=x'),
                         canonical_registration_url('https://example.com/register?id=a&utm_source=y'))

    def test_rotating_link_does_not_change_identity_or_material_hash(self):
        start, end, all_day, quality = normalize_event_timing(datetime(2026, 6, 1, 9))
        a = Event('sf', 'Example', start, end, source_url='https://www.tech-week.com/go/event/a',
                  registration_url='https://example.com/e/42', timing_quality=quality)
        b = replace(a, source_url='https://www.tech-week.com/go/event/b', metadata={'retrieved_at': 'later'})
        self.assertEqual(build_identity(a), build_identity(b))
        self.assertEqual(event_material_hash(a), event_material_hash(b))

    def test_unresolved_rotating_destination_uses_fallback(self):
        start, end, _, quality = normalize_event_timing(datetime(2026, 6, 1, 9))
        for host in ('www.tech-week.com', 'tech-week.com', 'www.tech-week.com:443'):
            with self.subTest(host=host):
                event = Event('sf', 'Example', start, end, registration_url=f'https://{host}/go/event/a', timing_quality=quality)
                changed = replace(event, registration_url=f'https://{host}/go/event/b')
                self.assertEqual(build_identity(event)[1], IdentityConfidence.FALLBACK)
                self.assertEqual(build_identity(event), build_identity(changed))
                self.assertEqual(event_material_hash(event), event_material_hash(changed))

    def test_aware_date_only_uses_pacific_date(self):
        start, end, all_day, quality = normalize_event_timing(datetime(2026, 6, 2, 1, tzinfo=timezone.utc), has_time=False)
        self.assertEqual((start, end, all_day), (date(2026, 6, 1), date(2026, 6, 2), True))

    def test_naive_time_is_pacific(self):
        start, end, *_ = normalize_event_timing(datetime(2026, 6, 1, 0))
        self.assertEqual(start.isoformat(), '2026-06-01T00:00:00-07:00')
        self.assertEqual(end.isoformat(), '2026-06-01T01:00:00-07:00')

    def test_transaction_rollback_and_readonly_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.sqlite'
            with StateStore(path) as state:
                with self.assertRaises(ValueError):
                    with state.transaction():
                        state.upsert_identity('id', 'google', 'hash', 'canonical')
                        raise ValueError('abort')
                self.assertIsNone(state.get_identity('id'))
                with state.transaction():
                    state.upsert_identity('id', 'google', 'hash', 'canonical')
            before = path.read_bytes()
            with StateStore(path, read_only=True) as state:
                self.assertEqual(state.get_identity('id')['calendar_event_id'], 'google')
                with self.assertRaises(RuntimeError):
                    state.record_outcome('id', 'update')
            self.assertEqual(path.read_bytes(), before)

    def test_first_use_readonly_creates_no_durable_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing' / 'state.sqlite'
            with StateStore(path, read_only=True) as state:
                self.assertEqual(state.mappings(), [])
                self.assertIsNone(state.get_baseline('sf'))
            self.assertFalse(path.parent.exists())

    def test_dismissal_and_successful_payload_survive_mapping_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.sqlite'
            with StateStore(path) as state:
                with state.transaction():
                    state.upsert_identity('id', 'google', 'hash', 'canonical', successful_payload='{"summary":"old"}')
                    state.set_dismissal('id')
                with state.transaction():
                    state.upsert_identity('id', 'google', 'hash', 'canonical')
            with StateStore(path, read_only=True) as state:
                row = state.get_identity('id')
                self.assertEqual(row['dismissal_status'], 'DISMISSED')
                self.assertEqual(row['successful_payload'], '{"summary":"old"}')

    def test_lock_excludes_second_run_and_releases_after_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.lock'
            with self.assertRaises(ValueError):
                with AppLock(path):
                    with self.assertRaises(RuntimeError):
                        with AppLock(path):
                            self.fail('overlap allowed')
                    raise ValueError('abort')
            with AppLock(path):
                pass

if __name__ == '__main__':
    unittest.main()

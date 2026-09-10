from pathlib import Path

import pytest

from techweek_etl.state import AppLock, StateStore


def test_transaction_rolls_back_after_failure(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    with StateStore(path) as state:
        with pytest.raises(ValueError):
            with state.transaction():
                state.upsert_identity("id", "calendar", "hash", "canonical")
                raise ValueError("stop")
        assert state.get_identity("id") is None


def test_read_only_store_rejects_all_state_changes(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    with StateStore(path) as state:
        with state.transaction():
            state.set_baseline("sf", 12)
    with StateStore(path, read_only=True) as dry_run:
        assert dry_run.get_baseline("sf") == 12
        with pytest.raises(RuntimeError, match="read-only"):
            dry_run.set_baseline("sf", 13)
        with pytest.raises(RuntimeError, match="read-only"):
            with dry_run.transaction():
                pass
    with StateStore(path, read_only=True) as dry_run:
        assert dry_run.get_baseline("sf") == 12


def test_read_only_first_run_creates_no_database(tmp_path: Path) -> None:
    path = tmp_path / "absent.sqlite"
    with StateStore(path, read_only=True) as dry_run:
        assert dry_run.get_baseline("sf") is None
    assert not path.exists()


def test_normal_upsert_does_not_restore_a_dismissed_identity(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    with StateStore(path) as state:
        with state.transaction():
            state.upsert_identity("id", "calendar", "hash", "canonical", dismissal_status="DISMISSED")
        with state.transaction():
            state.upsert_identity("id", "calendar", "updated", "canonical")
        assert state.get_identity("id")["dismissal_status"] == "DISMISSED"


def test_application_lock_excludes_an_overlapping_run(tmp_path: Path) -> None:
    lock_path = tmp_path / "app.lock"
    with AppLock(lock_path):
        with pytest.raises(RuntimeError, match="another techweek-etl run"):
            with AppLock(lock_path):
                pass
    with AppLock(lock_path):
        pass

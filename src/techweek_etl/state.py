"""Small durable state store with transaction and single-run safety."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from pathlib import Path
import sqlite3
from typing import Iterator


class AppLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._handle = None

    def __enter__(self) -> "AppLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._handle.close()
            self._handle = None
            raise RuntimeError("another techweek-etl run holds the application lock") from None
        return self

    def __exit__(self, *_: object) -> None:
        if self._handle:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


class StateStore:
    def __init__(self, path: Path, *, read_only: bool = False):
        self.path = Path(path)
        self.read_only = read_only
        if read_only:
            if self.path.exists():
                self.connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            else:
                # Dry runs against a first-use path get an empty ephemeral store.
                self.connection = sqlite3.connect(":memory:")
                self._initialize()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path)
            self._initialize()
        self.connection.row_factory = sqlite3.Row

    def _initialize(self) -> None:
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS identities (
          identity TEXT PRIMARY KEY, calendar_event_id TEXT, material_hash TEXT,
          confidence TEXT NOT NULL, dismissal_status TEXT, successful_payload TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS outcomes (
          id INTEGER PRIMARY KEY, identity TEXT, action TEXT NOT NULL, detail TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS healthy_baselines (
          city TEXT PRIMARY KEY, event_count INTEGER NOT NULL, snapshot_at TEXT NOT NULL
        );
        """)
        # Existing local state from an earlier build can be upgraded in place.
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(identities)")}
        for column in ("dismissal_status", "successful_payload"):
            if column not in columns:
                self.connection.execute(f"ALTER TABLE identities ADD COLUMN {column} TEXT")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "StateStore": return self
    def __exit__(self, *_: object) -> None: self.close()

    @contextmanager
    def transaction(self) -> Iterator["StateStore"]:
        if self.read_only:
            raise RuntimeError("dry-run state store is read-only")
        try:
            self.connection.execute("BEGIN")
            yield self
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def get_identity(self, identity: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM identities WHERE identity = ?", (identity,)).fetchone()

    def mappings(self) -> list[sqlite3.Row]:
        return list(self.connection.execute("SELECT * FROM identities ORDER BY identity"))

    def upsert_identity(self, identity: str, calendar_event_id: str | None, material_hash: str | None, confidence: str, *, successful_payload: str | None = None, dismissal_status: str | None = None) -> None:
        self._require_write()
        self.connection.execute("""INSERT INTO identities(identity, calendar_event_id, material_hash, confidence, dismissal_status, successful_payload, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(identity) DO UPDATE SET calendar_event_id=excluded.calendar_event_id,
        material_hash=excluded.material_hash, confidence=excluded.confidence, dismissal_status=COALESCE(excluded.dismissal_status, identities.dismissal_status),
        successful_payload=COALESCE(excluded.successful_payload, identities.successful_payload), updated_at=excluded.updated_at""",
        (identity, calendar_event_id, material_hash, confidence, dismissal_status, successful_payload, _now()))

    def set_dismissal(self, identity: str, status: str = "DISMISSED") -> None:
        self._require_write()
        self.connection.execute("UPDATE identities SET dismissal_status = ?, updated_at = ? WHERE identity = ?", (status, _now(), identity))

    def record_outcome(self, identity: str | None, action: str, detail: str = "") -> None:
        self._require_write()
        self.connection.execute("INSERT INTO outcomes(identity, action, detail, created_at) VALUES (?, ?, ?, ?)", (identity, action, detail, _now()))

    def get_baseline(self, city: str) -> int | None:
        row = self.connection.execute("SELECT event_count FROM healthy_baselines WHERE city = ?", (city.lower(),)).fetchone()
        return None if row is None else int(row[0])

    def set_baseline(self, city: str, event_count: int) -> None:
        self._require_write()
        self.connection.execute("""INSERT INTO healthy_baselines(city, event_count, snapshot_at) VALUES (?, ?, ?)
        ON CONFLICT(city) DO UPDATE SET event_count=excluded.event_count, snapshot_at=excluded.snapshot_at""", (city.lower(), event_count, _now()))

    def _require_write(self) -> None:
        if self.read_only:
            raise RuntimeError("dry-run state store is read-only")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

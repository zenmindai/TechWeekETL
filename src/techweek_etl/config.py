"""Runtime paths and fixed project defaults."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True, slots=True)
class Settings:
    """Filesystem locations.  Keep durable data out of the repository."""

    app_dir: Path
    database_path: Path
    lock_path: Path

    @classmethod
    def default(cls) -> "Settings":
        app_dir = Path.home() / "Library" / "Application Support" / "techweek-etl"
        return cls(app_dir, app_dir / "state.sqlite", app_dir / "techweek-etl.lock")

    def ensure_directories(self) -> None:
        self.app_dir.mkdir(parents=True, exist_ok=True)

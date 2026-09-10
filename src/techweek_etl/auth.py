"""Explicit desktop OAuth setup and unattended refresh-token loading."""
from __future__ import annotations

from pathlib import Path
import os
import tempfile
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ("https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.calendarlist.readonly")


def authorize_desktop(client_file: Path, token_file: Path) -> None:
    """The only OAuth path allowed to open a browser, called by an explicit auth command."""
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
    credentials = flow.run_local_server(port=0)
    _write_token(Path(token_file), credentials.to_json())


def build_calendar_service(token_file: Path) -> Any:
    """Load or refresh a prior desktop credential without any browser interaction."""
    token_path = Path(token_file)
    token_path = Path(token_path)
    credentials: Credentials | None = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _write_token(token_path, credentials.to_json())
    if not credentials or not credentials.valid or not credentials.has_scopes(SCOPES):
        raise RuntimeError("Calendar authorization is absent or expired; run the explicit auth setup command")
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _write_token(path: Path, content: str) -> None:
    """Atomically replace an OAuth token with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

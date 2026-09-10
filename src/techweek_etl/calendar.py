"""Google Calendar reads and payload construction.  This module never writes."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Iterable
from urllib.parse import urlsplit

from .config import PACIFIC
from .identity import canonical_registration_url
from .models import Event

ACCOUNT_EMAIL = "zenmindai@gmail.com"
CANDIDATE_CALENDAR_ID = "1cc8e5965d1ae7526d61b8d9828b5b7448900d410affd1e0c59e943678b6d053@group.calendar.google.com"
MANAGED_KEY = "techweek_etl"
MANAGED_START = "<!-- techweek-etl:start -->"
MANAGED_END = "<!-- techweek-etl:end -->"
PROTECTED_MARKERS = ("tech week, sf", "tech week, la")


@dataclass(frozen=True, slots=True)
class CalendarTarget:
    account_email: str
    calendar_id: str
    timezone: str


def verify_calendar_access(service: Any, calendar_id: str = CANDIDATE_CALENDAR_ID, *, expected_account: str = ACCOUNT_EMAIL) -> CalendarTarget:
    """Fail closed unless the authenticated account and candidate calendar are exact."""
    primary: dict[str, Any] | None = None
    page_token: str | None = None
    while True:
        response = service.calendarList().list(pageToken=page_token).execute()
        for item in response.get("items", []):
            if item.get("primary"):
                primary = item
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    if primary is None or primary.get("id", "").casefold() != expected_account.casefold():
        raise RuntimeError(f"Google OAuth account is not {expected_account}")
    calendar = next((item for item in _calendar_list(service) if item.get("id") == calendar_id), None)
    if calendar is None:
        raise RuntimeError("configured Candidate Events calendar is not in the authenticated account's calendar list")
    if calendar.get("summary") != "Candidate Events":
        raise RuntimeError("configured calendar is not named Candidate Events")
    if calendar.get("timeZone") != "America/Los_Angeles":
        raise RuntimeError("Candidate Events calendar must use America/Los_Angeles")
    if calendar.get("accessRole") not in {"owner", "writer"}:
        raise RuntimeError("Candidate Events calendar is not writable by zenmindai@gmail.com")
    return CalendarTarget(expected_account, calendar_id, calendar["timeZone"])


def _calendar_list(service: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        response = service.calendarList().list(pageToken=token).execute()
        items.extend(response.get("items", []))
        token = response.get("nextPageToken")
        if not token:
            return items


def inventory_events(service: Any, target: CalendarTarget) -> list[dict[str, Any]]:
    """Read every event, including cancelled records, without a date window."""
    events: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        response = service.events().list(
            calendarId=target.calendar_id, pageToken=token, showDeleted=True, singleEvents=False,
        ).execute()
        events.extend(response.get("items", []))
        token = response.get("nextPageToken")
        if not token:
            return events


def deterministic_event_id(identity: str) -> str:
    # Google accepts lowercase base32hex; a prefix avoids a numeric first character.
    encoded = base64.b32hexencode(hashlib.sha256(identity.encode("utf-8")).digest()).decode("ascii").rstrip("=").lower()
    return "te" + encoded


def identity_tag(identity: str) -> str:
    """Short private-property value used because Calendar caps values at 1024 bytes."""
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def managed_metadata(event: dict[str, Any]) -> dict[str, Any] | None:
    raw = event.get("extendedProperties", {}).get("private", {}).get(MANAGED_KEY)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    # Read the early/raw format too, so a local-state loss can still discover it.
    if not value.get("identity_tag") and value.get("identity"):
        value = {**value, "identity_tag": identity_tag(str(value["identity"]))}
    return value if value.get("identity_tag") else None


def is_protected(event: dict[str, Any]) -> bool:
    text = " ".join(str(event.get(key, "")) for key in ("summary", "description")).casefold()
    private = event.get("extendedProperties", {}).get("private", {})
    return any(marker in text for marker in PROTECTED_MARKERS) or any(
        token in str(key).casefold() for key in private for token in ("cron", "sync", "managed_by")
    )


def exact_event_urls(event: dict[str, Any]) -> set[str]:
    values = [event.get("htmlLink", ""), event.get("location", ""), event.get("description", "")]
    private = event.get("extendedProperties", {}).get("private", {})
    values.extend(str(value) for value in private.values())
    urls: set[str] = set()
    for value in values:
        for raw in re.findall(r"https?://[^\s<>()\[\]\"']+", value):
            candidate = raw.rstrip(".,;:!?)]")
            parsed = urlsplit(candidate)
            if parsed.netloc:
                urls.add(canonical_registration_url(candidate))
    return urls


def event_with_preserved_enrichment(event: Event, existing: dict[str, Any] | None) -> Event:
    """Carry forward useful managed enrichment when a later scrape has none."""
    if event.description.strip() or not existing:
        return event
    previous = str(existing.get("description", ""))
    match = re.search(re.escape(MANAGED_START) + r"(.*?)" + re.escape(MANAGED_END), previous, re.DOTALL)
    if not match:
        return event
    lines = [line.strip() for line in match.group(1).splitlines()]
    content = [line for line in lines if line and not line.startswith(("Tech Week ", "Registration: ", "Source: ", "Timing: "))]
    return replace(event, description="\n".join(content).strip()) if content else event


def event_payload(event: Event, *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return only source-owned fields for PATCH, retaining useful old enrichment."""
    previous_description = "" if existing is None else str(existing.get("description", ""))
    effective = event_with_preserved_enrichment(event, existing)
    if not event.description.strip() and MANAGED_START in previous_description and MANAGED_END in previous_description:
        managed = re.search(re.escape(MANAGED_START) + r".*?" + re.escape(MANAGED_END), previous_description, re.DOTALL).group(0)
    else:
        managed = managed_description(effective)
    description = merge_description(previous_description, managed)
    private = dict((existing or {}).get("extendedProperties", {}).get("private", {}))
    from .identity import event_material_hash
    private[MANAGED_KEY] = json.dumps({
        "identity_tag": identity_tag(event.identity or ""), "city": event.city,
        "material_hash": event_material_hash(effective), "version": 1,
    }, sort_keys=True)
    body: dict[str, Any] = {
        "summary": event.title.strip(), "description": description,
        "extendedProperties": {"private": private},
    }
    if event.all_day:
        body["start"] = {"date": event.start.isoformat()}
        body["end"] = {"date": event.end.isoformat()}
    else:
        body["start"] = {"dateTime": event.start.isoformat(), "timeZone": "America/Los_Angeles"}
        body["end"] = {"dateTime": event.end.isoformat(), "timeZone": "America/Los_Angeles"}
    return body


def insert_payload(event: Event) -> dict[str, Any]:
    body = event_payload(event)
    body["id"] = deterministic_event_id(event.identity or "")
    body["transparency"] = "transparent"
    body["attendees"] = []
    return body


def managed_description(event: Event) -> str:
    lines = [MANAGED_START, f"Tech Week {event.city.upper()} 2026"]
    if event.registration_url:
        lines.append(f"Registration: {event.registration_url}")
    if event.source_url:
        lines.append(f"Source: {event.source_url}")
    if event.timing_quality.value == "default_duration":
        lines.append("Timing: 60-minute approximate duration; check the source for updates")
    elif event.all_day:
        lines.append("Timing: all-day fallback because the source did not provide a start time")
    if event.description.strip():
        lines.extend(("", event.description.strip()))
    lines.append(MANAGED_END)
    return "\n".join(lines)


def merge_description(previous: str, managed: str) -> str:
    pattern = re.compile(re.escape(MANAGED_START) + r".*?" + re.escape(MANAGED_END), re.DOTALL)
    outside = pattern.sub("", previous).strip()
    return f"{outside}\n\n{managed}".strip() if outside else managed

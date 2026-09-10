"""Stable identities and hashes that survive Tech Week redirect rotation."""

from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Event, IdentityConfidence

TRACKING_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "utm_campaign", "utm_content", "utm_id", "utm_medium", "utm_source", "utm_term"})


def canonical_registration_url(url: str) -> str:
    """Preserve meaningful URL data while dropping known tracking query parameters."""
    parts = urlsplit(url.strip())
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in TRACKING_KEYS]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query, doseq=True), parts.fragment))


def is_rotating_techweek_url(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.hostname or "").lower() in {"tech-week.com", "www.tech-week.com"} and parts.path.startswith("/go/event/")


def _year(value: date | datetime) -> int:
    return value.year


def build_identity(event: Event, registration_url: str | None = None) -> tuple[str, IdentityConfidence]:
    destination = canonical_registration_url(registration_url or event.registration_url)
    if destination and urlsplit(destination).netloc and not is_rotating_techweek_url(destination):
        return f"v1:{_year(event.start)}:{event.city}:{destination}", IdentityConfidence.CANONICAL
    start = event.start.isoformat()
    basis = "\x1f".join((event.city, str(_year(event.start)), event.title.strip().casefold(), start))
    return f"v1:fallback:{sha256(basis.encode()).hexdigest()}", IdentityConfidence.FALLBACK


def event_material_hash(event: Event) -> str:
    """Hash content which should drive a calendar update, excluding retrieval/redirect churn."""
    payload = {
        "identity": event.identity,
        "city": event.city,
        "title": event.title.strip(),
        "start": event.start.isoformat(),
        "end": event.end.isoformat(),
        "all_day": event.all_day,
        "description": event.description.strip(),
        "registration_url": "" if is_rotating_techweek_url(event.registration_url) else canonical_registration_url(event.registration_url),
        "timing_quality": event.timing_quality.value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode()).hexdigest()

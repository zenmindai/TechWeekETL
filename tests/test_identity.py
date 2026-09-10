from datetime import datetime

from techweek_etl.config import PACIFIC

from techweek_etl.identity import build_identity, canonical_registration_url, event_material_hash
from techweek_etl.models import Event, IdentityConfidence


def event(*, source_url: str = "", registration_url: str = "https://tickets.example/e/launch?utm_source=tw") -> Event:
    return Event(
        city="sf", title="Launch", start=datetime(2026, 10, 12, 18, tzinfo=PACIFIC), end=datetime(2026, 10, 12, 19, tzinfo=PACIFIC),
        source_url=source_url, registration_url=registration_url,
    )


def test_rotating_techweek_links_share_a_registration_identity_and_hash() -> None:
    first = event(source_url="https://tech-week.com/go/event/a?token=one")
    second = event(source_url="https://tech-week.com/go/event/b?token=two")
    first_id, first_confidence = build_identity(first)
    second_id, second_confidence = build_identity(second)

    assert first_id == second_id == "v1:2026:sf:https://tickets.example/e/launch"
    assert first_confidence == second_confidence == IdentityConfidence.CANONICAL
    assert event_material_hash(first.with_identity(first_id, first_confidence)) == event_material_hash(second.with_identity(second_id, second_confidence))


def test_only_known_tracking_keys_are_removed() -> None:
    assert canonical_registration_url("HTTPS://Tickets.Example/e/x?utm_source=a&seat=vip&ref=b") == "https://tickets.example/e/x?seat=vip&ref=b"


def test_fallback_identity_is_marked_low_confidence_and_stable() -> None:
    identity, confidence = build_identity(event(registration_url=""))
    assert identity.startswith("v1:fallback:")
    assert confidence == IdentityConfidence.FALLBACK

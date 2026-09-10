"""Pure, conservative reconciliation of a snapshot with a Calendar inventory."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping

from .calendar import (
    event_with_preserved_enrichment,
    exact_event_urls,
    identity_tag,
    is_protected,
    managed_metadata,
)
from .identity import canonical_registration_url, event_material_hash
from .models import Event, IdentityConfidence, Snapshot, TimingQuality


@dataclass(frozen=True, slots=True)
class PlanItem:
    action: str  # INSERT, UPDATE, ADOPT, REVIEW, DISMISSED, MISSING, REPORT
    event: Event | None = None
    calendar_event: dict[str, Any] | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SyncPlan:
    items: tuple[PlanItem, ...]
    healthy_cities: frozenset[str]

    @property
    def mutations(self) -> tuple[PlanItem, ...]:
        return tuple(item for item in self.items if item.action in {"INSERT", "UPDATE", "ADOPT"})


def plan_sync(snapshot: Snapshot, inventory: list[dict[str, Any]], state: Any, resolved_links: Mapping[str, str] | None = None) -> SyncPlan:
    """No I/O and no state mutation.  Missing health always blocks that city's writes."""
    resolved_links = resolved_links or {}
    event_cities = {event.city for event in snapshot.events}
    healthy = {city for city in event_cities if _health_ok(snapshot, state, city)}
    managed: dict[str, list[dict[str, Any]]] = {}
    for existing in inventory:
        metadata = managed_metadata(existing)
        if metadata:
            managed.setdefault(str(metadata["identity_tag"]), []).append(existing)
    items: list[PlanItem] = []
    seen: set[str] = set()
    for event in sorted(snapshot.events, key=lambda x: x.identity or ""):
        if not event.identity:
            items.append(PlanItem("REVIEW", event, reason="event has no stable identity")); continue
        seen.add(event.identity)
        if event.city not in healthy:
            items.append(PlanItem("REPORT", event, reason="city health gate failed")); continue
        row = state.get_identity(event.identity)
        if row and row["dismissal_status"] == "DISMISSED":
            items.append(PlanItem("DISMISSED", event, reason="previous manual deletion")); continue
        matches = managed.get(identity_tag(event.identity), [])
        if len(matches) > 1:
            items.append(PlanItem("REVIEW", event, reason="duplicate managed calendar identity")); continue
        existing = matches[0] if matches else None
        if existing is None and row and row["calendar_event_id"]:
            mapped = next((record for record in inventory if record.get("id") == row["calendar_event_id"]), None)
            if mapped and mapped.get("status") == "cancelled":
                items.append(PlanItem("MISSING", event, mapped, "mapped calendar record is cancelled")); continue
        if existing:
            if is_protected(existing):
                items.append(PlanItem("REVIEW", event, existing, "protected calendar event")); continue
            if existing.get("status") == "cancelled":
                items.append(PlanItem("MISSING", event, existing, "managed calendar record is cancelled")); continue
            effective_hash = event_material_hash(event_with_preserved_enrichment(event, existing))
            source_hash = (managed_metadata(existing) or {}).get("material_hash")
            if (row and row["material_hash"] == effective_hash) or source_hash == effective_hash:
                items.append(PlanItem("REPORT", event, existing, "unchanged"))
            else:
                items.append(PlanItem("UPDATE", event, existing, "managed record changed"))
            continue
        if row and row["calendar_event_id"]:
            # A mapped event absent from inventory may be a deletion or incomplete inventory;
            # do not recreate it without investigation.
            items.append(PlanItem("MISSING", event, reason="mapped calendar record absent")); continue
        adopted = _adoption_candidates(event, inventory, resolved_links)
        if len(adopted) == 1:
            items.append(PlanItem("ADOPT", event, adopted[0], "unique exact destination/source URL match"))
        elif len(adopted) > 1:
            items.append(PlanItem("REVIEW", event, reason="ambiguous exact URL adoption"))
        elif event.identity_confidence is not IdentityConfidence.CANONICAL or event.timing_quality is TimingQuality.UNKNOWN:
            items.append(PlanItem("REVIEW", event, reason="uncertain identity or timing"))
        elif _title_time_candidate(event, inventory):
            items.append(PlanItem("REVIEW", event, reason="title/time candidate requires review"))
        else:
            items.append(PlanItem("INSERT", event, reason="new canonical event"))
    seen_tags = {identity_tag(identity) for identity in seen}
    for tag, records in managed.items():
        for existing in records:
          if tag not in seen_tags:
            # Never delete because a source is absent; only report in a healthy city.
              city = managed_metadata(existing).get("city", "") if managed_metadata(existing) else ""
              if city in healthy:
                  items.append(PlanItem("REPORT", None, existing, "source disappeared; no deletion"))
    return SyncPlan(tuple(items), frozenset(healthy))


def _health_ok(snapshot: Snapshot, state: Any, city: str) -> bool:
    health = snapshot.health_for(city)
    if health is None:
        return False
    # Baselines belong to the durable state; source-supplied baseline cannot weaken it.
    prior = state.get_baseline(city)
    if prior is not None and health.collected_count < prior * 0.8:
        return False
    return health.healthy


def _adoption_candidates(event: Event, inventory: list[dict[str, Any]], resolved: Mapping[str, str]) -> list[dict[str, Any]]:
    wanted = _event_urls(event, resolved)
    if not wanted:
        return []
    return [item for item in inventory if not managed_metadata(item) and not is_protected(item) and item.get("status") != "cancelled" and wanted.intersection(_inventory_urls(item, resolved))]


def _event_urls(event: Event, resolved: Mapping[str, str]) -> set[str]:
    raw = (event.registration_url, event.source_url, *event.source_urls)
    result = {canonical_registration_url(resolved.get(url, url)) for url in raw if url}
    return result


def _inventory_urls(item: dict[str, Any], resolved: Mapping[str, str]) -> set[str]:
    return {canonical_registration_url(resolved.get(url, url)) for url in exact_event_urls(item)}


def _title_time_candidate(event: Event, inventory: list[dict[str, Any]]) -> bool:
    for item in inventory:
        if managed_metadata(item) or is_protected(item) or item.get("status") == "cancelled":
            continue
        if str(item.get("summary", "")).strip().casefold() != event.title.strip().casefold():
            continue
        start = item.get("start", {})
        if _same_start(event.start, start):
            return True
    return False


def _same_start(target: date | datetime, value: dict[str, Any]) -> bool:
    if isinstance(target, datetime):
        raw = value.get("dateTime")
        if not raw:
            return False
        try:
            candidate = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return False
        if candidate.tzinfo is None or target.tzinfo is None:
            return candidate == target
        return candidate.timestamp() == target.timestamp()
    return value.get("date") == target.isoformat()

"""Bounded, idempotent Calendar writes for a precomputed SyncPlan."""
from __future__ import annotations

import json
import socket
import time
from typing import Any

from .calendar import CalendarTarget, deterministic_event_id, event_payload, exact_event_urls, identity_tag, insert_payload, is_protected, managed_metadata
from .identity import canonical_registration_url
from .diff import PlanItem, SyncPlan
from .identity import event_material_hash


def execute_plan(service: Any, target: CalendarTarget, plan: SyncPlan, state: Any, *, apply: bool = False, limit: int | None = None) -> list[PlanItem]:
    """Apply at most ``limit`` mutations. Dry-runs make neither Calendar nor state writes."""
    completed: list[PlanItem] = []
    # Diffing may have used an unbound read-only store; writes are always scoped here.
    if getattr(state, "account_email", None) is None:
        state.account_email, state.calendar_id = target.account_email, target.calendar_id
    remaining = limit
    for item in plan.items:
        if item.action == "MISSING" and apply and item.event and item.calendar_event and item.calendar_event.get("status") == "cancelled":
            _persist(state, item.event, item.calendar_event.get("id"), action="DISMISSED", dismissal="DISMISSED")
            completed.append(item)
            continue
        if item.action not in {"INSERT", "UPDATE", "ADOPT"}:
            completed.append(item); continue
        if remaining is not None and remaining <= 0:
            completed.append(PlanItem("REPORT", item.event, item.calendar_event, "mutation limit reached")); continue
        if not apply:
            completed.append(item); continue
        if remaining is not None:
            remaining -= 1
        try:
            result = _execute_item(service, target, item)
        except Exception as exc:
            completed.append(PlanItem("REVIEW", item.event, item.calendar_event, f"write failed: {exc}")); continue
        _persist(state, item.event, result.get("id"), action=item.action, payload=result)
        completed.append(item)
    return completed


def _execute_item(service: Any, target: CalendarTarget, item: PlanItem) -> dict[str, Any]:
    assert item.event is not None
    if item.action == "INSERT":
        return _insert_with_recovery(service, target, item.event)
    existing = item.calendar_event or {}
    return _conditional_patch(service, target, existing, item.event, adoption=item.action == "ADOPT")


def _conditional_patch(service: Any, target: CalendarTarget, existing: dict[str, Any], event: Any, *, adoption: bool) -> dict[str, Any]:
    current = existing
    for conflict_attempt in range(2):
        if not current.get("etag"):
            raise RuntimeError("Calendar event has no ETag; refusing unconditional patch")
        request = service.events().patch(calendarId=target.calendar_id, eventId=current["id"], body=event_payload(event, existing=current))
        request.headers["If-Match"] = current.get("etag", "")
        try:
            return _retry_execute(request)
        except Exception as exc:
            if _status(exc) != 412 or conflict_attempt:
                raise
            current = service.events().get(calendarId=target.calendar_id, eventId=current["id"]).execute()
            metadata = managed_metadata(current)
            wants = {canonical_registration_url(url) for url in (event.registration_url, event.source_url, *event.source_urls) if url}
            if current.get("status") == "cancelled" or is_protected(current) or (not adoption and (not metadata or metadata.get("identity_tag") != identity_tag(event.identity))) or (adoption and (metadata is not None or not wants.intersection(exact_event_urls(current)))):
                raise RuntimeError("ownership changed during ETag recovery")
    raise AssertionError("unreachable")


def _insert_with_recovery(service: Any, target: CalendarTarget, event: Any) -> dict[str, Any]:
    body = insert_payload(event)
    event_id = body["id"]
    try:
        return service.events().insert(calendarId=target.calendar_id, body=body).execute()
    except Exception as exc:
        # An interrupted create is ambiguous. Query deterministic ID before another insert.
        if not (_uncertain(exc) or _status(exc) == 409):
            raise
        try:
            existing = service.events().get(calendarId=target.calendar_id, eventId=event_id).execute()
        except Exception as get_exc:
            if _status(get_exc) == 404:
                # One bounded retry after the deterministic-id lookup proves absence.
                return service.events().insert(calendarId=target.calendar_id, body=body).execute()
            raise
        metadata = managed_metadata(existing)
        if existing.get("status") == "cancelled" or is_protected(existing):
            raise RuntimeError("deterministic Calendar ID is cancelled or protected")
        if metadata and metadata.get("identity_tag") == identity_tag(event.identity):
            return existing
        raise RuntimeError("deterministic Calendar ID exists but is not owned by this event")


def _retry_execute(request: Any, attempts: int = 3) -> dict[str, Any]:
    for attempt in range(attempts):
        try:
            return request.execute()
        except (TimeoutError, socket.timeout) as caught:
            last_error = caught
            retry = True
        except Exception as caught:
            last_error = caught
            retry = _status(caught) == 429 or (_status(caught) is not None and 500 <= _status(caught) < 600)
        if not retry or attempt == attempts - 1:
            raise last_error
        time.sleep(0.05 * (2**attempt))
    raise AssertionError("unreachable")


def _status(exc: Exception) -> int | None:
    status = getattr(getattr(exc, "resp", None), "status", None)
    return status if isinstance(status, int) else getattr(exc, "status_code", None)


def _uncertain(exc: Exception) -> bool:
    code = _status(exc)
    return isinstance(exc, (TimeoutError, socket.timeout)) or code == 429 or (code is not None and 500 <= code < 600)


def _persist(state: Any, event: Any, calendar_id: str | None, *, action: str, payload: dict[str, Any] | None = None, dismissal: str | None = None) -> None:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")) if payload is not None else None
    with state.transaction():
        state.upsert_identity(event.identity, calendar_id, event_material_hash(event), event.identity_confidence.value,
                              successful_payload=serialized, dismissal_status=dismissal)
        state.record_outcome(event.identity, action)

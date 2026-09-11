"""Cautious command-line orchestration for TechWeekETL.

Source collection, reconciliation, and Calendar execution deliberately remain
separate here: a saved source snapshot follows the same planning path as a
fresh collection.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .auth import authorize_desktop, build_calendar_service
from .browser import collect_city
from .calendar import ACCOUNT_EMAIL, CANDIDATE_CALENDAR_ID, inventory_events, verify_calendar_access
from .config import Settings
from .diff import PlanItem, SyncPlan, plan_sync
from .executor import execute_plan
from .extract import extract_snapshot
from .snapshots import read_snapshot, write_snapshot
from .state import AppLock, StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="techweek-etl", description="Cautious Tech Week Calendar ETL")
    _runtime_arguments(parser)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="show local configuration and authorization readiness")
    commands.add_parser("auth", help="explicitly open desktop OAuth authorization")
    for name, help_text in (("discover", "collect source traversal evidence"), ("extract", "write a normalized source snapshot")):
        child = commands.add_parser(name, help=help_text)
        child.add_argument("--city", choices=("sf", "la"), action="append", dest="cities", help="city to include (repeatable)")
        if name == "extract":
            child.add_argument("--output", type=Path, required=True, help="snapshot JSON path")
    inventory = commands.add_parser("calendar-inventory", help="read all Candidate Events calendar records")
    inventory.add_argument("--output", type=Path, help="write inventory JSON to this path")
    sync = commands.add_parser("sync", help="plan a sync; dry-run is the default")
    sync.add_argument("--snapshot", type=Path, help="replay this saved source snapshot")
    sync.add_argument("--city", choices=("sf", "la"), action="append", dest="cities", help="city to collect when no snapshot is given")
    sync.add_argument("--identity", action="append", dest="identities", help="snapshot event identity to select (repeatable)")
    sync.add_argument("--apply", action="store_true", help="allow Calendar and SQLite mutations")
    sync.add_argument("--limit", type=int, help="maximum total mutations")
    # argparse normally accepts global options only before the subcommand. Make
    # operational paths ergonomic in either position while preserving an option
    # already supplied before the subcommand.
    for child in commands.choices.values():
        _runtime_arguments(child, suppress_defaults=True)
    return parser


def _runtime_arguments(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument("--app-dir", type=Path, default=default, help="application-data directory")
    parser.add_argument("--database", type=Path, default=default, help="SQLite state path")
    parser.add_argument("--lock", type=Path, default=default, help="application lock path")
    parser.add_argument("--token", type=Path, default=default, help="OAuth token path")
    parser.add_argument("--client", type=Path, default=default, help="Desktop OAuth client-secret path")
    parser.add_argument("--account", default=argparse.SUPPRESS if suppress_defaults else ACCOUNT_EMAIL, help="required Google account email")
    parser.add_argument("--calendar-id", default=argparse.SUPPRESS if suppress_defaults else CANDIDATE_CALENDAR_ID, help="Candidate Events calendar ID")
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS if suppress_defaults else False, help="emit JSON reports")


def _paths(args: argparse.Namespace) -> tuple[Settings, Path, Path]:
    base = Settings.default() if args.app_dir is None else Settings(Path(args.app_dir), Path(args.app_dir) / "state.sqlite", Path(args.app_dir) / "techweek-etl.lock")
    settings = Settings(base.app_dir, args.database or base.database_path, args.lock or base.lock_path)
    return settings, args.token or settings.app_dir / "token.json", args.client or settings.app_dir / "client_secret.json"


def _cities(args: argparse.Namespace) -> tuple[str, ...]:
    return tuple(args.cities or ("sf", "la"))


def _emit(args: argparse.Namespace, report: Any) -> None:
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return
    if isinstance(report, dict):
        for key, value in report.items():
            print(f"{key}: {value}")
    else:
        print(report)


def _plan_report(items: Sequence[PlanItem]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.action] = counts.get(item.action, 0) + 1
    return {"actions": counts, "items": [
        {"action": item.action, "identity": item.event.identity if item.event else None,
         "city": item.event.city if item.event else None,
         "title": item.event.title if item.event else None,
         "start": item.event.start.isoformat() if item.event else None,
         "end": item.event.end.isoformat() if item.event else None,
         "registration_url": item.event.registration_url if item.event else None,
         "source_url": item.event.source_url if item.event else None,
         "calendar_event_id": item.calendar_event.get("id") if item.calendar_event else None, "reason": item.reason}
        for item in items
    ]}


def main(argv: Sequence[str] | None = None, *, collector: Callable[[str], Any] = collect_city) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "limit", None) is not None and args.limit < 0:
        raise SystemExit("--limit must be zero or greater")
    settings, token_path, client_path = _paths(args)
    # The lock covers every command. This prevents a manual inventory, source
    # collection, or OAuth refresh from racing an apply run against local state.
    with AppLock(settings.lock_path):
        if args.command == "doctor":
            _emit(args, {"app_dir": str(settings.app_dir), "database": str(settings.database_path),
                         "lock": str(settings.lock_path), "token": str(token_path), "client": str(client_path),
                         "token_exists": token_path.exists(), "client_exists": client_path.exists(),
                         "account": args.account, "calendar_id": args.calendar_id})
            return 0
        if args.command == "auth":
            if not client_path.is_file():
                raise SystemExit(f"OAuth client file does not exist: {client_path}")
            authorize_desktop(client_path, token_path)
            service = build_calendar_service(token_path)
            target = verify_calendar_access(service, args.calendar_id, expected_account=args.account)
            _emit(args, {"authorized": True, "account": target.account_email, "calendar_id": target.calendar_id})
            return 0
        if args.command == "discover":
            traversals = [collector(city) for city in _cities(args)]
            _emit(args, {"cities": [{"city": item.city, "rows": len(item.raw_events), "displayed_count": item.displayed_count,
                                      "traversal_complete": item.traversal_complete, "issues": list(item.issues)} for item in traversals]})
            return 0
        if args.command == "extract":
            with StateStore(settings.database_path, read_only=True) as state:
                previous = {city: state.get_baseline(city) for city in _cities(args)}
            snapshot = extract_snapshot(_cities(args), previous, collector=collector)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            write_snapshot(args.output, snapshot)
            _emit(args, {"snapshot": str(args.output), "events": len(snapshot.events),
                         "healthy_cities": [item.city for item in snapshot.city_health if item.healthy]})
            return 0
        if args.command == "sync" and args.snapshot and args.cities:
            raise SystemExit("--city cannot be combined with --snapshot; replay uses the snapshot's complete city evidence")
        if args.command == "sync" and args.identities and not args.snapshot:
            raise SystemExit("--identity requires --snapshot so selection has complete source evidence")
        service = build_calendar_service(token_path)
        target = verify_calendar_access(service, args.calendar_id, expected_account=args.account)
        inventory = inventory_events(service, target)
        if args.command == "calendar-inventory":
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            _emit(args, {"events": len(inventory), "output": str(args.output) if args.output else None})
            return 0
        # Snapshot replay is intentionally read before any extraction and then
        # proceeds through exactly the same plan_sync/execute_plan pipeline.
        with StateStore(settings.database_path, read_only=not args.apply,
                        account_email=target.account_email, calendar_id=target.calendar_id) as state:
            if args.snapshot:
                snapshot = read_snapshot(args.snapshot)
            else:
                previous = {city: state.get_baseline(city) for city in _cities(args)}
                snapshot = extract_snapshot(_cities(args), previous, collector=collector)
            plan = plan_sync(snapshot, inventory, state)
            if args.identities:
                wanted = set(args.identities)
                selected: list[PlanItem] = []
                for identity in wanted:
                    matches = [item for item in plan.items if item.event and item.event.identity == identity]
                    if not matches:
                        raise SystemExit(f"requested identity is absent from the complete plan: {identity}")
                    if len(matches) != 1:
                        raise SystemExit(f"requested identity is ambiguous in the complete plan: {identity}")
                selected = [item for item in plan.items if item.event and item.event.identity in wanted]
                # Keep the complete health verdict, while executing only the
                # explicit user selection. This never treats unselected source
                # events or cities as disappeared.
                plan = SyncPlan(tuple(selected), plan.healthy_cities)
            completed = execute_plan(service, target, plan, state, apply=args.apply, limit=args.limit)
            incomplete_execution = any(
                "write failed" in item.reason or "mutation limit reached" in item.reason
                for item in completed
            )
            # An explicit identity selection is a controlled partial apply, so
            # it cannot establish a complete source baseline either.
            if args.apply and not args.identities and not incomplete_execution:
                with state.transaction():
                    for health in snapshot.city_health:
                        # plan_sync incorporates the durable baseline gate. Do
                        # not let a source-supplied health verdict lower it.
                        if health.city in plan.healthy_cities:
                            state.set_baseline(health.city, health.collected_count)
        report = _plan_report(completed)
        report.update({"dry_run": not args.apply, "snapshot": str(args.snapshot) if args.snapshot else None,
                       "healthy_cities": sorted(plan.healthy_cities)})
        _emit(args, report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

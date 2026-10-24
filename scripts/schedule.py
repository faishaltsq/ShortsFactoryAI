#!/usr/bin/env python3
"""Plan seven days and explicitly control local scheduler ticks; no daemon."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.core.orchestration.jobstore import JobStore  # noqa: E402
from packages.core.orchestration.planner import ProductionPlanner  # noqa: E402
from packages.core.orchestration.scheduler import DispatchResult, Scheduler  # noqa: E402


def _run_pipeline(store: JobStore, job_id: str, *, provider_mode: str) -> DispatchResult:
    from packages.core.config import Settings
    from packages.core.orchestration.states import JobState
    from packages.core.pipeline import PipelineRunner

    runner = PipelineRunner(store, Settings(db_path=store.db_path), force_mock=provider_mode == "mock")
    report = runner.run(job_id, stop_at=JobState.READY_FOR_APPROVAL)
    return DispatchResult(success=report.ok and report.final_state == JobState.READY_FOR_APPROVAL.value,
                          retryable=report.final_state not in {"BLOCKED", "REJECTED", "CANCELLED"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persisted production plans and opt-in scheduler (no daemon)")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "jobs" / "factory.db")
    parser.add_argument("--artifacts", type=Path, help="job artifacts root; defaults to the database directory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="read-only status; no providers or database creation")
    plan = commands.add_parser("plan", help="persist an inert seven-day plan, even while paused")
    plan.add_argument("--start", required=True, help="ISO-8601 datetime with explicit UTC offset")
    plan.add_argument("--timezone", help="optional IANA timezone for calendar-day scheduling")
    plan.add_argument("--videos-per-day", required=True, type=int)
    plan.add_argument("--genres", required=True, help="comma-separated domain genres in rotation order")
    plan.add_argument("--mode", default="live", choices=("mock", "live"))
    plan.add_argument("--days", default=7, type=int, help="number of calendar days to plan (1-30)")
    plan.add_argument("--posting-times", help="comma-separated local HH:MM, one per daily video (e.g. 07:00,12:00,19:00)")
    plan.add_argument("--max-attempts", default=3, type=int)
    plan.add_argument("--retry-base-s", default=60, type=float)
    enable = commands.add_parser("enable", help="persist explicit operator permission; starts no process")
    enable.add_argument("--confirm-unattended", action="store_true")
    commands.add_parser("pause", help="disable future dispatches; existing work is not killed")
    tick = commands.add_parser("tick", help="run a bounded tick, only after explicit enable")
    tick.add_argument("--limit", type=int, default=1)
    args = parser.parse_args(argv)

    try:
        if args.command == "status":
            output = Scheduler.read_status(args.db)
        elif args.command == "tick" and not Scheduler.read_status(args.db)["enabled"]:
            raise PermissionError("scheduler is disabled; explicit enable --confirm-unattended is required")
        elif args.command == "enable" and not args.confirm_unattended:
            raise PermissionError("enable requires --confirm-unattended")
        else:
            store = JobStore(args.db, args.artifacts or args.db.parent)
            if args.command == "plan":
                start = datetime.fromisoformat(args.start)
                if start.tzinfo is None or start.utcoffset() is None:
                    raise ValueError("--start requires an explicit UTC offset")
                if args.timezone:
                    start = start.astimezone(ZoneInfo(args.timezone))
                output = asdict(ProductionPlanner(store).plan_seven_days(
                    start=start, videos_per_day=args.videos_per_day,
                    genres=[genre.strip() for genre in args.genres.split(",")], provider_mode=args.mode,
                    max_attempts=args.max_attempts, retry_base_s=args.retry_base_s,
                    days=args.days,
                    posting_times=([value.strip() for value in args.posting_times.split(",")]
                                   if args.posting_times else None),
                ))
            else:
                scheduler = Scheduler(store, runner=lambda job_id, *, provider_mode: _run_pipeline(
                    store, job_id, provider_mode=provider_mode))
                if args.command == "enable":
                    scheduler.enable(operator_confirmed=args.confirm_unattended)
                    output = scheduler.status()
                elif args.command == "pause":
                    scheduler.pause()
                    output = scheduler.status()
                else:
                    output = asdict(scheduler.tick(limit=args.limit))
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 1 if output.get("failed", 0) else 0
    except (ValueError, PermissionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ZoneInfoNotFoundError:
        print("error: timezone is unavailable; use a supported IANA zone or an explicit offset", file=sys.stderr)
        return 2
    except sqlite3.Error:
        print("error: scheduler database operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Operator approval for a job that reached READY_FOR_APPROVAL.

The pipeline never approves anything itself: it only proves eligibility by
writing approval.json. This script is the operator's explicit decision, and the
gate is re-read from disk before acting so a stale verdict cannot ride through.

Usage:
  uv run python scripts/approve.py --list
  uv run python scripts/approve.py --approve <job_id>
  uv run python scripts/approve.py --reject <job_id> --reason "hook is weak"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from packages.core.approval import ApprovalRejected, approve, pending, reject  # noqa: E402
from packages.core.config import JOBS_DIR, get_settings  # noqa: E402
from packages.core.orchestration import JobStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="operator approval for Shorts Factory jobs")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true", help="show jobs waiting for approval")
    action.add_argument("--approve", metavar="JOB_ID", help="approve a job")
    action.add_argument("--reject", metavar="JOB_ID", help="reject a job")
    parser.add_argument("--reason", default="no reason given", help="reason recorded with --reject")
    parser.add_argument("--by", default=None, help="operator identity (default: $SHORTS_OPERATOR)")
    args = parser.parse_args()

    settings = get_settings()
    store = JobStore(settings.db_path, JOBS_DIR)

    try:
        if args.list:
            rows = pending(store)
            if not rows:
                print("no job is waiting for approval")
                return 0
            for job_id, title, gate in rows:
                verdict = "eligible" if gate.eligible else "BLOCKED"
                print(f"{job_id}  {verdict:8}  {title}")
                for blocker in gate.blockers:
                    print(f"    - {blocker}")
            return 0
        if args.approve:
            approve(store, args.approve, args.by)
            print(f"approved {args.approve}")
            return 0
        if args.reject:
            reject(store, args.reject, args.reason, args.by)
            print(f"rejected {args.reject}: {args.reason}")
            return 0
    except (ApprovalRejected, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

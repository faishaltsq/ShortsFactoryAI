#!/usr/bin/env python3
"""Explicit operator entry point. No credentials, network or browser on --help/status."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from packages.core.orchestration.jobstore import JobStore  # noqa: E402
from packages.core.publishing.contracts import PublishingArtifact, UploadOptions  # noqa: E402
from packages.core.publishing.errors import PublishingError  # noqa: E402


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouTube operator commands (private-upload first)")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--connect", action="store_true", help="explicitly open installed-app OAuth in system browser")
    actions.add_argument("--status", metavar="JOB_ID", help="local status only; no Google request or refresh")
    actions.add_argument("--upload", metavar="JOB_ID", help="upload approved live media privately, or resume its session")
    actions.add_argument("--schedule", metavar="JOB_ID", help="separately authorize future publication")
    actions.add_argument("--publish-now", metavar="JOB_ID", help="separately authorize public status now")
    actions.add_argument("--reconcile", metavar="JOB_ID", help="read exact remote video; never reinsert/update")
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--config-dir", type=Path, default=None, help="protected credentials outside repository")
    parser.add_argument("--confirm", action="store_true", help="explicit approval of schedule/public/manual association")
    parser.add_argument("--by", dest="operator", help="operator identity required for separate publication approval")
    parser.add_argument("--publish-at", help="ISO 8601 timezone-aware instant at least two minutes ahead")
    parser.add_argument("--video-id", help="only --reconcile after manual media/video association")
    parser.add_argument("--category-id", help="YouTube category ID explicitly selected for upload")
    kids = parser.add_mutually_exclusive_group()
    kids.add_argument("--made-for-kids", dest="made_for_kids", action="store_const", const=True, default=None)
    kids.add_argument("--not-made-for-kids", dest="made_for_kids", action="store_const", const=False)
    synthetic = parser.add_mutually_exclusive_group()
    synthetic.add_argument("--synthetic-media", dest="synthetic_media", action="store_const", const=True, default=None)
    synthetic.add_argument("--no-synthetic-media", dest="synthetic_media", action="store_const", const=False)
    args = parser.parse_args(argv)
    job_id = args.status or args.upload or args.schedule or args.publish_now or args.reconcile
    if job_id and not re.fullmatch(r"[0-9a-f]{16}", job_id):
        parser.error("invalid_job_id")
    if args.schedule or args.publish_now or args.reconcile:
        if not args.confirm or not args.operator or not args.operator.strip():
            parser.error("explicit_confirmation_and_operator_required")
    if args.upload and (args.category_id is None or args.made_for_kids is None or args.synthetic_media is None):
        parser.error("upload_requires_explicit_category_kids_and_synthetic_disclosures")
    if args.category_id is not None and not re.fullmatch(r"[1-9][0-9]{0,3}", args.category_id):
        parser.error("invalid_category_id")
    if args.video_id is not None and (not args.reconcile or not re.fullmatch(r"[A-Za-z0-9_-]{11}", args.video_id)):
        parser.error("video_id_requires_explicit_manual_reconciliation")
    if args.schedule:
        try:
            stamp = datetime.fromisoformat((args.publish_at or "").replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp <= datetime.now(timezone.utc) + timedelta(minutes=2):
                raise ValueError
        except ValueError:
            parser.error("future_timezone_publish_at_required")
        args.publish_at = stamp
    elif args.publish_at is not None:
        parser.error("publish_at_requires_schedule")
    return args


def main(argv: list[str] | None = None, *, http_factory: Callable | None = None,
         browser_open: Callable[[str], bool] | None = None) -> int:
    args = _arguments(argv)
    try:
        # Status does not even construct a protected store or a network client.
        if args.status:
            store = JobStore(args.data_root / "jobs" / "factory.db", args.data_root / "jobs")
            record = store.get(args.status)
            try:
                artifact = PublishingArtifact.model_validate(store.read_artifact(args.status, "publishing.json"))
                publishing = artifact.model_dump(mode="json", exclude_none=True)
            except FileNotFoundError:
                publishing = None
            print(json.dumps({"job_id": record.id, "state": record.state.value, "publishing": publishing}))
            return 0

        import httpx
        from packages.core.publishing.loopback import run_loopback
        from packages.core.publishing.oauth import InstalledClient, OAuthFlow, TokenManager
        from packages.core.publishing.secure import ProtectedStore
        from packages.core.publishing.service import PublishingService
        from packages.core.publishing.youtube import YouTubeHTTPAdapter

        protected = ProtectedStore(args.config_dir)
        installed = InstalledClient.from_store(protected)
        factory = http_factory or (lambda: httpx.Client(timeout=20, trust_env=False, follow_redirects=False))
        with factory() as http:
            if args.connect:
                import webbrowser
                run_loopback(OAuthFlow(installed, protected, http), allow_connect=True,
                             browser_open=browser_open or webbrowser.open)
                print(json.dumps({"connected": True}))
                return 0
            store = JobStore(args.data_root / "jobs" / "factory.db", args.data_root / "jobs")
            gateway = YouTubeHTTPAdapter(http, TokenManager(installed, protected, http), allow_network=True)
            service = PublishingService(store, gateway, protected)
            if args.upload:
                result = service.upload_private(args.upload, UploadOptions(category_id=args.category_id,
                    made_for_kids=args.made_for_kids, contains_synthetic_media=args.synthetic_media), allow_upload=True)
            elif args.schedule:
                result = service.schedule(args.schedule, publish_at=args.publish_at, confirm=args.confirm,
                                          operator=args.operator, allow_schedule=True)
            elif args.publish_now:
                result = service.publish_now(args.publish_now, confirm=args.confirm, operator=args.operator,
                                             allow_publish=True)
            else:
                result = service.reconcile(args.reconcile, video_id=args.video_id, confirm=args.confirm,
                                           operator=args.operator, allow_read=True)
            print(result.model_dump_json(exclude_none=True))
            return 0
    except PublishingError as error:
        print(json.dumps({"error": error.code}), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError):
        # Never print validation/input/upstream exception messages: they can contain secrets.
        print(json.dumps({"error": "publishing_command_failed"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run one production job through the pipeline (dry-run safe).

By default uses mock providers so nothing spends budget; --live routes to the
real configured providers.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.core.config import JOBS_DIR, get_settings  # noqa: E402
from packages.core.orchestration import JobStore  # noqa: E402
from packages.core.orchestration.states import STOP_POINTS as STOPS  # noqa: E402
from packages.core.pipeline import PipelineRunner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Shorts Factory job")
    parser.add_argument("--title", default="Cahaya matahari adalah masa lalu")
    parser.add_argument("--live", action="store_true", help="use configured live providers")
    parser.add_argument("--stop", default="storyboard", choices=sorted(STOPS))
    parser.add_argument("--resume", default=None, help="job id to resume instead of creating a new job")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = get_settings()
    store = JobStore(settings.db_path, JOBS_DIR)
    if args.resume:
        job = store.get(args.resume)
        print(f"job resumed: {job.id} (state={job.state.value})")
    else:
        job = store.create(title=args.title)
        print(f"job created: {job.id}")

    runner = PipelineRunner(store, settings, force_mock=not args.live)
    report = runner.run(job.id, stop_at=STOPS[args.stop])

    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    print(f"artifacts: {store.artifact_root(job.id)}")
    print(f"final state: {report.final_state}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

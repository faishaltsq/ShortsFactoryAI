#!/usr/bin/env python3
"""Read back a job's exact media, verify hashes/properties and export visual evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.core.artifacts import validate_artifact  # noqa: E402
from packages.core.config import JOBS_DIR, get_settings  # noqa: E402
from packages.core.media.audio import verify_audio  # noqa: E402
from packages.core.media.contracts import AudioArtifact, RenderArtifact  # noqa: E402
from packages.core.media.process import atomic_json, run_checked  # noqa: E402
from packages.core.media.render import verify_render  # noqa: E402
from packages.core.orchestration import JobStore  # noqa: E402
from packages.core.schemas import Script, Storyboard  # noqa: E402


def verify_job(job_id: str, *, frames: bool = False) -> dict:
    store = JobStore(get_settings().db_path, JOBS_DIR)
    record = store.get(job_id)
    root = store.artifact_root(job_id)
    def artifact(name):
        return validate_artifact(name, store.read_artifact(job_id, name))
    script = Script.model_validate(artifact("script.json"))
    storyboard = Storyboard.model_validate(artifact("storyboard.json"))
    audio = AudioArtifact.model_validate(artifact("audio.json"))
    render = RenderArtifact.model_validate(artifact("render.json"))
    qc = artifact("qc.json")
    verify_audio(audio, script, storyboard, root)
    probe = verify_render(render, storyboard, audio, root)
    if not qc["technical_pass"] or qc["render_sha256"] != render.sha256:
        raise ValueError("QC failed or belongs to a different render")
    # `qc.json` covers technical checks only; editorial clearance and source
    # verification live in their own artifacts. Reporting them as hardcoded False
    # told the operator a cleared job had unverified sources right before upload.
    try:
        editorial = artifact("editorial_qc.json")
        editorial_verified = editorial["overall"] == "pass" and all(c["pass"] for c in editorial["checks"])
    except (OSError, ValueError, KeyError):
        editorial_verified = False
    try:
        verification = artifact("verification.json")
        sources_verified = verification["status"] == "supported"
    except (OSError, ValueError, KeyError):
        sources_verified = False
    try:
        approval = artifact("approval.json")
        approval_eligible = bool(approval["eligible"])
    except (OSError, ValueError, KeyError):
        approval_eligible = False
    report = {"job_id": job_id, "state": record.state.value, "provider_mode": record.payload.get("provider_mode"),
              "output_path": str(root / render.output_path), "size_bytes": (root / render.output_path).stat().st_size,
              "duration_seconds": float(probe["format"]["duration"]), "video_frames": render.frame_count,
              "scene_count": len(storyboard.scenes), "subtitle_count": len(storyboard.subtitles),
              "technical_checks": qc["checks"], "audio_stats": qc["audio_stats"], "sha256": render.sha256,
              "editorial_verified": editorial_verified, "sources_verified": sources_verified,
              "approval_eligible": approval_eligible, "published": False}
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    if frames:
        picks, outputs = [], []
        for index, scene in enumerate(storyboard.scenes):
            start, end = scene.startFrame * 1000 / storyboard.fps, (scene.startFrame + scene.durationInFrames) * 1000 / storyboard.fps
            cues = [c for c in storyboard.subtitles if start <= c.startMs < end]
            cue = cues[len(cues) // 2]
            timestamp = (cue.startMs + cue.endMs) / 2000
            output = evidence / f"scene-{index + 1:02d}.png"
            run_checked(["ffmpeg", "-v", "error", "-y", "-ss", str(timestamp), "-i", str(root / render.output_path),
                         "-frames:v", "1", "-vf", "scale=480:854", str(output)], log_path=evidence / "frames.log")
            if not output.is_file():
                raise ValueError("frame extraction did not produce an image")
            picks.append({"scene_id": scene.sceneId, "timestamp_s": timestamp, "subtitle": cue.text,
                          "title": [t.text for t in scene.text if t.style.role == "title"], "path": str(output)})
            outputs.append(output)
        if len(outputs) >= 2:
            # Grid the frames for a single-glance review. The old code required
            # exactly four scenes, so a five-scene job silently produced no sheet.
            contact = evidence / "contact-sheet.png"
            columns = 2 if len(outputs) <= 4 else 3
            rows = (len(outputs) + columns - 1) // columns
            layout = "|".join(
                f"{(index % columns) * 480}_{(index // columns) * 854}" for index in range(len(outputs))
            )
            args = ["ffmpeg", "-v", "error", "-y"]
            for output in outputs:
                args.extend(["-i", str(output)])
            args.extend(["-filter_complex",
                         f"xstack=inputs={len(outputs)}:layout={layout}:fill=black",
                         "-frames:v", "1", str(contact)])
            run_checked(args, log_path=evidence / "frames.log")
            report["contact_sheet"] = str(contact)
            report["contact_sheet_grid"] = f"{columns}x{rows}"
        report["frame_evidence"] = picks
    atomic_json(evidence / "verification.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--frames", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify_job(args.job_id, frames=args.frames), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Render validated JSON props through the fixed Remotion application."""
from __future__ import annotations

import json
import math
import re
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Callable

from ..config import PROJECT_ROOT
from ..schemas import Script, Storyboard
from .assets import AssetAgent
from .audio import verify_audio
from .contracts import AudioArtifact, RenderArtifact, TechnicalQCArtifact
from .process import atomic_json, checked_path, json_hash, probe_media, run_checked, sha256_file
from .progress import RemotionProgress, RenderProgress


def validate_probe(probe: dict, *, expected_frames: int, fps: int, width: int, height: int) -> dict[str, bool]:
    videos = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    audios = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if len(audios) != 1:
        raise ValueError("render must contain exactly one audio stream")
    if len(videos) != 1:
        raise ValueError("render must contain exactly one video stream")
    video, audio = videos[0], audios[0]
    duration = float(probe["format"]["duration"])
    checks = {
        "resolution": video.get("width") == width and video.get("height") == height,
        "frame_rate": Fraction(video.get("r_frame_rate", "0/1")) == fps,
        "video_codec": video.get("codec_name") == "h264",
        "pixel_format": video.get("pix_fmt") == "yuv420p",
        "audio_codec": audio.get("codec_name") == "aac",
        "frame_count": int(video.get("nb_frames", 0)) == expected_frames,
        "duration_matches_narration": math.isfinite(duration) and abs(duration - expected_frames / fps) < 0.12,
        "audio_covers_video": abs(float(audio.get("duration", 0)) - expected_frames / fps) < 0.12,
    }
    failed = [key for key, passed in checks.items() if not passed]
    if failed:
        raise ValueError("render validation failed: " + ", ".join(failed))
    return checks


def verify_render(artifact: RenderArtifact, storyboard: Storyboard, audio: AudioArtifact, job_dir: Path) -> dict:
    path = checked_path(job_dir, artifact.output_path)
    if artifact.sha256 != sha256_file(path):
        raise ValueError("render checksum mismatch")
    if artifact.storyboard_sha256 != json_hash(storyboard.model_dump(mode="json", exclude_none=True)):
        raise ValueError("render no longer matches storyboard")
    if artifact.audio_sha256 != audio.sha256:
        raise ValueError("render no longer matches narration")
    probe = probe_media(path)
    validate_probe(probe, expected_frames=storyboard.total_frames, fps=storyboard.fps, width=storyboard.width, height=storyboard.height)
    return probe


class RenderAgent:
    def __init__(self, video_dir: Path | None = None) -> None:
        self.video_dir = video_dir or PROJECT_ROOT / "packages" / "video"

    def run(self, script: Script, storyboard: Storyboard, audio: AudioArtifact, job_dir: Path,
            cancelled: Callable[[], bool] | None = None,
            progress: Callable[[RenderProgress], None] | None = None) -> RenderArtifact:
        AssetAgent().run(storyboard)
        verify_audio(audio, script, storyboard, job_dir)
        if not 30 <= audio.duration_ms / 1000 <= 45:
            raise ValueError("narration outside 30-45s window; revise script before rendering")
        if not re.fullmatch(r"[0-9a-f]{16}", job_dir.name):
            raise ValueError("render requires a canonical job directory")
        cli = self.video_dir / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
        if not cli.is_file():
            raise ValueError("Remotion dependencies are not installed")
        relative_src = f"jobs/{job_dir.name}/narration-{audio.sha256[:12]}.wav"
        public_audio = checked_path(self.video_dir / "public", relative_src)
        public_audio.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checked_path(job_dir, audio.narration_path), public_audio)
        props = storyboard.model_dump(mode="json", exclude_none=True)
        props["narration"] = {"src": relative_src, "durationMs": round(audio.duration_ms), "volume": 1}
        props_path = job_dir / "render-props.json"
        atomic_json(props_path, {"storyboard": props})
        partial = job_dir / "output.partial.mp4"
        parser = RemotionProgress(storyboard.total_frames)

        def observe(chunk: str) -> None:
            for update in parser.feed(chunk):
                if progress is not None:
                    progress(update)

        run_checked(["node", str(cli), "render", "src/index.ts", "Short", str(partial),
                     "--props=" + str(props_path), "--codec=h264", "--pixel-format=yuv420p", "--color-space=bt709", "--concurrency=2"],
                    cwd=self.video_dir, log_path=job_dir / "render.log", timeout=900, cancelled=cancelled,
                    on_output=observe if progress is not None else None)
        observe("\n")
        probe = probe_media(partial)
        validate_probe(probe, expected_frames=storyboard.total_frames, fps=storyboard.fps, width=storyboard.width, height=storyboard.height)
        output = job_dir / "output.mp4"
        partial.replace(output)
        return RenderArtifact(output_path="output.mp4", sha256=sha256_file(output),
                              storyboard_sha256=json_hash(storyboard.model_dump(mode="json", exclude_none=True)),
                              audio_sha256=audio.sha256, duration_ms=float(probe["format"]["duration"]) * 1000,
                              frame_count=storyboard.total_frames, probe=probe)


def technical_quality(storyboard: Storyboard, audio: AudioArtifact, render: RenderArtifact, job_dir: Path,
                      cancelled: Callable[[], bool] | None = None) -> TechnicalQCArtifact:
    probe = verify_render(render, storyboard, audio, job_dir)
    checks = validate_probe(probe, expected_frames=storyboard.total_frames, fps=storyboard.fps, width=storyboard.width, height=storyboard.height)
    log = job_dir / "technical-qc.log"
    log.write_text("", encoding="utf-8")
    run_checked(["ffmpeg", "-hide_banner", "-nostats", "-i", str(checked_path(job_dir, render.output_path)),
                 "-vf", "blackdetect=d=0.4:pix_th=0.02:pic_th=0.98,freezedetect=n=-60dB:d=6",
                 "-af", "silencedetect=n=-45dB:d=2.5,loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                log_path=log, timeout=180, cancelled=cancelled)
    text = log.read_text(encoding="utf-8")
    stats = json.loads(re.findall(r"\{[^{}]+\}", text)[-1])
    loudness, peak = float(stats["input_i"]), float(stats["input_tp"])
    checks.update({
        "duration_window": 30 <= render.duration_ms / 1000 <= 45.12,
        "subtitles_present": bool(storyboard.subtitles),
        "subtitle_bounds": all(0 <= c.startMs < c.endMs <= render.duration_ms for c in storyboard.subtitles),
        "narration_loudness": -18 <= loudness <= -14,
        "true_peak": peak <= -1.0,
        "no_black_gaps": "black_start:" not in text,
        "no_long_silence": "silence_start:" not in text,
        "no_frozen_scenes": "freeze_start:" not in text,
    })
    notes = [f"failed: {name}" for name, passed in checks.items() if not passed]
    notes.append("Technical checks only. Editorial/source verification and operator approval remain required.")
    return TechnicalQCArtifact(technical_pass=all(checks.values()), checks=checks, notes=notes,
                               render_sha256=render.sha256, audio_stats={"integrated_lufs": loudness, "true_peak_dbtp": peak})

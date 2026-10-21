"""Local licensed audio, narration-sidechain ducking and measured two-pass loudness."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Callable

from ..schemas import Storyboard
from .assets import verify_assets
from .contracts import AnchoredSFX, AssetManifest, AudioArtifact, AudioMixArtifact
from .process import atomic_json, checked_path, json_hash, probe_media, run_checked, sha256_file
from .scene_data import BackgroundMusicSpec, SceneAudioSpec


def measure_loudness(path: Path, log: Path, cancelled: Callable[[], bool] | None = None) -> dict:
    log.write_text("", encoding="utf-8")
    run_checked(["ffmpeg", "-hide_banner", "-nostats", "-protocol_whitelist", "file,pipe", "-i", str(path),
                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                log_path=log, timeout=180, cancelled=cancelled)
    matches = re.findall(r"\{[^{}]+\}", log.read_text(encoding="utf-8"))
    if not matches:
        raise ValueError("FFmpeg returned no loudness measurements")
    measured = json.loads(matches[-1])
    if not all(math.isfinite(float(measured[k])) for k in ["input_i", "input_tp", "input_lra", "input_thresh", "target_offset"]):
        raise ValueError("audio is silent or has invalid loudness measurements")
    return measured


def mix_audio(storyboard: Storyboard, narration: AudioArtifact, assets: AssetManifest, job_dir: Path,
              cancelled: Callable[[], bool] | None = None) -> AudioMixArtifact:
    verify_assets(assets, storyboard, job_dir)
    if narration.mix is not None:
        raise ValueError("refusing to mix an already mixed narration")
    by_id = {asset.id: asset for asset in assets.assets}
    source = checked_path(job_dir, narration.narration_path)
    if sha256_file(source) != narration.sha256:
        raise ValueError("narration checksum mismatch before mix")
    fingerprint = json_hash({"narration": narration.sha256, "assets": assets.model_dump(mode="json"),
                             "storyboard": storyboard.model_dump(mode="json", exclude_none=True), "mix_version": 1})
    receipt_path = job_dir / "audio/mix-receipt.json"
    if receipt_path.is_file():
        cached = json.loads(receipt_path.read_text(encoding="utf-8"))
        if cached.get("fingerprint") == fingerprint:
            receipt = AudioMixArtifact.model_validate(cached["mix"])
            output = checked_path(job_dir, receipt.output_path)
            if not output.is_file() or sha256_file(output) != receipt.sha256:
                raise ValueError("cached mix checksum mismatch")
            return receipt
    total_samples = round(storyboard.total_frames * 48000 / storyboard.fps)
    duration = total_samples / 48000
    args = ["ffmpeg", "-hide_banner", "-y", "-filter_complex_threads", "1", "-protocol_whitelist", "file,pipe", "-i", str(source)]
    graph = []
    inputs = 1
    labels = ["voice"]
    music = BackgroundMusicSpec.model_validate(storyboard.backgroundMusic) if storyboard.backgroundMusic else None
    if music:
        graph.append("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=2[voice][side_raw]")
        graph.append("[side_raw]apad=pad_dur=1[side]")
        if music.loop:
            args.extend(["-stream_loop", "-1"])
        args.extend(["-protocol_whitelist", "file,pipe", "-i", str(checked_path(job_dir, by_id[music.assetRef].staged_path))])
        graph.append(f"[{inputs}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                     f"apad,atrim=end_sample={total_samples},volume={music.volume},"
                     f"afade=t=in:d={min(0.25, duration / 4)},afade=t=out:st={max(0, duration - 0.5)}:d={min(0.5, duration)}[music]")
        graph.append("[music][side]sidechaincompress=threshold=0.025:ratio=8:attack=15:release=250[ducked]")
        labels.append("ducked")
        inputs += 1
    else:
        graph.append("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[voice]")
    cues = []
    for scene in storyboard.scenes:
        if not scene.audio:
            continue
        for effect in SceneAudioSpec.model_validate(scene.audio).sfx:
            if effect.frame >= scene.durationInFrames:
                raise ValueError("SFX frame is outside the measured narration scene")
            absolute = scene.startFrame + effect.frame
            delay_samples = round(absolute * 48000 / storyboard.fps)
            remaining = (scene.durationInFrames - effect.frame) / storyboard.fps
            asset = by_id[effect.assetRef]
            if asset.kind != "sfx":
                raise ValueError("SFX requires a licensed sfx asset")
            args.extend(["-protocol_whitelist", "file,pipe", "-i", str(checked_path(job_dir, asset.staged_path))])
            label = f"effect{len(cues)}"
            graph.append(f"[{inputs}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                         f"atrim=duration={remaining},asetpts=PTS-STARTPTS,volume={effect.volume},"
                         f"adelay={delay_samples}S:all=1[{label}]")
            labels.append(label)
            inputs += 1
            cues.append(AnchoredSFX(asset_id=effect.assetRef, scene_id=scene.sceneId, scene_frame=effect.frame,
                                    absolute_frame=absolute, volume=effect.volume))
    if not music and not cues:
        raise ValueError("audio mix requires explicit licensed music or SFX")
    graph.append("".join(f"[{label}]" for label in labels) + f"amix=inputs={len(labels)}:duration=first:"
                 f"dropout_transition=0:normalize=0,alimiter=limit=0.89:level=false:latency=true,"
                 f"apad,atrim=end_sample={total_samples}[mixed]")
    filter_graph = ";".join(graph)
    premix = checked_path(job_dir, "audio/premix.wav")
    args.extend(["-filter_complex", filter_graph, "-map", "[mixed]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(premix)])
    run_checked(args, log_path=job_dir / "audio/mix.log", timeout=180, cancelled=cancelled)
    measured = measure_loudness(premix, job_dir / "audio/mix-measure.log", cancelled)
    loudnorm = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
                f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
                f"offset={measured['target_offset']}:linear=true,aresample=48000,apad,atrim=end_sample={total_samples}")
    output = checked_path(job_dir, "mix.wav")
    run_checked(["ffmpeg", "-hide_banner", "-y", "-protocol_whitelist", "file,pipe", "-i", str(premix), "-af", loudnorm,
                 "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(output)],
                log_path=job_dir / "audio/mix-normalize.log", timeout=180, cancelled=cancelled)
    final = measure_loudness(output, job_dir / "audio/mix-final-measure.log", cancelled)
    actual_duration = float(probe_media(output)["format"]["duration"]) * 1000
    if abs(actual_duration - narration.duration_ms) > 2:
        raise ValueError("mix changed narration timing")
    if abs(float(final["input_i"]) + 16) > 1:
        raise ValueError("mix failed the -16 LUFS target")
    receipt = AudioMixArtifact(input_narration_path=narration.narration_path, input_narration_sha256=narration.sha256,
                            assets_sha256=json_hash(assets.model_dump(mode="json")), source_manifest_sha256=assets.manifest_sha256,
                            output_path="mix.wav", sha256=sha256_file(output), duration_ms=actual_duration,
                            integrated_lufs=float(final["input_i"]), true_peak_dbtp=float(final["input_tp"]),
                            ducking="sidechaincompress" if music else "not-applicable", sfx=cues,
                            filter_sha256=hashlib.sha256(filter_graph.encode()).hexdigest())
    atomic_json(receipt_path, {"fingerprint": fingerprint, "mix": receipt.model_dump(mode="json")})
    return receipt

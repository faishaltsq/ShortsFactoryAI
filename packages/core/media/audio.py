"""Narration-driven scene timing, subtitle cues and normalized local audio."""
from __future__ import annotations

import json
import math
import re
import wave
from pathlib import Path
from typing import Callable

from ..providers.tts import EdgeTTSProvider
from ..schemas import Script, Storyboard
from .contracts import AssetManifest, AudioArtifact, AudioSegment
from .assets import load_assets
from .mix import mix_audio
from .process import atomic_json, checked_path, json_hash, probe_media, run_checked, sha256_file


def _group_words(words: list[dict], duration_ms: float, offset_ms: float, scene_index: int) -> list[dict]:
    if not words:
        raise ValueError("real word boundaries are required for subtitle synchronization")
    groups, group = [], []
    previous = 0
    for word in words:
        start, end = int(word["startMs"]), int(word["endMs"])
        if start < previous or end <= start or end > duration_ms + 100:
            raise ValueError("invalid or overlapping TTS word boundaries")
        previous = end
        if group and (len(group) >= 5 or len(" ".join(w["text"] for w in group) + " " + word["text"]) > 42):
            groups.append(group)
            group = []
        group.append(word)
    if group:
        groups.append(group)
    return [
        {"id": f"s{scene_index}-cue-{i}", "text": " ".join(w["text"] for w in g),
         "startMs": round(offset_ms + g[0]["startMs"]),
         "endMs": round(offset_ms + min(g[-1]["endMs"], duration_ms))}
        for i, g in enumerate(groups)
    ]


def timeline_from_audio(storyboard: Storyboard, durations_ms: list[float], boundaries: list[list[dict]]) -> Storyboard:
    if len(storyboard.scenes) != len(durations_ms) or len(durations_ms) != len(boundaries):
        raise ValueError("one measured audio segment is required per scene")
    scenes, cues, cursor = [], [], 0
    for index, (scene, duration, words) in enumerate(zip(storyboard.scenes, durations_ms, boundaries)):
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("audio duration must be positive and finite")
        frames = max(30, math.ceil(duration * storyboard.fps / 1000))
        scenes.append({**scene.model_dump(mode="json", exclude_none=True), "startFrame": cursor, "durationInFrames": frames})
        cues.extend(_group_words(words, duration, cursor * 1000 / storyboard.fps, index))
        cursor += frames
    data = storyboard.model_dump(mode="json", exclude_none=True)
    data.update(scenes=scenes, subtitles=cues, narration={"src": "narration.wav", "durationMs": round(cursor * 1000 / storyboard.fps)})
    return Storyboard.model_validate(data)


def verify_audio(artifact: AudioArtifact, script: Script, storyboard: Storyboard, job_dir: Path, *, assets: AssetManifest | None = None) -> None:
    if artifact.script_sha256 != json_hash(script.model_dump(mode="json", exclude_none=True)):
        raise ValueError("narration no longer matches the script")
    if artifact.storyboard_sha256 != json_hash(storyboard.model_dump(mode="json", exclude_none=True)):
        raise ValueError("audio timing no longer matches the storyboard")
    if artifact.assets_sha256 or artifact.mix or storyboard.backgroundMusic or any(s.audio or s.assetRefs for s in storyboard.scenes):
        assets = load_assets(storyboard, job_dir, assets)
        if artifact.assets_sha256 != json_hash(assets.model_dump(mode="json")):
            raise ValueError("audio asset manifest checksum mismatch")
    if (storyboard.backgroundMusic or any(s.audio for s in storyboard.scenes)) and artifact.mix is None:
        raise ValueError("licensed audio requested but mixed track receipt is missing")
    if artifact.mix:
        mix = artifact.mix
        original = checked_path(job_dir, mix.input_narration_path)
        if not original.is_file() or sha256_file(original) != mix.input_narration_sha256:
            raise ValueError("original narration checksum mismatch")
        if mix.assets_sha256 != artifact.assets_sha256 or mix.sha256 != artifact.sha256 or mix.output_path != artifact.narration_path:
            raise ValueError("audio mix receipt mismatch")
        if mix.source_manifest_sha256 != assets.manifest_sha256:
            raise ValueError("mix source manifest checksum mismatch")
        from .scene_data import SceneAudioSpec
        expected_sfx = [{"asset_id": effect.assetRef, "scene_id": scene.sceneId,
                         "scene_frame": effect.frame, "absolute_frame": scene.startFrame + effect.frame,
                         "volume": effect.volume}
                        for scene in storyboard.scenes if scene.audio
                        for effect in SceneAudioSpec.model_validate(scene.audio).sfx]
        if [cue.model_dump() for cue in mix.sfx] != expected_sfx:
            raise ValueError("mix SFX anchors no longer match narration timeline")
        if abs(float(probe_media(original)["format"]["duration"]) * 1000 - artifact.duration_ms) > 2:
            raise ValueError("mix original narration duration mismatch")
    for segment in artifact.segments:
        path = checked_path(job_dir, segment.path)
        if not path.is_file() or sha256_file(path) != segment.sha256:
            raise ValueError("narration segment checksum mismatch")
    narration = checked_path(job_dir, artifact.narration_path)
    if sha256_file(narration) != artifact.sha256:
        raise ValueError("narration checksum mismatch")
    probe = probe_media(narration)
    if abs(float(probe["format"]["duration"]) * 1000 - artifact.duration_ms) > 2:
        raise ValueError("narration duration mismatch")
    if artifact.total_frames != storyboard.total_frames:
        raise ValueError("narration frame count mismatch")


class AudioAgent:
    def __init__(self, *, voice: str, rate: str, tts=None) -> None:
        self.voice, self.rate = voice, rate
        self.tts = tts or EdgeTTSProvider(voice=voice, rate=rate)

    def run(self, script: Script, storyboard: Storyboard, job_dir: Path,
            cancelled: Callable[[], bool] | None = None, *, assets: AssetManifest | None = None) -> tuple[Storyboard, AudioArtifact]:
        if len(script.segments) != len(storyboard.scenes):
            raise ValueError("storyboard must have exactly one scene per script segment")
        if any(scene.segment != segment.text for scene, segment in zip(storyboard.scenes, script.segments)):
            raise ValueError("scene narration must exactly match the approved script")
        if storyboard.fps != 30:
            raise ValueError("audio engine currently supports the verified 30 FPS profile")
        assets = load_assets(storyboard, job_dir, assets)
        audio_dir = job_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        durations, boundaries, raw_files = [], [], []
        for index, segment in enumerate(script.segments):
            if cancelled is not None and cancelled():
                raise RuntimeError("job cancelled by operator")
            raw_path = audio_dir / f"segment-{index:02d}.mp3"
            receipt_path = raw_path.with_suffix(".json")
            fingerprint = json_hash({"text": segment.text, "voice": self.voice, "rate": self.rate})
            cached = None
            if raw_path.exists() and receipt_path.exists():
                try:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    if receipt["fingerprint"] == fingerprint and receipt["sha256"] == sha256_file(raw_path):
                        cached = receipt["words"]
                except (ValueError, KeyError):
                    cached = None
            words = cached if cached else self.tts.synthesize(segment.text, raw_path)
            probe = probe_media(raw_path)
            duration = float(probe["format"]["duration"]) * 1000
            _group_words(words, duration, 0, index)
            atomic_json(receipt_path, {"fingerprint": fingerprint, "sha256": sha256_file(raw_path), "words": words})
            durations.append(duration)
            boundaries.append(words)
            raw_files.append(raw_path)
        timed = timeline_from_audio(storyboard, durations, boundaries)
        pieces = []
        for index, (raw_path, scene, duration) in enumerate(zip(raw_files, timed.scenes, durations)):
            pcm = audio_dir / f"segment-{index:02d}.wav"
            samples = scene.durationInFrames * 1600
            run_checked(["ffmpeg", "-hide_banner", "-y", "-i", str(raw_path), "-af",
                         f"aresample=48000,apad,atrim=end_sample={samples}", "-ar", "48000", "-ac", "1",
                         "-c:a", "pcm_s16le", str(pcm)], log_path=audio_dir / "decode.log", cancelled=cancelled)
            pieces.append(AudioSegment(scene_id=scene.sceneId, path=pcm.relative_to(job_dir).as_posix(),
                                       raw_duration_ms=duration, duration_frames=scene.durationInFrames, sha256=sha256_file(pcm)))
        combined = audio_dir / "combined.wav"
        with wave.open(str(combined), "wb") as output:
            output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            for piece in pieces:
                with wave.open(str(checked_path(job_dir, piece.path)), "rb") as source:
                    while block := source.readframes(48000):
                        output.writeframes(block)
        measure_log = audio_dir / "loudness.log"
        measure_log.write_text("", encoding="utf-8")
        run_checked(["ffmpeg", "-hide_banner", "-nostats", "-i", str(combined), "-af",
                     "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                    log_path=measure_log, cancelled=cancelled)
        matches = re.findall(r"\{[^{}]+\}", measure_log.read_text(encoding="utf-8"))
        if not matches:
            raise ValueError("FFmpeg returned no loudness measurements")
        measured = json.loads(matches[-1])
        if not all(math.isfinite(float(measured[k])) for k in ["input_i", "input_tp", "input_lra", "input_thresh", "target_offset"]):
            raise ValueError("narration is silent or has invalid loudness measurements")
        loudnorm = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
                    f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
                    f"offset={measured['target_offset']}:linear=true")
        narration = job_dir / "narration.wav"
        run_checked(["ffmpeg", "-hide_banner", "-y", "-i", str(combined), "-af", loudnorm,
                     "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(narration)],
                    log_path=audio_dir / "normalize.log", cancelled=cancelled)
        duration_ms = float(probe_media(narration)["format"]["duration"]) * 1000
        artifact = AudioArtifact(voice=self.voice, rate=self.rate, narration_path="narration.wav", duration_ms=duration_ms,
                                 sha256=sha256_file(narration), script_sha256=json_hash(script.model_dump(mode="json", exclude_none=True)),
                                 storyboard_sha256=json_hash(timed.model_dump(mode="json", exclude_none=True)), fps=timed.fps,
                                 total_frames=timed.total_frames, segments=pieces, cues=timed.subtitles)
        artifact.assets_sha256 = json_hash(assets.model_dump(mode="json"))
        if timed.backgroundMusic or any(scene.audio for scene in timed.scenes):
            mix = mix_audio(timed, artifact, assets, job_dir, cancelled)
            artifact = artifact.model_copy(update={"mix": mix, "narration_path": mix.output_path, "sha256": mix.sha256})
        verify_audio(artifact, script, timed, job_dir, assets=assets)
        return timed, artifact

"""Real FFmpeg tests using explicitly labelled, self-created fixture tones only."""
import math
import struct
import wave
from pathlib import Path

import pytest

from packages.core.media.assets import AssetAgent
from packages.core.media.audio import AudioAgent, verify_audio
from packages.core.media.process import atomic_json, probe_media, sha256_file
from packages.core.schemas import SceneSpec, Script, Storyboard


def labelled_tone(path, frequency, duration, *, gated=False):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(b"".join(struct.pack("<h", int(
            6000 * math.sin(2 * math.pi * frequency * i / 48000)
            * (1 if not gated or 0.8 < i / 48000 < 1.7 else 0))) for i in range(round(duration * 48000))))


class FixtureTTS:
    def __init__(self):
        self.calls = 0

    def synthesize(self, text, output):
        self.calls += 1
        labelled_tone(output, 800, 2.0, gated=True)
        return [{"text": text, "startMs": 800, "endMs": 1700}]


def audio_inputs(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    tracks = []
    for ref, kind, frequency, duration in [("bgm-fixture", "music", 180, 1.0), ("sfx-fixture", "sfx", 2000, 0.15)]:
        path = library / f"{ref}.wav"
        labelled_tone(path, frequency, duration)
        tracks.append({"id": ref, "path": path.name, "kind": kind, "license": "project-original",
                       "attribution": "Shorts Factory AI labelled test tone, not production music",
                       "source": "project:tests/test_audio_mix.py", "sha256": sha256_file(path)})
    manifest = library / "manifest.json"
    atomic_json(manifest, {"assets": tracks})
    script = Script(title="Fixture audio", genre="fiction", content_type="fictional", segments=[
        {"kind": "hook", "text": "Narasi uji pertama."}, {"kind": "payoff", "text": "Narasi uji kedua."}])
    storyboard = Storyboard(id="audio-fixture", backgroundMusic={"assetRef": "bgm-fixture", "volume": 0.3, "loop": True}, scenes=[
        SceneSpec(sceneId="one", template="KineticTypography", segment=script.segments[0].text, durationInFrames=300),
        SceneSpec(sceneId="two", template="KineticTypography", segment=script.segments[1].text, durationInFrames=300,
                  startFrame=300, audio={"sfx": [{"assetRef": "sfx-fixture", "frame": 6, "volume": 0.6}]}),
    ])
    job = tmp_path / "job"
    job.mkdir()
    assets = AssetAgent().run(storyboard, job, manifest_path=manifest)
    atomic_json(job / "assets.json", assets.model_dump(mode="json"))
    return script, storyboard, job, assets


def test_audio_agent_mixes_licensed_tracks_without_changing_narration_timeline(tmp_path):
    script, storyboard, job, assets = audio_inputs(tmp_path)
    tts = FixtureTTS()
    timed, audio = AudioAgent(voice="fixture", rate="+0%", tts=tts).run(script, storyboard, job)
    assert audio.mix is not None
    assert audio.mix.ducking == "sidechaincompress"
    assert audio.narration_path == "mix.wav"
    assert audio.duration_ms == pytest.approx(4000, abs=1)
    assert timed.total_frames == 120
    assert audio.mix.sfx[0].absolute_frame == 66
    assert audio.mix.sfx[0].scene_id == "two"
    assert audio.mix.integrated_lufs == pytest.approx(-16, abs=1)
    assert audio.mix.true_peak_dbtp <= -1.0
    assert (job / audio.mix.input_narration_path).is_file()
    assert audio.mix.input_narration_sha256 != audio.sha256
    assert probe_media(job / audio.narration_path)["streams"][0]["channels"] == 2
    verify_audio(audio, script, timed, job)
    before = sha256_file(job / "mix.wav")
    again, cached = AudioAgent(voice="fixture", rate="+0%", tts=tts).run(script, storyboard, job)
    assert tts.calls == 2
    assert cached.sha256 == before
    assert again.total_frames == timed.total_frames

    # Measure the actual carrier bands, not just the filter name in a receipt.
    def band(frequency, start, seconds=0.1):
        with wave.open(str(job / audio.narration_path), "rb") as stream:
            stream.setpos(round(start * stream.getframerate()))
            raw = stream.readframes(round(seconds * stream.getframerate()))
            mono = struct.unpack("<" + "h" * (len(raw) // 2), raw)[::stream.getnchannels()]
        real = sum(value * math.cos(2 * math.pi * frequency * i / 48000) for i, value in enumerate(mono))
        imaginary = sum(value * math.sin(2 * math.pi * frequency * i / 48000) for i, value in enumerate(mono))
        return math.hypot(real, imaginary) / len(mono)

    assert band(180, 1.3) < band(180, 0.5) * 0.6  # Narration ducks the actual music band.
    assert band(2000, 2.22) > max(1, band(2000, 2.02)) * 20  # Scene-two frame six = 2.2s.
    assert band(180, 2.5) > 20  # One-second music input really loops into later scenes.


@pytest.mark.parametrize("target", ["source", "manifest", "original", "mix"])
def test_mixed_audio_resume_rejects_mutated_inputs(tmp_path, target):
    script, storyboard, job, assets = audio_inputs(tmp_path)
    timed, audio = AudioAgent(voice="fixture", rate="+0%", tts=FixtureTTS()).run(script, storyboard, job)
    paths = {"source": Path(assets.library_root) / assets.assets[0].path,
             "manifest": Path(assets.library_root) / assets.manifest_path,
             "original": job / audio.mix.input_narration_path, "mix": job / audio.narration_path}
    with paths[target].open("ab") as stream:
        stream.write(b"mutation")
    with pytest.raises(ValueError, match="checksum"):
        verify_audio(audio, script, timed, job)


def test_sfx_rejects_anchor_outside_measured_scene(tmp_path):
    script, storyboard, job, assets = audio_inputs(tmp_path)
    storyboard.scenes[1].audio["sfx"][0]["frame"] = 90  # Valid provisional frame, outside real 60-frame segment.
    assets = AssetAgent().run(storyboard, job, manifest_path=Path(assets.library_root) / assets.manifest_path)
    atomic_json(job / "assets.json", assets.model_dump(mode="json"))
    with pytest.raises(ValueError, match="outside the measured"):
        AudioAgent(voice="fixture", rate="+0%", tts=FixtureTTS()).run(script, storyboard, job)

import json
import wave

import pytest

from packages.core.schemas import SceneSpec, Storyboard


def _storyboard():
    return Storyboard(id="timeline-test", scenes=[
        SceneSpec(sceneId="a", template="KineticTypography", segment="Halo dunia.", durationInFrames=300),
        SceneSpec(sceneId="b", template="EducationalExplainer", segment="Narasi kedua.", startFrame=300, durationInFrames=300),
    ])


def test_timeline_uses_measured_durations_not_model_estimates():
    from packages.core.media.audio import timeline_from_audio

    storyboard = timeline_from_audio(_storyboard(), [1234.0, 2345.0], [
        [{"text": "Halo", "startMs": 50, "endMs": 400}, {"text": "dunia.", "startMs": 430, "endMs": 950}],
        [{"text": "Narasi", "startMs": 20, "endMs": 700}, {"text": "kedua.", "startMs": 730, "endMs": 1900}],
    ])
    assert [(s.startFrame, s.durationInFrames) for s in storyboard.scenes] == [(0, 38), (38, 71)]
    assert storyboard.subtitles[0].startMs == 50
    assert storyboard.subtitles[1].startMs == 1287
    assert storyboard.subtitles[-1].endMs <= storyboard.total_frames / 30 * 1000


def test_timeline_requires_actual_word_boundaries():
    from packages.core.media.audio import timeline_from_audio

    with pytest.raises(ValueError, match="boundar"):
        timeline_from_audio(_storyboard(), [2000, 2000], [[], []])


def test_storyboard_cannot_replace_approved_narration():
    from packages.core.agents import StoryboardAgent
    from packages.core.providers import MockProvider, ProviderRouter

    router = ProviderRouter(worker_chain=[MockProvider()])
    from packages.core.schemas import Script
    from packages.core.providers.mock import FIXTURES
    script = Script.model_validate(json.loads(FIXTURES["script"]))
    storyboard = StoryboardAgent(router, fps=30, width=1080, height=1920).run(script)
    assert [s.segment for s in storyboard.scenes] == [s.text for s in script.segments]


def test_audio_probe_reads_real_pcm_file(tmp_path):
    from packages.core.media.process import probe_media

    path = tmp_path / "labelled-test-silence.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(bytes(48000 * 2))
    probe = probe_media(path)
    assert float(probe["format"]["duration"]) == pytest.approx(1.0)
    assert probe["streams"][0]["codec_type"] == "audio"


def test_asset_agent_rejects_unimplemented_template():
    from packages.core.media.assets import AssetAgent

    storyboard = _storyboard()
    storyboard.scenes[0].template = "MotionComic"
    with pytest.raises(ValueError, match="not implemented"):
        AssetAgent().run(storyboard)


def test_audio_agent_runs_real_ffmpeg_with_labelled_offline_tone(tmp_path):
    import math
    import struct
    from packages.core.media.audio import AudioAgent, verify_audio
    from packages.core.schemas import Script

    class LabelledTestTTS:
        def synthesize(self, text, output):
            with wave.open(str(output), "wb") as stream:
                stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                stream.writeframes(b"".join(struct.pack("<h", int(5000 * math.sin(2 * math.pi * 440 * i / 48000))) for i in range(59232)))
            return [{"text": text, "startMs": 50, "endMs": 950}]

    script = Script(title="Labelled test tone", genre="fiction", content_type="fictional",
                    segments=[{"kind": "hook", "text": "Halo dunia."}, {"kind": "payoff", "text": "Narasi kedua."}])
    timed, artifact = AudioAgent(voice="test", rate="+0%", tts=LabelledTestTTS()).run(script, _storyboard(), tmp_path)
    verify_audio(artifact, script, timed, tmp_path)
    assert artifact.total_frames == 76
    assert artifact.duration_ms == pytest.approx(76 / 30 * 1000, abs=1)
    assert len(artifact.cues) == 2


def test_video_validation_rejects_missing_audio():
    from packages.core.media.render import validate_probe

    probe = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920,
                          "r_frame_rate": "30/1"}], "format": {"duration": "35"}}
    with pytest.raises(ValueError, match="audio"):
        validate_probe(probe, expected_frames=1050, fps=30, width=1080, height=1920)

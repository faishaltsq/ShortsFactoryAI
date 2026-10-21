"""Dialect tests: real model answers must normalize into SceneSpec."""

from packages.core.schemas import Storyboard
from packages.core.storyboard_normalize import (
    normalize_animation,
    normalize_template,
    normalize_storyboard,
)

# Shape observed from a live worker-model answer (2026-10-20), trimmed.
REAL_DIALECT = {
    "meta": {"fps": 30, "width": 1080, "height": 1920, "language": "id-ID"},
    "scenes": [
        {
            "id": "scene-01",
            "template": "kinetic typography",
            "narration": "Komputer tertua di dunia masih menyala setiap hari.",
            "text": [
                {"kind": "title", "value": "Komputer Tertua di Dunia"},
                {"kind": "highlight", "value": "Masih menyala."},
            ],
            "duration_seconds": 8,
            "animation": {"name": "word-by-word", "duration": 24},
            "transition": {"type": "crossfade", "duration": 12},
        },
        {
            "id": "scene-02",
            "visual": "Historical Timeline",
            "segment": "Roda gigi perunggu mengunci satu sama lain.",
            "text": ["Roda Gigi Perunggu"],
            "durationInFrames": 420,
        },
    ],
}


def test_real_dialect_validates_into_storyboard():
    normalized = normalize_storyboard(REAL_DIALECT, fallback_id="job-1")
    storyboard = Storyboard.model_validate(normalized)

    assert storyboard.id == "job-1"
    assert storyboard.fps == 30
    first, second = storyboard.scenes
    assert first.sceneId == "scene-01"
    assert first.template == "KineticTypography"
    assert first.text[0].text == "Komputer Tertua di Dunia"
    assert first.text[0].style.role == "title"
    assert first.durationInFrames == 240  # 8s @30fps
    assert first.animation.preset == "wordByWord"
    assert first.transition.type == "fade"
    assert second.template == "HistoricalTimeline"
    assert second.text[0].text == "Roda Gigi Perunggu"
    # sequential timing enforced
    assert second.startFrame == first.durationInFrames
    assert storyboard.total_frames == 240 + 420


def test_bare_array_and_missing_fields():
    normalized = normalize_storyboard(
        [{"template": "unknown-thing", "text": "Hanya satu baris teks"}],
        fallback_id="x",
    )
    storyboard = Storyboard.model_validate(normalized)
    scene = storyboard.scenes[0]
    assert scene.sceneId.startswith("scene-")
    assert scene.template == "EducationalExplainer"  # unknown keyword fallback
    assert scene.segment == "Hanya satu baris teks"
    assert 30 <= scene.durationInFrames <= 3000


def test_duration_from_words_when_no_timing():
    normalized = normalize_storyboard(
        [{"segment": " ".join(["kata"] * 26), "template": "parallax"}],
        fallback_id="y",
        fps=30,
    )
    scene = Storyboard.model_validate(normalized).scenes[0]
    # 26 words / 2.6 wps = 10s + 1s breathing = 11s = 330 frames
    assert scene.durationInFrames == 330
    assert scene.template == "ParallaxStory"


def test_animation_aliases():
    assert normalize_animation("count_up")["preset"] == "countUp"
    assert normalize_animation({"preset": "sideways"})["preset"] == "fadeIn"
    assert normalize_template("Motion Comic") == "MotionComic"
    assert normalize_template(None) == "EducationalExplainer"


def test_scenes_as_escaped_json_string():
    import json as _json

    payload = {"scenes": _json.dumps([{"id": "a", "segment": "halo", "template": "comic"}])}
    storyboard = Storyboard.model_validate(normalize_storyboard(payload, fallback_id="s"))
    assert storyboard.scenes[0].segment == "halo"


def test_scenes_as_bare_narration_string():
    storyboard = Storyboard.model_validate(
        normalize_storyboard({"scenes": "Kalimat narasi utuh."}, fallback_id="s")
    )
    assert storyboard.scenes[0].segment == "Kalimat narasi utuh."


def test_seconds_to_ms_subtitle_cues():
    normalized = normalize_storyboard(
        {"scenes": [{"segment": "halo", "template": "comic"}],
         "subtitles": [{"id": "c1", "text": "halo", "start": 0.5, "end": 2.0}]},
        fallback_id="z",
    )
    cues = Storyboard.model_validate(normalized).subtitles
    assert cues[0].startMs == 500
    assert cues[0].endMs == 2000


def test_illustrated_template_and_lifted_data():
    payload = {"scenes": [{
        "id": "s1", "visual": "Illustrated Scene", "segment": "Cahaya tertunda.",
        "setting": "space", "timeOfDay": "night",
        "actors": [{"pose": "Pointing", "x": 0.3, "ground": 0.74}],
        "props": [{"kind": "Sun", "x": 0.7, "y": 0.25}],
        "shots": [{"framing": "Wide", "camera": "push in"}],
    }]}
    scene = normalize_storyboard(payload, fallback_id="j")["scenes"][0]
    assert scene["template"] == "IllustratedStory"
    assert scene["data"]["setting"] == "space"
    assert scene["data"]["actors"][0]["pose"] == "point"
    assert scene["data"]["props"][0]["kind"] == "sun"
    assert scene["data"]["shots"][0] == {"framing": "wide", "camera": "pushIn", "weight": 1.0}
    Storyboard.model_validate(normalize_storyboard(payload, fallback_id="j"))


def test_unknown_illustration_key_is_dropped_not_fatal():
    payload = {"scenes": [{"visual": "illustration", "segment": "x", "setting": "city", "mood": "tense"}]}
    scene = normalize_storyboard(payload, fallback_id="j")["scenes"][0]
    assert "mood" not in scene["data"]


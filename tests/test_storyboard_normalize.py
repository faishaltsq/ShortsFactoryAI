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
    # The model asked for HistoricalTimeline but supplied no timeline events.
    # Inventing dates would fabricate content, so the scene degrades to the
    # data-free template and keeps the text the model did write.
    assert second.template == "KineticTypography"
    assert second.text[0].text == "Roda Gigi Perunggu"
    # sequential timing enforced
    assert second.startFrame == first.durationInFrames
    assert storyboard.total_frames == 240 + 420


def test_declared_template_with_complete_data_is_preserved():
    """A model that does supply valid template data keeps its chosen renderer."""
    normalized = normalize_storyboard(
        [{"template": "HistoricalTimeline", "segment": "Roda gigi perunggu.",
          "text": ["Roda Gigi Perunggu"],
          "data": {"title": "Linimasa", "events": [
              {"date": "1956", "label": "Dartmouth"},
              {"date": "2022", "label": "GPT"}]}}],
        fallback_id="job-2",
    )
    scene = Storyboard.model_validate(normalized).scenes[0]
    assert scene.template == "HistoricalTimeline"
    assert scene.data["events"][0]["date"] == "1956"


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
    # ParallaxStory is completed from the narration rather than invented:
    # a title is taken from the text the model wrote (capped at the contract's 70
    # characters), and one neutral layer is added so the scene can render.
    assert scene.template == "ParallaxStory"
    assert scene.data["title"] == ("kata " * 26).strip()[:70].strip()
    assert scene.data["layers"] == [{"depth": 0.5, "shape": "ridge"}]


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



# --- structured template data: the live model must not be able to fail a job ---

def _scene(template, data, segment="Narasi satu segmen.", scene_id="s1"):
    return {
        "sceneId": scene_id,
        "template": template,
        "segment": segment,
        "text": [{"text": "Judul", "role": "title"}],
        "data": data,
    }


def test_invented_infographic_keys_do_not_fail_the_storyboard():
    """Regression: a live run died on `data={'metric': '15,3', 'unit': ...}`.

    The model invented its own infographic schema. Unknown keys are dropped and the
    scene falls back to the one template that needs no structured data, so the job
    keeps its narration instead of failing at STORYBOARD_READY.
    """
    from packages.core.schemas import Storyboard
    from packages.core.storyboard_normalize import normalize_storyboard

    payload = {"storyboard": {"scenes": [
        _scene("InfographicMotion", {"metric": "15,3", "unit": "persen",
                                     "color": "#FF4D6D", "accent": "#FF4D6D", "fontSize": 30}),
    ]}}
    out = normalize_storyboard(payload, fallback_id="regresi")
    scene = out["scenes"][0]
    assert scene["template"] == "KineticTypography"
    assert scene.get("data") is None
    assert Storyboard.model_validate(out).scenes[0].segment == "Narasi satu segmen."


def test_infographic_dialect_is_normalised_into_the_strict_contract():
    from packages.core.schemas import Storyboard
    from packages.core.storyboard_normalize import normalize_storyboard

    payload = {"storyboard": {"scenes": [_scene("InfographicMotion", {
        "headline": "Akurasi model",
        "metrics": [{"name": "2012", "amount": "15,3", "suffix": "persen"},
                    {"name": "2024", "amount": 92}],
        "maximum": 100,
        "precision": 1,
    })]}}
    data = Storyboard.model_validate(normalize_storyboard(payload, fallback_id="x")).scenes[0].data
    assert data["title"] == "Akurasi model"
    assert data["items"] == [{"label": "2012", "value": 15.3, "unit": "persen"},
                             {"label": "2024", "value": 92.0}]
    assert data["maxValue"] == 100.0
    assert data["decimals"] == 1


def test_indonesian_decimal_comma_and_unit_suffix_are_parsed():
    from packages.core.storyboard_normalize import _number

    assert _number("15,3") == 15.3
    assert _number("15,3 persen") == 15.3
    assert _number("1.234,5") == 1234.5
    assert _number("1,234.5") == 1234.5
    assert _number("92") == 92.0
    assert _number(92) == 92.0
    assert _number("tanpa angka") is None
    assert _number(True) is None


def test_timeline_comic_and_parallax_dialects_are_normalised():
    from packages.core.schemas import Storyboard
    from packages.core.storyboard_normalize import normalize_storyboard

    payload = {"storyboard": {"scenes": [
        _scene("HistoricalTimeline", {"headline": "Linimasa", "moments": [
            {"year": 1956, "title": "Dartmouth"},
            {"year": 2022, "title": "GPT", "description": "Model bahasa besar"}]}, scene_id="s1"),
        _scene("MotionComic", {"frames": [{"dialogue": "Halo dunia", "character": "Nara"}]}, scene_id="s2"),
        _scene("ParallaxStory", {"title": "Kota", "panes": [
            {"z": 0.3, "kind": "city"}, {"z": 0.8, "kind": "ridge"}]}, scene_id="s3"),
    ]}}
    scenes = Storyboard.model_validate(normalize_storyboard(payload, fallback_id="x")).scenes

    assert scenes[0].template == "HistoricalTimeline"
    assert scenes[0].data["events"] == [
        {"date": "1956", "label": "Dartmouth"},
        {"date": "2022", "label": "GPT", "detail": "Model bahasa besar"},
    ]
    assert scenes[1].template == "MotionComic"
    assert scenes[1].data["panels"] == [{"caption": "Halo dunia", "speaker": "Nara"}]
    assert scenes[2].template == "ParallaxStory"
    assert scenes[2].data["layers"] == [{"depth": 0.3, "shape": "city"},
                                        {"depth": 0.8, "shape": "ridge"}]


def test_parallax_layer_without_a_visual_is_dropped_not_rendered_blank():
    from packages.core.storyboard_normalize import normalize_storyboard

    payload = {"storyboard": {"scenes": [_scene("ParallaxStory", {
        "title": "Kota", "layers": [{"depth": 0.4}, {"depth": 0.9, "shape": "ridge"}]})]}}
    layers = normalize_storyboard(payload, fallback_id="x")["scenes"][0]["data"]["layers"]
    assert layers == [{"depth": 0.9, "shape": "ridge"}]


def test_valid_template_data_is_left_alone():
    """The normaliser must not downgrade a scene the model already got right."""
    from packages.core.schemas import Storyboard
    from packages.core.storyboard_normalize import normalize_storyboard

    payload = {"storyboard": {"scenes": [_scene("InfographicMotion", {
        "title": "Akurasi", "items": [{"label": "2024", "value": 92, "unit": "persen"}],
        "maxValue": 100, "decimals": 0})]}}
    scene = Storyboard.model_validate(normalize_storyboard(payload, fallback_id="x")).scenes[0]
    assert scene.template == "InfographicMotion"
    assert scene.data["items"] == [{"label": "2024", "value": 92.0, "unit": "persen"}]


def test_storyboard_prompt_states_every_template_data_contract():
    """The prompt must carry the contracts; otherwise the model invents them."""
    from packages.core import prompts

    text = prompts.STORYBOARD_SYSTEM
    for token in ('"items"', '"events"', '"layers"', '"panels"', '"setting"', '"maxValue"'):
        assert token in text, f"storyboard prompt never states {token}"


# --- scene/segment alignment: a formatting deviation must not fail the job ---

def test_merged_scenes_are_split_to_match_the_script():
    """Regression: a live run failed with 'storyboard must return one scene per segment'."""
    import json

    from packages.core.agents import StoryboardAgent
    from packages.core.providers import MockProvider, ProviderRouter
    from packages.core.schemas import Script

    script = Script.model_validate(json.loads(__import__("packages.core.providers.mock", fromlist=["FIXTURES"]).FIXTURES["script"]))
    merged = {"storyboard": {"scenes": [{
        "sceneId": "s1", "template": "KineticTypography",
        "segment": "gabungan", "text": [{"text": "Judul", "role": "title"}]}]}}
    router = ProviderRouter(worker_chain=[MockProvider({"storyboard": json.dumps(merged)})])
    storyboard = StoryboardAgent(router, fps=30, width=1080, height=1920).run(script)

    assert len(storyboard.scenes) == len(script.segments)
    assert [s.segment for s in storyboard.scenes] == [s.text for s in script.segments]
    assert len({s.sceneId for s in storyboard.scenes}) == len(storyboard.scenes)


def test_extra_scenes_are_dropped_to_match_the_script():
    import json

    from packages.core.agents import StoryboardAgent
    from packages.core.providers import MockProvider, ProviderRouter
    from packages.core.schemas import Script
    from packages.core.providers.mock import FIXTURES

    script = Script.model_validate(json.loads(FIXTURES["script"]))
    scenes = [{"sceneId": f"x{i}", "template": "KineticTypography", "segment": f"s{i}",
               "text": [{"text": f"T{i}", "role": "title"}]} for i in range(len(script.segments) + 3)]
    router = ProviderRouter(worker_chain=[MockProvider({"storyboard": json.dumps({"storyboard": {"scenes": scenes}})})])
    storyboard = StoryboardAgent(router, fps=30, width=1080, height=1920).run(script)

    assert len(storyboard.scenes) == len(script.segments)


def test_aligned_scene_never_invents_template_data():
    """A cloned scene must not fabricate numbers; it degrades to a data-free template."""
    from packages.core.agents import _align_scenes

    scenes = [{"sceneId": "a", "template": "InfographicMotion",
               "data": {"title": "Akurasi", "items": [{"label": "2012", "value": 15.3}]}}]
    aligned = _align_scenes(scenes, 3)
    assert len(aligned) == 3
    for scene in aligned[1:]:
        assert scene["template"] == "KineticTypography"
        assert "data" not in scene


def test_quality_prompt_does_not_ask_for_unmeasured_duration_judgement():
    """Draft timing is word-guessed; judging it produced false failures on live runs."""
    from packages.core import prompts
    from packages.core.schemas import SceneSpec, Storyboard

    assert "JANGAN menilai durasi" in prompts.QUALITY_SYSTEM
    board = Storyboard(id="x", scenes=[SceneSpec(sceneId="a", template="KineticTypography", segment="Halo.")])
    assert "bukan narasi terukur" in prompts.quality_user(board, "{}")


def test_text_frames_are_clamped_to_the_scene_they_belong_to():
    """A live reviewer found text that vanished before its scene ended.

    in/out frames are the model's guess; the scene duration is authoritative, so
    an out-of-range frame is clamped instead of hiding text mid-scene.
    """
    from packages.core.schemas import Storyboard
    from packages.core.storyboard_normalize import normalize_storyboard

    raw = {"storyboard": {"scenes": [
        {"sceneId": "s1", "template": "KineticTypography", "segment": "Satu.",
         "durationInFrames": 330,
         "text": [{"text": "A", "role": "title", "inFrame": 10, "outFrame": 230}]},
        {"sceneId": "s2", "template": "KineticTypography", "segment": "Dua.",
         "durationInFrames": 100,
         "text": [{"text": "B", "role": "title", "inFrame": 900, "outFrame": 2000}]},
    ]}}
    scenes = Storyboard.model_validate(normalize_storyboard(raw, fallback_id="x")).scenes

    assert (scenes[0].text[0].inFrame, scenes[0].text[0].outFrame) == (10, 230)
    # Clamped into [0, duration) rather than left outside the scene.
    assert scenes[1].text[0].inFrame == 99
    assert scenes[1].text[0].outFrame == 100


def test_text_that_would_end_before_it_starts_loses_its_out_frame():
    from packages.core.schemas import Storyboard
    from packages.core.storyboard_normalize import normalize_storyboard

    raw = {"storyboard": {"scenes": [
        {"sceneId": "s1", "template": "KineticTypography", "segment": "Satu.",
         "durationInFrames": 100,
         "text": [{"text": "A", "role": "title", "inFrame": 50, "outFrame": 20}]},
    ]}}
    element = Storyboard.model_validate(normalize_storyboard(raw, fallback_id="x")).scenes[0].text[0]
    assert element.outFrame is None, "an inverted range would hide the text entirely"


def test_music_descriptor_without_a_manifest_asset_is_dropped():
    """Live models answer with a mood, not an asset id; nothing can resolve a mood."""
    from packages.core.storyboard_normalize import normalize_storyboard

    out = normalize_storyboard({"scenes": [{"segment": "Satu.", "durationInFrames": 60}],
                                "backgroundMusic": {"mood": "curious", "intensity": 0.35}},
                               fallback_id="music")
    assert "backgroundMusic" not in out


def test_music_reference_keeps_only_the_licensed_contract():
    from packages.core.schemas import Storyboard
    from packages.core.storyboard_normalize import normalize_storyboard

    out = normalize_storyboard({"scenes": [{"segment": "Satu.", "durationInFrames": 60}],
                                "music": {"assetRef": " bgm-01 ", "volume": 1.4,
                                          "loop": False, "mood": "curious"}},
                               fallback_id="music")
    assert out["backgroundMusic"] == {"assetRef": "bgm-01", "volume": 1.0, "loop": False}
    Storyboard.model_validate(out)

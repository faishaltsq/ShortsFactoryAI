"""Normalize LLM storyboard dialect into the strict SceneSpec contract.

Real models answer with close-but-not-exact shapes: `id` instead of `sceneId`,
`value` instead of `text`, `duration_seconds` instead of `durationInFrames`,
`meta` blocks, unknown template spellings. This module maps that dialect onto
the renderer contract in one deterministic place, so agents stay thin.
"""

from __future__ import annotations

import json
import re
from typing import Any

WORD_PER_SEC = 2.6

_TEMPLATE_KEYWORDS = [
    ("kinetic", "KineticTypography"),
    ("comic", "MotionComic"),
    ("infographicmotion", "InfographicMotion"),
    ("infographic", "InfographicMotion"),
    ("info", "EducationalExplainer"),
    ("explainer", "EducationalExplainer"),
    ("timeline", "HistoricalTimeline"),
    ("historical", "HistoricalTimeline"),
    ("history", "HistoricalTimeline"),
    ("parallax", "ParallaxStory"),
    ("story", "ParallaxStory"),
]
_ROLE_KEYWORDS = [
    ("title", "title"), ("heading", "title"), ("hero", "title"),
    ("highlight", "highlight"), ("stat", "highlight"), ("number", "highlight"),
    ("caption", "caption"), ("sub", "caption"),
    ("kicker", "kicker"), ("label", "kicker"), ("tag", "kicker"),
    ("body", "body"), ("text", "body"),
]
_ANIMATION_ALIASES = {
    "wordbyword": "wordByWord", "word_by_word": "wordByWord",
    "word-by-word": "wordByWord", "type": "wordByWord",
    "countup": "countUp", "count_up": "countUp", "counter": "countUp",
    "popin": "popIn", "pop": "popIn", "bounce": "popIn",
    "slideup": "slideUp", "slide_up": "slideUp", "rise": "slideUp",
    "wipein": "wipeIn", "wipe": "wipeIn",
    "fadein": "fadeIn", "fade": "fadeIn", "": "fadeIn",
}
_TRANSITION_ALIASES = {
    "none": "none", "cut": "none", "hard": "none",
    "fade": "fade", "crossfade": "fade", "dissolve": "fade",
    "slideup": "slideUp", "slide": "slideUp",
    "wipe": "wipe", "wipeleft": "wipe", "wiperight": "wipe",
    "zoom": "zoom", "punch": "zoom", "scale": "zoom",
}


def normalize_template(raw: Any) -> str:
    text = re.sub(r"[^a-z]", "", str(raw or "").lower())
    for needle, template in _TEMPLATE_KEYWORDS:
        if needle in text:
            return template
    return "EducationalExplainer"


def normalize_role(raw: Any) -> str:
    text = str(raw or "").lower()
    for needle, role in _ROLE_KEYWORDS:
        if needle in text:
            return role
    return "body"


def _int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first(mapping: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def normalize_animation(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        preset = _first(raw, ("preset", "name", "type"), "fadeIn")
        duration = _int(_first(raw, ("durationInFrames", "duration", "frames")))
        intensity = _float(raw.get("intensity"))
    else:
        preset, duration, intensity = raw, None, None
    key = str(preset or "").strip()
    resolved = (
        _ANIMATION_ALIASES.get(key.lower())
        or _ANIMATION_ALIASES.get(re.sub(r"[^a-z_]", "", key.lower()))
        or "fadeIn"
    )
    out: dict[str, Any] = {"preset": resolved}
    if duration:
        out["durationInFrames"] = max(1, min(duration, 600))
    if intensity is not None:
        out["intensity"] = max(0.0, min(intensity, 2.0))
    return out


def normalize_transition(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        kind = _first(raw, ("type", "name", "preset"), "fade")
        duration = _int(_first(raw, ("durationInFrames", "duration", "frames")), 10)
    else:
        kind, duration = raw, 10
    key = str(kind or "fade").strip().lower()
    resolved = (
        _TRANSITION_ALIASES.get(key)
        or _TRANSITION_ALIASES.get(re.sub(r"[^a-z]", "", key))
        or "fade"
    )
    return {"type": resolved, "durationInFrames": max(1, min(duration or 10, 60))}


def _normalize_text_element(raw: Any, index: int, scene_id: str) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        raw = {"text": str(raw)}
    text = str(_first(raw, ("text", "value", "content", "title", "label"), "")).strip()
    style_in = raw.get("style") if isinstance(raw.get("style"), dict) else {}
    role = normalize_role(_first(raw, ("role", "kind", "type"), style_in.get("role")))
    style: dict[str, Any] = {"role": role}
    size = _int(_first(raw, ("size", "fontSize"), style_in.get("size")))
    if size:
        style["size"] = size
    color = _first(raw, ("color", "colour"), style_in.get("color"))
    if isinstance(color, str) and color:
        style["color"] = color
    if raw.get("uppercase") is not None:
        style["uppercase"] = bool(raw["uppercase"])
    align = str(_first(raw, ("align", "alignment"), style_in.get("align") or "")).lower()
    if align in ("left", "center", "right"):
        style["align"] = align
    element: dict[str, Any] = {
        "id": str(_first(raw, ("id", "textId"), f"{scene_id}-t{index}")),
        "text": text,
        "style": style,
    }
    in_frame = _int(_first(raw, ("inFrame", "in_frame")))
    out_frame = _int(_first(raw, ("outFrame", "out_frame")))
    if in_frame is not None:
        element["inFrame"] = in_frame
    if out_frame is not None:
        element["outFrame"] = out_frame
    return element


def _normalize_duration(scene: dict[str, Any], segment: str, fps: int) -> int:
    frames = _int(_first(scene, ("durationInFrames", "duration_in_frames", "frames", "duration")))
    if frames and frames > 0:
        return max(30, min(frames, 3000))
    seconds = _float(
        _first(scene, ("duration_seconds", "durationSec", "duration_s", "seconds", "dur"))
    )
    if seconds and seconds > 0:
        return max(30, min(int(seconds * fps), 3000))
    words = len(segment.split())
    estimated = int((words / WORD_PER_SEC) * fps) + fps  # breathing room
    return max(30, min(estimated, 3000))


def _normalize_scene(raw: Any, index: int, fps: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"scene {index} is not an object: {type(raw).__name__}")
    scene_id = str(_first(raw, ("sceneId", "id", "scene_id", "name"), f"scene-{index + 1:02d}"))
    text_raw = _first(raw, ("text", "texts", "elements", "captions", "items"), [])
    if isinstance(text_raw, str):
        text_raw = [{"text": text_raw}]
    if not isinstance(text_raw, list):
        text_raw = [text_raw]
    text_elements = [
        _normalize_text_element(item, i, scene_id) for i, item in enumerate(text_raw)
    ]
    segment = str(
        _first(raw, ("segment", "narration", "voiceover", "caption", "subtitle", "text"), "")
    )
    if not segment:
        segment = " ".join(el["text"] for el in text_elements if el["text"]).strip()
    scene: dict[str, Any] = {
        "sceneId": scene_id,
        "template": normalize_template(_first(raw, ("template", "visual", "visualTemplate"))),
        "segment": segment,
        "text": text_elements,
        "animation": normalize_animation(raw.get("animation")),
        "transition": normalize_transition(raw.get("transition")),
        "durationInFrames": _normalize_duration(raw, segment, fps),
        "startFrame": _int(_first(raw, ("startFrame", "start_frame", "from")), 0) or 0,
    }
    assets = _first(raw, ("assetRefs", "assets", "asset_refs"), [])
    if isinstance(assets, list):
        scene["assetRefs"] = [str(a) for a in assets]
    audio = raw.get("audio")
    if isinstance(audio, dict):
        scene["audio"] = audio
    data = raw.get("data")
    if isinstance(data, dict):
        scene["data"] = data
    return scene


def _cue_time(cue: dict[str, Any], ms_keys: tuple[str, ...], sec_keys: tuple[str, ...]) -> int | None:
    """Explicit ms keys win; otherwise a value under 600 is read as seconds."""
    ms = _float(_first(cue, ms_keys))
    if ms is not None:
        return int(ms)
    sec = _float(_first(cue, sec_keys))
    if sec is None:
        return None
    return int(sec * 1000) if sec < 600 else int(sec)


def _normalize_subtitles(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    cues: list[dict[str, Any]] = []
    for i, cue in enumerate(raw):
        if not isinstance(cue, dict):
            continue
        text = str(_first(cue, ("text", "value", "line", "content"), "")).strip()
        if not text:
            continue
        start = _cue_time(cue, ("startMs", "start_ms"), ("start", "from", "begin"))
        end = _cue_time(cue, ("endMs", "end_ms"), ("end", "to"))
        if start is None or end is None or end <= start:
            continue
        cues.append(
            {"id": str(_first(cue, ("id", "cue_id"), f"cue-{i:03d}")), "text": text,
             "startMs": start, "endMs": end}
        )
    return cues


def normalize_storyboard(
    data: Any,
    *,
    fallback_id: str,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    language: str = "id-ID",
) -> dict[str, Any]:
    """Map any accepted model dialect onto a Storyboard-shaped dict."""
    if isinstance(data, list):
        data = {"scenes": data}
    if not isinstance(data, dict):
        raise ValueError(f"storyboard payload must be object or array, got {type(data).__name__}")
    wrapper = data.get("storyboard")
    if isinstance(wrapper, dict):
        # {"storyboard": {...}} wrapper: the inner object is the payload,
        # the outer one may still carry meta/notes.
        merged = dict(wrapper)
        if isinstance(data.get("meta"), dict) and "meta" not in merged:
            merged["meta"] = data["meta"]
        data = merged

    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    fps = int(_first(meta, ("fps", "frameRate"), fps) or fps)
    width = int(_first(meta, ("width", "w"), width) or width)
    height = int(_first(meta, ("height", "h"), height) or height)
    language = str(_first(meta, ("language", "lang"), language) or language)

    scenes_raw = _first(data, ("scenes", "shots", "sequence", "storyboard"), [])
    if isinstance(scenes_raw, dict):
        scenes_raw = _first(scenes_raw, ("scenes", "shots"), [])
    if isinstance(scenes_raw, str):
        # model JSON-escaped the whole scene list, or answered with narration
        try:
            parsed = json.loads(scenes_raw)
        except json.JSONDecodeError:
            parsed = [{"segment": scenes_raw}]
        scenes_raw = parsed
    if isinstance(scenes_raw, dict):
        scenes_raw = _first(scenes_raw, ("scenes", "shots"), [scenes_raw])
    if not isinstance(scenes_raw, list) or not scenes_raw:
        raise ValueError("storyboard payload contains no scenes")

    scenes = [_normalize_scene(item, i, fps) for i, item in enumerate(scenes_raw)]
    # deterministic sequential timing; gaps/overlaps are the orchestrator's job
    cursor = 0
    for scene in scenes:
        scene["startFrame"] = cursor
        cursor += scene["durationInFrames"]

    out: dict[str, Any] = {
        "id": str(_first(data, ("id", "storyboardId", "jobId"), fallback_id) or fallback_id),
        "language": language,
        "width": width,
        "height": height,
        "fps": fps,
        "scenes": scenes,
        "subtitles": _normalize_subtitles(_first(data, ("subtitles", "subtitles_cues", "captions"))),
    }
    theme = data.get("theme")
    if isinstance(theme, dict) and theme:
        out["theme"] = theme
    narration = data.get("narration")
    if isinstance(narration, dict):
        out["narration"] = narration
    music = _first(data, ("backgroundMusic", "music", "bgm"))
    if isinstance(music, dict):
        out["backgroundMusic"] = music
    watermark = data.get("watermark")
    if isinstance(watermark, dict):
        out["watermark"] = watermark
    return out

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
    ("illustrat", "IllustratedStory"),
    ("drawing", "IllustratedStory"),
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

_SETTING_ALIASES = {
    "space": "space", "galaxy": "space", "sky": "space", "cosmos": "space", "universe": "space",
    "desert": "desert", "dune": "desert", "sand": "desert",
    "city": "city", "urban": "city", "street": "city", "building": "city",
    "ocean": "ocean", "sea": "ocean", "water": "ocean", "beach": "ocean",
    "forest": "forest", "jungle": "forest", "tree": "forest", "nature": "forest",
    "interior": "interior", "room": "interior", "indoor": "interior", "house": "interior",
    "abstract": "abstract", "pattern": "abstract", "minimal": "abstract",
}
_POSE_ALIASES = {
    "stand": "stand", "idle": "stand", "default": "stand",
    "point": "point", "pointing": "point", "gesture": "point",
    "reach": "reach", "reaching": "reach", "lift": "reach",
    "walk": "walk", "walking": "walk", "run": "walk",
    "lookup": "lookUp", "look_up": "lookUp", "gaze": "lookUp", "sky": "lookUp",
    "shrug": "shrug", "confused": "shrug", "ask": "shrug",
    "sit": "sit", "sitting": "sit", "kneel": "sit",
}
_PROP_ALIASES = {
    "sun": "sun", "sunlight": "sun", "star_sun": "sun",
    "moon": "moon", "lunar": "moon",
    "planet": "planet", "earth": "planet", "globe": "planet",
    "star": "star", "spark": "star",
    "cloud": "cloud", "sky_cloud": "cloud",
    "mountain": "mountain", "hill": "mountain", "ridge": "mountain",
    "tree": "tree", "plant": "tree", "forest_tree": "tree",
    "tower": "tower", "building": "tower", "skyscraper": "tower",
    "gear": "gear", "cog": "gear", "machine": "gear",
    "book": "book", "document": "book", "paper": "book",
    "wave": "wave", "water_wave": "wave", "sea": "wave",
    "clock": "clock", "time": "clock", "watch": "clock",
    "bulb": "bulb", "idea": "bulb", "lamp": "bulb", "light": "bulb",
    "arrow": "arrow", "direction": "arrow", "pointer": "arrow",
}
_FRAMING_ALIASES = {"wide": "wide", "establishing": "wide", "far": "wide",
                    "medium": "medium", "mid": "medium", "normal": "medium",
                    "close": "close", "closeup": "close", "tight": "close", "detail": "close"}
_CAMERA_ALIASES = {
    "static": "static", "none": "static", "locked": "static",
    "pushin": "pushIn", "push_in": "pushIn", "zoom_in": "pushIn", "zoom": "pushIn",
    "pullout": "pullOut", "pull_out": "pullOut", "zoom_out": "pullOut",
    "panleft": "panLeft", "pan_left": "panLeft", "left": "panLeft",
    "panright": "panRight", "pan_right": "panRight", "right": "panRight",
    "tiltup": "tiltUp", "tilt_up": "tiltUp", "up": "tiltUp",
    "handheld": "handheld", "shake": "handheld", "organic": "handheld",
}
_FX_ALIASES = {
    "lightrays": "lightRays", "light_rays": "lightRays", "rays": "lightRays", "sunbeam": "lightRays",
    "dust": "dust", "particles": "dust", "motes": "dust",
    "stars": "stars", "starry": "stars",
    "speedlines": "speedLines", "speed_lines": "speedLines", "motion": "speedLines",
    "impact": "impact", "burst": "impact", "shock": "impact",
    "vignette": "vignette", "dark_edges": "vignette",
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


_ILLUSTRATION_KEYS = ("setting", "timeOfDay", "imageRef", "actors", "props", "fx", "shots", "caption")
_PROP_KINDS = ("sun", "moon", "planet", "star", "cloud", "mountain", "tree",
               "tower", "gear", "book", "wave", "clock", "bulb", "arrow")
_FX_VALUES = ("lightRays", "dust", "stars", "speedLines", "impact", "vignette")


def _alias(table: dict[str, str], raw: Any, default: str) -> str:
    key = str(raw or "").strip().lower()
    if key in table:
        return table[key]
    squeezed = re.sub(r"[^a-z_]", "", key)
    return table.get(squeezed, default)


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    number = _float(value)
    return default if number is None else max(low, min(number, high))


def normalize_illustration(raw: dict[str, Any]) -> dict[str, Any]:
    """Whitelist and clamp the illustration payload; never pass unknown keys through."""
    out: dict[str, Any] = {
        "setting": _alias(_SETTING_ALIASES, raw.get("setting") or raw.get("environment"), "abstract"),
    }
    if raw.get("title"):
        out["title"] = str(raw["title"])[:70]
    if raw.get("caption"):
        out["caption"] = str(raw["caption"])[:90]
    if raw.get("timeOfDay"):
        out["timeOfDay"] = _alias(
            {"dawn": "dawn", "sunrise": "dawn", "morning": "dawn", "day": "day", "noon": "day",
             "dusk": "dusk", "sunset": "dusk", "evening": "dusk", "night": "night", "dark": "night"},
            raw.get("timeOfDay"), "night",
        )
    if raw.get("imageRef"):
        out["imageRef"] = str(raw["imageRef"])[:200]

    actors = raw.get("actors") or raw.get("characters") or []
    out["actors"] = [
        {
            "pose": _alias(_POSE_ALIASES, (a or {}).get("pose") or (a or {}).get("action"), "stand"),
            "x": _clamp((a or {}).get("x"), 0, 1, 0.5),
            "ground": _clamp((a or {}).get("ground") or (a or {}).get("y"), 0, 1, 0.72),
            "scale": _clamp((a or {}).get("scale"), 0.4, 1.8, 1.0),
            "facing": "left" if str((a or {}).get("facing", "right")).lower().startswith("l") else "right",
            "tone": _alias({"primary": "primary", "secondary": "secondary", "accent": "accent"},
                           (a or {}).get("tone"), "primary"),
            "silhouette": bool((a or {}).get("silhouette")),
        }
        for a in actors[:3] if isinstance(a, dict)
    ]

    props = raw.get("props") or raw.get("objects") or []
    normalised_props = []
    for p in props[:5]:
        if not isinstance(p, dict):
            continue
        kind = _alias(_PROP_ALIASES, p.get("kind") or p.get("type"), "")
        if kind not in _PROP_KINDS:
            continue
        normalised_props.append({
            "kind": kind,
            "x": _clamp(p.get("x"), 0, 1, 0.5),
            "y": _clamp(p.get("y"), 0, 1, 0.35),
            "scale": _clamp(p.get("scale"), 0.4, 2.0, 1.0),
        })
    out["props"] = normalised_props

    effects = []
    for item in (raw.get("fx") or raw.get("effects") or [])[:4]:
        value = _alias(_FX_ALIASES, item, "")
        if value in _FX_VALUES and value not in effects:
            effects.append(value)
    out["fx"] = effects

    shots = raw.get("shots") or []
    normalised_shots = []
    for s in shots[:4]:
        if not isinstance(s, dict):
            continue
        normalised_shots.append({
            "framing": _alias(_FRAMING_ALIASES, s.get("framing") or s.get("shot"), "wide"),
            "camera": _alias(_CAMERA_ALIASES, s.get("camera") or s.get("move"), "pushIn"),
            "weight": _clamp(s.get("weight"), 0.5, 3.0, 1.0),
        })
    out["shots"] = normalised_shots or [{"framing": "wide", "camera": "pushIn", "weight": 1.0}]
    return out


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
    if scene["template"] == "IllustratedStory":
        merged = dict(data) if isinstance(data, dict) else {}
        for key in _ILLUSTRATION_KEYS:
            if key not in merged and key in raw:
                merged[key] = raw[key]
        scene["data"] = normalize_illustration(merged)
    elif isinstance(data, dict):
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

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


def _number(value: Any) -> float | None:
    """Parse a model-authored number, tolerating Indonesian decimal commas and units."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().replace(" ", "")
    if not text:
        return None
    # "15,3" -> "15.3"; "1.234,5" -> "1234.5"; "1,234.5" -> "1234.5"
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    else:
        text = text.replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _text_of(value: Any, limit: int) -> str | None:
    """Model text, tolerating a bare number where a year or label is expected."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = str(int(value)) if float(value).is_integer() else str(value)
        return text[:limit]
    if not isinstance(value, str):
        return None
    text = value.strip()[:limit].strip()
    return text or None


def _first_list(raw: dict[str, Any], keys: tuple[str, ...]) -> list:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, list) and value:
            return value
    return []


def _normalize_infographic(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a model's infographic payload onto the strict contract; drop unknown fields."""
    out: dict[str, Any] = {}
    title = _text_of(_first(raw, ("title", "headline", "heading")), 70)
    if title:
        out["title"] = title
    items: list[dict[str, Any]] = []
    for entry in _first_list(raw, ("items", "metrics", "stats", "data", "values"))[:4]:
        if isinstance(entry, dict):
            label = _text_of(_first(entry, ("label", "name", "title", "metric", "caption")), 52)
            value = _number(_first(entry, ("value", "amount", "number", "figure", "metric")))
            unit = _text_of(_first(entry, ("unit", "suffix")), 16)
        else:
            label, value, unit = _text_of(entry, 52), _number(entry), None
        if not label or value is None or value < 0 or value > 1e12:
            continue
        item: dict[str, Any] = {"label": label, "value": value}
        if unit:
            item["unit"] = unit
        items.append(item)
    if items:
        out["items"] = items
    max_value = _number(_first(raw, ("maxValue", "maximum", "scale_max", "max")))
    if max_value is not None and 0 < max_value <= 1e12:
        out["maxValue"] = max_value
    decimals = _int(_first(raw, ("decimals", "precision", "decimal_places")))
    if decimals is not None and 0 <= decimals <= 2:
        out["decimals"] = decimals
    return out


def _normalize_timeline(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    title = _text_of(_first(raw, ("title", "headline", "heading")), 70)
    if title:
        out["title"] = title
    events: list[dict[str, Any]] = []
    for entry in _first_list(raw, ("events", "moments", "timeline", "items"))[:4]:
        if not isinstance(entry, dict):
            continue
        date = _text_of(_first(entry, ("date", "year", "when")), 24)
        label = _text_of(_first(entry, ("label", "title", "event", "name", "text")), 70)
        if not date or not label:
            continue
        event: dict[str, Any] = {"date": date, "label": label}
        detail = _text_of(_first(entry, ("detail", "description", "body")), 100)
        if detail:
            event["detail"] = detail
        events.append(event)
    if events:
        out["events"] = events
    return out


_PARALLAX_SHAPES = ("ridge", "city", "circle")


def _normalize_parallax(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    title = _text_of(_first(raw, ("title", "headline", "heading")), 70)
    if title:
        out["title"] = title
    caption = _text_of(_first(raw, ("caption", "subtitle")), 160)
    if caption:
        out["caption"] = caption
    layers: list[dict[str, Any]] = []
    for entry in _first_list(raw, ("layers", "depth", "panes", "items"))[:4]:
        if not isinstance(entry, dict):
            continue
        depth = _number(_first(entry, ("depth", "z", "level")))
        shape = _alias({k: k for k in _PARALLAX_SHAPES},
                       _first(entry, ("shape", "kind", "type")), "")
        asset_ref = _text_of(_first(entry, ("assetRef", "asset", "image")), 200)
        layer: dict[str, Any] = {"depth": max(0.1, min(1.0, depth if depth is not None else 0.5))}
        if shape in _PARALLAX_SHAPES:
            layer["shape"] = shape
        elif asset_ref:
            layer["assetRef"] = asset_ref
        else:
            continue  # a layer without exactly one visual cannot render
        layers.append(layer)
    if layers:
        out["layers"] = layers
    return out


def _normalize_comic(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    title = _text_of(_first(raw, ("title", "headline", "heading")), 70)
    if title:
        out["title"] = title
    panels: list[dict[str, Any]] = []
    for entry in _first_list(raw, ("panels", "frames", "items", "beats"))[:3]:
        if not isinstance(entry, dict):
            caption = _text_of(entry, 120)
            if caption:
                panels.append({"caption": caption})
            continue
        caption = _text_of(_first(entry, ("caption", "text", "line", "dialogue")), 120)
        if not caption:
            continue
        panel: dict[str, Any] = {"caption": caption}
        speaker = _text_of(_first(entry, ("speaker", "character", "who")), 32)
        if speaker:
            panel["speaker"] = speaker
        asset_ref = _text_of(_first(entry, ("assetRef", "asset", "image")), 200)
        if asset_ref:
            panel["assetRef"] = asset_ref
        panels.append(panel)
    if panels:
        out["panels"] = panels
    return out


_STRUCTURED_NORMALIZERS = {
    "InfographicMotion": _normalize_infographic,
    "HistoricalTimeline": _normalize_timeline,
    "ParallaxStory": _normalize_parallax,
    "MotionComic": _normalize_comic,
}


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


def _complete_structural_data(template: str, data: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any] | None:
    """Complete a decorative template from the narration the model already wrote.

    Only fields that carry no factual claim may be synthesised: a parallax layer
    shape and a comic caption both restate the scene's own text. Numbers and dates
    are never invented, so InfographicMotion and HistoricalTimeline are not
    completed here — those scenes degrade to a data-free template instead.
    """
    headline = _text_of(scene["text"][0]["text"], 70) if scene.get("text") else None
    if template == "ParallaxStory":
        title = data.get("title") or headline or _text_of(scene.get("segment"), 70)
        if not title:
            return None
        out = {"title": title, "layers": data.get("layers") or [{"depth": 0.5, "shape": "ridge"}]}
        if data.get("caption"):
            out["caption"] = data["caption"]
        return out
    if template == "MotionComic":
        panels = data.get("panels") or []
        if not panels:
            caption = headline or _text_of(scene.get("segment"), 120)
            if not caption:
                return None
            panels = [{"caption": caption}]
        out = {"panels": panels}
        if data.get("title"):
            out["title"] = data["title"]
        return out
    return None


def _renderable(template: str, data: dict[str, Any] | None) -> bool:
    """True when this template's data satisfies the strict renderer contract."""
    from .media.scene_data import SCENE_DATA_MODELS, validate_scene_data

    if template not in SCENE_DATA_MODELS:
        return True
    try:
        validate_scene_data(template, data)
    except (ValueError, TypeError):
        return False
    return True


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
        normalizer = _STRUCTURED_NORMALIZERS.get(scene["template"])
        # Unknown keys from a model must never reach the strict renderer contract.
        scene["data"] = normalizer(data) if normalizer else data
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


def _normalize_music(raw: Any) -> dict[str, Any] | None:
    """Keep only a music block that names a licensed local asset.

    Models invent descriptors such as {"mood": "curious", "intensity": 0.35}. No
    manifest asset exists for a mood, so such a block is dropped instead of being
    persisted as a reference the asset stage cannot resolve.
    """
    if not isinstance(raw, dict):
        return None
    asset_ref = _first(raw, ("assetRef", "asset_ref", "id"))
    if not isinstance(asset_ref, str) or not asset_ref.strip():
        return None
    music: dict[str, Any] = {"assetRef": asset_ref.strip()}
    volume = _float(_first(raw, ("volume", "gain", "level")))
    if volume is not None:
        music["volume"] = max(0.0, min(volume, 1.0))
    if isinstance(raw.get("loop"), bool):
        music["loop"] = raw["loop"]
    return music


def clamp_text_frames(scene: dict[str, Any]) -> None:
    """Keep every text element's frames inside the scene it belongs to.

    A model's in/out frames are advisory guesses against a duration it also
    guessed. Timing is owned by the orchestrator, so any later re-timing (word
    estimate or measured narration) must re-clamp them: a stale outFrame hides
    the text mid-scene, and the draft reviewer rightly calls that a bug.
    """
    duration = scene.get("durationInFrames")
    if not isinstance(duration, int) or duration <= 0:
        return
    for element in scene.get("text") or []:
        if not isinstance(element, dict):
            continue
        start = element.get("inFrame")
        end = element.get("outFrame")
        if isinstance(start, int) and not 0 <= start < duration:
            element["inFrame"] = max(0, min(start, duration - 1))
        if isinstance(end, int) and not 0 < end <= duration:
            element["outFrame"] = max(1, min(end, duration))
        if (isinstance(element.get("inFrame"), int) and isinstance(element.get("outFrame"), int)
                and element["outFrame"] <= element["inFrame"]):
            element.pop("outFrame", None)


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
    for scene in scenes:
        if _renderable(scene["template"], scene.get("data")):
            continue
        completed = _complete_structural_data(scene["template"], scene.get("data") or {}, scene)
        if completed is not None and _renderable(scene["template"], completed):
            scene["data"] = completed
            continue
        # A model that ignored the template contract must not fail the whole job.
        # Fall back to the one template that needs no structured data, keeping the
        # narration and text the model did produce. Numbers are never invented.
        scene["template"] = "KineticTypography"
        scene.pop("data", None)
    # deterministic sequential timing; gaps/overlaps are the orchestrator's job
    cursor = 0
    for scene in scenes:
        scene["startFrame"] = cursor
        cursor += scene["durationInFrames"]
        # A model's in/out frames are advisory and frequently fall outside the
        # scene it wrote them for, which makes text vanish mid-scene. Timing is
        # owned by the orchestrator, so clamp them to the scene's own duration.
        clamp_text_frames(scene)

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
    music = _normalize_music(_first(data, ("backgroundMusic", "music", "bgm")))
    if music is not None:
        out["backgroundMusic"] = music
    watermark = data.get("watermark")
    if isinstance(watermark, dict):
        out["watermark"] = watermark
    return out

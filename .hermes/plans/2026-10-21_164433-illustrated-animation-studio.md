# Illustrated animation studio — plan

## Goal

Replace the current text-first scenes with a deterministic, procedural vector-illustration system so every narrative scene shows an actual drawn world (characters, props, environments, camera moves, shot cuts) instead of typography on a gradient.

## Current context / assumptions

The implementer has zero context. Read these first:

| Fact | Where it is proven |
| --- | --- |
| The renderer is Remotion 4.0.537 + React 18, TypeScript `strict`, no extra deps allowed | `packages/video/package.json` |
| Six templates exist and are registered in three places | `packages/video/src/types.ts` (`TEMPLATE_IDS`), `packages/video/src/compositions/registry.ts`, `packages/core/schemas.py` (`TemplateId`, `ALLOWED_TEMPLATES`) |
| The LLM never emits React — only validated JSON | `AGENTS.md` rule 5, `packages/video/src/scene-data.ts`, `packages/core/media/scene_data.py` |
| Paid image/video generation needs operator approval | `AGENTS.md` rule 12 — so this plan uses **no** image generation service |
| Real images are only allowed as operator-supplied licensed local rasters | `packages/core/media/assets.py`, `docs/MEDIA.md` |
| Today the storyboard prompt only permits two text templates | `packages/core/prompts.py` line 69: `template HANYA dari yang sudah diimplementasikan: KineticTypography, EducationalExplainer` |
| `MotionComic` draws one generic geometric person; `ParallaxStory` draws only `ridge`/`city`/`circle` | `packages/video/src/compositions/MotionComic.tsx` line 18, `ParallaxStory.tsx` line 17 |
| Render props replace logical asset ids with staged paths | `packages/core/media/assets.py` → `render_storyboard()` |
| `packages/video/src/scene-data.ts` must keep **zero runtime relative imports** | `packages/video/scripts/test-scene-data.mjs` loads it through `ts.transpileModule` + `vm`, and relative `require` resolves from the *script* dir, not the virtual file |

Assumptions:

- "Studio animation" here means: full-bleed drawn frames, a character rig with poses and secondary motion, layered parallax, a virtual camera with real moves, and hard cuts between framings inside one scene. It does **not** mean photoreal or AI-generated footage.
- Determinism is mandatory: the pipeline hashes artifacts and re-verifies media. No `Math.random()`, no time-based seeds, no network fetches at render time.
- 1080×1920 @ 30 fps, safe areas top 260 / bottom 320 (Shorts UI overlays).

## Architecture / proposed approach

Add a fixed art vocabulary (environments, actors, props, effects, camera moves, shots) as typed JSON that the LLM composes and Python/TS validate; a new `IllustratedStory` template renders that vocabulary as layered SVG under a virtual camera, cutting between 1–4 shots inside a single scene. All art derives its colours from the existing theme tokens, all motion derives from the frame number, and an optional `imageRef` lets an operator-supplied licensed plate sit behind the vector art so real imagery is still possible without any paid service.

## Vocabulary reference (do not invent values)

| Enum | Values |
| --- | --- |
| `setting` | `space`, `desert`, `city`, `ocean`, `forest`, `interior`, `abstract` |
| `timeOfDay` | `dawn`, `day`, `dusk`, `night` |
| `pose` | `stand`, `point`, `reach`, `walk`, `lookUp`, `shrug`, `sit` |
| `prop.kind` | `sun`, `moon`, `planet`, `star`, `cloud`, `mountain`, `tree`, `tower`, `gear`, `book`, `wave`, `clock`, `bulb`, `arrow` |
| `fx` | `lightRays`, `dust`, `stars`, `speedLines`, `impact`, `vignette` |
| `framing` | `wide`, `medium`, `close` |
| `camera` | `static`, `pushIn`, `pullOut`, `panLeft`, `panRight`, `tiltUp`, `handheld` |
| `tone` | `primary`, `secondary`, `accent` |
| `facing` | `left`, `right` |

Scene data contract (all keys, nothing else allowed):

```json
{
  "title": "optional, <=70 chars",
  "caption": "optional, <=90 chars",
  "setting": "space",
  "timeOfDay": "night",
  "imageRef": "optional logical asset id",
  "actors": [{"pose": "point", "x": 0.3, "ground": 0.74, "scale": 1, "facing": "right", "tone": "accent", "silhouette": false}],
  "props": [{"kind": "sun", "x": 0.74, "y": 0.26, "scale": 1.3}],
  "fx": ["lightRays", "dust", "vignette"],
  "shots": [{"framing": "wide", "camera": "pushIn", "weight": 1}, {"framing": "close", "camera": "handheld", "weight": 1.2}]
}
```

Only `setting` is mandatory. `actors`, `props`, `fx` default to `[]`; `shots` defaults to `[{"framing":"wide","camera":"pushIn","weight":1}]`. Unknown keys are rejected — a typo must fail loudly, not silently disappear.

---

## Phase 0 — branch and contract

### Task 0.1 — create the branch

```bash
cd /c/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI
git switch -c apex/20261021-illustrated-studio
git status --short
```

Expected: `Switched to a new branch 'apex/20261021-illustrated-studio'`. `git status --short` shows `M apps/dashboard/next-env.d.ts` (a build artifact from an earlier run) — **never stage it**, always `git add` explicit paths.

### Task 0.2 — RED: python rejects the new template name

Add to `tests/test_illustration_data.py`:

```python
import pytest

from packages.core.schemas import SceneSpec, Storyboard


def _scene(**data):
    return SceneSpec(
        sceneId="s1",
        template="IllustratedStory",
        segment="Cahaya butuh delapan menit untuk sampai ke Bumi.",
        durationInFrames=300,
        data=data,
    )


def test_minimal_illustration_needs_only_a_setting():
    scene = _scene(setting="space")
    assert scene.data["setting"] == "space"


def test_unknown_setting_is_rejected():
    with pytest.raises(ValueError, match="setting"):
        _scene(setting="underwater")


def test_unknown_illustration_key_is_rejected():
    with pytest.raises(ValueError):
        _scene(setting="space", camera="pushIn")


def test_actor_bounds_are_enforced():
    with pytest.raises(ValueError):
        _scene(setting="space", actors=[{"pose": "point", "x": 1.4, "ground": 0.7}])


def test_shots_are_optional():
    # validate_scene_data only validates; it does not inject defaults into scene.data.
    # The default shot is injected by normalize_illustration (tested in test_storyboard_normalize.py)
    # and by validateIllustrationData on the TypeScript side.
    assert _scene(setting="desert").data == {"setting": "desert"}
```

Run:

```bash
uv run pytest -o addopts='' -p no:cacheprovider \
  --basetemp='C:/Users/cubeb/AppData/Local/hermes/cache/scratch/illustration-red' \
  tests/test_illustration_data.py
```

Expected: collection error / failures — `IllustratedStory` is not in `ALLOWED_TEMPLATES`, so `SceneSpec` raises `unknown template 'IllustratedStory'`.

### Task 0.3 — GREEN: register the template id in python

Edit `packages/core/schemas.py`. Add `"IllustratedStory",` as the last entry of both `TemplateId` and `ALLOWED_TEMPLATES` (lines 10–26). Append only — existing order stays stable.

Run the same pytest command. Expected: `2 passed, 3 failed`.

- `test_minimal_illustration_needs_only_a_setting` and `test_shots_are_optional` now pass — the template id is known and `data` is not validated yet, so it flows through untouched.
- The other three still fail: `validate_scene_data` has no model registered for `IllustratedStory`, so nothing rejects an unknown setting, an unknown key, or an out-of-range actor. Task 0.4 fixes exactly that.

Commit:

```bash
git add packages/core/schemas.py tests/test_illustration_data.py
git commit -m "feat(schema): register IllustratedStory template id"
```

### Task 0.4 — GREEN: strict pydantic model for illustration data

Append to `packages/core/media/scene_data.py`, before `SCENE_DATA_MODELS`:

```python
class IllustrationActor(StrictData):
    pose: Literal["stand", "point", "reach", "walk", "lookUp", "shrug", "sit"] = "stand"
    x: float = Field(default=0.5, ge=0, le=1)
    ground: float = Field(default=0.72, ge=0, le=1)
    scale: float = Field(default=1.0, ge=0.4, le=1.8)
    facing: Literal["left", "right"] = "right"
    tone: Literal["primary", "secondary", "accent"] = "primary"
    silhouette: bool = False


class IllustrationProp(StrictData):
    kind: Literal[
        "sun", "moon", "planet", "star", "cloud", "mountain", "tree",
        "tower", "gear", "book", "wave", "clock", "bulb", "arrow",
    ]
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    scale: float = Field(default=1.0, ge=0.4, le=2.0)


class IllustrationShot(StrictData):
    framing: Literal["wide", "medium", "close"] = "wide"
    camera: Literal["static", "pushIn", "pullOut", "panLeft", "panRight", "tiltUp", "handheld"] = "pushIn"
    weight: float = Field(default=1.0, ge=0.5, le=3.0)


class IllustrationData(StrictData):
    title: str | None = Field(default=None, min_length=1, max_length=70)
    caption: str | None = Field(default=None, min_length=1, max_length=90)
    setting: Literal["space", "desert", "city", "ocean", "forest", "interior", "abstract"]
    timeOfDay: Literal["dawn", "day", "dusk", "night"] | None = None
    imageRef: str | None = Field(default=None, min_length=1, max_length=200)
    actors: list[IllustrationActor] = Field(default_factory=list, max_length=3)
    props: list[IllustrationProp] = Field(default_factory=list, max_length=5)
    fx: list[Literal["lightRays", "dust", "stars", "speedLines", "impact", "vignette"]] = Field(
        default_factory=list, max_length=4
    )
    shots: list[IllustrationShot] = Field(
        default_factory=lambda: [IllustrationShot()], min_length=1, max_length=4
    )

    @model_validator(mode="after")
    def unique_fx(self):
        if len(set(self.fx)) != len(self.fx):
            raise ValueError("fx entries must be unique")
        return self
```

Then add `"IllustratedStory": IllustrationData,` to `SCENE_DATA_MODELS`.

Note: `StrictData` uses `strict=True`, and the existing `InfographicItem.value: float` already accepts JSON integers (the fixture `"value": 3816` passes today), so `x: float` with `0.5`/`1` both work.

Run:

```bash
uv run pytest -o addopts='' -p no:cacheprovider \
  --basetemp='C:/Users/cubeb/AppData/Local/hermes/cache/scratch/illustration-green' \
  tests/test_illustration_data.py
```

Expected: `5 passed`.

Commit:

```bash
git add packages/core/media/scene_data.py
git commit -m "feat(media): validate IllustratedStory scene data"
```

### Task 0.5 — RED/GREEN: licensed plate support (`imageRef`)

`imageRef` must behave exactly like `panels[].assetRef` / `layers[].assetRef`: it has to appear in `scene.assetRefs`, and `render_storyboard` must rewrite it to the staged path.

Add to `tests/test_illustration_data.py`:

```python
from packages.core.media.assets import referenced_assets, render_storyboard
from packages.core.media.contracts import AssetManifest, ResolvedAsset

SHA = "c" * 64


def _storyboard_with_plate():
    return Storyboard(id="plate", scenes=[_scene(
        setting="ocean",
        imageRef="plate",
    ).model_copy(update={"assetRefs": ["plate"]})])


def _manifest():
    return AssetManifest(
        mode="licensed-local",
        templates=["IllustratedStory"],
        license="per-asset",
        library_root="C:/library",
        manifest_path="assets-manifest.json",
        manifest_sha256="a" * 64,
        dependencies_sha256="b" * 64,
        assets=[ResolvedAsset(
            id="plate", path="plate.png", kind="image", license="project-original",
            attribution="Operator supplied", source="local", sha256=SHA,
            staged_path=f"assets/{SHA}.png",
        )],
    )


def test_image_ref_must_be_declared_in_asset_refs():
    board = Storyboard(id="x", scenes=[_scene(setting="ocean", imageRef="plate")])
    with pytest.raises(ValueError, match="imageRef"):
        referenced_assets(board)


def test_render_props_rewrite_image_ref_to_staged_path():
    props = render_storyboard(_storyboard_with_plate(), _manifest())
    assert props["scenes"][0]["data"]["imageRef"] == f"assets/{SHA}.png"
```

Run — expect both to fail.

Now edit `packages/core/media/assets.py`:

In `referenced_assets`, inside the `for scene in storyboard.scenes:` loop, after the `panels`/`layers` block:

```python
        image_ref = (scene.data or {}).get("imageRef")
        if image_ref:
            if image_ref not in scene.assetRefs:
                raise ValueError("illustration imageRef must also appear in scene.assetRefs")
            add(image_ref, "image")
```

In `render_storyboard`, after the `for key in ("panels", "layers"):` block:

```python
        if (scene.get("data") or {}).get("imageRef"):
            scene["data"]["imageRef"] = paths[scene["data"]["imageRef"]]
```

Run the same pytest command → `7 passed`. Commit:

```bash
git add packages/core/media/assets.py tests/test_illustration_data.py
git commit -m "feat(media): resolve IllustratedStory image plates"
```

### Task 0.6 — RED/GREEN: normalizer accepts the new dialect

Real models answer with `"visual": "illustrated scene"` and put the illustration keys at the scene root instead of inside `data`. Normalize both.

Add to `tests/test_storyboard_normalize.py`:

```python
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
```

Run — expect `AttributeError`/`KeyError` failures.

Edit `packages/core/storyboard_normalize.py`:

1. Prepend to `_TEMPLATE_KEYWORDS` (before `("kinetic", ...)`):

```python
    ("illustrat", "IllustratedStory"),
    ("drawing", "IllustratedStory"),
```

2. Add alias tables after `_TRANSITION_ALIASES`:

```python
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
```

3. Add the normalizer, placed after `normalize_transition`:

```python
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
```

4. In `_normalize_scene`, replace the `data = raw.get("data")` block with:

```python
    data = raw.get("data")
    if scene["template"] == "IllustratedStory":
        merged = dict(data) if isinstance(data, dict) else {}
        for key in _ILLUSTRATION_KEYS:
            if key not in merged and key in raw:
                merged[key] = raw[key]
        scene["data"] = normalize_illustration(merged)
    elif isinstance(data, dict):
        scene["data"] = data
```

Run:

```bash
uv run pytest -o addopts='' -p no:cacheprovider \
  --basetemp='C:/Users/cubeb/AppData/Local/hermes/cache/scratch/illustration-normalize' \
  tests/test_storyboard_normalize.py tests/test_illustration_data.py
```

Expected: all pass.

Commit:

```bash
git add packages/core/storyboard_normalize.py tests/test_storyboard_normalize.py
git commit -m "feat(storyboard): normalize illustration dialect"
```

---

## Phase 1 — art kit (TypeScript)

Every file below lives under `packages/video/src/art/`. Rules for all of them:

- Colours come from `paletteFor(theme, timeOfDay)`; no theme hex literals.
- Neutral overlays (`rgba(0,0,0,x)`, `rgba(255,255,255,x)`) are allowed — `Short.tsx` already does this.
- No `Math.random()`. Use `rand(seed)` from `art/rng.ts`.
- No animation libraries. Everything is a pure function of `frame`.

### Task 1.1 — illustration types + validator inside `scene-data.ts`

`scene-data.ts` must keep zero runtime relative imports, so the illustration contract lives there (not in `art/`). `art/*` files import the types from `../scene-data` with `import type`, which is erased at compile time.

Add to `packages/video/src/scene-data.ts`, after the existing interfaces:

```ts
export const SETTINGS = ['space', 'desert', 'city', 'ocean', 'forest', 'interior', 'abstract'] as const;
export const TIMES_OF_DAY = ['dawn', 'day', 'dusk', 'night'] as const;
export const POSES = ['stand', 'point', 'reach', 'walk', 'lookUp', 'shrug', 'sit'] as const;
export const PROP_KINDS = ['sun', 'moon', 'planet', 'star', 'cloud', 'mountain', 'tree', 'tower', 'gear', 'book', 'wave', 'clock', 'bulb', 'arrow'] as const;
export const EFFECTS = ['lightRays', 'dust', 'stars', 'speedLines', 'impact', 'vignette'] as const;
export const FRAMINGS = ['wide', 'medium', 'close'] as const;
export const CAMERA_MOVES = ['static', 'pushIn', 'pullOut', 'panLeft', 'panRight', 'tiltUp', 'handheld'] as const;

export type Setting = (typeof SETTINGS)[number];
export type TimeOfDay = (typeof TIMES_OF_DAY)[number];
export type Pose = (typeof POSES)[number];
export type PropKind = (typeof PROP_KINDS)[number];
export type Effect = (typeof EFFECTS)[number];
export type Framing = (typeof FRAMINGS)[number];
export type CameraMove = (typeof CAMERA_MOVES)[number];

export interface IllustrationActor {
  pose: Pose;
  x: number;
  ground: number;
  scale: number;
  facing: 'left' | 'right';
  tone: 'primary' | 'secondary' | 'accent';
  silhouette: boolean;
}

export interface IllustrationProp {kind: PropKind; x: number; y: number; scale: number}
export interface IllustrationShot {framing: Framing; camera: CameraMove; weight: number}

export interface IllustrationData {
  title?: string;
  caption?: string;
  setting: Setting;
  timeOfDay?: TimeOfDay;
  imageRef?: string;
  actors: IllustrationActor[];
  props: IllustrationProp[];
  fx: Effect[];
  shots: IllustrationShot[];
}

const ILLUSTRATION_KEYS = ['title', 'caption', 'setting', 'timeOfDay', 'imageRef', 'actors', 'props', 'fx', 'shots'];

const oneOf = <T extends string>(allowed: readonly T[], value: unknown, field: string, fallback: T): T => {
  if (value == null) return fallback;
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) {
    throw new Error(`Unsupported illustration ${field}: ${String(value)}`);
  }
  return value as T;
};

const unit = (value: unknown, field: string, fallback: number, min = 0, max = 1): number => {
  if (value == null) return fallback;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) {
    throw new Error(`Illustration ${field} must be a finite number in ${min}..${max}`);
  }
  return value;
};

const record = (value: unknown, keys: string[], label: string): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`Illustration ${label} must be an object`);
  const data = value as Record<string, unknown>;
  if (Object.keys(data).some((key) => !keys.includes(key))) throw new Error(`Unsupported illustration ${label} field`);
  return data;
};

const optionalText = (value: unknown, max: number, field: string): string | undefined => {
  if (value == null) return undefined;
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error(`Invalid illustration ${field}`);
  return value;
};

export function validateIllustrationData(raw: unknown): IllustrationData {
  const data = record(raw, ILLUSTRATION_KEYS, 'data');
  const out: IllustrationData = {
    setting: oneOf(SETTINGS, data.setting, 'setting', 'abstract'),
    actors: [],
    props: [],
    fx: [],
    shots: [{framing: 'wide', camera: 'pushIn', weight: 1}],
  };
  const title = optionalText(data.title, 70, 'title');
  if (title) out.title = title;
  const caption = optionalText(data.caption, 90, 'caption');
  if (caption) out.caption = caption;
  if (data.timeOfDay != null) out.timeOfDay = oneOf(TIMES_OF_DAY, data.timeOfDay, 'timeOfDay', 'night');
  if (data.imageRef != null) out.imageRef = localImage(String(data.imageRef));

  if (data.actors != null) {
    if (!Array.isArray(data.actors) || data.actors.length > 3) throw new Error('Illustration actors must be an array of at most 3');
    out.actors = data.actors.map((item, i) => {
      const a = record(item, ['pose', 'x', 'ground', 'scale', 'facing', 'tone', 'silhouette'], `actor ${i}`);
      return {
        pose: oneOf(POSES, a.pose, 'pose', 'stand'),
        x: unit(a.x, `actor ${i} x`, 0.5),
        ground: unit(a.ground, `actor ${i} ground`, 0.72),
        scale: unit(a.scale, `actor ${i} scale`, 1, 0.4, 1.8),
        facing: a.facing === 'left' ? 'left' : 'right',
        tone: oneOf(['primary', 'secondary', 'accent'] as const, a.tone, 'tone', 'primary'),
        silhouette: Boolean(a.silhouette),
      };
    });
  }

  if (data.props != null) {
    if (!Array.isArray(data.props) || data.props.length > 5) throw new Error('Illustration props must be an array of at most 5');
    out.props = data.props.map((item, i) => {
      const p = record(item, ['kind', 'x', 'y', 'scale'], `prop ${i}`);
      return {
        kind: oneOf(PROP_KINDS, p.kind, 'prop kind', 'star'),
        x: unit(p.x, `prop ${i} x`, 0.5),
        y: unit(p.y, `prop ${i} y`, 0.35),
        scale: unit(p.scale, `prop ${i} scale`, 1, 0.4, 2),
      };
    });
  }

  if (data.fx != null) {
    if (!Array.isArray(data.fx) || data.fx.length > 4) throw new Error('Illustration fx must be an array of at most 4');
    const seen: Effect[] = [];
    for (const item of data.fx) {
      const effect = oneOf(EFFECTS, item, 'fx', 'dust');
      if (!seen.includes(effect)) seen.push(effect);
    }
    out.fx = seen;
  }

  if (data.shots != null) {
    if (!Array.isArray(data.shots) || data.shots.length < 1 || data.shots.length > 4) {
      throw new Error('Illustration shots must be an array of 1..4');
    }
    out.shots = data.shots.map((item, i) => {
      const s = record(item, ['framing', 'camera', 'weight'], `shot ${i}`);
      return {
        framing: oneOf(FRAMINGS, s.framing, 'framing', 'wide'),
        camera: oneOf(CAMERA_MOVES, s.camera, 'camera', 'pushIn'),
        weight: unit(s.weight, `shot ${i} weight`, 1, 0.5, 3),
      };
    });
  }
  return out;
}
```

Do **not** touch the `validateSceneData` switch yet. `TemplateId` does not contain `IllustratedStory` until Task 2.2, so `case 'IllustratedStory':` would be a TS2367 error today. The validator is an exported function that nothing calls until Task 2.2 — that is legal and tsc-clean.

Verify:

```bash
cd packages/video && npx tsc --noEmit && node scripts/test-scene-data.mjs
```

Expected: tsc exits 0 with no output; the script prints `PASS template contracts: six valid fixtures, incomplete/unknown/remote/nonfinite rejected` (the message still says "six" until Task 2.3).

Commit:

```bash
git add packages/video/src/scene-data.ts
git commit -m "feat(video): illustration data contract and validator"
```

### Task 1.2 — deterministic randomness + palette

`packages/video/src/art/rng.ts`:

```ts
/**
 * Exact-integer hash mapped to 0..1. Never Math.random(): a Remotion render must
 * produce identical frames on every run, and the pipeline hashes the artifacts.
 */
export const rand = (seed: number): number => {
  let t = (seed + 0x6d2b79f5) | 0;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

export const randRange = (seed: number, min: number, max: number): number => min + rand(seed) * (max - min);
```

`packages/video/src/art/palette.ts`:

```ts
import type {ThemeSpec} from '../types';
import type {TimeOfDay} from '../scene-data';

const clamp = (value: number, low = 0, high = 1): number => Math.min(high, Math.max(low, value));

const parse = (hex: string): [number, number, number] => {
  const raw = hex.replace('#', '');
  const full = raw.length === 3 ? raw.split('').map((c) => c + c).join('') : raw.padEnd(6, '0').slice(0, 6);
  const value = Number.parseInt(full, 16);
  if (!Number.isFinite(value)) throw new Error(`Invalid theme colour: ${hex}`);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
};

const toHex = (rgb: [number, number, number]): string =>
  '#' + rgb.map((v) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0')).join('');

export const mix = (a: string, b: string, t: number): string => {
  const [r1, g1, b1] = parse(a);
  const [r2, g2, b2] = parse(b);
  const k = clamp(t);
  return toHex([r1 + (r2 - r1) * k, g1 + (g2 - g1) * k, b1 + (b2 - b1) * k]);
};

export const alpha = (hex: string, a: number): string => {
  const [r, g, b] = parse(hex);
  return `rgba(${r}, ${g}, ${b}, ${clamp(a)})`;
};

export const shade = (hex: string, amount: number): string => mix(hex, '#000000', amount);
export const tint = (hex: string, amount: number): string => mix(hex, '#ffffff', amount);

export interface ArtPalette {
  skyTop: string;
  skyBottom: string;
  ground: string;
  groundFar: string;
  figure: string;
  figureAccent: string;
  prop: string;
  glow: string;
  ink: string;
}

const LIGHT: Record<TimeOfDay, number> = {dawn: 0.42, day: 0.72, dusk: 0.3, night: 0};

/** All art colours are derived from the theme; only black/white are mixed in. */
export const paletteFor = (theme: ThemeSpec, timeOfDay: TimeOfDay = 'night'): ArtPalette => {
  const light = LIGHT[timeOfDay];
  return {
    skyTop: mix(shade(theme.background, 0.35), theme.backgroundAccent, 0.55),
    skyBottom: mix(theme.backgroundAccent, theme.accent, light * 0.55),
    ground: mix(theme.background, theme.secondary, 0.18),
    groundFar: mix(theme.backgroundAccent, theme.secondary, 0.34),
    figure: theme.primary,
    figureAccent: theme.accent,
    prop: mix(theme.secondary, theme.primary, 0.4),
    glow: alpha(theme.accent, 0.55),
    ink: mix(theme.background, '#000000', 0.45),
  };
};
```

Verify:

```bash
cd packages/video && npx tsc --noEmit
```

Expected: exit 0, no output.

Commit:

```bash
git add packages/video/src/art/rng.ts packages/video/src/art/palette.ts
git commit -m "feat(art): deterministic rng and theme-derived palette"
```

### Task 1.3 — camera

`packages/video/src/art/Camera.tsx`:

```tsx
import React from 'react';
import type {CameraMove} from '../scene-data';

export interface CameraState {scale: number; x: number; y: number; rotate: number}

const smooth = (t: number): number => {
  const p = Math.min(1, Math.max(0, t));
  return p * p * (3 - 2 * p);
};

export const cameraAt = (
  move: CameraMove,
  frame: number,
  durationInFrames: number,
  strength = 1,
): CameraState => {
  const t = durationInFrames <= 1 ? 1 : smooth(frame / (durationInFrames - 1));
  switch (move) {
    case 'pushIn':
      return {scale: 1 + 0.12 * t * strength, x: 0, y: 0, rotate: 0};
    case 'pullOut':
      return {scale: 1.12 - 0.12 * t * strength, x: 0, y: 0, rotate: 0};
    case 'panLeft':
      return {scale: 1.08, x: 64 * (1 - t) * strength, y: 0, rotate: 0};
    case 'panRight':
      return {scale: 1.08, x: -64 * (1 - t) * strength, y: 0, rotate: 0};
    case 'tiltUp':
      return {scale: 1.06, x: 0, y: 72 * (1 - t) * strength, rotate: 0};
    case 'handheld': {
      // Two incommensurate sines read as organic drift and stay perfectly deterministic.
      const sway = Math.sin(frame / 17) * 5 + Math.sin(frame / 6.3) * 2.2;
      return {
        scale: 1.05,
        x: sway * strength,
        y: Math.cos(frame / 13) * 3.4 * strength,
        rotate: Math.sin(frame / 23) * 0.18,
      };
    }
    default:
      return {scale: 1, x: 0, y: 0, rotate: 0};
  }
};

export const Camera: React.FC<{state: CameraState; children: React.ReactNode}> = ({state, children}) => (
  <div
    style={{
      position: 'absolute',
      inset: 0,
      transform: `scale(${state.scale}) translate(${state.x}px, ${state.y}px) rotate(${state.rotate}deg)`,
      transformOrigin: '50% 54%',
    }}
  >
    {children}
  </div>
);
```

Verify: tsc exit 0.

Commit: `git commit -m "feat(art): virtual camera moves"`.

### Task 1.4 — shot director

`packages/video/src/art/shots.ts` (no runtime imports — the verification script loads it through `ts.transpileModule`):

```ts
import type {IllustrationShot} from '../scene-data';

export interface ShotSpan {
  shot: IllustrationShot;
  index: number;
  start: number;
  duration: number;
  local: number;
}

const MIN_SHOT_FRAMES = 12;

/** Split a scene into weighted shots. Deterministic, gap-free, and never shorter than 12 frames. */
export const shotAt = (
  shots: IllustrationShot[],
  frame: number,
  durationInFrames: number,
): ShotSpan => {
  if (shots.length === 0) throw new Error('IllustratedStory requires at least one shot');
  const usable = durationInFrames >= MIN_SHOT_FRAMES * shots.length ? shots : [shots[0]];
  const weights = usable.map((s) => (s.weight > 0 ? s.weight : 1));
  const total = weights.reduce((a, b) => a + b, 0);
  const spans = weights.map((w) => Math.max(MIN_SHOT_FRAMES, Math.floor((w / total) * durationInFrames)));
  const drift = spans.reduce((a, b) => a + b, 0) - durationInFrames;
  spans[spans.length - 1] = Math.max(MIN_SHOT_FRAMES, spans[spans.length - 1] - drift);

  let start = 0;
  for (let i = 0; i < spans.length; i += 1) {
    const end = start + spans[i];
    if (frame < end || i === spans.length - 1) {
      return {
        shot: usable[i],
        index: i,
        start,
        duration: spans[i],
        local: Math.min(spans[i] - 1, Math.max(0, frame - start)),
      };
    }
    start = end;
  }
  throw new Error('shot lookup failed');
};

export const FRAMING_SCALE: Record<IllustrationShot['framing'], number> = {
  wide: 1,
  medium: 1.3,
  close: 1.66,
};
```

Verify: tsc exit 0.

Commit: `git commit -m "feat(art): weighted shot director"`.

### Task 1.5 — environments

`packages/video/src/art/Environment.tsx`:

```tsx
import React from 'react';
import type {Setting, TimeOfDay} from '../scene-data';
import {alpha, mix, shade, type ArtPalette} from './palette';
import {rand} from './rng';

const W = 1080;
const H = 1920;
const HORIZON = 1180;

const Stars: React.FC<{palette: ArtPalette; count: number; seed?: number}> = ({palette, count, seed = 0}) => (
  <g>
    {Array.from({length: count}, (_, i) => {
      const x = rand(seed + i * 3 + 1) * W;
      const y = rand(seed + i * 3 + 2) * HORIZON * 0.92;
      const r = 1 + rand(seed + i * 3 + 3) * 2.6;
      return <circle key={i} cx={x} cy={y} r={r} fill={palette.figure} opacity={0.25 + rand(seed + i) * 0.55} />;
    })}
  </g>
);

const Celestial: React.FC<{palette: ArtPalette; cx: number; cy: number; r: number; crescent?: boolean; glow?: boolean}> = ({
  palette,
  cx,
  cy,
  r,
  crescent,
  glow = true,
}) => (
  <g>
    {glow ? <circle cx={cx} cy={cy} r={r * 2.6} fill={palette.glow} opacity={0.16} /> : null}
    <circle cx={cx} cy={cy} r={r} fill={palette.prop} />
    {crescent ? <circle cx={cx + r * 0.42} cy={cy - r * 0.18} r={r * 0.92} fill={palette.skyTop} /> : null}
  </g>
);

const Ridge: React.FC<{fill: string; opacity: number; y: number; amplitude: number; seed: number; drift: number}> = ({
  fill,
  opacity,
  y,
  amplitude,
  seed,
  drift,
}) => {
  const points = Array.from({length: 9}, (_, i) => {
    const x = (i / 8) * W;
    const height = amplitude * (0.45 + rand(seed + i) * 0.55);
    return `${x.toFixed(0)},${(y - height).toFixed(0)}`;
  });
  return (
    <path
      d={`M0,${H} L0,${y} L${points.join(' L')} L${W},${y} L${W},${H} Z`}
      fill={fill}
      opacity={opacity}
      transform={`translate(${drift} 0)`}
    />
  );
};

const City: React.FC<{palette: ArtPalette; drift: number}> = ({palette, drift}) => {
  const blocks = [
    {x: -60, w: 180, h: 540}, {x: 96, w: 140, h: 700}, {x: 210, w: 200, h: 460},
    {x: 386, w: 160, h: 640}, {x: 522, w: 210, h: 520}, {x: 706, w: 150, h: 720},
    {x: 836, w: 190, h: 480}, {x: 1000, w: 160, h: 600},
  ];
  return (
    <g transform={`translate(${drift} 0)`}>
      {blocks.map((b, bi) => {
        const top = HORIZON - b.h;
        const cols = Math.max(1, Math.floor((b.w - 24) / 34));
        const rows = Math.max(1, Math.floor((b.h - 40) / 44));
        return (
          <g key={bi}>
            <rect x={b.x} y={top} width={b.w} height={b.h} fill={shade(palette.ground, 0.35)} />
            {Array.from({length: cols * rows}, (_, ci) => {
              const cx = b.x + 16 + (ci % cols) * 34;
              const cy = top + 26 + Math.floor(ci / cols) * 44;
              const lit = rand(bi * 1000 + ci) > 0.45;
              return <rect key={ci} x={cx} y={cy} width={16} height={22} fill={lit ? palette.figureAccent : palette.ink} opacity={lit ? 0.72 : 0.5} />;
            })}
          </g>
        );
      })}
    </g>
  );
};

const Body: React.FC<{setting: Setting; palette: ArtPalette; progress: number; drift: number}> = ({setting, palette, progress, drift}) => {
  switch (setting) {
    case 'space':
      return (
        <g>
          <ellipse cx={W * 0.76} cy={H * 0.3} rx={320} ry={220} fill={palette.figureAccent} opacity={0.07} />
          <ellipse cx={W * 0.24} cy={H * 0.52} rx={260} ry={180} fill={palette.prop} opacity={0.06} />
          <path d={`M0,${H} Q${W * 0.5},${HORIZON - 180} ${W},${H} L${W},${H} Z`} fill={palette.ground} opacity={0.85} transform={`translate(${drift * 0.4} 0)`} />
        </g>
      );
    case 'desert':
      return (
        <g>
          <Celestial palette={palette} cx={W * 0.72} cy={H * 0.24} r={96} />
          <Ridge fill={palette.groundFar} opacity={0.55} y={HORIZON} amplitude={190} seed={11} drift={drift * 0.3} />
          <Ridge fill={palette.ground} opacity={0.95} y={HORIZON + 90} amplitude={140} seed={29} drift={drift * 0.7} />
          {[0, 1, 2].map((i) => (
            <path
              key={i}
              d={`M${120 + i * 300},${HORIZON + 210 + i * 90} q120,-26 240,0`}
              stroke={alpha(palette.figure, 0.12)}
              strokeWidth={4}
              fill="none"
            />
          ))}
        </g>
      );
    case 'city':
      return (
        <g>
          <Celestial palette={palette} cx={W * 0.78} cy={H * 0.2} r={64} crescent />
          <City palette={palette} drift={drift * 0.4} />
          <rect x={0} y={HORIZON} width={W} height={H - HORIZON} fill={shade(palette.ground, 0.5)} />
          <path d={`M0,${HORIZON + 120} L${W},${HORIZON + 40}`} stroke={alpha(palette.figure, 0.14)} strokeWidth={6} />
        </g>
      );
    case 'ocean':
      return (
        <g>
          <Celestial palette={palette} cx={W * 0.5} cy={H * 0.22} r={92} crescent />
          <rect x={0} y={HORIZON} width={W} height={H - HORIZON} fill={shade(palette.ground, 0.15)} />
          {[0, 1, 2, 3, 4].map((i) => (
            <path
              key={i}
              d={`M0,${HORIZON + 60 + i * 120} q270,-48 540,0 t540,0`}
              stroke={alpha(palette.prop, 0.28 - i * 0.04)}
              strokeWidth={8 + i * 3}
              fill="none"
              transform={`translate(${drift * (0.2 + i * 0.15)} 0)`}
            />
          ))}
          <rect x={W * 0.46} y={HORIZON} width={70} height={H - HORIZON} fill={alpha(palette.figureAccent, 0.16)} />
        </g>
      );
    case 'forest':
      return (
        <g>
          <Ridge fill={palette.groundFar} opacity={0.5} y={HORIZON + 40} amplitude={90} seed={41} drift={drift * 0.25} />
          {[0, 1, 2, 3, 4, 5].map((i) => {
            const x = 60 + i * 190 + rand(70 + i) * 60;
            const height = 260 + rand(90 + i) * 220;
            return (
              <g key={i} transform={`translate(${x + drift * 0.5} 0)`}>
                <rect x={-12} y={HORIZON - height * 0.32} width={24} height={height * 0.4} fill={shade(palette.ground, 0.45)} />
                <circle cx={0} cy={HORIZON - height * 0.62} r={height * 0.3} fill={shade(palette.groundFar, 0.2)} opacity={0.92} />
              </g>
            );
          })}
          <rect x={0} y={HORIZON + 60} width={W} height={H - HORIZON} fill={shade(palette.ground, 0.3)} />
        </g>
      );
    case 'interior':
      return (
        <g>
          <rect x={0} y={0} width={W} height={HORIZON} fill={mix(palette.skyBottom, palette.ground, 0.4)} />
          <rect x={0} y={HORIZON} width={W} height={H - HORIZON} fill={shade(palette.ground, 0.28)} />
          <rect x={W * 0.6} y={H * 0.16} width={W * 0.3} height={H * 0.3} fill={alpha(palette.figureAccent, 0.5)} />
          <path d={`M${W * 0.6},${H * 0.46} L${W * 0.2},${H} L${W * 0.9},${H} Z`} fill={alpha(palette.figureAccent, 0.12)} />
          <rect x={W * 0.06} y={H * 0.66} width={W * 0.28} height={H * 0.12} rx={18} fill={shade(palette.ground, 0.42)} />
        </g>
      );
    default:
      return (
        <g opacity={0.75}>
          {[0, 1, 2, 3].map((i) => (
            <circle
              key={i}
              cx={W * 0.5}
              cy={H * 0.46}
              r={180 + i * 150 + progress * 40}
              fill="none"
              stroke={alpha(palette.figureAccent, 0.16 - i * 0.03)}
              strokeWidth={6}
            />
          ))}
          <rect x={0} y={HORIZON + 180} width={W} height={H} fill={alpha(palette.ink, 0.35)} />
        </g>
      );
  }
};

export const Environment: React.FC<{
  setting: Setting;
  timeOfDay: TimeOfDay;
  palette: ArtPalette;
  progress: number;
}> = ({setting, timeOfDay, palette, progress}) => {
  const drift = (progress - 0.5) * 46;
  const gradientId = `sky-${setting}`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid slice" style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}} aria-hidden="true">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={palette.skyTop} />
          <stop offset="62%" stopColor={mix(palette.skyTop, palette.skyBottom, 0.72)} />
          <stop offset="100%" stopColor={palette.skyBottom} />
        </linearGradient>
      </defs>
      <rect x={0} y={0} width={W} height={H} fill={`url(#${gradientId})`} />
      {timeOfDay === 'night' ? <Stars palette={palette} count={90} /> : null}
      <Body setting={setting} palette={palette} progress={progress} drift={drift} />
    </svg>
  );
};
```

Verify: tsc exit 0.

Commit: `git commit -m "feat(art): layered environments"`.

### Task 1.6 — character rig

`packages/video/src/art/Figure.tsx`:

```tsx
import React from 'react';
import {interpolate, spring, useVideoConfig} from 'remotion';
import type {IllustrationActor, Pose} from '../scene-data';
import {alpha, shade, tint, type ArtPalette} from './palette';

interface Joints {torso: number; head: number; armL: number; armR: number; legL: number; legR: number; hipY: number}

const POSES: Record<Pose, Joints> = {
  stand: {torso: 0, head: 0, armL: 8, armR: -8, legL: 4, legR: -4, hipY: 0},
  point: {torso: -3, head: -6, armL: 10, armR: -95, legL: 5, legR: -5, hipY: 0},
  reach: {torso: -8, head: -10, armL: 14, armR: -140, legL: 6, legR: -6, hipY: -4},
  walk: {torso: 4, head: 2, armL: 26, armR: -30, legL: 20, legR: -20, hipY: -2},
  lookUp: {torso: -2, head: -18, armL: 10, armR: -10, legL: 4, legR: -4, hipY: 0},
  shrug: {torso: 0, head: 4, armL: 62, armR: -62, legL: 6, legR: -6, hipY: 0},
  sit: {torso: 6, head: 2, armL: 30, armR: -30, legL: 84, legR: 76, hipY: 26},
};

const SHOULDER = {left: {x: 74, y: 176}, right: {x: 126, y: 176}};
const HIP = {left: {x: 86, y: 286}, right: {x: 114, y: 286}};

/** angle 0 points straight down; positive swings toward the viewer's left. */
const limbEnd = (from: {x: number; y: number}, length: number, angle: number) => {
  const rad = Math.PI / 2 + (angle * Math.PI) / 180;
  return {x: from.x + Math.cos(rad) * length, y: from.y + Math.sin(rad) * length};
};

const Limb: React.FC<{
  from: {x: number; y: number};
  upper: number;
  lower: number;
  angle: number;
  width: number;
  color: string;
  cap: 'hand' | 'foot';
  capColor: string;
}> = ({from, upper, lower, angle, width, color, cap, capColor}) => {
  const knee = limbEnd(from, upper, angle);
  const tip = limbEnd(knee, lower, angle * 0.6);
  return (
    <g>
      <g stroke={color} strokeWidth={width} strokeLinecap="round" fill="none">
        <line x1={from.x} y1={from.y} x2={knee.x} y2={knee.y} />
        <line x1={knee.x} y1={knee.y} x2={tip.x} y2={tip.y} />
      </g>
      {cap === 'foot' ? (
        // Shoe: a sole plus a toe box, so the leg does not end in a bare stroke.
        <g fill={capColor}>
          <ellipse cx={tip.x} cy={tip.y + width * 0.18} rx={width * 0.86} ry={width * 0.36} />
          <rect x={tip.x - width * 0.5} y={tip.y - width * 0.2} width={width * 1.05} height={width * 0.42} rx={width * 0.2} />
        </g>
      ) : (
        // Mitten: palm plus a thumb nub reads as a hand at 1080px wide.
        <g fill={capColor}>
          <circle cx={tip.x} cy={tip.y} r={width * 0.78} />
          <ellipse cx={tip.x - width * 0.55} cy={tip.y + width * 0.34} rx={width * 0.34} ry={width * 0.5} transform={`rotate(-30 ${tip.x} ${tip.y})`} />
        </g>
      )}
    </g>
  );
};

export const Figure: React.FC<{
  actor: IllustrationActor;
  palette: ArtPalette;
  frame: number;
  index: number;
}> = ({actor, palette, frame, index}) => {
  const {fps} = useVideoConfig();
  const pose = POSES[actor.pose] ?? POSES.stand;
  const walk = actor.pose === 'walk' ? Math.sin(frame / 5.4) * 24 : 0;
  const breathe = Math.sin(frame / 26 + index) * 1.6;
  const sway = Math.sin(frame / 19 + index) * 0.7;

  // spring() with a negative frame is undefined behaviour; clamp before calling it.
  const enterRaw = spring({frame: Math.max(0, frame - index * 4), fps, config: {damping: 14, stiffness: 130, mass: 0.9}});
  const enter = Number.isFinite(enterRaw) ? Math.min(1, Math.max(0, enterRaw)) : 1;
  const opacity = interpolate(frame, [0, 10], [0, 1], {extrapolateRight: 'clamp'});

  const body = actor.tone === 'accent' ? palette.figureAccent : actor.tone === 'secondary' ? palette.prop : palette.figure;
  const ink = actor.silhouette ? shade(palette.ink, 0.1) : body;
  const limbColor = actor.silhouette ? ink : shade(body, 0.18);
  const skin = actor.silhouette ? ink : tint(body, 0.18);
  const rim = alpha(tint(palette.figure, 0.7), 0.55);

  const blink = (frame + index * 37) % 97 < 4;
  const heightPx = 0.52 * 1920 * actor.scale;
  const widthPx = (heightPx * 200) / 430;

  return (
    <div
      style={{
        position: 'absolute',
        left: actor.x * 1080 - widthPx / 2,
        top: actor.ground * 1920 - heightPx,
        width: widthPx,
        height: heightPx,
        opacity: opacity * enter,
        transform: `translateY(${(1 - enter) * 40}px) rotate(${sway}deg) scaleX(${actor.facing === 'left' ? -1 : 1})`,
        transformOrigin: '50% 100%',
      }}
    >
      <svg viewBox="0 0 200 430" style={{width: '100%', height: '100%'}} aria-hidden="true">
        <ellipse cx={100} cy={418} rx={54} ry={9} fill={alpha(palette.ink, 0.38)} />
        <g transform={`translate(0 ${pose.hipY + breathe})`}>
          <Limb from={HIP.left} upper={68} lower={66} angle={pose.legL + walk} width={22} color={limbColor} cap="foot" capColor={shade(body, 0.42)} />
          <Limb from={HIP.right} upper={68} lower={66} angle={pose.legR - walk} width={22} color={limbColor} cap="foot" capColor={shade(body, 0.42)} />
          <rect x={66} y={152} width={68} height={140} rx={30} fill={ink} transform={`rotate(${pose.torso} 100 290)`} />
          {/* Rim light from the scene's key light keeps a flat figure from reading as a sticker. */}
          <rect x={66} y={152} width={12} height={140} rx={6} fill={rim} transform={`rotate(${pose.torso} 100 290)`} />
          <Limb from={SHOULDER.left} upper={64} lower={58} angle={pose.armL - walk * 0.7} width={20} color={limbColor} cap="hand" capColor={skin} />
          <Limb from={SHOULDER.right} upper={64} lower={58} angle={pose.armR + walk * 0.7} width={20} color={limbColor} cap="hand" capColor={skin} />
          <g transform={`rotate(${pose.torso + pose.head} 100 152)`}>
            <circle cx={100} cy={116} r={42} fill={ink} />
            <path d="M58 106 Q100 48 142 106 Q120 86 100 90 Q80 86 58 106Z" fill={shade(body, 0.3)} />
            <path d="M60 104 Q100 62 140 104" stroke={rim} strokeWidth={5} fill="none" strokeLinecap="round" />
            {actor.silhouette ? null : (
              <g>
                {blink ? (
                  <g stroke={palette.ink} strokeWidth={4} strokeLinecap="round">
                    <line x1={82} y1={112} x2={92} y2={112} />
                    <line x1={108} y1={112} x2={118} y2={112} />
                  </g>
                ) : (
                  <g fill={palette.ink}>
                    <ellipse cx={87} cy={111} rx={5} ry={6.5} />
                    <ellipse cx={113} cy={111} rx={5} ry={6.5} />
                  </g>
                )}
                <path d="M90 132 Q100 140 110 132" stroke={palette.ink} strokeWidth={4} strokeLinecap="round" fill="none" />
              </g>
            )}
          </g>
        </g>
      </svg>
    </div>
  );
};
```

`ArtPalette` has no `secondary` field — the `secondary` tone maps to `palette.prop`. Do not add a field to `ArtPalette` for it.

Verify: tsc exit 0.

Commit: `git commit -m "feat(art): posed character rig"`.

### Task 1.7 — props

`packages/video/src/art/Prop.tsx`:

```tsx
import React from 'react';
import type {IllustrationProp} from '../scene-data';
import {alpha, shade, type ArtPalette} from './palette';

const BOX = 100;

const Shape: React.FC<{kind: IllustrationProp['kind']; palette: ArtPalette}> = ({kind, palette}) => {
  switch (kind) {
    case 'sun':
      return (
        <g>
          <circle cx={50} cy={50} r={46} fill={palette.glow} />
          <circle cx={50} cy={50} r={32} fill={palette.figureAccent} />
        </g>
      );
    case 'moon':
      return (
        <g>
          <circle cx={50} cy={50} r={44} fill={palette.glow} />
          <circle cx={50} cy={50} r={30} fill={palette.prop} />
          <circle cx={62} cy={43} r={26} fill={palette.skyTop} />
        </g>
      );
    case 'planet':
      return (
        <g>
          <circle cx={50} cy={50} r={28} fill={palette.prop} />
          <ellipse cx={50} cy={50} rx={44} ry={13} fill="none" stroke={palette.figureAccent} strokeWidth={5} opacity={0.85} transform="rotate(-18 50 50)" />
        </g>
      );
    case 'star':
      return <path d="M50 6 L58 42 L94 50 L58 58 L50 94 L42 58 L6 50 L42 42 Z" fill={palette.figureAccent} />;
    case 'cloud':
      return (
        <g fill={alpha(palette.figure, 0.72)}>
          <ellipse cx={38} cy={58} rx={26} ry={18} />
          <ellipse cx={62} cy={50} rx={30} ry={22} />
          <ellipse cx={78} cy={60} rx={20} ry={15} />
        </g>
      );
    case 'mountain':
      return <path d="M4 92 L38 26 L58 62 L72 40 L96 92 Z" fill={shade(palette.groundFar, 0.1)} />;
    case 'tree':
      return (
        <g>
          <rect x={44} y={58} width={12} height={38} fill={shade(palette.ground, 0.45)} />
          <circle cx={50} cy={42} r={26} fill={shade(palette.groundFar, 0.15)} />
          <circle cx={34} cy={54} r={17} fill={shade(palette.groundFar, 0.05)} />
          <circle cx={66} cy={54} r={17} fill={shade(palette.groundFar, 0.05)} />
        </g>
      );
    case 'tower':
      return (
        <g>
          <rect x={30} y={14} width={40} height={82} fill={shade(palette.ground, 0.35)} />
          {[0, 1, 2, 3].map((row) => [0, 1].map((col) => (
            <rect key={`${row}-${col}`} x={38 + col * 16} y={24 + row * 18} width={10} height={12} fill={palette.figureAccent} opacity={0.7} />
          )))}
        </g>
      );
    case 'gear':
      return (
        <g fill={palette.prop}>
          <circle cx={50} cy={50} r={26} />
          {Array.from({length: 8}, (_, i) => (
            <rect key={i} x={46} y={8} width={8} height={16} transform={`rotate(${i * 45} 50 50)`} />
          ))}
          <circle cx={50} cy={50} r={10} fill={palette.skyTop} />
        </g>
      );
    case 'book':
      return (
        <g>
          <rect x={16} y={26} width={68} height={52} rx={6} fill={palette.prop} />
          <rect x={16} y={26} width={10} height={52} fill={shade(palette.prop, 0.3)} />
          <line x1={36} y1={44} x2={74} y2={44} stroke={palette.skyTop} strokeWidth={4} />
          <line x1={36} y1={58} x2={66} y2={58} stroke={palette.skyTop} strokeWidth={4} />
        </g>
      );
    case 'wave':
      return (
        <g stroke={palette.figureAccent} strokeWidth={7} fill="none" strokeLinecap="round">
          <path d="M4 44 q22,-18 44,0 t44,0" />
          <path d="M4 64 q22,-18 44,0 t44,0" opacity={0.7} />
        </g>
      );
    case 'clock':
      return (
        <g>
          <circle cx={50} cy={50} r={34} fill={palette.prop} />
          <circle cx={50} cy={50} r={26} fill={palette.skyTop} />
          <line x1={50} y1={50} x2={50} y2={32} stroke={palette.figureAccent} strokeWidth={5} strokeLinecap="round" />
          <line x1={50} y1={50} x2={66} y2={56} stroke={palette.figureAccent} strokeWidth={5} strokeLinecap="round" />
        </g>
      );
    case 'bulb':
      return (
        <g>
          <circle cx={50} cy={40} r={24} fill={palette.figureAccent} />
          <rect x={42} y={62} width={16} height={18} rx={4} fill={palette.prop} />
          <g stroke={palette.figureAccent} strokeWidth={4} strokeLinecap="round">
            <line x1={50} y1={4} x2={50} y2={14} />
            <line x1={20} y1={20} x2={27} y2={27} />
            <line x1={80} y1={20} x2={73} y2={27} />
          </g>
        </g>
      );
    default:
      return (
        <g>
          <line x1={10} y1={50} x2={76} y2={50} stroke={palette.figureAccent} strokeWidth={8} strokeLinecap="round" />
          <path d="M68 32 L92 50 L68 68 Z" fill={palette.figureAccent} />
        </g>
      );
  }
};

export const Prop: React.FC<{prop: IllustrationProp; palette: ArtPalette; frame: number; index: number}> = ({
  prop,
  palette,
  frame,
  index,
}) => {
  const size = 150 * prop.scale;
  const float = Math.sin(frame / 34 + index * 1.7) * 6 * prop.scale;
  return (
    <div
      style={{
        position: 'absolute',
        left: prop.x * 1080 - size / 2,
        top: prop.y * 1920 - size / 2 + float,
        width: size,
        height: size,
      }}
    >
      <svg viewBox={`0 0 ${BOX} ${BOX}`} style={{width: '100%', height: '100%'}} aria-hidden="true">
        <Shape kind={prop.kind} palette={palette} />
      </svg>
    </div>
  );
};
```

Verify: tsc exit 0.

Commit: `git commit -m "feat(art): prop vocabulary"`.

### Task 1.8 — effects

`packages/video/src/art/Effects.tsx`:

```tsx
import React from 'react';
import type {Effect} from '../scene-data';
import {alpha, type ArtPalette} from './palette';
import {rand} from './rng';

const W = 1080;
const H = 1920;

export const Effects: React.FC<{list: Effect[]; palette: ArtPalette; frame: number; progress: number}> = ({
  list,
  palette,
  frame,
  progress,
}) => (
  <>
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid slice" style={{position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none'}} aria-hidden="true">
      {list.includes('lightRays') ? (
        <g opacity={0.22}>
          {Array.from({length: 5}, (_, i) => (
            <polygon
              key={i}
              points={`${420 + i * 46},0 ${560 + i * 46},0 ${900 + i * 120},${H} ${620 + i * 120},${H}`}
              fill={palette.figureAccent}
              opacity={0.3 + rand(i) * 0.3}
              transform={`translate(${Math.sin(frame / 60 + i) * 14} 0)`}
            />
          ))}
        </g>
      ) : null}

      {list.includes('dust') ? (
        <g fill={palette.figure}>
          {Array.from({length: 44}, (_, i) => {
            const drift = frame * (0.5 + rand(i + 7) * 1.6);
            const x = rand(i + 21) * W + Math.sin(frame / 40 + i) * 26;
            const y = H - ((drift + rand(i + 55) * H) % H);
            return <circle key={i} cx={x} cy={y} r={1.6 + rand(i + 91) * 3.2} opacity={0.14 + rand(i + 3) * 0.4} />;
          })}
        </g>
      ) : null}

      {list.includes('stars') ? (
        <g fill={palette.figure}>
          {Array.from({length: 80}, (_, i) => {
            const twinkle = 0.25 + Math.abs(Math.sin(frame / (18 + rand(i) * 30) + i)) * 0.65;
            return (
              <circle key={i} cx={rand(i + 400) * W} cy={rand(i + 500) * H * 0.62} r={1 + rand(i + 600) * 2.4} opacity={twinkle} />
            );
          })}
        </g>
      ) : null}

      {list.includes('speedLines') ? (
        <g stroke={palette.figure} strokeLinecap="round">
          {Array.from({length: 16}, (_, i) => {
            const y = rand(i + 700) * H;
            const length = 90 + rand(i + 800) * 220;
            const x = ((frame * (26 + rand(i + 900) * 40)) % (W + length)) - length;
            return <line key={i} x1={x} y1={y} x2={x + length} y2={y} strokeWidth={2 + rand(i + 950) * 4} opacity={0.16 + rand(i + 990) * 0.3} />;
          })}
        </g>
      ) : null}

      {list.includes('impact') ? (
        <g
          stroke={palette.figureAccent}
          strokeWidth={6}
          strokeLinecap="round"
          opacity={Math.max(0, 1 - progress * 1.4)}
          transform={`translate(${W / 2} ${H * 0.46})`}
        >
          {Array.from({length: 14}, (_, i) => {
            const angle = (i / 14) * Math.PI * 2;
            const inner = 120 + progress * 70;
            const outer = inner + 90 + rand(i + 77) * 120;
            return (
              <line
                key={i}
                x1={Math.cos(angle) * inner}
                y1={Math.sin(angle) * inner}
                x2={Math.cos(angle) * outer}
                y2={Math.sin(angle) * outer}
              />
            );
          })}
        </g>
      ) : null}
    </svg>

    {list.includes('vignette') ? (
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(ellipse at 50% 46%, rgba(0,0,0,0) 46%, ${alpha(palette.ink, 0.62)} 100%)`,
        }}
      />
    ) : null}
  </>
);
```

Verify: tsc exit 0.

Commit: `git commit -m "feat(art): atmosphere and impact effects"`.

### Task 1.9 — stage

`packages/video/src/art/Stage.tsx`:

```tsx
import React from 'react';
import {Img, staticFile} from 'remotion';
import type {IllustrationData} from '../scene-data';
import {Environment} from './Environment';
import {Figure} from './Figure';
import {Prop} from './Prop';
import type {ArtPalette} from './palette';

export const Stage: React.FC<{
  data: IllustrationData;
  palette: ArtPalette;
  frame: number;
  progress: number;
  scale: number;
}> = ({data, palette, frame, progress, scale}) => (
  <div style={{position: 'absolute', inset: 0, transform: `scale(${scale})`, transformOrigin: '50% 54%'}}>
    {data.imageRef ? (
      <Img
        src={staticFile(data.imageRef)}
        style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}}
      />
    ) : null}
    <div style={{position: 'absolute', inset: 0, opacity: data.imageRef ? 0.72 : 1}}>
      <Environment
        setting={data.setting}
        timeOfDay={data.timeOfDay ?? 'night'}
        palette={palette}
        progress={progress}
      />
    </div>
    {data.props.map((prop, i) => (
      <Prop key={`prop-${i}`} prop={prop} palette={palette} frame={frame} index={i} />
    ))}
    {data.actors.map((actor, i) => (
      <Figure key={`actor-${i}`} actor={actor} palette={palette} frame={frame} index={i} />
    ))}
  </div>
);
```

Verify: tsc exit 0.

Commit: `git commit -m "feat(art): stage composition"`.

---

## Phase 2 — the template

### Task 2.1 — `IllustratedStory` composition

`packages/video/src/compositions/IllustratedStory.tsx`:

```tsx
import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import type {ThemeSpec} from '../types';
import type {IllustrationData} from '../scene-data';
import type {SceneProps} from '../components/NarrativeFrame';
import {validateSceneData} from '../scene-data';
import {resolveTheme} from '../themes/brand';
import {Watermark} from '../components/Chrome';
import {slideUp} from '../components/presets';
import {Camera, cameraAt} from '../art/Camera';
import {Effects} from '../art/Effects';
import {Stage} from '../art/Stage';
import {FRAMING_SCALE, shotAt} from '../art/shots';
import {paletteFor} from '../art/palette';

export const IllustratedStoryScene: React.FC<SceneProps> = ({scene, theme: inputTheme, watermark}) => {
  const theme: ThemeSpec = resolveTheme(inputTheme);
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  validateSceneData(scene);

  const data = scene.data as unknown as IllustrationData;
  const palette = paletteFor(theme, data.timeOfDay ?? 'night');
  const span = shotAt(data.shots, frame, scene.durationInFrames);
  const progress = span.duration <= 1 ? 1 : span.local / (span.duration - 1);
  const camera = cameraAt(span.shot.camera, span.local, span.duration);
  const title = data.title ?? scene.text.find((t) => t.style.role === 'title')?.text ?? '';
  const kicker = scene.text.find((t) => t.style.role === 'kicker')?.text ?? '';
  const entrance = slideUp({frame: span.local, fps, durationInFrames: 16, intensity: 0.4});

  return (
    <div style={{position: 'absolute', inset: 0, overflow: 'hidden', background: palette.skyTop}}>
      <Camera state={camera}>
        <Stage data={data} palette={palette} frame={span.local} progress={progress} scale={FRAMING_SCALE[span.shot.framing]} />
      </Camera>

      <Effects list={data.fx} palette={palette} frame={frame} progress={progress} />

      {watermark ? <Watermark text={watermark} theme={theme} /> : null}

      {title ? (
        <div
          style={{
            ...entrance,
            position: 'absolute',
            top: 300,
            left: 72,
            right: 72,
            fontFamily: theme.fontHeading,
            fontSize: 72,
            lineHeight: 1.08,
            color: theme.primary,
            textShadow: '0 6px 26px rgba(0,0,0,0.65)',
            overflowWrap: 'anywhere',
          }}
        >
          {title}
        </div>
      ) : null}

      {kicker ? (
        <div
          style={{
            position: 'absolute',
            top: 268,
            left: 72,
            fontFamily: theme.fontBody,
            fontSize: 30,
            letterSpacing: 5,
            textTransform: 'uppercase',
            color: theme.accent,
            opacity: Math.min(1, span.local / 10),
          }}
        >
          {kicker}
        </div>
      ) : null}

      {data.caption ? (
        <div
          style={{
            position: 'absolute',
            top: 400,
            left: 72,
            right: 72,
            fontFamily: theme.fontBody,
            fontSize: 40,
            lineHeight: 1.28,
            color: theme.secondary,
            opacity: Math.min(1, span.local / 12) * 0.95,
          }}
        >
          {data.caption}
        </div>
      ) : null}
    </div>
  );
};
```

`IllustrationData` is a type-only import, so it is erased at build time and costs nothing at runtime.

### Task 2.2 — register the template everywhere

1. `packages/video/src/types.ts` — append `'IllustratedStory',` to `TEMPLATE_IDS`.
2. `packages/video/src/compositions/registry.ts` — add the import and `IllustratedStory: IllustratedStoryScene,`.
3. `packages/video/src/Root.tsx` — no change (it iterates `TEMPLATE_IDS`).
4. `packages/video/src/scene-data.ts` — now that the id exists in `TemplateId`, add the dispatch case to the `validateSceneData` switch, immediately before `case 'KineticTypography':`:

```ts
    case 'IllustratedStory': validateIllustrationData(scene.data); break;
```

Verify:

```bash
cd packages/video && npx tsc --noEmit
```

Expected: exit 0.

### Task 2.3 — fixture scene + still smoke count

Add a 7th scene to `packages/video/fixtures/all-templates.json` (append after `demo-6`, and bump `demo-6`'s `startFrame`? No — leave existing frames untouched, append `startFrame: 900`):

```json
{
  "sceneId": "demo-7",
  "template": "IllustratedStory",
  "segment": "Adegan demonstrasi fiksi untuk pengujian lokal.",
  "assetRefs": [],
  "text": [
    {"id": "t-6", "text": "Cahaya yang tertunda", "style": {"role": "title"}}
  ],
  "animation": {"preset": "slideUp", "durationInFrames": 20},
  "transition": {"type": "none", "durationInFrames": 0},
  "startFrame": 900,
  "durationInFrames": 150,
  "data": {
    "title": "Cahaya yang tertunda",
    "caption": "8 menit 20 detik dari Matahari",
    "setting": "space",
    "timeOfDay": "night",
    "actors": [{"pose": "point", "x": 0.3, "ground": 0.74, "scale": 1, "facing": "right", "tone": "accent", "silhouette": false}],
    "props": [
      {"kind": "sun", "x": 0.74, "y": 0.26, "scale": 1.3},
      {"kind": "planet", "x": 0.18, "y": 0.2, "scale": 0.7}
    ],
    "fx": ["lightRays", "dust", "vignette"],
    "shots": [
      {"framing": "wide", "camera": "pushIn", "weight": 1},
      {"framing": "close", "camera": "handheld", "weight": 1.2}
    ]
  }
}
```

In `packages/video/scripts/still-smoke.mjs` change both `6` counts to `7` and the message to `7/7 real Remotion stills verified`.

In `packages/video/scripts/test-scene-data.mjs`:
- change the final message to `PASS template contracts: seven valid fixtures, incomplete/unknown/remote/nonfinite rejected`,
- add explicit rejects for the new template:

```js
const illustrated = fixture.scenes.find(s => s.template === 'IllustratedStory');
assert.throws(() => validateSceneData({...illustrated, data: {...illustrated.data, setting: 'underwater'}}));
assert.throws(() => validateSceneData({...illustrated, data: {...illustrated.data, camera: 'pushIn'}}));
assert.doesNotThrow(() => validateSceneData({...illustrated, data: {setting: 'desert'}}));
```

Verify:

```bash
cd packages/video
node scripts/test-scene-data.mjs
node scripts/still-smoke.mjs "$(node -p 'require("path").resolve("../../data/renders/still-smoke")')"
```

Expected: the contract line, then seven `PASS <Template> 1080x1920` lines, then `7/7 real Remotion stills verified`.

Open `data/renders/still-smoke/IllustratedStory.png` and confirm by eye: a night sky with a lit sun, a small planet, a standing figure pointing right, dust, and a vignette. If the figure is off-frame or the art is a flat rectangle, fix `Figure.tsx`/`Environment.tsx` before continuing — do not proceed on a blank still.

Commit:

```bash
git add packages/video/src/compositions/IllustratedStory.tsx packages/video/src/compositions/registry.ts \
        packages/video/src/types.ts packages/video/fixtures/all-templates.json \
        packages/video/scripts/still-smoke.mjs packages/video/scripts/test-scene-data.mjs
git commit -m "feat(video): IllustratedStory composition and fixtures"
```

### Task 2.4 — animation and cut assertions

`packages/video/scripts/test-illustration.mjs`:

```js
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';
import vm from 'node:vm';

const videoDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = process.argv[2];
if (!outDir || !path.isAbsolute(outDir)) throw new Error('Pass an absolute output directory');
mkdirSync(outDir, {recursive: true});

const compile = (rel) => {
  const source = readFileSync(path.join(videoDir, rel), 'utf8');
  const js = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
  const mod = {exports: {}};
  vm.runInNewContext(js, {module: mod, exports: mod.exports, require: createRequire(import.meta.url)});
  return mod.exports;
};
const {shotAt} = compile('src/art/shots.ts');

const fixture = JSON.parse(readFileSync(path.join(videoDir, 'fixtures/all-templates.json'), 'utf8'));
const scene = fixture.scenes.find((s) => s.template === 'IllustratedStory');
assert.ok(scene, 'fixture is missing the IllustratedStory scene');

const cli = path.join(videoDir, 'node_modules/@remotion/cli/remotion-cli.js');
const still = (name, frame, props) => {
  const propsPath = path.join(outDir, `${name}-props.json`);
  const png = path.join(outDir, `${name}.png`);
  writeFileSync(propsPath, JSON.stringify(props));
  const r = spawnSync(process.execPath, [cli, 'still', 'src/index.ts', 'IllustratedStory', png,
    `--props=${propsPath}`, `--frame=${frame}`, '--overwrite', '--log=error'],
    {cwd: videoDir, encoding: 'utf8', timeout: 180000});
  if (r.status !== 0) throw new Error(`${name}@${frame}: ${r.stderr} ${r.stdout}`);
  return png;
};

const stats = (args) => {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-nostats', ...args, '-frames:v', '1', '-f', 'null', '-'],
    {encoding: 'utf8', timeout: 60000});
  if (r.status !== 0) throw new Error(`ffmpeg failed: ${r.stderr}`);
  return Object.fromEntries([...r.stderr.matchAll(/lavfi\.signalstats\.(YMIN|YMAX|YAVG)=([0-9.]+)/g)]
    .map((m) => [m[1], Number(m[2])]));
};
const spread = (png) => stats(['-i', png, '-vf', 'signalstats,metadata=print']);
const diffMean = (a, b) => stats(['-i', a, '-i', b, '-filter_complex', '[0:v][1:v]blend=all_mode=difference,signalstats,metadata=print']).YAVG;

// 1. Art must exist without any typography at all.
const artOnly = {scene: {...scene, text: [], data: {...scene.data, title: undefined, caption: undefined}},
                 theme: fixture.theme, watermark: fixture.watermark.text};
const artA = still('art-0', 0, artOnly);
const artB = still('art-60', 60, artOnly);
const artSpread = spread(artB);
// Measured baseline on this machine: spread 183, motion 11.73, cut 17.20, drift 0.07.
// Thresholds sit near half the baseline so a real regression trips them, not noise.
assert.ok(artSpread.YMAX - artSpread.YMIN >= 80, `illustration is nearly flat (spread ${artSpread.YMAX - artSpread.YMIN})`);

// 2. It must actually animate between two frames.
const motion = diffMean(artA, artB);
assert.ok(motion >= 4, `illustration does not animate (mean frame difference ${motion})`);

// 3. A shot boundary must read as a cut, not a drift.
const full = {scene, theme: fixture.theme, watermark: fixture.watermark.text};
const span = shotAt(scene.data.shots, 0, scene.durationInFrames);
const boundary = span.duration;
const beforeCut = still('cut-before', boundary - 1, full);
const afterCut = still('cut-after', boundary, full);
const midA = still('mid-a', boundary + 20, full);
const midB = still('mid-b', boundary + 21, full);
const cutDelta = diffMean(beforeCut, afterCut);
const driftDelta = diffMean(midA, midB);
assert.ok(cutDelta >= driftDelta * 10 && cutDelta >= 5, `shot boundary is not a cut (cut ${cutDelta} vs drift ${driftDelta})`);

console.log(`PASS illustration: spread ${(artSpread.YMAX - artSpread.YMIN).toFixed(1)}, motion ${motion.toFixed(2)}, cut ${cutDelta.toFixed(2)} vs drift ${driftDelta.toFixed(2)}`);
```

Run:

```bash
cd packages/video
node scripts/test-illustration.mjs "$(node -p 'require("path").resolve("../../data/renders/illustration-review")')"
```

Expected: `PASS illustration: spread <n>, motion <n>, cut <n> vs drift <n>`.

If a threshold fails, record the printed numbers first, then adjust the threshold to roughly half the observed value — never loosen it to zero. If `motion` is below 0.5 the art really is static; fix the animation, not the test.

Commit:

```bash
git add packages/video/scripts/test-illustration.mjs
git commit -m "test(video): assert illustration art, motion and shot cuts"
```

---

## Phase 3 — make the pipeline actually use it

### Task 3.1 — storyboard prompt

Replace `STORYBOARD_SYSTEM` in `packages/core/prompts.py` (currently lines 65–83) with:

```python
STORYBOARD_SYSTEM = """\
Kamu adalah StoryboardAgent. Ubah naskah menjadi StoryboardSpec untuk renderer Remotion.

Tujuan visual: setiap adegan harus terlihat seperti produksi studio animasi — ada dunia yang
digambar, karakter yang berakting, kamera yang bergerak, dan potongan gambar. Jangan membuat
adegan yang hanya berisi tulisan di atas gradien.

Aturan template:
- IllustratedStory = pilihan utama. Pakai untuk minimal dua dari tiga adegan, atau semua adegan
  bila naskah bercerita. Ini satu-satunya template bergambar penuh.
- KineticTypography hanya untuk hook atau punchline pendek (maksimal satu adegan).
- EducationalExplainer untuk daftar fakta. HistoricalTimeline untuk urutan waktu.
- InfographicMotion untuk angka. MotionComic untuk dialog. ParallaxStory untuk lanskap lebar.

Aturan data IllustratedStory (letakkan di dalam "data"):
- "setting" WAJIB, salah satu: space, desert, city, ocean, forest, interior, abstract.
- "timeOfDay" opsional: dawn, day, dusk, night.
- "title" opsional <=70 karakter, "caption" opsional <=90 karakter.
- "actors" 0-3: {"pose":"stand|point|reach|walk|lookUp|shrug|sit","x":0..1,"ground":0..1,
  "scale":0.4..1.8,"facing":"left|right","tone":"primary|secondary|accent","silhouette":bool}
  ground 0.62-0.78 untuk berdiri di garis horizon, 0.9 untuk latar depan.
- "props" 0-5: {"kind":"sun|moon|planet|star|cloud|mountain|tree|tower|gear|book|wave|clock|bulb|arrow",
  "x":0..1,"y":0..1,"scale":0.4..2}
- "fx" 0-4 dari: lightRays, dust, stars, speedLines, impact, vignette.
- "shots" 1-4: {"framing":"wide|medium|close","camera":"static|pushIn|pullOut|panLeft|panRight|tiltUp|handheld","weight":0.5..3}
  Mulai dengan wide, tutup dengan close. weight menentukan lama shot.
- Untuk template lain, sertakan "data" sesuai kontraknya bila diperlukan.

Aturan umum:
- Tepat satu scene per segmen naskah, urutan sama. Jangan menambah/menghapus narasi.
- animation.preset HANYA dari: popIn, slideUp, wordByWord, wipeIn, countUp, fadeIn.
- transition.type HANYA dari: none, fade, slideUp, wipe, zoom.
- frame rate 30, resolusi 1080x1920.
- startFrame = akhir scene sebelumnya (tanpa celah, tanpa tumpang tindih).
- durationInFrames ~ ceil(kata_segmen / 2.6) * 30, kisaran 180-480 per scene.
- segment HARUS teks naratif asli dari naskah (bukan judul template).
- text[] maksimal 1 elemen title per scene; kicker hanya untuk EducationalExplainer.
- subtitles: satu cue per 2-6 kata, startMs/endMs berurutan tanpa tumpang tindih.
- watermark.text = nama kanal.
- Jangan pernah menulis kode, React, SVG, CSS, atau HTML. Hanya data JSON.

Kembalikan HANYA JSON: {"storyboard": {...StoryboardSpec...}}
"""
```

No test asserts on prompt text today, so verification is the live/mock run in Task 3.2.

Commit: `git commit -m "feat(prompts): storyboard must produce illustrated scenes"`.

### Task 3.2 — demo fixture uses the new template

In `packages/core/providers/mock.py`, replace the `_demo_scenes` loop (lines 176–191) with an explicit illustrated storyboard:

```python
_DEMO_ILLUSTRATIONS = [
    {
        "title": "Cahaya dari Masa Lalu",
        "caption": "Setiap tatapan ke langit adalah masa lalu",
        "setting": "space",
        "timeOfDay": "night",
        "actors": [{"pose": "point", "x": 0.32, "ground": 0.76, "scale": 1.0, "tone": "accent"}],
        "props": [{"kind": "sun", "x": 0.74, "y": 0.24, "scale": 1.3},
                  {"kind": "planet", "x": 0.16, "y": 0.18, "scale": 0.7}],
        "fx": ["lightRays", "dust", "vignette"],
        "shots": [{"framing": "wide", "camera": "pushIn", "weight": 1.1},
                  {"framing": "close", "camera": "handheld", "weight": 1.0}],
    },
    {
        "title": "149,6 Juta Kilometer",
        "caption": "Cahaya menempuhnya dalam 8 menit 20 detik",
        "setting": "space",
        "timeOfDay": "night",
        "actors": [],
        "props": [{"kind": "sun", "x": 0.2, "y": 0.3, "scale": 1.1},
                  {"kind": "planet", "x": 0.8, "y": 0.42, "scale": 0.9}],
        "fx": ["dust", "stars"],
        "shots": [{"framing": "wide", "camera": "panRight", "weight": 1.2},
                  {"framing": "medium", "camera": "pushIn", "weight": 0.9}],
    },
    {
        "title": "Perjalanan yang Selalu Terlambat",
        "caption": "Yang terlihat sudah terjadi",
        "setting": "desert",
        "timeOfDay": "dusk",
        "actors": [{"pose": "lookUp", "x": 0.5, "ground": 0.86, "scale": 1.15, "silhouette": True}],
        "props": [{"kind": "sun", "x": 0.5, "y": 0.34, "scale": 1.5}],
        "fx": ["lightRays", "vignette"],
        "shots": [{"framing": "medium", "camera": "tiltUp", "weight": 1.0},
                  {"framing": "close", "camera": "static", "weight": 0.8}],
    },
    {
        "title": "1,3 Detik dari Bulan",
        "caption": "Alam semesta adalah kumpulan pesan lama",
        "setting": "ocean",
        "timeOfDay": "night",
        "actors": [{"pose": "stand", "x": 0.66, "ground": 0.88, "scale": 1.05, "tone": "secondary"}],
        "props": [{"kind": "moon", "x": 0.5, "y": 0.2, "scale": 1.4}],
        "fx": ["stars", "vignette"],
        "shots": [{"framing": "wide", "camera": "pullOut", "weight": 1.2},
                  {"framing": "close", "camera": "handheld", "weight": 1.0}],
    },
]

_demo_scenes = []
for _i, _segment in enumerate(_demo_script["segments"]):
    _demo_scenes.append({
        "sceneId": f"scene-{_i + 1:02d}",
        "template": "IllustratedStory",
        "segment": _segment["text"],
        "assetRefs": [],
        "text": [{"id": f"title-{_i}", "text": _DEMO_ILLUSTRATIONS[_i]["title"], "style": {"role": "title"}}],
        "animation": {"preset": "slideUp", "durationInFrames": 22},
        "transition": {"type": "fade", "durationInFrames": 8},
        "startFrame": _i * 270,
        "durationInFrames": 270,
        "data": _DEMO_ILLUSTRATIONS[_i],
    })
```

Verify the pipeline still reaches approval:

```bash
uv run python scripts/run_pipeline.py --title "Demo studio ilustrasi" --stop approval
```

Expected: a `job created: <id>` line, stage logs, `final state: READY_FOR_APPROVAL`, `artifacts: ...\data\jobs\<id>`. Then:

```bash
uv run python scripts/verify_video.py <id>
```

Expected: exit 0 and the technical checks pass. Open `data/jobs/<id>/output.mp4` and `data/jobs/<id>/thumbnail.png`. The video must show four drawn scenes with camera movement and at least one cut — not four text cards.

Commit: `git commit -m "feat(mock): demo storyboard is illustrated"`.

### Task 3.3 — full offline suite

```bash
uv run pytest -o addopts='' -p no:cacheprovider \
  --basetemp='C:/Users/cubeb/AppData/Local/hermes/cache/scratch/illustration-suite'
uv run ruff check packages/core scripts tests
uv run python scripts/export_schemas.py --check
uv run python scripts/check_secrets.py
```

Expected: all tests pass (was 457 before this work), `All checks passed!`, `20 artifact schemas verified`, `Secret scan: 0 findings ...`.

Commit any doc/schema regeneration that `export_schemas.py` reports as changed.

---

## Phase 4 — retire the placeholder art

### Task 4.1 — MotionComic uses the real rig

In `packages/video/src/compositions/MotionComic.tsx`, replace the inline `<svg>` fallback (lines 18–22) with the shared figure:

```tsx
{panel.assetRef ? (
  <Img src={staticFile(localImage(panel.assetRef))} style={{width: '34%', height: '100%', objectFit: 'cover', borderRadius: SPACE.radius}} />
) : (
  <div style={{width: '34%', height: '100%', position: 'relative', flexShrink: 0}}>
    <Figure
      actor={{pose: i === 0 ? 'point' : i === 1 ? 'shrug' : 'stand', x: 0.5, ground: 0.96, scale: 0.55, facing: 'right', tone: 'accent', silhouette: false}}
      palette={paletteFor(theme, 'night')}
      frame={frame}
      index={i}
    />
  </div>
)}
```

Add imports: `import {Figure} from '../art/Figure';` and `import {paletteFor} from '../art/palette';`.

Verify: `cd packages/video && npx tsc --noEmit`, then

```bash
node scripts/still-smoke.mjs "$(node -p 'require("path").resolve("../../data/renders/still-smoke")')"
```

Expected: still `7/7` passing. Open `MotionComic.png` and confirm three panels now contain an actual posed character, not the old circle-and-arc glyph.

Commit: `git commit -m "feat(video): MotionComic uses the character rig"`.

### Task 4.2 — ParallaxStory shapes use the environment silhouettes

In `packages/video/src/compositions/ParallaxStory.tsx`, replace the three inline shape branches (lines 18–20) with prop rendering:

```tsx
{layer.shape === 'circle' ? <Prop prop={{kind: 'moon', x: 0.7, y: 0.26, scale: 1.1}} palette={paletteFor(theme, 'night')} frame={frame} index={i} /> : null}
{layer.shape === 'ridge' ? <Prop prop={{kind: 'mountain', x: 0.5, y: 0.62, scale: 3.2}} palette={paletteFor(theme, 'night')} frame={frame} index={i} /> : null}
{layer.shape === 'city' ? <Prop prop={{kind: 'tower', x: 0.5, y: 0.7, scale: 3.4}} palette={paletteFor(theme, 'night')} frame={frame} index={i} /> : null}
```

Add imports for `Prop` and `paletteFor`.

Verify: `npx tsc --noEmit` and still smoke `7/7`.

Commit: `git commit -m "feat(video): ParallaxStory reuses art props"`.

### Task 4.3 — sample storyboard shows the new look in Remotion Studio

In `packages/video/src/sample/storyboard.ts`, append a fourth scene after `scene-03`:

```ts
    {
      sceneId: 'scene-04',
      template: 'IllustratedStory',
      segment: 'Malam ini, lihat bulan. Cahayanya butuh satu koma tiga detik untuk sampai ke matamu.',
      assetRefs: [],
      text: [{id: 't4', text: '1,3 Detik dari Bulan', style: {role: 'title'}}],
      animation: {preset: 'slideUp', durationInFrames: 20},
      transition: {type: 'fade', durationInFrames: 12},
      startFrame: 900,
      durationInFrames: 270,
      data: {
        title: '1,3 Detik dari Bulan',
        caption: 'Cahaya bulan selalu terlambat',
        setting: 'ocean',
        timeOfDay: 'night',
        actors: [{pose: 'stand', x: 0.68, ground: 0.88, scale: 1.05, facing: 'right', tone: 'secondary', silhouette: false}],
        props: [{kind: 'moon', x: 0.5, y: 0.2, scale: 1.4}],
        fx: ['stars', 'vignette'],
        shots: [{framing: 'wide', camera: 'pullOut', weight: 1.2}, {framing: 'close', camera: 'handheld', weight: 1}],
      },
    },
```

Also bump `narration.durationMs` to `30000` and add one subtitle cue `{id: 's8', text: 'Cahayanya butuh 1,3 detik.', startMs: 24000, endMs: 29000}`.

Verify: `npx tsc --noEmit` → exit 0. Optional: `npm run dev` and look at the `Short` composition.

Commit: `git commit -m "feat(video): sample storyboard includes an illustrated scene"`.

---

## Phase 5 — docs and final gate

### Task 5.1 — document the contract

In `docs/MEDIA.md`, under "Fixed template data", add:

```markdown
- `IllustratedStory`: `data={setting, timeOfDay?, title?, caption?, imageRef?, actors?, props?, fx?, shots?}`.
  Only `setting` is required; `actors`/`props`/`fx` default to empty and `shots` defaults to one `wide`/`pushIn`.
  Vocabulary is closed: seven settings, seven poses, fourteen prop kinds, six effects, three framings, seven camera moves.
  The scene is split into 1–4 weighted shots with hard cuts; the camera moves inside each shot; the character rig
  animates poses, walk cycles, breathing, blink and hair sway from the frame number only.
  `imageRef` is an operator-supplied licensed plate: it must also appear in `scene.assetRefs`, and it is drawn
  beneath the vector art so real imagery can be used without any paid generation service.
```

In `README.md`, extend the "Working now" bullet list with one line:

```markdown
- `IllustratedStory` template: procedural vector illustration (environments, posed characters, props, atmosphere, virtual camera, shot cuts) driven by validated JSON — no image-generation service and no operator-supplied media required.
```

Commit:

```bash
git add docs/MEDIA.md README.md
git commit -m "docs: IllustratedStory contract"
```

### Task 5.2 — final verification gate

Run every gate, in this order, from the repo root:

```bash
uv run pytest -o addopts='' -p no:cacheprovider \
  --basetemp='C:/Users/cubeb/AppData/Local/hermes/cache/scratch/illustration-final'
uv run ruff check packages/core scripts tests
uv run python scripts/export_schemas.py --check
uv run python scripts/check_secrets.py
cd packages/video && npx tsc --noEmit && node scripts/test-scene-data.mjs
node scripts/still-smoke.mjs "$(node -p 'require("path").resolve("../../data/renders/still-smoke")')"
node scripts/test-illustration.mjs "$(node -p 'require("path").resolve("../../data/renders/illustration-review")')"
```

Expected: tests all pass; `All checks passed!`; `20 artifact schemas verified`; `Secret scan: 0 findings`; no tsc output; `PASS template contracts: seven ...`; `7/7 real Remotion stills verified`; `PASS illustration: ...`.

Measure the render cost regression on the same machine, because SVG layering is not free:

```bash
cd /c/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI
uv run python scripts/run_pipeline.py --title "Ukur render ilustrasi" --stop render
```

Record the `RENDERING` stage duration printed in the log. The pre-change reference was ~53 s for a four-scene 36 s video. Anything above ~2× that means the art is too heavy: reduce `dust` particle count (44), `stars` count (90), or drop the `lightRays` opacity group before shipping.

Finally:

```bash
git status --short
```

Expected: only `M apps/dashboard/next-env.d.ts` (pre-existing, never staged). Everything else committed.

---

## Tests / validation summary

| Layer | Command | Pass condition |
| --- | --- | --- |
| Python contract | `uv run pytest tests/test_illustration_data.py` | all pass |
| Python normalizer | `uv run pytest tests/test_storyboard_normalize.py` | all pass |
| Full suite | `uv run pytest` | same count as before + new tests, 0 failures |
| TS contract | `node scripts/test-scene-data.mjs` | `PASS template contracts: seven ...` |
| TS types | `npx tsc --noEmit` in `packages/video` | exit 0, no output |
| Stills | `node scripts/still-smoke.mjs <abs dir>` | `7/7 real Remotion stills verified` |
| Motion + cuts | `node scripts/test-illustration.mjs <abs dir>` | `PASS illustration: ...` |
| End to end | `run_pipeline.py --stop approval` then `verify_video.py <id>` | `READY_FOR_APPROVAL`, exit 0 |

Measured baseline for the new template on this machine (a 1080x1920 night-space frame, 150-frame scene):

```
PASS illustration: spread 183.0, motion 11.73, cut 17.20 vs drift 0.07
PASS IllustratedStory 1080x1920
7/7 real Remotion stills verified
```

`spread` is the luma range inside the safe area (art is not flat), `motion` is the mean frame difference between frame 0 and 60 (the scene animates), `cut` is the difference across a shot boundary versus `drift` across two adjacent frames inside a shot (a real cut, not a pan). The thresholds in `test-illustration.mjs` are set near half these values so a regression trips them without noise.

TDD discipline: every task that adds behaviour writes the failing assertion first, runs it, shows the failure, then implements. Never commit a test that has never been seen failing.

## Risks, tradeoffs, and open questions

**Render cost.** Each frame now draws a gradient sky, up to 90 stars, 44 dust motes, 8 city blocks with window grids, and a multi-path character. Chromium re-renders all of it per frame. Mitigation: particle counts are constants at the top of `Effects.tsx` and `Environment.tsx`; measure at Task 5.2 and cut them if the render doubles.

**SVG gradient id collisions.** `Environment.tsx` derives the gradient id from `setting`, so two scenes with the same setting would collide *if both were mounted at once*. `Short` mounts one scene at a time inside its `Sequence`, so this is safe today. If a future transition mounts two scenes simultaneously, switch to a per-scene suffix.

**The model may not follow the vocabulary.** The normalizer is deliberately forgiving (aliases, clamping, dropping unknown keys), but a model that emits `setting: "underwater"` maps to `abstract` rather than failing. That is a visible degradation, not a silent wrong render — `abstract` is obviously not an ocean. If it happens often in live runs, add the missing value to the enum rather than loosening the validator.

**Forgiving defaults differ from the other four templates.** Those reject incomplete data on purpose. `IllustratedStory` defaults `actors`/`props`/`fx`/`shots` so a partial model answer still renders something coherent. This is a deliberate asymmetry; do not "fix" it by making the new template strict — it would make live runs fail on formatting instead of producing a scene.

**Determinism.** `rand()` is integer-only (mulberry32), and every animation is a pure function of `frame`. No `Date.now()`, no `Math.random()`. If a future contributor reaches for `Math.random()`, the render hash in `render.json` stops being reproducible — treat that as a bug.

**No image generation.** This plan deliberately avoids any paid or generative image service per `AGENTS.md` rule 12. If the operator later wants photographic plates, the existing `assets-manifest.json` path already handles it: add the image, hash it, reference it as `imageRef`. That path is licence-checked and checksum-bound, and needs no new code.

**Open question 1 — subtitle overlap.** `Subtitles` renders at `bottom: 360` and the caption card at `bottom: 470`. On scenes with a long caption both can be on screen at once. If it looks crowded in the Task 3.2 review, move the caption to `bottom: 540` or drop `caption` from the prompt for scenes with subtitles.

**Open question 2 — one template or several.** A single `IllustratedStory` with a setting enum covers a lot, but a "dialogue between two characters" scene has no framing support for shot/reverse-shot. If the demo feels repetitive after this milestone, the next step is a second illustrated template with a two-actor staging contract, not more settings on this one.

**Rollback.** Every phase is its own commit. To abandon the art direction without losing the pipeline work: `git revert` the `feat(video): IllustratedStory composition and fixtures` commit and reset the mock fixture in `packages/core/providers/mock.py` back to `KineticTypography`/`EducationalExplainer` — the Python contract additions are additive and harmless on their own.


---

## Execution status (2026-10-21, controller-run)

Executed on branch `apex/20261021-illustrated-studio` with `opusantigravity` subagents (see the delegation note at the end). Commits are on that branch; nothing was pushed.

### Done

- **Task 0.1** — branch created.
- **Task 0.2–0.6** — commit `1226a94` (schema + pydantic model) and `f79d179` (normalizer + `imageRef`). RED step observed: `Input should be 'KineticTypography', ... [type=literal_error, input_value='IllustratedStory']`. Intermediate at 0.3 was exactly `2 passed, 3 failed` as predicted.
- **Task 1.1** — commit `4dd76fa`. tsc 0, contract script unchanged at "six" (correct at that point).
- **Task 1.2–1.4** — commit `6fc434e`. Behaviour probed independently: shots monotonic, switch at frame 68, degenerate 3-shots-in-20-frames degrades to 1, empty list throws, rng 2000/2000 distinct in [0,1).
- **Task 1.5–1.8** — commit `3d5dba9`.
- **Task 1.9 + 2.1** — commit `07c95cd`.
- **Task 2.2** — commit `90f58c6` (controller-landed, integration point).
- **Task 2.3** — commit `e86b441`. Fixture scene added, smoke count raised to 7, `7/7 real Remotion stills verified`.
- **Task 2.4** — commit `8d95e44`. `PASS illustration: spread 183.0, motion 11.72, cut 16.13 vs drift 0.08`.
- **Task 3.1** — commit `97b4005`.
- **Task 3.2** — commit `c1aa61b`. Real pipeline run `b8c965987dc946fd`: 4 scenes, all `IllustratedStory`, settings `space, space, desert, ocean`, MP4 9.16 MB, `verify_video.py` exit 0, `-16.01 LUFS`, no black gaps or frozen scenes.
- **Task 3.3 / 5.2 gates** — 466 pytest tests pass (was 457 before this work), Ruff clean, 20 schemas verified, secret scan 0 findings.
- **Task 4.1–4.3** — commit `cfd61f2` (after the three regressions below were fixed).
- **Task 5.1** — commit `40d9af0`.

### Deviations from the plan, and why

The plan's code was executed verbatim except where looking at the rendered PNG proved it wrong. Every change below is a source fix, never a loosened assertion:

1. **`close` framing scale 1.66 → 1.30, `Stage` `transformOrigin` 54% → 78%.** At 1.66 the character's head was pushed into the title band. Anchoring on the ground line makes a tighter framing crop sky instead of the subject.
2. **Title, kicker and caption render on the `wide` shot only.** Keeping them on every framing buried the character under type; a close-up is supposed to play clean.
3. **`paletteFor` ground colours now respond to `timeOfDay`; `dusk` 0.3 → 0.42.** A dusk desert was rendering as midnight with invisible dunes.
4. **`lightRays` feathered with a gradient mask.** Hard polygons read as cardboard cut-outs.
5. **`Figure` and `Prop` gained `fit?: 'frame' | 'box'`.** Both place themselves in absolute 1080×1920 coordinates, which is right for `Stage` but puts them outside a 34%-wide panel. `MotionComic` uses `fit="box"`; without it the characters were clipped away entirely.
6. **`ParallaxStory` renders `Prop` in an HTML wrapper, not inside `<svg>`.** `Prop` returns a positioned `div`; a `div` inside `<svg>` is invalid and rendered nothing. The ridge layer also uses `paletteFor(theme, 'dusk')` so it stays a shade of the theme's own ground instead of vanishing into the card.

Items 5 and 6 are worth calling out because the subagents reported success, and `tsc` plus the still-smoke luma check both passed while the art was missing. Only inspecting the PNG caught them.

### Not done

- **No live provider run.** The demo used mock LLM content. A real `--live` run would exercise the new `STORYBOARD_SYSTEM` prompt against a live model, which was never attempted here; the prompt is verified only by string assertions.
- **No operator-supplied `imageRef` exercised end to end.** Python resolution and renderer rewrite are unit-tested, but no real licensed plate was staged through `assets-manifest.json`.
- **Render cost measured on wall-clock stage events, not a controlled benchmark.** Text-only jobs before the change: 53 s and 48 s. Illustrated jobs: 48 s and 62 s. That is within the plan's 2× ceiling, but the sample is two runs each on a laptop under other load.

### Known limitation

`Figure`'s rig is a flat-shape puppet: poses, walk cycle, breathing, blink and hair sway. It is not skeletal animation and has no IK, so a pose that needs a hand planted on a surface will not hold contact.

### Delegation note

Delegation ran on `opusantigravity` via the local 9router gateway. `tig/claude-opus-5.5` was requested first and rejected on evidence: it returns a valid chat completion but corrupts tool-call arguments (4/4 malformed, e.g. `{"content": print('hi), "path": src/hello.py}`), so no subagent could run with it. Its SSE stream was also empty for some requests. `opusantigravity` produced valid tool-call JSON 4/4.

# Local media contracts

This subsystem performs local file resolution, fixed-template Remotion rendering, measured FFmpeg mixing, and PNG thumbnail generation. It does not download assets, call paid image/video providers, or invent license metadata.

## Integration API (for pipeline owner)

```python
from packages.core.media.assets import AssetAgent, verify_assets
from packages.core.media.audio import AudioAgent, verify_audio
from packages.core.media.render import RenderAgent
from packages.core.media.thumbnail import ThumbnailAgent, verify_thumbnail

assets = AssetAgent().run(storyboard, job_dir, manifest_path=None)
# Persist assets.model_dump(mode="json") as assets.json at ASSETS_READY.
# With manifest_path=None the operator's input is job_dir/assets-manifest.json.
# Passing an explicit manifest_path selects its parent as the confined library root.
timed, audio = AudioAgent(voice=voice, rate=rate).run(script, storyboard, job_dir)
# Persist timed as storyboard.json and audio as audio.json. audio.mix contains the
# complete mix receipt; optional mix.json can contain audio.mix.model_dump(...).
render = RenderAgent().run(script, timed, audio, job_dir)
thumbnail = ThumbnailAgent().run(timed, metadata, job_dir)
# Persist thumbnail.model_dump(mode="json") as thumbnail.json before approval.
verify_assets(assets, timed, job_dir)
verify_audio(audio, script, timed, job_dir)
verify_thumbnail(thumbnail, timed, metadata, job_dir)
```

`AudioAgent.run`, `RenderAgent.run`, `ThumbnailAgent.run`, `verify_audio` and `verify_thumbnail` accept optional keyword-only `assets=AssetManifest`. Normal persisted pipeline calls load `assets.json` themselves. A cancelled callback is supported on media agents. A thumbnail uses `metadata.thumbnail.text` (1–32 nonblank characters), the first scene and its deterministic 70%-frame; metadata can be `VideoMetadata` or the full metadata dictionary. Pass the same metadata representation to verification.

The parent must register/export `ThumbnailArtifact` for `thumbnail.json` and optionally `AudioMixArtifact` for `mix.json`. Both classes live in `packages/core/media/contracts.py`. `AssetManifest` and `AudioArtifact` have new fields and need their existing schema exports regenerated. No global artifact registry is edited by this work package.

Every read/resume of assets.json must call `verify_assets`; audio verification also checks source assets and mix provenance. Canonical storyboard references remain logical IDs; only render/thumbnail props contain staged paths. RenderAgent serves the job directory with Remotion `--public-dir`, rather than adding job media to the source tree's public directory. The renderer consumes one premixed track and does not layer BGM a second time.

## Operator-supplied local manifest

`assets-manifest.json` is an input, not the generated `assets.json` receipt. Its top level is `{"assets": [...]}`. Each entry requires:

- `id`: an exact local identifier, used in scene.assetRefs and template image references.
- `path`: a relative local file inside the manifest directory.
- `kind`: `image`, `music`, or `sfx`.
- `license`: `project-original`, `CC0-1.0`, `CC-BY-4.0`, or `CC-BY-SA-4.0`.
- `attribution`: actual supplied attribution, including creator/required credit.
- `source`: actual provenance (a URL may be recorded as text; it is never fetched).
- `sha256`: SHA-256 of the real file, supplied by the operator.

Custom licenses require a `LicenseRef-...` identifier, a confined `license_file`, and its `license_sha256`. Do not label downloaded material project-original. Metadata and checksum validation establishes byte provenance and completeness, not independent legal verification of the operator's rights assertion.

Supported images are raster PNG/JPEG/WebP; SVG, executable content and remote image URLs are not accepted. Music/SFX are local WAV/MP3/FLAC/OGG/M4A with one audio stream and no video. Paths reject absolute paths, traversal, protocols and escaping symlinks. The source remains untouched. Verified copies are staged as `job_dir/assets/<full-sha256>.<extension>`. Source manifest, source media, custom license documents and staged bytes are rechecked on resume; mutation fails instead of being silently accepted.

No bundled production music is supplied. The test tones are explicitly self-created test fixtures, not production BGM and not licensed third-party songs.

## Fixed template data

All six names are registered as standalone compositions with `{scene, theme}` metadata. Full `Short` dispatch uses the same registry. The four new templates reject absent/incomplete/unknown data at asset/render time; present malformed data also fails Python SceneSpec validation. Legacy storyboards with no new-template data can still be read, but cannot pass ASSETS_READY until repaired. No generic-template fallback is used.

- `MotionComic`: `data={title?, panels:[{caption, speaker?, assetRef?}]}`; 1–3 panels. Without an image, panels use project-created geometric character illustrations.
- `HistoricalTimeline`: `data={title?, events:[{date, label, detail?}]}`; 2–4 events in supplied order. The renderer does not invent dates or evidence.
- `ParallaxStory`: `data={title, caption?, layers:[{depth, shape? , assetRef?}]}`; 1–4 layers, depth 0.1–1. Each requires exactly one staged image reference or a named project-created shape (`ridge`, `city`, `circle`).
- `InfographicMotion`: `data={title, items:[{label, value, unit?}], maxValue?, decimals?}`; 1–4 finite nonnegative values; decimals 0–2. A supplied positive maxValue must cover every value. Counters snap to the exact final value.
- `IllustratedStory`: `data={setting, timeOfDay?, title?, caption?, imageRef?, actors?, props?, fx?, shots?}`.
  Only `setting` is required; `actors`/`props`/`fx` default to empty and `shots` defaults to one `wide`/`pushIn`.
  Vocabulary is closed: seven settings, seven poses, fourteen prop kinds, six effects, three framings, seven camera moves.
  The scene is split into 1–4 weighted shots with hard cuts; the camera moves inside each shot; the character rig
  animates poses, walk cycles, breathing, blink and hair sway from the frame number only.
  `imageRef` is an operator-supplied licensed plate: it must also appear in `scene.assetRefs`, and it is drawn
  beneath the vector art so real imagery can be used without any paid generation service.

Images in panels/layers must also occur in `scene.assetRefs`. Typography/colors come from theme tokens. New narrative layouts are confined to top 260px/bottom 320px safe areas. Backgrounds and decorative watermark elements are not narrative text.

## Audio timeline and mixing

Narration synthesis remains an injectable provider boundary. Real FFprobe segment lengths still determine scene durations and subtitle offsets. The minimum 30-frame scene and frame-quantized PCM timeline are unchanged.

- Music selection: `storyboard.backgroundMusic={"assetRef":"<music-id>","volume":0.15,"loop":true}`.
  The block is validated where the storyboard is written: a mood/intensity descriptor without an
  `assetRef` is rejected, and the normalizer drops one a model invents rather than persisting a
  reference no manifest can resolve.
- Scene effects: `scene.audio={"sfx":[{"assetRef":"<sfx-id>","frame":6,"volume":0.5}]}`. `frame` is relative to the scene after narration timing; out-of-range anchors fail rather than being clamped. An effect is trimmed at its scene boundary.
- Text element `inFrame`/`outFrame` are re-clamped against the scene's own duration twice: once after the draft timing estimate and again after measured narration re-times the scene. A stale `outFrame` from the draft would otherwise hide the text mid-scene.
- The thumbnail is rendered at `ASSETS_READY` for operator preview and re-rendered after `AUDIO_READY`, because narration re-times the storyboard it is bound to. `ThumbnailAgent` reuses its PNG only while the storyboard hash still matches.
- Licensed music is looped only if requested, faded, and sidechain-compressed from the actual narration signal. Narration, ducked BGM and sample-delayed SFX are mixed with a limiter, then two-pass loudnorm targets -16 LUFS and -1.5 dBTP. The measured final result must be within 1 LU of target and at most -1 dBTP.
- `narration.wav` preserves the dry normalized original; `mix.wav` is the single render input when a mix exists. `audio.narration_path` names whichever final track should play. Mix receipts bind original narration, source manifest, resolved asset receipt, graph hash, anchors and output checksum. The total sample count is kept identical to the narration timeline.

FFmpeg/FFprobe calls are local, shell-free and bounded. Default tests inject labelled local fixture TTS; they do not call Edge TTS or model providers. Default production TTS is still Edge TTS (network-backed), not an offline speech engine.

## Verification commands

Run from repo root; choose a unique scratch basetemp when running concurrently:

```bash
uv run pytest tests/test_licensed_assets.py tests/test_audio_mix.py tests/test_thumbnail.py tests/test_media.py --basetemp='C:/Users/cubeb/AppData/Local/hermes/cache/scratch/media-tests'
```

From `packages/video`:

```bash
npx tsc --noEmit
node scripts/still-smoke.mjs 'C:/Users/cubeb/AppData/Local/hermes/cache/scratch/media-stills'
```

The still smoke renders six real 1080×1920 PNGs and records per-file hashes in `stills.json`. Its narrative fixture is clearly labelled fictional/demo. A working local render does not establish live TTS/model, editorial fact verification, account authorization or a successful YouTube upload.

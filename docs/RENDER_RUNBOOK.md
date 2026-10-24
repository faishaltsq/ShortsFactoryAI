# Local render runbook

## Entry points

Run from the repository root with the project-managed interpreter:

```bash
uv run python scripts/run_pipeline.py --title "Demo" --stop storyboard
uv run python scripts/run_pipeline.py --resume JOB_ID --stop audio
uv run python scripts/run_pipeline.py --resume JOB_ID --stop render
uv run python scripts/verify_video.py JOB_ID --frames
```

Supported stops are research, script, creative, storyboard, audio and render. `render` includes technical QC and stops before editorial approval or publishing. Mock LLM mode is the default; real TTS is used when running the audio stage. A full render normally takes substantially less time than the hard timeout, but the first Chromium setup may take longer.

Live providers are the default and never fall back to fixture content; `--mock` is explicit. Provider mode is stored on the job and cannot be switched during resume. Existing jobs without provenance are refused; start a new job rather than marking old fixture data as live.

## Artifact ownership

SQLite `data/jobs/factory.db` is the authoritative job/event/usage store. Each `data/jobs/JOB_ID/` directory contains validated canonical JSON and generated media:

- `job.json`, `research.json`, `topic.json`, `script.json`, `review.json`, `storyboard.json`.
- `draft_qc.json`, `metadata.json` when stopping at the storyboard review step.
- `assets.json`, `audio.json`, `narration.wav`, cached per-segment audio and real word boundaries.
- `render-props.json`, `render.json`, `output.mp4`, `render.log`.
- `qc.json`, `technical-qc.log`, and optional `evidence/verification.json`/frame images.

Canonical JSON is validated by Pydantic and JSON Schema before atomic replacement. Intermediate cache/diagnostic files are not interpreted as canonical stage-success artifacts. Narration/render checksums, measured durations, scene continuity and script/storyboard fingerprints are checked before cached media reuse.

Generated narration is copied to the gitignored `packages/video/public/jobs/JOB_ID/` directory so the fixed Remotion application can resolve it through `staticFile()`. No model-generated JavaScript is executed.

## Failure recovery

Read the failed stage and `last_error` in the SQLite/job snapshot, plus the relevant audio/render/QC log. Resume the same ID after fixing the external problem. Validated completed artifacts are replayed without another model call. Invalid canonical JSON or changed media hashes fail explicitly instead of being treated as completed stages.

A process interrupted before writing `render.json` leaves an incomplete render that is not considered successful. Locks are persisted and have a thirty-minute stale threshold; do not delete the database to clear a lock. Production lease ownership/heartbeats and automated reboot recovery are not part of this milestone.

If the narration falls outside 30–45 seconds, revise the script in a new job before rendering. The engine does not pad a short narration with dead air or truncate a long one merely to pass QC.

## Technical gates

- Exact configured dimensions/FPS, H.264, yuv420p, AAC and expected frame count.
- Audio/container duration within a bounded tolerance of the measured timeline.
- Narration loudness between -18 and -14 LUFS; true peak no higher than -1 dBTP.
- No detected black gap ≥0.4 s, silence ≥2.5 s or frozen interval ≥6 s under the configured detectors.
- Nonempty subtitle cues with in-range timestamps.

The renderer explicitly selects `--color-space=bt709`. On the installed Remotion/FFmpeg combination, JPEG-frame defaults otherwise produced full-range `yuvj420p` despite a yuv420p argument. A six-frame probe confirmed the explicit BT.709 path before the complete sample was rerendered.

Technical QC does not establish editorial quality, licensing outside the vector manifest, source verification or public-publishing permission. The sample remains in `TECHNICAL_QC` with editorial/factual flags false.

## Regression checks

```bash
uv run pytest
uv run ruff check packages/core scripts tests
uv run python scripts/export_schemas.py --check
uv run python scripts/check_secrets.py
cd packages/video
npm run typecheck
```

Standalone template smoke commands:

```bash
npx remotion still src/index.ts KineticTypography ../../data/renders/smoke-kinetic.png --frame=60
npx remotion still src/index.ts EducationalExplainer ../../data/renders/smoke-explainer.png --frame=60
```

The Python suite never needs live provider credentials. Tests use isolated temporary databases; the offline audio test generates labelled test-tone fixtures and exercises actual FFmpeg/FFprobe. The narrated sample is an additional network-backed TTS/local-render integration check, not part of the default test suite.

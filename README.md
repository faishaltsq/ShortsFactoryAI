# Shorts Factory AI

Local-first Indonesian YouTube Shorts production engine. Python owns orchestration and persistence; fixed React/Remotion templates own rendering. The local production pipeline reaches operator approval; unattended execution and live YouTube publishing are not enabled.

## Working now

- SQLite jobs/events, persisted plans, token-owned leases, atomic validated artifacts and job snapshots. The scheduler defaults to disabled.
- Explicit worker/strategist provider adapters, deterministic mock mode, and strict live mode without fixture fallback.
- Research, script, source retrieval with quote checks, originality screening, creative review, storyboard, and editorial eligibility.
- Six fixed templates: `KineticTypography`, `EducationalExplainer`, `MotionComic`, `HistoricalTimeline`, `ParallaxStory`, and `InfographicMotion`.
- Local licensed-asset manifests, optional music/SFX mixing, Indonesian Edge TTS, word-boundary subtitles, and narration-measured scene timing.
- H.264/AAC MP4, 1080×1920 PNG thumbnails, technical QC, and checksum-verified warm resume.
- FastAPI read-only studio with Next.js dashboard; explicit local CLI approval and private-first YouTube publishing commands. No account is connected by default.

## Requirements and installation

Verified on Windows 11, Python 3.12.10, Node 26.7.0 and FFmpeg/FFprobe 9.0.1. Python dependencies are locked in `uv.lock`; video dependencies are locked in `packages/video/package-lock.json`. No Docker or VPS is required.

```bash
uv sync --frozen
cd packages/video
npm ci --include=dev --no-audit --no-fund
cd ../../apps/dashboard
npm ci --include=dev --no-audit --no-fund
cd ../..
```

FFmpeg, FFprobe, Node and uv must be on PATH. The existing shell may export `NODE_ENV=production`; `--include=dev` is deliberate.

## Produce a local demo

Run from the repository root:

```bash
uv run python scripts/run_pipeline.py --title "Demo cahaya dari masa lalu" --stop approval
# Copy the actual job ID printed by the command:
uv run python scripts/verify_video.py JOB_ID
uv run python scripts/approve.py --list
```

The pipeline uses mock **LLM content**, real network-backed Edge TTS, and local Remotion/FFmpeg rendering. It is not fully offline. No paid LLM completion is required for this demo. The pipeline stops at `READY_FOR_APPROVAL`; it does not approve or upload the job.

Output: `data/jobs/JOB_ID/output.mp4` and, when metadata supplies a thumbnail concept, `data/jobs/JOB_ID/thumbnail.png`. A visible `DEMO / MOCK SCRIPT` watermark distinguishes fixture content. Repeating `uv run python scripts/run_pipeline.py --resume JOB_ID --stop approval` validates and reuses completed media. Mock jobs cannot be published.

The verified local sample is `data/jobs/45dd2b1b1b914db0/output.mp4`: 36.608 seconds, 1080×1920, 30 FPS, H.264/AAC, four scenes, 18 subtitle cues, and 16 passing technical checks. Its `approval.json` reports 10/10 checks, but factual sources remain `needs_review` because the content provider is mock.

## Providers and configuration

`.env.example` lists the local configuration names. Existing environment variables take precedence over `.env`. Credentials are never included in job artifacts. The DeepSeek adapter uses only the configured base URL and model; the local router's credential fallback is restricted to the exact `http://localhost:20128` origin.

- `--live` selects configured model adapters and disables mock fallback. Unavailable providers cause an explicit failed/blocked job.
- The worker model configured in this environment is `tig/deepseek-v4.1-flash` on the local router.
- The strategist CLI uses the configured alias `opus`. That alias is **not evidence of the exact Claude Opus 5.5 model/version**.
- Claude completions disable tools, inherited MCP servers and session persistence; prompts are supplied over stdin. These tightened options have adapter tests and were checked against the installed CLI help. A full live production run with these options has not been revalidated.
- `scripts/probe_providers.py` reports availability without a completion by default. Its explicit `--live` diagnostic spends a completion per live adapter and is not a production job. Production usage accounting should be used for budget-controlled runs instead.
- Daily usage is persisted per job. The current USD rates are **unverified estimates**, not the third-party provider's invoice. The guard checks recorded totals before calls; it is not a concurrent cost reservation or a strict provider-side spending cap. Do not treat this milestone as an unattended paid runner.

## Verification

```bash
uv run pytest
uv run ruff check packages/core scripts tests
uv run python scripts/export_schemas.py --check
uv run python scripts/check_secrets.py
cd packages/video && npm run typecheck && node scripts/test-scene-data.mjs
node scripts/still-smoke.mjs "$(node -p 'require("path").resolve("../../data/renders/still-smoke")')"
cd ../../apps/dashboard && npm run typecheck && npm test && npm run build && npm run test:e2e
```

The six-template still smoke saves its PNGs under ignored `data/renders/still-smoke/`. Tests isolate databases/artifacts and mock network/model boundaries. One audio integration test uses explicitly labelled generated test audio with real FFmpeg/FFprobe; the end-to-end media sample used real Edge TTS.

## Operator surfaces and remaining limits

- [Studio setup and measurements](docs/STUDIO.md): local read-only API and dashboard.
- [Editorial approval](docs/APPROVAL.md): explicit local review decisions. A mock job may be locally eligible but cannot pass publishing's live-only gate.
- [Media](docs/MEDIA.md): licensed asset manifest, six render templates, mixing and thumbnail checks.
- [Scheduler](docs/SCHEDULER.md): persisted seven-day plans and dispatch; disabled by default. No startup/reboot service is registered.
- [Publishing](docs/PUBLISHING.md): installed-app OAuth and private-first operator CLI; offline-tested only. No account connection, upload, remote schedule or public publication was performed in this milestone.

Live provider end-to-end behavior and YouTube upload still need separately authorized operator action. See [implementation status](docs/IMPLEMENTATION_STATUS.md) and [AGENTS.md](AGENTS.md).

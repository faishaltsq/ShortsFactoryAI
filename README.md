# Shorts Factory AI

Local-first Indonesian YouTube Shorts production engine. Python owns orchestration and persistence; fixed React/Remotion templates own rendering. This is a working CLI/video milestone, **not yet the complete dashboard or unattended publishing application**.

## Working now

- SQLite jobs/events, exclusive pipeline locks, atomic validated JSON artifacts and job snapshots.
- Explicit worker/strategist provider adapters, deterministic mock mode, and strict live mode without fixture fallback.
- Research suggestions, selection, script, creative review, storyboard and draft metadata through the logical agents.
- `KineticTypography` and `EducationalExplainer` vector templates. Other declared template categories are rejected by the asset/render stages until implemented.
- Real Indonesian Edge TTS, word-boundary subtitles, measured per-scene durations, two-pass loudness normalization.
- H.264/AAC MP4 export with BT.709, 1080×1920, 30 FPS, and technical QC.
- Checksum-verified resume: completed media are reused without another synthesis or render.

## Requirements and installation

Verified on Windows 11, Python 3.12.10, Node 26.7.0 and FFmpeg/FFprobe 9.0.1. Python dependencies are locked in `uv.lock`; video dependencies are locked in `packages/video/package-lock.json`. No Docker or VPS is required.

```bash
uv sync --frozen
cd packages/video
npm ci --include=dev --no-audit --no-fund
cd ../..
```

FFmpeg, FFprobe, Node and uv must be on PATH. The existing shell may export `NODE_ENV=production`; `--include=dev` is deliberate.

## Produce a demo

Run from the repository root:

```bash
uv run python scripts/run_pipeline.py --title "Demo cahaya dari masa lalu" --stop storyboard
# Copy the actual job ID printed by the command:
uv run python scripts/run_pipeline.py --resume JOB_ID --stop render
uv run python scripts/verify_video.py JOB_ID --frames
```

The first command uses mock **LLM content**. The second uses the real network-backed Edge TTS service and local Remotion/FFmpeg rendering. It is not a fully offline workflow. No paid LLM completion is required for this demo.

Output: `data/jobs/JOB_ID/output.mp4`. A visible `DEMO / MOCK SCRIPT` watermark distinguishes fixture content. Repeating the resume command validates and reuses completed artifacts rather than rerendering.

The verified sample in this workspace is:

`data/jobs/89b158426e7a4011/output.mp4`

It is 36.608 seconds, 1080×1920, 30 FPS, H.264/AAC, with four scenes and eighteen subtitle cues. Evidence is in the same job directory under `evidence/`. Technical success does not mark editorial or factual review as passed.

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
cd packages/video
npm run typecheck
```

The default tests isolate databases/artifacts and mock network/model boundaries. An audio integration test uses explicitly labelled generated test audio with real FFmpeg/FFprobe, without contacting TTS.

## Boundaries and next milestones

FastAPI routes, the Next.js dashboard, seven-day planning, startup services, recurring scheduling, source retrieval/claim verification, licensed BGM/SFX, thumbnail production, and YouTube OAuth/upload controls are not implemented yet. No scheduler, startup task, cron job, account connection, upload or public publishing was enabled.

See [implementation status](docs/IMPLEMENTATION_STATUS.md), [render runbook](docs/RENDER_RUNBOOK.md), and [AGENTS.md](AGENTS.md).

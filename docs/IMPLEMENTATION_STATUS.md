# Implementation status

## Verified milestone

Fixture jobs were removed from this workspace; production runs are the only recorded provenance. The current verified sample is job `b55babc8f8ea414f` (live providers, `READY_FOR_APPROVAL`, 10/10 approval checks).

| Property | Observed result |
| --- | --- |
| File | `data/jobs/b55babc8f8ea414f/output.mp4` |
| Container duration | 36.608 s |
| Video duration | 36.600 s |
| Resolution | 1080×1920 |
| Frame rate/count | 30 FPS / 1098 frames |
| Video | H.264 / yuv420p / BT.709 limited range |
| Audio | AAC / 48 kHz / stereo |
| Size | 2,852,953 bytes |
| Integrated loudness | -16.01 LUFS |
| True peak | -5.10 dBTP |
| Storyboard/subtitles | 4 scenes / 18 cues |
| SHA-256 | `606e0af716c4458e3fd691381928b95dac870013186102d1e9c360aa9dbd4814` |

FFprobe checks, checksum verification and FFmpeg black/silence/freeze scanning passed. One extracted frame per scene was inspected for clipping, subtitle readability and the demo label. Stills cannot prove perceptual audio alignment; subtitle timing is based on the TTS word-boundary events, not a separate ASR alignment test.

Both implemented templates passed standalone `remotion still`. The resume command reused the completed media and did not make another provider or TTS call.

## Phase assessment (original media milestone; current status below)

The table and historical build order below describe the earlier two-template checkpoint. For the current six-template, approval and publishing status, use the production completion milestone and `docs/superpowers/plans/2026-10-21-production-completion.md`.

| Phase | State | Evidence or missing work |
| --- | --- | --- |
| Environment audit | Performed | Native Windows; RTX 3050 Laptop 6 GB confirmed; project Python/Node/FFmpeg inspected |
| Video engine | Working milestone | Two real template implementations, two standalone stills, real validated MP4 |
| AI pipeline | Mock pipeline working; live incomplete | Adapters, schemas, routing, usage and persistence exist; a complete live-only run has not passed the tightened integration |
| Audio/visual integration | Core narration path working | Real TTS, measured timing, subtitles, transitions, normalization and technical QC; only generated vectors, no BGM/SFX library |
| Dashboard/API | Working | `apps/api` snapshot/SSE/video routes plus the `apps/dashboard` console; measured in `docs/STUDIO.md` |
| Automation | Implemented, disabled by default | Seven-day planner, persisted dispatch, token-owned leases and retry caps live in `packages/core/orchestration/{planner,scheduler,leases}.py` with `scripts/schedule.py` and `docs/SCHEDULER.md`; the operator enable switch defaults off and no startup registration was added |
| Publishing | Implemented offline, never exercised live | Installed-app OAuth, resumable transport, private-first receipts and uncertain-recovery in `packages/core/publishing/`, `scripts/publish.py`, `docs/PUBLISHING.md`. No account was connected, no upload happened, nothing was scheduled remotely |

## Changes delivered in this milestone

- `packages/core/artifacts.py`, `schemas.py`: Pydantic/JSON-Schema validation and honest factual-review status.
- `packages/core/providers/`: explicit mock/live modes, health/model checks, protected error messages, tool-free Claude CLI completions, Edge TTS adapter.
- `packages/core/orchestration/jobstore.py`: locked/idempotent transitions, atomic JSON writes, path confinement and job snapshots.
- `packages/core/pipeline/runner.py`: resumable execution through technical media QC, no placeholder audio/assets success.
- `packages/core/media/`: asset resolution, narration synthesis/cache, audio-driven timing, render orchestration, physical media checks and cancellation boundaries.
- `packages/video/src/`: real per-scene metadata, title-sized typography, explicit unsupported-template failures, theme resolution and subtitle safe-area correction.
- `config/schemas/`: generated canonical artifact schemas.
- `scripts/`: CLI runner, verification/evidence exporter, schema exporter, credential scanner and provider diagnostic.
- `tests/`: state, contract, provider, confinement, isolation, resume, audio and media regression tests.
- `pyproject.toml`, `uv.lock`, `.gitignore`, `README.md`, `docs/`: reproducible setup and operational documentation.

## Known limitations

- Research currently proposes candidates through an LLM; it does not fetch primary sources or prove claims. Factual scripts stay `needs_review`, fictional scripts are labelled, and rendered media do not imply factual clearance.
- All seven templates have renderers and are wired through `SCENE_RENDERERS`. A model that supplies data outside a template's strict contract can no longer fail the job: `storyboard_normalize` maps the common dialect, completes decorative templates (parallax/comic) from the narration, and degrades a scene that would require inventing numbers or dates to `KineticTypography`, keeping the text the model did write.
- Edge TTS needs network access; there is no offline voice fallback yet. No paid image/video service or music download was added.
- Live adapter changes are unit-tested, but their full paid end-to-end workflow still needs a bounded operator-reviewed integration run. The CLI alias `opus` does not establish Opus 5.5 identity.
- The Codex CLI fallback (`gpt-6.1-sol`) is wired and unit-tested against the CLI's JSON event stream, but this machine's Codex login currently answers `401 Incorrect API key` for every model, including the configured default. The adapter's health probe only checks that the binary runs, so `codex-cli` looks healthy until a completion is attempted; the router then benches it after three failed calls and the strategist chain reaches mock. Set `CODEX_CLI_ENABLED=0` while the login is broken, or re-authenticate the CLI, before relying on it for live review.
- USD estimates are not verified reseller prices. Budget reservations, per-call worst-case accounting, verified cost configuration and isolated accounting for manual diagnostics remain before unattended paid runs.
- Locks have a thirty-minute stale threshold. Owned lease tokens, periodic heartbeats and reboot recovery service tests remain before unattended or multi-worker operation.
- Cancellation is cooperative at stage/subprocess boundaries. A TTS request in progress is bounded by its timeout. The dashboard cancel control and the `POST /api/jobs/{id}/cancel` route are in place; the in-memory cancel flag is still process-local, so a cancel issued to an API process that did not start the run only marks the job and does not reach the worker.
- Normal resume reuses media and now invalidates derived draft artifacts when the script changes (`_invalidate_from`): a cached storyboard is reused only while its scenes still carry the current script's narration. The invalidation refuses to run once `audio.json` or `render.json` exists, so a rendered MP4 is never silently orphaned; the operator starts a new job in that case. An explicit manual rerender command is still missing.
- Content revision is bounded (`MAX_REPAIRS`, default 2) and persisted in `repair.json` before the model call. A draft that fails editorial review twice, or a revision that returns the script unchanged, sets the job to `BLOCKED` rather than `FAILED`, because that needs an operator decision. A live run can therefore spend up to two extra script calls per job.
- Retries are bounded by `MAX_JOB_ATTEMPTS` (default 3): a job that fails that many times is transitioned to `BLOCKED` instead of being retried again. Raising the cap and resuming is legal.
- Research and topic selection read real production history (`packages/core/research/history.py`): earlier titles become the research avoid-list and earlier genres the recent-genre context. The post-hoc `originality.json` gate still runs; history only steers the prompts.
- Historical jobs and usage rows were preserved. Legacy artifacts without provider-mode provenance are not silently adopted into a new live run.

## Build order after this milestone

1. ~~Add FastAPI read/status/artifact routes and a small dashboard previewing the real job artifacts.~~ Done: `apps/api` and `apps/dashboard`, measured in `docs/STUDIO.md`.
2. Add source retrieval, claim verification, originality checks and proper non-mock editorial approval gates. Retrieval, claim verification and the originality gate are in (`verification.json`, `originality.json`); the editorial approval gate itself is still fixture-driven.
3. Add validated licensed assets, the other template renderers, music/SFX mixing and thumbnail generation.
4. Add seven-day planning and persisted scheduling, owned leases, reboot/interrupt tests, and an explicit operator enable switch.
5. Implement YouTube OAuth and private-upload-first publication, requiring explicit operator approval before any account or upload action.

## Studio milestone (2026-10-20)

A second verified run, `89dc199b959242b3`, reached `TECHNICAL_QC` through the same pipeline while the console was open: 88.6 s wall, 79.8 s of it the real Remotion/FFmpeg render, 6.9 s real Edge TTS, 16/16 technical checks passed, `-16.01 LUFS`. While it rendered, `/api/studio/snapshot` answered at p50 64 ms (p95 113 ms) with zero failures and all 179 events reached the SSE stream. Full numbers, method and the known limits are in `docs/STUDIO.md`; the artifacts are in `evidence/`.

This checkpoint is ready for an operator-requested commit/push. Git history records the publication state; this document does not imply that the remaining production features are complete.

## Production completion milestone (2026-10-21)

The pre-approval pipeline now produces and validates the full artifact set — `metadata.json`, `assets.json`, `thumbnail.json`, `audio.json` with an embedded mix receipt — and approval refuses to open unless each one validates against its schema and its media hashes and dimensions match.

| Property | Observed result |
| --- | --- |
| Job | `b55babc8f8ea414f`, "Sejarah AI" (live providers) |
| State | `READY_FOR_APPROVAL` after 64 s wall (6 s TTS, 53 s render, ~4 s thumbnail) |
| Thumbnail | `thumbnail.png`, 1080×1920, 1,002,505 bytes, scene `scene-01` frame 134 |
| Approval | `eligible: true`, 10/10 checks pass, zero blockers |
| Checks | technical_qc, editorial_review, source_verification, originality, metadata, assets, audio, render, media_integrity, thumbnail |
| Warm resume | 1.86 s wall, no TTS, no provider call, no re-render, state unchanged |
| Offline suite | 451 pytest tests, Ruff clean, `tsc --noEmit` clean in `packages/video` and `apps/dashboard`, 13 dashboard unit tests, dashboard build green |
| Video stills | All six templates pass standalone `remotion still` |

Approval binds to artifact and media fingerprints, so editing `script.json`, `metadata.json` or any validated media after approval invalidates it. `thumbnail.json` and `mix.json` are registered in `ARTIFACT_MODELS` and exported to `config/schemas/`; `audio.json` remains the authoritative mix receipt and `mix.json` is its inspection copy. The thumbnail is served read-only: `GET /api/jobs/{id}/thumbnail` returns the PNG only after the recorded SHA-256 matches, and the console shows the thumbnail plus any approval blockers next to the job.

The pipeline renews its token-owned lease during long stages and checks ownership before state transitions. Concurrency tests cover a blocked stage and an expired lease taken by another worker; the old worker stops without marking the job failed.

Creative review persists `creative_draft.json` before revising the script and writes `review.json` only after verification and originality evidence complete. Resume repairs a missing evidence sidecar or interrupted revision without repeating the creative model call; a draft with changed script inputs is rejected.

Unverified live surface: no YouTube account was connected, no upload occurred, no remote schedule exists, and no paid-model run was executed. Deleting `data/jobs/factory.db` would drop job rows while artifact directories survive; recovery from that state is manual.

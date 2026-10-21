# Production Completion Plan

## Scope and authority

Complete the remaining local production features from the implementation-status build order. Review follows implementation and verification. The work does not authorize connecting a YouTube account, uploading videos, publishing publicly, raising budgets, using paid media services, or enabling unattended recurring production. Those actions remain explicit operator commands.

## Architecture and tradeoffs

- Keep the FastAPI/dashboard and Hermes integration observation-only. Operator mutations use local CLI entry points.
- Use SQLite for planning, dispatch, leases, and upload receipts. This minimizes infrastructure at the cost of single-machine deployment.
- Renew token-owned leases and reject stale owners. SQLite transactions protect claims and state transitions; persisted artifacts remain independently validated.
- Separate content eligibility from operator approval. Bind approval to validated artifact and media fingerprints so later edits invalidate approval.
- Resolve only licensed, checksum-verified local assets. No paid generation or unverified media downloads are required.
- Implement YouTube OAuth and resumable transport behind injectable boundaries. Offline contract tests do not establish live account access or a successful upload.

## Work packages

- [x] Harden editorial eligibility and operator approval; verify missing/corrupt evidence and physical media; integrate lifecycle and dashboard projections.
- [x] Implement seven-day plans, persisted dispatch, owned leases, retry limits, and restart/interruption tests. Keep automation disabled by default.
- [x] Implement the four remaining templates, licensed local assets, music/SFX mixing, and validated thumbnails. Exercise all six standalone templates.
- [x] Implement installed-app OAuth and private-first publishing, explicit scheduling/publication approval, resumable recovery, and offline HTTP tests.
- [x] Integrate the CLI and artifact contracts, exercise a complete local media run through READY_FOR_APPROVAL, verify warm resume, run quality/security checks, and document evidence and remaining live prerequisites.

## Ownership while parallel work runs

- Parent: approval.py, artifacts.py, pipeline/runner.py, observability, existing approval tests, operator documentation, schema export, and integration verification.
- Scheduler worker: orchestration/jobstore.py, new planner/scheduler/lease modules, schedule CLI, scheduler/lease tests, docs/SCHEDULER.md.
- Media worker: media modules, schemas.py if needed, packages/video, new asset/mix/thumbnail tests, docs/MEDIA.md.
- Publishing worker: new publishing modules, publish CLI, publishing tests, docs/PUBLISHING.md.

Do not edit files owned by another worker until that worker finishes and hands off ownership.

## Verification gates

1. Targeted tests for each vertical behavior, including failure paths and independent-store concurrency.
2. Full offline pytest and Ruff.
3. Canonical schema export/check and credential scan.
4. Video TypeScript check, all-template still smoke, dashboard TypeScript/build and existing browser regression tests where available.
5. One real local MP4 and thumbnail with FFprobe/hash validation; identify fixture content, real TTS, local rendering, and source/editorial status separately.
6. Resume must perform no repeated synthesis/render/provider work when validated outputs remain current.

## Execution status

### Done

- Approval gate: `packages/core/approval.py` verifies schema validity, evidence quotes, physical media hashes/sizes and the thumbnail against the metadata fingerprint; it fails closed on missing, corrupt, stale or path-escaping artifacts.
- Artifact registry: `thumbnail.json` and `mix.json` registered in `ARTIFACT_MODELS` and exported to `config/schemas/`; `audio.json` keeps the authoritative mix receipt and `mix.json` is written beside it for inspection when a mix exists.
- Orchestration: seven-day planner, persisted dispatch, token-owned leases with heartbeats, retry caps and the operator enable switch (off by default) in `packages/core/orchestration/{planner,scheduler,leases}.py`.
- Media: four additional Remotion templates, licensed local asset resolution, music/SFX mixing (`mix.json`) and validated 1080×1920 thumbnails rendered from the metadata concept.
- Publishing: installed-app OAuth, resumable transport, private-first receipts and uncertain-upload recovery, plus the retry-cap fix that returned the consumed attempt instead of falling through.
- Operator surface: `scripts/{approve,publish,schedule}.py`, `GET /api/jobs/{id}/thumbnail`, and a console that shows the thumbnail and approval blockers per job.
- Verification on 2026-10-21: 451 pytest tests, Ruff clean, `tsc --noEmit` in `packages/video` and `apps/dashboard`, 13 dashboard unit tests, dashboard production build, six standalone 1080×1920 stills, five dashboard browser tests, schema export check and credential scan — all passing. Pipeline concurrency tests cover lease renewal through a blocked stage and rejection of a stolen lease. Resume tests cover missing verification/originality sidecars, an interrupted creative revision, local licensed assets, and stale thumbnail regeneration.
- End-to-end: job `45dd2b1b1b914db0` reached `READY_FOR_APPROVAL` with `eligible: true` and 10/10 approval checks; warm resume completed in 1.86 s with no repeated TTS, provider or render work.

### Not done, needs the live environment

- YouTube OAuth, private upload, remote scheduling/publication, and a paid-model end-to-end run require separate operator authorization and account/provider prerequisites. No live success is implied by offline tests.
- The scheduler enable switch has never been turned on outside tests; no startup registration or reboot-recovery service exists yet.

### Skipped on purpose

- No unattended recurring production, startup registration, paid service addition, or account/upload action is enabled during development.

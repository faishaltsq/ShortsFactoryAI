# Pixel Production Studio Implementation Plan

> **For agentic workers:** Implement task-by-task, preserving the approved operator brief. Use strict RED–GREEN checks and bounded file ownership; do not commit or push unless the operator asks.

**Goal:** Add a functioning pixel-office dashboard over the existing persisted Python production pipeline.

**Architecture:** Add typed persistent observability beside the current job tables; instrument worker lifecycle and actual Remotion counters; serve snapshots/replay/SSE through FastAPI and a same-origin Next.js UI. Keep optional Hermes observation disabled until explicitly configured server-side.

**Tech Stack:** Existing Python/Pydantic/SQLite/FastAPI/uvicorn and Remotion; Next.js 16.4.2 (registry-verified), React, TypeScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-20-pixel-production-studio-design.md`

## Global Constraints

- Keep the current repository, Python orchestration, provider routing, job state machine, and validated artifacts.
- Required agent IDs and six statuses are exactly those in the spec.
- No global Hermes configuration writes, Orca modification, upstream PR installation, paid AI call, scheduler, or publishing.
- No secret/token/raw model/tool payload in browser, event rows, or logs.
- Production statuses reflect actual persisted events. Isolate and label all visual fixtures.
- Canonical media remain 1080×1920, 30 FPS, narration-derived timing and validated output.
- Use `npm install --include=dev --no-audit --no-fund`; the shell may otherwise prune dev dependencies.

## Review Focus

1. A crash leaves a working event behind: expired/ended worker lease must project waiting/stale, not endless animation.
2. Events arrive during reconnect: consistent snapshot cursor plus ordered replay must not drop state or duplicate history.
3. Two jobs use the same agent: preserve each task; aggregate only for the office, never overwrite history.
4. Hostile descriptions/webhooks/media paths: allowlist metadata, redact known secrets, reject invalid signatures/replays/paths and foreign origins.
5. Artifacts are reused or a renderer fails: never emit fake working/progress/100% for cached or invalid output.

## Task 1 — Persistent event vertical slice

**Files:** Create `packages/core/observability/{__init__,events,store,projection,lifecycle}.py`, `tests/test_studio_events.py`, `tests/test_studio_lifecycle.py`. Modify `packages/core/pipeline/runner.py`.

**Interfaces:** `StudioEventStore(db_path)`, `emit(job_id, agent_id, event_type, status, description, ...)`, `page(after, limit, job_id)`, worker lease operations; `StudioService(store).snapshot(job_id=None, mode='production')` returns the spec contract. Runner owns the lifecycle observer but continues using the existing router/store/state transitions.

- [ ] RED: Persist an event with a known environment-secret sentinel, reopen the store, and assert ordered replay, redaction, bounded progress, and no state leakage between jobs.
  ```python
  assert reopened.page(after=first.event_id)[0].job_id == second_job.id
  assert sentinel not in json.dumps(reopened.page(), default=str)
  ```
- [ ] Run `uv run pytest tests/test_studio_events.py -x` and confirm the new interface is missing.
- [ ] Implement additive versioned tables, validated event writes, ordered cursor pages and transactionally consistent projections.
- [ ] GREEN: Run focused tests; add and prove expired-lease, completed-reuse, actual mock-worker ResearchAgent/ScriptAgent, failure and budget boundaries.
  ```python
  assert not any(e.status == 'working' for e in resumed_events if e.event_type == 'artifact_reused')
  assert stale_agent['status'] == 'waiting' and stale_agent['stale']
  ```

## Task 2 — Actual render telemetry

**Files:** Create `packages/core/media/progress.py`, `tests/test_render_progress.py`. Modify `packages/core/media/{process,render}.py` and runner's render callback.

**Interfaces:** `RenderProgress` with phase/completed/total/percent; incremental parser consumes real Remotion output; `run_checked(..., on_output=None)` and `RenderAgent.run(..., progress=None)` preserve all existing callers.

- [ ] RED: Feed rendered and encoded counters, duplicate/regressing/malformed lines and mismatched totals. Assert monotonic bounded progress below 100 until artifact validation.
  ```python
  assert parse('Rendered 450/900').percent == 45
  assert parse('Encoded 900/900').percent < 100
  ```
- [ ] Run `uv run pytest tests/test_render_progress.py -x`, implement the parser and incremental file tail callback, then rerun to GREEN.
- [ ] Prove the output callback sees actual subprocess lines and a nonzero exit never yields a completed event.

## Task 3 — Local API, streaming, preview and optional Hermes receiver

**Files:** Create `apps/{__init__.py,api/__init__.py,api/main.py}`, `packages/core/observability/hermes.py`, `tests/test_studio_api.py`, `tests/test_hermes_observer.py`, `scripts/{studio_demo,run_studio_api}.py`. Modify `.gitignore` only for new local artifacts.

**Interfaces:** Exact endpoints and snapshot/event types in the spec. App factory accepts injected `JobStore` for isolated tests. Hermes receiver accepts native signed raw bytes; no global configuration activation.

- [ ] RED: Assert twelve idle agents, no configuration/provider secrets, strict cursor/job validation, stale recovery, foreign-origin rejection, missing/bad/path-escaped video 404, valid media Range 206.
  ```python
  assert len(client.get('/api/studio/snapshot').json()['agents']) == 12
  assert client.get('/api/studio/snapshot', headers={'Origin':'https://foreign.invalid'}).status_code == 403
  ```
- [ ] Implement API delegation, loopback/host/origin boundaries, snapshot SSE and confined artifact preview. Add explicit isolated fixture CLI; never fall back from production to demo.
- [ ] RED–GREEN Hermes: disabled/unsigned/tampered/stale/oversize/duplicate/mismatched-header deliveries are rejected; signed current delivery stores only metadata and cannot change a job state.
  ```python
  assert observer.accept(raw, headers) is not None
  with pytest.raises(ValueError):
      observer.accept(raw, headers)  # persistent replay rejection
  ```

## Task 4 — Pixel office UI (isolated frontend ownership)

**Files:** Create application files only beneath `apps/dashboard/`: manifest/lock/config, App Router shell, typed contract/reducer/SSE hook, office/inspector/queue/review/preview components, original pixel SVG, asset ledger, styles, unit tests and Chromium E2E.

**Interfaces:** Consume the exact public contract. Relative `/api/` paths proxy server-side to `127.0.0.1:8018`; no credential or provider endpoint reaches the client.

- [ ] RED: Reducer/unit tests reject stale/duplicate cursor updates; E2E specifies six visible/selectable characters, twelve role options, explicit demo labeling, idle without animation, disconnect/reconnect, responsive layout and animation control.
- [ ] Implement navy/neutral office with original artwork, readable system fonts, status-driven transforms, selected-role inspector, real job/quality/video data and empty/loading/error states.
- [ ] GREEN: `npm run test`, `npm run typecheck`, `npm run build`, `npm run test:e2e`. Retain fixtures explicitly labeled as fixture evidence, not live worker proof.

## Task 5 — Integrated evidence and limitations

**Files:** Create `docs/PIXEL_STUDIO_{AUDIT,VERIFICATION}.md`, update `README.md`, add screenshot evidence under `docs/evidence/pixel-studio/` (only nonsensitive UI). Keep videos/DBs/runtime reports gitignored.

- [ ] Run actual mock-only worker stages with paid adapters unreachable. Validate event rows and reconnect from a saved cursor.
- [ ] Run a real local Remotion job reusing approved narration into a new job directory. During the render measure SSE updates, browser action latency/frames, and responsive states. Verify the produced MP4 with FFprobe and existing QC.
- [ ] Capture and inspect desktop/tablet/mobile and actual-render screenshots. State exactly which screenshots are demo, production, or real rendering.
- [ ] Run Python suite, Ruff, schema checks, secret scan, dashboard unit/type/build/E2E, video TypeScript and dependency audits. Review intended diff, without committing/pushing.
- [ ] Recheck the global Hermes config hash and existing Orca/Hermes process/listener presence; report the limit of that evidence.

## Out of scope for this POC

Unattended scheduling, OAuth/upload/publication, paid source verification, a global Hermes outbound target, and importing Pixel Agents PR #399. These remain explicit future work, not fake successful stages.

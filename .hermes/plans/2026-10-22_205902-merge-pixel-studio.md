# Merge both studios into one, with Pixel Studio as the shell

## Goal

Collapse `feature/pixel-studio` into `apex/20261021-illustrated-studio` so the repo has **one** FastAPI app and **one** dashboard — the Pixel Studio UI/UX (Tailwind, sidebar, pixel office, multi-page) driving the illustrated-pipeline backend — and put every plan file behind a single index.

---

## Current context / assumptions

The implementer has zero context. Read these first; every claim below was verified against the working tree.

| Fact | Where it is proven |
|---|---|
| Two branches diverged from `master` @ `250e694`, **22 ahead / 24 behind** each other | `git merge-base`, `git rev-list --left-right --count` |
| `apex/20261021-illustrated-studio` is checked out in the main repo, HEAD `7334e14`, 1 commit ahead of `origin` | `git status -sb` |
| `feature/pixel-studio` @ `8543ea2` exists **only as a ref**; its checkout (`C:\Users\cubeb\orca\workspaces\ShortsFactoryAI\hawksbill`) has **lost `.git`** — `git -C … status` → `fatal: not a git repository` | verified twice |
| That lost worktree still holds the only copy of runtime state: `config/studio.json`, `config/studio-history/*.json` (10 snapshots), `data/jobs/` (18 jobs), `data/renders/` | `ls` on both trees |
| **`feature/pixel-studio`'s committed `apps/api/app.py` is Python-invalid**: `authorization: str *** None` where `\|` belongs (3 occurrences, lines 51/100/116). The *working-tree* copy is correct (21320 bytes, `ast.parse` → OK) | `git show feature/pixel-studio:apps/api/app.py \| grep -n "str \*\*\*"` |
| Apex baseline is green: `uv run pytest` → **480 passed**; dashboard `tsc --noEmit` clean; 13 `node:test` unit tests pass | ran both |
| Apex has 20 schema files + 7 Remotion templates + art kit; pixel has 12 schemas and 2 templates | `config/schemas/`, `packages/video/src/compositions/` |
| `packages/video/package.json` is byte-identical on both branches | `diff` → empty |
| 19 files are **staged but uncommitted** in the main repo (the Schedule feature: `packages/core/observability/schedule.py`, `apps/dashboard/src/components/Schedule.tsx`, `tests/test_schedule.py`, …) | `git status --short` |
| 27 files were changed on **both** sides since the merge base — a plain `git merge` conflicts on all of them | `comm -12` over `git diff --name-only` |
| Pixel's `.gitignore` ignores `.hermes/`, which would orphan the tracked plan `.hermes/plans/2026-10-21_164433-illustrated-animation-studio.md` | `git ls-files .hermes` |
| Plans currently live in 3 places: `.hermes/plans/` (1), `docs/superpowers/plans/` (2), `docs/superpowers/specs/` (1) | `find` |
| Pixel **already retired the CLI strategist** at commit `0443a9f`: `packages/core/providers/claude_cli.py` and `codex_cli.py` do not exist on that branch, `config.py` has no `ClaudeCliConfig`/`CodexCliConfig`, and `providers/__init__.py` exports neither | `git show feature/pixel-studio:…` |
| Apex still carries them: 2 adapter modules, 2 config dataclasses, 2 router chain entries, 1 export pair, 6 tests in `test_codex_cli.py`, 1 in `test_providers.py`, 1 in `test_provider_safety.py` — **8 tests depend on the CLI** | `grep -rn "ClaudeCliProvider\|CodexCliProvider"` |

Assumptions:

- The **merged studio runs on `127.0.0.1:3018`** — the operator's only bookmark. The API stays on `8018` but is **internal-only**: it binds to loopback, the browser never addresses it directly (Next rewrites `/api/*`), and it appears in no bookmark, doc or launcher. Ports 3000, 3201 and 8000 are retired.
- **HTTP-only strategist.** The operator-editable OpenAI-compatible endpoint is the only strategist path. `claude`/`codex` CLI adapters are deleted, not kept as fallbacks. `AGENTS.md §12` still records the CLI as verified on this machine; that fact stops being load-bearing after the merge.
- **`config/studio-history/` is ignored by git** (10 snapshots exist on disk and stay untracked). Rollback history is local-only; `docs/STUDIO.md` must say so.
- **`docs/superpowers/` is kept as history** and takes no new files. `docs/PLANS.md` is the single index.
- Python 3.12 venv via `uv`; Node 26.7.0; `NODE_ENV=production` is exported in this shell, so **every** JS install must use `npm install --include=dev` and every dev/test script must force its own `NODE_ENV`.
- Runtime data is preserved, not discarded: pixel's 18 jobs are copied into the main repo's `data/jobs/` (16-hex ids, no collision) before anything is deleted.

---

## Architecture / proposed approach

Apex is the **trunk** (it owns the pipeline, 480 tests, the illustrated renderer, approval/publishing, and the newest work); Pixel supplies the **presentation and configuration layer** (studio.json, personas, activity telemetry, the Tailwind App-Router shell, vitest/Playwright/axe). Core modules that both branches rewrote are resolved **per file, apex-first**, then pixel's additive behaviours are re-applied on top — never `git merge`.

Two mechanisms stay deliberately duplicated because they answer different questions, and the plan names the boundary so nobody "consolidates" them later:

| Concept | Owner | Storage | Consumer |
|---|---|---|---|
| **Cross-job event feed** (12-role floor, SSE cursor) | apex `observability/` | `studio_events` table | `/api/studio/stream`, `/api/studio/snapshot` |
| **Per-job activity** (who is working on *this* job) | pixel `activity.py` | `jobs.payload.studio_activity` | `/api/jobs/{id}`, pixel office |
| **Recurring production control** (interval, topics, on/off) | pixel `core/scheduler.py` | `config/studio.json → schedule` | `/api/schedule*`, Studio page |
| **Schedule projection** (ON GOING / RESEARCHING / UPCOMING) | apex `observability/schedule.py` | read-only over job states | `/api/studio/schedule`, Jadwal page |
| **7-day persisted plans + dispatch leases** | apex `orchestration/planner.py` + `scheduler.py` | `production_plans` / `production_slots` | `scripts/schedule.py` (CLI only) |

---

## Step-by-step tasks

### Phase 0 — Preserve state before touching anything

**T0.1 — Snapshot the pixel runtime state.**

```bash
mkdir -p "$HOME/sf-pixel-backup"
cp -r "C:/Users/cubeb/orca/workspaces/ShortsFactoryAI/hawksbill/config" "$HOME/sf-pixel-backup/config"
cp -r "C:/Users/cubeb/orca/workspaces/ShortsFactoryAI/hawksbill/data"   "$HOME/sf-pixel-backup/data"
cp "C:/Users/cubeb/orca/workspaces/ShortsFactoryAI/hawksbill/apps/api/app.py" "$HOME/sf-pixel-backup/app.py.good"
```

Verify — expect `10` snapshots, `18` job dirs, and a file with no `***`:

```bash
ls "$HOME/sf-pixel-backup/config/studio-history" | wc -l      # → 10
ls "$HOME/sf-pixel-backup/data/jobs" | wc -l                   # → 18
grep -c '\*\*\*' "$HOME/sf-pixel-backup/app.py.good"           # → 0
```

**T0.2 — Kill the wedged servers and free RAM.** Two Next processes were spinning at ~1 core each with 0.85 GB free.

```bash
powershell -NoProfile -Command "Stop-Process -Id 42400,24836,42376,7164,43208 -Force -ErrorAction SilentlyContinue"
netstat -ano | grep -E ":(3000|3018|3201)\s+.*LISTENING" || echo "ports clear"
```

**T0.3 — Commit the staged Schedule work.** It is real, finished work and must not be swept into the merge.

```bash
cd "C:/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI"
git add -A
git -c core.autocrlf=false commit -m "feat(schedule): production schedule projection and panel

Adds packages/core/observability/schedule.py (read-only status projection over
persisted job states), the /api/studio/schedule endpoint, SchedulePanel in the
dashboard, and tests/test_schedule.py. Also stops tsbuildinfo/AGENTS.md churn."
git log --oneline -1
```

Expected: a new commit on `apex/20261021-illustrated-studio`; `git status --short` → empty.

> Note: `apps/dashboard/AGENTS.md` is a file `next dev` regenerates. It is staged. The merged dashboard sets `agentRules: false`, so delete it in **T0.4** rather than committing it.

**T0.4 — Delete the generated Next agent-rules file and the stray DB.**

```bash
git rm --cached apps/dashboard/AGENTS.md
rm -f apps/dashboard/AGENTS.md
ls -la data/factory.db        # 0 bytes, stray: the real DB is data/jobs/factory.db
rm -f data/factory.db
git commit -m "chore: drop generated next agent-rules file and stray empty db"
```

**T0.5 — Record the pixel baseline numbers** (needed for the final gate, do not guess them):

```bash
cd "$HOME/sf-pixel-backup/.." 2>/dev/null
PIXEL_WT="C:/Users/cubeb/orca/workspaces/ShortsFactoryAI/hawksbill"
cd "$PIXEL_WT" && uv run --project . pytest -q 2>&1 | tail -3
```

Write the resulting `N passed` into `docs/PLANS.md` later at T9.2. If the run errors on `apps/api/app.py`, run it with the good copy in place:

```bash
cp "$HOME/sf-pixel-backup/app.py.good" apps/api/app.py && uv run pytest -q 2>&1 | tail -3
```

**T0.6 — Create the working branch and a clean pixel reference worktree.**

```bash
cd "C:/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI"
git checkout -b merge/pixel-studio-ui
git worktree add ../sf-pixel-ref feature/pixel-studio
cp "$HOME/sf-pixel-backup/app.py.good" ../sf-pixel-ref/apps/api/app.py
cd ../sf-pixel-ref && python -c "import ast;ast.parse(open('apps/api/app.py',encoding='utf-8').read());print('app.py OK')"
```

Expected: `app.py OK`. **Do not** run pytest in that worktree before this copy — the branch commit is broken.

**T0.7 — Confirm the local model router is up.** It answers `200` right now, but it is a separate process and the merged pipeline depends on it for *both* tiers.

```bash
curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 http://localhost:20128/v1/models
```

Expected: `200`. Anything else means no worker and no strategist — do not start a `live` job. The strategist *env* fix itself is T4.3b, because it needs pixel's `config.py` in place first.

---

### Phase 1 — Dashboard: install the Pixel Studio shell

**T1.1 — Replace the dashboard tree.** Delete apex's single-page shell, copy pixel's.

```bash
cd "C:/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI"
git rm -r --cached apps/dashboard/src apps/dashboard/tests >/dev/null
rm -rf apps/dashboard/src apps/dashboard/tests apps/dashboard/playwright.config.ts
cp -r ../sf-pixel-ref/apps/dashboard/src            apps/dashboard/
cp -r ../sf-pixel-ref/apps/dashboard/e2e            apps/dashboard/
cp    ../sf-pixel-ref/apps/dashboard/postcss.config.mjs \
      ../sf-pixel-ref/apps/dashboard/vitest.config.mts \
      ../sf-pixel-ref/apps/dashboard/eslint.config.mjs \
      ../sf-pixel-ref/apps/dashboard/tsconfig.json \
      ../sf-pixel-ref/apps/dashboard/playwright.config.ts \
      apps/dashboard/
# Tracked env template: pixel's version documents STUDIO_*. T4.3c appends
# STRATEGIST_* to this file; nothing else may overwrite it afterwards.
cp ../sf-pixel-ref/.env.example .env.example
```

**T1.2 — Keep the design contract, rewritten for the pixel tokens.**

```bash
cp ../sf-pixel-ref/docs/PIXEL_STUDIO.md apps/dashboard/design/DESIGN.md
```

Then edit `apps/dashboard/design/DESIGN.md`: replace the first line `# Pixel Studio` with `# Pixel Studio — design contract (merged)` and append:

```markdown
## Relationship to the illustrated pipeline

This shell is the operator console for the illustrated production pipeline.
The floor shows the twelve canonical roles (`packages/core/personas.py`); the
timeline, artifacts and approval gate come from the persisted state machine.
Approval is an operator action here, never automatic.
```

Verify: `head -1 apps/dashboard/design/DESIGN.md` → `# Pixel Studio — design contract (merged)`.

**T1.3 — Write `apps/dashboard/package.json`.** One toolchain: pixel's deps + `cross-env`, port 3018.

```json
{
  "name": "shorts-factory-studio",
  "version": "0.1.0",
  "private": true,
  "engines": { "node": ">=20.9.0" },
  "scripts": {
    "dev": "cross-env NODE_ENV=development NEXT_TELEMETRY_DISABLED=1 next dev --hostname 127.0.0.1 --port 3018",
    "build": "cross-env NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 next build",
    "start": "cross-env NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 next start --hostname 127.0.0.1 --port 3018",
    "lint": "eslint src",
    "typecheck": "tsc --noEmit",
    "test": "cross-env NODE_ENV=test vitest run",
    "test:e2e": "cross-env NODE_ENV=test playwright test",
    "test:e2e:list": "cross-env NODE_ENV=test playwright test --list"
  },
  "dependencies": {
    "next": "16.4.2",
    "react": "19.3.1",
    "react-dom": "19.3.1"
  },
  "devDependencies": {
    "@axe-core/playwright": "4.14.0",
    "@playwright/test": "1.64.1",
    "@tailwindcss/postcss": "^4.3.3",
    "@testing-library/dom": "^10.4.2",
    "@testing-library/react": "^16.3.3",
    "@types/node": "22.20.5",
    "@types/react": "19.3.0",
    "@types/react-dom": "19.3.0",
    "cross-env": "10.1.0",
    "eslint": "^10.13.0",
    "eslint-config-next": "16.4.2",
    "jsdom": "^30.1.3",
    "tailwindcss": "^4.3.3",
    "typescript": "5.6.3",
    "vitest": "^5.0.5"
  }
}
```

**T1.4 — Write `apps/dashboard/next.config.ts`.** Pixel's proxy, pointed at 8018, with `agentRules: false`.

```ts
import type { NextConfig } from "next";

// One origin for UI + API: no CORS, no token in the browser.
const API_ORIGIN = process.env.STUDIO_API_ORIGIN ?? "http://127.0.0.1:8018";

const nextConfig: NextConfig = {
  // Keep `next dev` from writing AGENTS.md into apps/dashboard; the architecture
  // rules live in the repo-root AGENTS.md and must not be duplicated.
  agentRules: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
```

**T1.5 — Point Playwright at 3018 and keep its fake-API safety property.** Edit `apps/dashboard/playwright.config.ts`: change `baseURL` to `"http://127.0.0.1:3018"` and the `webServer.command` to:

```ts
    command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3018",
    url: "http://127.0.0.1:3018",
```

Keep `env: { NODE_ENV: "development", STUDIO_API_ORIGIN: "http://127.0.0.1:9" }` — the closed port is what makes an unmocked request fail loudly.

**T1.6 — Install and prove the shell builds.**

```bash
cd apps/dashboard
npm install --include=dev --no-audit --no-fund
npm run typecheck
npm run build
```

Expected: `tsc` silent; build ends `Route (app)` table listing `/`, `/jobs`, `/jobs/[id]`, `/providers`, `/studio`, `/usage`. If `npm install` fails on peer ranges, relax `next`/`react`/`react-dom` to `^16.4.2` / `^19.3.1` and re-run.

**T1.7 — Delete the apex dashboard unit tests that no longer have modules.**

```bash
cd ../..
git rm -r --cached apps/dashboard/tests 2>/dev/null || true
ls apps/dashboard/tests 2>/dev/null || echo "gone"
grep -rn "lib/state\|lib/selectors" apps/dashboard/src || echo "no references"
```

Both `lib/state.ts` and `lib/selectors.ts` were apex-only; pixel's `lib/team.ts` + `lib/useStudioLive.ts` replace them, and `src/lib/team.test.ts` already covers status derivation. Expected: `gone`, then `no references`.

---

### Phase 2 — Python: state machine and store

**T2.1 — `packages/core/orchestration/states.py`: keep apex, add `STOP_POINTS`.** Append after the `ARTIFACT_FOR_STATE` block (apex line 89):

```python
#: Pipeline stop points shared by the CLI and the API — one source of truth.
STOP_POINTS: dict[str, JobState] = {
    "research": JobState.TOPIC_SELECTED,
    "script": JobState.SCRIPT_GENERATED,
    "creative": JobState.CREATIVE_REVIEW,
    "storyboard": JobState.STORYBOARD_READY,
    "audio": JobState.AUDIO_READY,
    "render": JobState.TECHNICAL_QC,
    "editorial": JobState.EDITORIAL_QC,
    "approval": JobState.READY_FOR_APPROVAL,
}
```

**T2.2 — Test first (TDD): the merged stop table covers all eight stages.**

Create `tests/test_stop_points.py`:

```python
from packages.core.orchestration.states import STOP_POINTS, JobState


def test_stop_points_cover_every_stage_the_merged_pipeline_can_stop_at():
    assert STOP_POINTS["research"] is JobState.TOPIC_SELECTED
    assert STOP_POINTS["storyboard"] is JobState.STORYBOARD_READY
    assert STOP_POINTS["render"] is JobState.TECHNICAL_QC
    assert STOP_POINTS["editorial"] is JobState.EDITORIAL_QC
    assert STOP_POINTS["approval"] is JobState.READY_FOR_APPROVAL
    assert set(STOP_POINTS) == {
        "research", "script", "creative", "storyboard",
        "audio", "render", "editorial", "approval",
    }
```

Run before adding the code → expect `ImportError: cannot import name 'STOP_POINTS'`. Then add T2.1, re-run:

```bash
uv run pytest tests/test_stop_points.py -q     # → 1 passed
```

**T2.3 — Update pixel's narrower assertion.** In the ported `tests/test_states.py` (arrives at T4.1), replace

```python
    assert set(STOP_POINTS) == {"research", "script", "creative", "storyboard", "audio", "render"}
```

with

```python
    assert {"research", "script", "creative", "storyboard", "audio", "render"} <= set(STOP_POINTS)
```

because the merged pipeline has 11 stages, not 9.

**T2.4 — `packages/core/orchestration/jobstore.py`: add `set_activity`.** Apex's store already has `_lock`, `payload`, `snapshot()`. Insert after `events()` (apex line 178):

```python
    def set_activity(self, job_id: str, value: dict[str, Any]) -> None:
        """Persist a runner-reported activity snapshot.

        Validation happens before the write so an invalid snapshot cannot leave a
        partial row. State, attempts, updated_at and job_events are untouched:
        this is observation, not a lifecycle transition.
        """
        from ..activity import ActivitySnapshot

        activity = ActivitySnapshot.model_validate(value).model_dump(mode="json")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"job {job_id} not found")
            payload = json.loads(row["payload"])
            payload["studio_activity"] = activity
            conn.execute(
                "UPDATE jobs SET payload=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), job_id),
            )
        self.snapshot(job_id)
```

**T2.5 — Test first.** Create `tests/test_jobstore_activity.py`:

```python
import pytest

from packages.core.orchestration import JobStore


def test_set_activity_persists_without_touching_state_or_events(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="aktivitas")
    before = store.get(job.id)
    store.set_activity(job.id, {
        "token": "a" * 32, "agent": "ScriptAgent", "stage": "SCRIPT_GENERATED",
        "phase": "running", "updated_at": "2026-10-22T00:00:00+00:00", "completed": {},
    })
    after = store.get(job.id)
    assert after.state is before.state
    assert after.updated_at == before.updated_at
    assert after.payload["studio_activity"]["agent"] == "ScriptAgent"
    assert store.events(job.id) == []


def test_set_activity_rejects_a_bad_token_before_writing(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="aktivitas")
    with pytest.raises(ValueError):
        store.set_activity(job.id, {"token": "short", "updated_at": "x", "completed": {}})
    assert "studio_activity" not in store.get(job.id).payload
```

Run → `ModuleNotFoundError: packages.core.activity`. Create the module in T3.1, then re-run → `2 passed`.

---

### Phase 3 — Python: pixel's additive core modules

**T3.1 — Copy the three additive modules verbatim.**

```bash
cd "C:/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI"
cp ../sf-pixel-ref/packages/core/activity.py   packages/core/activity.py
cp ../sf-pixel-ref/packages/core/personas.py   packages/core/personas.py
cp ../sf-pixel-ref/packages/core/studio.py     packages/core/studio.py
```

**T3.2 — Extend `STAGE_AGENTS` in `packages/core/activity.py`** for the two extra apex stages. Replace the closing of the dict (after `"TECHNICAL_QC": "RenderAgent",`):

```python
    "TECHNICAL_QC": "RenderAgent",
    "EDITORIAL_QC": "MetadataAgent",
    "READY_FOR_APPROVAL": "FactoryOrchestrator",
```

Verify: `uv run pytest tests/test_jobstore_activity.py tests/test_activity.py -q` → all pass (the ported `test_activity.py` arrives at T4.1; if absent yet, run only the first file).

**T3.3 — Make `personas.py` tolerate apex's extra agent.** Apex has `ClaimExtractorAgent`, which pixel's `AGENT_CLASSES` does not list — that is fine (it is a helper, not a pipeline stage), but `TEAM` must still resolve 12 rows. Verify:

```bash
uv run python -c "from packages.core.personas import TEAM, PERSONAS; print(len(TEAM), len(PERSONAS))"
```

Expected: `12 7`. If it raises `KeyError`, add the missing key to `AGENT_CLASSES` rather than to `_ROWS`.

**T3.4 — `packages/core/studio.py`: widen `RUNNER_STOPS` to the merged table.** Replace

```python
RUNNER_STOPS = ("research", "script", "creative", "storyboard", "audio", "render")
```

with

```python
RUNNER_STOPS = tuple(STOP_POINTS)   # single source of truth; see orchestration/states.py
```

and add at the top of the file, after the other imports:

```python
from .orchestration.states import STOP_POINTS
```

Verify: `uv run python -c "from packages.core.studio import RUNNER_STOPS; print(RUNNER_STOPS)"` → `('research', 'script', 'creative', 'storyboard', 'audio', 'render', 'editorial', 'approval')`.

---

### Phase 4 — Python: resolve the rewritten core files, apex-first

For each file below, apex's version is the base. Copy it, then apply only the listed edit. This is the whole merge.

**T4.1 — Copy pixel's test suite in, minus the three that apex already owns.**

```bash
cd "C:/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI"
for f in activity api_providers api_schedule api_studio artifact_contracts budget_unlimited \
         personas pipeline_activity provider_settings router_studio run_cancel studio studio_config; do
  cp "../sf-pixel-ref/tests/test_$f.py" "tests/test_$f.py"
done
cp ../sf-pixel-ref/tests/conftest.py tests/conftest.py    # then re-apply apex's isolated_runtime (T4.2)
```

**Do not** copy pixel's `test_states.py`, `test_providers.py`, `test_provider_safety.py`, `test_scheduler.py`, `test_media.py`, `test_schemas.py`, `test_storyboard_normalize.py`, `test_pipeline_boundaries.py`, `test_pipeline_mock.py` — apex already has richer versions. Port the two genuinely new assertions by hand:

`tests/test_states.py` — append:

```python
def test_stop_points_cover_pipeline():
    from packages.core.orchestration.states import STOP_POINTS
    assert STOP_POINTS["storyboard"] is JobState.STORYBOARD_READY
    assert STOP_POINTS["render"] is JobState.TECHNICAL_QC
    assert {"research", "script", "creative", "storyboard", "audio", "render"} <= set(STOP_POINTS)
```

`tests/test_providers.py` — append pixel's HTTP-strategist test, adapted:

```python
def test_strategist_http_endpoint_is_used_when_configured(tmp_path, monkeypatch):
    from packages.core.providers.openai_compat import OpenAICompatProvider
    from packages.core.providers.router import ProviderRouter
    provider = OpenAICompatProvider(name="strategist-http", base_url="http://127.0.0.1:9/v1",
                                    api_key="", model="m", tier="strategist", timeout_s=1)
    router = ProviderRouter(worker_chain=[], strategist_chain=[provider], allow_mock_default=False)
    assert router._chain("strategist")[0].name == "strategist-http"
```

**T4.2 — Re-apply apex's `tests/conftest.py` isolation on top of pixel's.** Pixel's version adds `STUDIO_CONFIG`, which the merged suite needs. Merge the two by keeping pixel's file and appending apex's `sample_storyboard` fixture:

```python
@pytest.fixture()
def sample_storyboard():
    path = ROOT / "packages" / "video" / "src" / "sample" / "storyboard.ts"
    return path
```

Verify the isolation actually holds:

```bash
uv run pytest tests/test_api_studio.py -q     # → passes, and data/jobs is untouched
git status --short data/                      # → empty
```

**T4.3 — `packages/core/config.py`: take pixel's file whole. It is already HTTP-only.**

```bash
cp ../sf-pixel-ref/packages/core/config.py packages/core/config.py
```

Pixel's `config.py` has `_studio()`, `_sget()`, `_budget_limit()`, `_key_status()`, `StrategistConfig`, `max_daily_tokens: int | None`, and **no** `ClaudeCliConfig` / `CodexCliConfig`. That is the target shape — do not re-add them.

Verify — the three things the merged app needs, and the absence of the CLI:

```bash
uv run python -c "
from packages.core.config import get_settings as g
import dataclasses
s = g()
print('unlimited:', s.budget.unlimited)
print('strategist:', s.strategist.base_url[:26] or '(unset)')
names = {f.name for f in dataclasses.fields(s)}
print('cli fields:', sorted(n for n in names if n.endswith('_cli')) or 'none')
"
```

Expected:

```
unlimited: True
strategist: http://localhost:20128/v1
cli fields: none
```

**T4.3b — Fix the strategist env gap the merge exposes.** Apex reached the strategist through the CLI, so it never needed `STRATEGIST_BASE_URL`; pixel's `config.py` reads it. `.env` currently has **no** `STRATEGIST_*` keys, so without this the merged app builds a strategist chain of `[mock]` only — and a `live` run skips mock, so `CREATIVE_REVIEW` would die with `all providers failed` and the job would land `FAILED`.

Verified read-only: the local router answers `200` with 102 models, and `cx/gpt-6.1-sol` — the model already named in pixel's `studio.json` — is present.

```bash
cd "C:/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI"
grep -q '^STRATEGIST_BASE_URL=' .env || cat >> .env <<'EOF'
STRATEGIST_BASE_URL=http://localhost:20128/v1
STRATEGIST_MODEL=cx/gpt-6.1-sol
EOF
grep -n '^STRATEGIST' .env
```

Then prove the app sees a configured strategist:

```bash
uv run python -c "
from packages.core.config import get_settings
s = get_settings()
print('base_url:', s.strategist.base_url)
print('model:   ', s.strategist.model)
print('configured:', s.strategist.configured)
print('key_origin_mismatch:', s.strategist.key_origin_mismatch)
"
```

Expected:

```
base_url: http://localhost:20128/v1
model:    cx/gpt-6.1-sol
configured: True
key_origin_mismatch: False
```

`key_origin_mismatch: False` is load-bearing: `_key_status()` withholds the API key when the effective `base_url` host differs from the host in `STRATEGIST_BASE_URL`. Both are `localhost:20128` here, so the Hermes-managed key is used. If it prints `True`, the key is empty and every strategist call 401s — reconcile the two URLs before continuing.

**T4.3c — Update `.env.example` so the next machine is not silently broken.** Append the same two keys to `.env.example` (which is tracked), because `.env` is not:

```bash
grep -q '^STRATEGIST_BASE_URL=' .env.example || cat >> .env.example <<'EOF'

# ---- Strategist (HTTP only; the CLI adapters were retired) ----
STRATEGIST_BASE_URL=http://localhost:20128/v1
STRATEGIST_MODEL=cx/gpt-6.1-sol
EOF
grep -n '^STRATEGIST' .env.example
```

Expected: two matching lines in `.env.example`.

**T4.4 — `packages/core/providers/router.py`: take pixel's file whole.**

```bash
cp ../sf-pixel-ref/packages/core/providers/router.py packages/core/providers/router.py
```

Pixel's router already has everything the merge needs: `None`-safe `_check_budget`, the `studio.agents.get(agent)` override block (prompt substitution plus `copy.deepcopy` before applying model/temperature), `_prov_temperature()`, and a strategist chain of `[strategist-http?, mock]` with no CLI imports. Nothing to re-add.

**T4.5 — Delete the CLI adapters and their config surface.** This is the HTTP-only decision, made concrete.

```bash
cd "C:/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI"
git rm packages/core/providers/claude_cli.py packages/core/providers/codex_cli.py
git rm tests/test_codex_cli.py
git show HEAD:packages/core/providers/__init__.py >/dev/null   # for reference only
cp ../sf-pixel-ref/packages/core/providers/__init__.py packages/core/providers/__init__.py
cp ../sf-pixel-ref/scripts/probe_providers.py scripts/probe_providers.py
```

Then remove the two now-dead tests from apex's suite. In `tests/test_providers.py`, delete the whole `test_claude_cli_healthy_probe` function and its `from packages.core.providers.claude_cli import ClaudeCliProvider` import. In `tests/test_provider_safety.py`, delete `test_claude_completion_disables_tools_and_session_storage` (lines 23–40).

Verify — no CLI reference survives in code, and the removal is deliberate rather than accidental:

```bash
grep -rn "ClaudeCliProvider\|CodexCliProvider\|claude_cli\|codex_cli" \
  packages/ apps/ scripts/ tests/ --include=*.py || echo "CLI fully retired"
uv run pytest tests/test_providers.py tests/test_provider_safety.py tests/test_router_studio.py tests/test_provider_settings.py -q
```

Expected: `CLI fully retired`, then `25 passed` (4 + 4 + 4 + 12 + the shared helpers — read the actual number, but there must be **no** failures and no import errors).

**T4.6 — Add pixel's regression test for the retirement.** Append to `tests/test_providers.py`:

```python
def test_cli_retired_but_old_studio_snapshot_still_loads(tmp_path, monkeypatch):
    """Rollback to a snapshot written before the CLI was retired must still work.

    `studio.py` drops the retired `strategist_cli` key before validation, so a
    history file from the old build loads instead of failing `extra=forbid`.
    """
    from packages.core.studio import StudioConfig

    legacy = {"version": 1, "providers": {"strategist_cli": {"enabled": True}},
              "runner": {"default_mode": "mock", "default_stop": "storyboard"}}
    config = StudioConfig.model_validate(legacy)
    assert not hasattr(config.providers, "strategist_cli")
    assert config.runner.default_stop == "storyboard"
```

Run it → passes against pixel's `studio.py` (T3.4 already copied it). If it fails with `extra_forbidden`, the `_drop_retired_cli` validator was lost in a copy — restore it from `../sf-pixel-ref/packages/core/studio.py`.

**T4.7 — `packages/core/artifacts.py`: apex base + pixel's lenient review sections.**

```bash
cp ../sf-pixel-ref/packages/core/artifacts.py packages/core/artifacts.py
```

Pixel's file is missing 8 apex contracts. Re-add them by taking apex's file and applying only pixel's `ReviewSection` / `FactualSection` change:

```bash
git show HEAD:packages/core/artifacts.py > packages/core/artifacts.py
```

Then replace apex's two section classes (lines 43–50) with:

```python
class ReviewSection(BaseModel):
    # Models often add their own notes beyond the contract. Unknown fields are
    # ignored rather than failing the whole review: the requested content is
    # still used, and one extra field must not throw away QC output.
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    passed: bool = Field(alias="pass")
    findings: list[str] = Field(default_factory=list)


class FactualSection(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    passed: bool = Field(alias="pass")
    unsupported_claims: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
```

Add `ConfigDict` to the pydantic import line. Verify:

```bash
uv run pytest tests/test_schemas.py tests/test_artifact_contracts.py tests/test_pipeline_mock.py -q
uv run python -c "
from packages.core.artifacts import ARTIFACT_MODELS as M
need={'verification.json','originality.json','approval.json','thumbnail.json','mix.json','publishing.json','editorial_qc.json'}
print(sorted(need-set(M)))"
```

Expected: tests pass; `[]`.

**T4.8 — `packages/core/prompts.py`: apex base + pixel's `DEFAULT_SYSTEM` map.**

```bash
git show HEAD:packages/core/prompts.py > packages/core/prompts.py
```

Append at the end of the file:

```python
#: Default system prompt per editable agent, so the Studio editor can show what
#: a blank override falls back to. Presentation only — never a second source of truth.
DEFAULT_SYSTEM: dict[str, str] = {
    "ResearchAgent": RESEARCH_SYSTEM,
    "TopicSelectionAgent": TOPIC_SYSTEM,
    "ScriptAgent": SCRIPT_SYSTEM,
    "CreativeDirectorAgent": CREATIVE_SYSTEM,
    "StoryboardAgent": STORYBOARD_SYSTEM,
    "QualityAgent": QUALITY_SYSTEM,
    "MetadataAgent": METADATA_SYSTEM,
}
```

Verify: `uv run python -c "from packages.core.prompts import DEFAULT_SYSTEM as d; print(len(d), 'illustras' in d['StoryboardAgent'])"` → `7 True`.

**T4.9 — `packages/core/providers/__init__.py`: pixel's HTTP-only exports.**

```bash
cp ../sf-pixel-ref/packages/core/providers/__init__.py packages/core/providers/__init__.py
```

Pixel's version exports `OpenAICompatProvider`, `MockProvider`, `ProviderRouter`, `build_router` and the base types — no CLI. Verify:

```bash
uv run python -c "import packages.core.providers as p; print(sorted(n for n in p.__all__ if 'Cli' in n) or 'no CLI exports')"
```

Expected: `no CLI exports`.

---

### Phase 5 — Python: one runner, one telemetry fan-out

**T5.1 — Write the fan-out adapter.** Create `packages/core/observability/telemetry.py`:

```python
"""One runner call site, two readers.

The event log answers "what is happening across all jobs" (SSE floor, 12 roles);
the job payload answers "what is this job's agent doing right now" (job detail,
pixel office). Both are real telemetry from the same stage boundary — this class
exists so the runner never has to remember to write twice.
"""
from __future__ import annotations

from ..activity import ActivityReporter
from .lifecycle import RunObserver


class RunTelemetry:
    def __init__(self, store, job_id: str, *, source: str, activity_token: str) -> None:
        self.events = RunObserver(store, job_id, source=source)
        self.activity = ActivityReporter(store, job_id, activity_token)

    def start(self) -> None:
        self.events.start()
        self.activity.begin("FactoryOrchestrator", "PREFLIGHT")

    def stage(self, agent: str, stage: str, *, reused: bool) -> None:
        self.events.started(stage)
        self.activity.begin(agent, stage, reused=reused)

    def done(self, agent: str, stage: str, artifact: str, *, reused: bool) -> None:
        self.events.completed(stage, reused=reused)
        self.activity.complete(agent, artifact)

    def failed(self, *, error_type: str, blocked: bool = False) -> None:
        self.events.failed(blocked=blocked, error_type=error_type)

    def finish(self, state: str, outcome: str) -> None:
        self.events.finish(state)
        self.activity.finish(outcome)
```

**T5.2 — Test first.** Create `tests/test_telemetry_fanout.py`:

```python
from packages.core.observability.telemetry import RunTelemetry
from packages.core.orchestration import JobStore


def test_one_stage_boundary_writes_both_readers(tmp_path):
    store = JobStore(tmp_path / "factory.db", tmp_path / "jobs")
    job = store.create(title="fanout")
    telemetry = RunTelemetry(store, job.id, source="mock", activity_token="c" * 32)
    telemetry.start()
    telemetry.stage("ScriptAgent", "SCRIPT_GENERATED", reused=False)
    telemetry.done("ScriptAgent", "SCRIPT_GENERATED", "script.json", reused=False)
    telemetry.finish("SCRIPT_GENERATED", "done")

    activity = store.get(job.id).payload["studio_activity"]
    assert activity["agent"] == "ScriptAgent"
    assert activity["completed"]["ScriptAgent"] == "script.json"
    assert activity["phase"] == "done"
    assert any(e["agent_id"] == "ScriptAgent" for e in store.events(job.id))
```

Run → fails on the missing module; create T5.1; re-run → `1 passed`.

**T5.3 — Wire the fan-out into `packages/core/pipeline/runner.py`.** Keep apex's stage list (11 stages) and leases. Change the signature and the four call sites:

```python
    def run(self, job_id: str, *, stop_at: JobState = JobState.STORYBOARD_READY,
            cancelled=None, activity_token: str | None = None) -> PipelineReport:
```

Replace `observer = self.observer = RunObserver(...)` + `observer.start()` with:

```python
                    telemetry = self.observer = RunTelemetry(
                        self.store, job_id,
                        source="mock" if self.force_mock else "production",
                        activity_token=activity_token or uuid4().hex,
                    )
                    telemetry.start()
```

Replace the `observer.started(state.value)` line with:

```python
                            telemetry.stage(STAGE_AGENTS[state.value], state.value, reused=reused)
```

Replace `observer.completed(state.value, reused=reused)` with:

```python
                        telemetry.done(STAGE_AGENTS[state.value], state.value, artifact, reused=reused)
```

Replace `observer.failed(...)` / `observer.finish(...)` with `telemetry.failed(...)` / `telemetry.finish(...)` and add the cancellation check inside the stage loop, right after the `CANCELLED` check:

```python
                        if cancelled is not None and callable(cancelled) and cancelled():
                            report.blocked_reason = "dibatalkan operator"
                            break
```

Add the imports:

```python
from uuid import uuid4

from ..activity import STAGE_AGENTS
from ..observability.telemetry import RunTelemetry
```

Verify:

```bash
uv run pytest tests/test_pipeline_mock.py tests/test_run_cancel.py tests/test_pipeline_activity.py tests/test_pipeline_boundaries.py tests/test_studio_lifecycle.py -q
```

Expected: all pass. `test_run_cancel.py` proves `cancelled=` works; `test_pipeline_activity.py` proves `studio_activity` is written.

---

### Phase 6 — Python: one API app

**T6.1 — Keep apex's `apps/api/main.py` as the base.** It already exposes `create_app(store=None)` (required by `tests/test_studio_api.py`, `test_studio_decisions.py`, `test_studio_stream_live.py`) and all apex routes. Do not rewrite it.

**T6.2 — Append pixel's route groups.** Insert the following into `create_app`, immediately before `return app` (apex line 233). Copy the bodies **verbatim** from the reference file to avoid transcription drift:

```bash
sed -n '50,90p;   ../sf-pixel-ref/apps/api/app.py   # auth + helpers
sed -n '158,504p; ../sf-pixel-ref/apps/api/app.py   # studio config, jobs, usage, providers, schedule
```

Add above `create_app` (module level):

```python
from packages.core.pipeline import PipelineRunner
from packages.core.personas import PERSONAS, TEAM
from packages.core.prompts import DEFAULT_SYSTEM
from packages.core.providers.router import UsageTracker, build_router
from packages.core.scheduler import Scheduler, status_payload
from packages.core.studio import (
    AGENT_KEYS, StudioConfig, StudioConfigError, load_history, load_studio,
    rollback_studio, save_studio, studio_path,
)

RUNS: dict[str, dict[str, Any]] = {}
RUN_LOCK = threading.Lock()
CANCELLED_RUNS: set[str] = set()
SCHEDULER: Scheduler | None = None
SCHEDULER_LOCK = threading.Lock()
```

Then inside `create_app`, before `return app`, paste pixel's route bodies with **one change**: `_store()` must reuse the injected store so tests stay isolated.

```python
    def _store() -> JobStore:
        return job_store
```

Verify the route table is the union:

```bash
uv run python - <<'PY'
from apps.api.main import create_app
paths = sorted({r.path for r in create_app().routes})
need = {"/api/health", "/api/studio/snapshot", "/api/studio/stream", "/api/studio/schedule",
        "/api/studio", "/api/studio/history", "/api/studio/models", "/api/studio/rollback",
        "/api/jobs", "/api/jobs/{job_id}", "/api/jobs/{job_id}/run", "/api/jobs/{job_id}/cancel",
        "/api/jobs/{job_id}/artifact/{name}", "/api/jobs/{job_id}/approve",
        "/api/jobs/{job_id}/reject", "/api/jobs/{job_id}/video", "/api/jobs/{job_id}/thumbnail",
        "/api/usage/today", "/api/providers", "/api/providers/models",
        "/api/schedule", "/api/schedule/tick", "/api/schedule/apply", "/api/events"}
print("missing:", sorted(need - set(paths)))
PY
```

Expected: `missing: []`.

**T6.3 — Route the scheduler thread through the injected store.** Pixel's `_new_scheduler()` calls `_store()`; with T6.2 that is the injected store, so `tests/test_api_schedule.py` stops touching the operator's real DB. Verify:

```bash
uv run pytest tests/test_api_schedule.py tests/test_api_studio.py tests/test_api_providers.py -q
```

**T6.4 — Fix `test_api_studio.py`'s `_client`.** It monkeypatches `apps.api.app.JOBS_DIR`, which no longer exists. Replace the helper body with:

```python
def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio.json"))
    monkeypatch.delenv("STUDIO_TOKEN", raising=False)
    from packages.core.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    from packages.core.orchestration import JobStore
    store = JobStore(tmp_path / "jobs" / "factory.db", tmp_path / "jobs")
    return TestClient(create_app(store=store), base_url="http://localhost",
                      client=("127.0.0.1", 45000)), tmp_path / "studio.json"
```

Verify: `uv run pytest tests/test_api_studio.py -q` → passes; `git status --short data/` → empty.

**T6.5 — Point the launcher at the merged app.**

```bash
cp ../sf-pixel-ref/scripts/run_studio_api.py scripts/run_studio_api.py
```

Edit the default port `8000` → `8018` and the app path to `"apps.api.server:app"`. Verify:

```bash
uv run python scripts/run_studio_api.py &   # then:
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8018/api/health   # → 200
kill %1
```

**T6.6 — `apps/__init__.py`.** Pixel ships it; apex lacks it. Keep it (`cp ../sf-pixel-ref/apps/__init__.py apps/__init__.py`).

**T6.7 — Full Python gate.**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: **`≈ 552 passed`**, computed as:

| Component | Count |
|---|---|
| Apex baseline | 480 |
| minus CLI tests removed (T4.5: 6 + 1 + 1) | −8 |
| plus pixel's ported test files (T4.1) | +76 |
| plus this plan's new tests (T2.2, T2.5, T5.2, T4.6) | +4 |
| minus double-counted (pixel's `test_states`/`test_providers`/`test_scheduler` were **not** copied) | 0 |
| **Expected** | **552** |

Read the real number rather than trusting the arithmetic; what matters is **0 failed, 0 errors**. If it lands within ±5 of 552, the port is complete. A number near 480 means pixel's tests did not get copied; a number near 560 with failures means a copy clobbered an apex module. Record the exact figure in `docs/PLANS.md` (T8.2).

Also confirm the CLI really is gone from the suite:

```bash
uv run pytest --collect-only -q 2>/dev/null | grep -ci "claude\|codex" || echo "0 CLI tests collected"
```

Expected: `0 CLI tests collected`.

---

### Phase 7 — Dashboard: re-attach the two features pixel lacks

**T7.1 — Approval controls on the job detail page.** Edit `apps/dashboard/src/app/jobs/[id]/page.tsx`. Add the imports:

```tsx
import { approveJob, rejectJob, DecisionRefused } from "@/lib/decisions";
```

Create `apps/dashboard/src/lib/decisions.ts`:

```ts
export class DecisionRefused extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

async function post<T>(path: string, body: object): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = (await response.json().catch(() => null))?.detail;
    throw new DecisionRefused(response.status,
      typeof detail === "string" ? detail : `Permintaan ditolak (${response.status})`);
  }
  return (await response.json()) as T;
}

export function approveJob(jobId: string, operator: string): Promise<{ state: string }> {
  return post(`/api/jobs/${jobId}/approve`, { operator });
}

export function rejectJob(jobId: string, reason: string, operator: string): Promise<{ state: string }> {
  return post(`/api/jobs/${jobId}/reject`, { operator, reason });
}
```

Then, inside the page component, above the `return`:

```tsx
  const [operator, setOperator] = useState("");
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const pending = data?.record.state === "READY_FOR_APPROVAL";

  const decide = async (kind: "approve" | "reject") => {
    if (!operator.trim()) { setDecisionError("Isi nama operator dulu."); return; }
    if (kind === "reject" && !reason.trim()) { setDecisionError("Penolakan butuh alasan."); return; }
    setDeciding(true); setDecisionError(null);
    try {
      if (kind === "approve") await approveJob(id, operator.trim());
      else await rejectJob(id, reason.trim(), operator.trim());
      await load();
    } catch (err) {
      setDecisionError(err instanceof DecisionRefused ? err.message : "Keputusan gagal dikirim.");
    } finally { setDeciding(false); }
  };
```

and insert this section just before the artifact section:

```tsx
      {pending && (
        <section className="px-frame" aria-label="Keputusan operator" data-testid="approval-controls">
          <h2 className="mb-4 text-lg font-medium">Keputusan operator</h2>
          <div className="flex flex-wrap items-end gap-3">
            <label className="block space-y-1">
              <span className="text-xs text-zinc-500">Operator</span>
              <input value={operator} maxLength={80} onChange={(e) => setOperator(e.target.value)}
                placeholder="siapa yang memutuskan" data-testid="operator-name"
                className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm" />
            </label>
            <button onClick={() => void decide("approve")} disabled={deciding}
              data-testid="approve" className="px-button" data-primary="true">Setujui</button>
            <button onClick={() => setRejecting((v) => !v)} disabled={deciding}
              data-testid="reject" className="px-button">Tolak</button>
          </div>
          {rejecting && (
            <div className="mt-3 space-y-2">
              <textarea value={reason} maxLength={500} rows={2} onChange={(e) => setReason(e.target.value)}
                placeholder="wajib: apa yang harus diperbaiki" data-testid="reject-reason"
                className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm" />
              <button onClick={() => void decide("reject")} disabled={deciding}
                data-testid="reject-confirm" className="px-button">Kirim penolakan</button>
            </div>
          )}
          {decisionError && <p role="alert" data-testid="decision-error" className="mt-3 text-xs text-rose-400">{decisionError}</p>}
        </section>
      )}
```

Verify: `cd apps/dashboard && npm run typecheck` → silent.

**T7.2 — Jadwal page.** Create `apps/dashboard/src/app/schedule/page.tsx` that renders apex's projection:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import type { ProductionSchedule, ScheduleStatus } from "@/lib/contracts";
import { fetchSchedule } from "@/lib/api";
import { ErrorState } from "@/components/states";

const FILTERS: (ScheduleStatus | "SEMUA")[] = ["SEMUA", "ON GOING", "RESEARCHING", "UPCOMING", "SELESAI", "GAGAL", "TERTAHAN"];

export default function SchedulePage() {
  const [schedule, setSchedule] = useState<ProductionSchedule | null>(null);
  const [filter, setFilter] = useState<ScheduleStatus | "SEMUA">("SEMUA");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try { setSchedule(await fetchSchedule()); }
    catch (err) { setError(err instanceof Error ? err.message : "Jadwal gagal dimuat."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (error) return <ErrorState title="Jadwal tidak bisa dimuat" message={error} onRetry={() => void load()} />;
  if (loading) return <p role="status" className="text-sm text-zinc-500">Memuat jadwal…</p>;

  const entries = (schedule?.entries ?? []).filter((e) => filter === "SEMUA" || e.status === filter);
  return (
    <div className="space-y-6">
      <header className="px-page-header">
        <div>
          <p className="px-eyebrow">JADWAL PRODUKSI</p>
          <h1 className="text-2xl font-semibold tracking-tight">Jadwal</h1>
          <p className="text-sm text-zinc-400">Proyeksi status dari state job yang tersimpan. Tidak memulai apa pun.</p>
        </div>
        <button onClick={() => void load()} className="px-button">Muat ulang</button>
      </header>
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f}
            className={`rounded-md border px-3 py-1 text-xs ${filter === f ? "border-sky-600 bg-sky-950 text-sky-200" : "border-zinc-700 text-zinc-400"}`}>
            {f}{f !== "SEMUA" ? ` ${schedule?.counts?.[f] ?? 0}` : ` ${schedule?.total ?? 0}`}
          </button>
        ))}
      </div>
      <ul className="space-y-2">
        {entries.length === 0 && <li className="text-sm text-zinc-500">Tidak ada job pada status ini.</li>}
        {entries.map((e) => (
          <li key={e.job_id} className="px-frame flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="min-w-0 break-words">{e.title}</span>
            <span className="flex flex-wrap items-center gap-2 text-xs text-zinc-400">
              <span className="px-chip">{e.status}</span>
              <span>{e.stage_label}</span>
              <span>{e.next_action}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

**T7.3 — Copy apex's schedule contract into the pixel lib.** Append `apps/dashboard/src/lib/contracts.ts` to the new file of the same name:

```bash
git show HEAD:apps/dashboard/src/lib/contracts.ts > apps/dashboard/src/lib/contracts.ts
```

Keep only the `SCHEDULE_STATUSES` / `ScheduleStatus` / `ScheduleEntry` / `ProductionSchedule` block (lines 33–49 of that file) — pixel's `lib/api.ts` owns everything else.

**T7.4 — Add `fetchSchedule` to pixel's API client.** Append to `apps/dashboard/src/lib/api.ts`:

```ts
import type { ProductionSchedule } from "./contracts";

export async function fetchSchedule(): Promise<ProductionSchedule> {
  const response = await fetch("/api/studio/schedule", { cache: "no-store" });
  if (!response.ok) throw new Error(`Jadwal tidak tersedia (${response.status})`);
  return (await response.json()) as ProductionSchedule;
}
```

**T7.5 — Add the nav entry.** In `apps/dashboard/src/components/Sidebar.tsx`, insert into `NAV` after the Jobs entry:

```tsx
  { href: "/schedule", label: "Jadwal", hint: "Produksi berjalan", glyph: "M2 3h12v2H2z M2 7h9v2H2z M2 11h12v2H2z" },
```

**T7.6 — Prove the shell still builds and the unit tests pass.**

```bash
cd apps/dashboard && npm run typecheck && npm test
```

Expected: `tsc` silent; vitest reports `Test Files  8 passed` (or whatever the count is — record it) and `0 failed`.

---

### Phase 8 — Docs, plans index, and the `.gitignore` trap

**T8.1 — One studio doc.** Merge pixel's `docs/PIXEL_STUDIO.md` into apex's `docs/STUDIO.md`: keep apex's event-bridge table and append pixel's "Konfigurasi / Riwayat & rollback / Batasan" sections, then add a section titled **"Lima konsep 'schedule'"** containing the five-row table from *Architecture* above. Delete `docs/PIXEL_STUDIO.md` (`git rm docs/PIXEL_STUDIO.md`).

While merging, correct the rollback paragraph: `config/studio-history/` is **gitignored**, so the doc must not claim the snapshots are committed.

Verify: `grep -c "Lima konsep" docs/STUDIO.md` → `1`; `grep -c "di-commit ke git" docs/STUDIO.md` → `0`.

**T8.2 — Create the single plan index.** Write `docs/PLANS.md`:

```markdown
# Plans and specs — single index

Every plan in this repo is listed here. If a plan is not in this table, it is
not a plan this project is following.

| Plan | Location | Status | Scope |
|---|---|---|---|
| Illustrated animation studio | `.hermes/plans/2026-10-21_164433-illustrated-animation-studio.md` | implemented | procedural vector illustration renderer |
| Merge Pixel Studio into one studio | `.hermes/plans/2026-10-22_205902-merge-pixel-studio.md` | in progress | UI/UX + config layer onto the illustrated pipeline |
| Pixel production studio (original) | `docs/superpowers/plans/2026-10-20-pixel-production-studio.md` | superseded by `docs/STUDIO.md` | first dashboard milestone |
| Production completion | `docs/superpowers/plans/2026-10-21-production-completion.md` | implemented | publishing, plans, leases, templates |
| Pixel production studio design | `docs/superpowers/specs/2026-10-20-pixel-production-studio-design.md` | superseded by `apps/dashboard/design/DESIGN.md` | original UI contract |

## Conventions

- New plans go in `.hermes/plans/YYYY-MM-DD_HHMMSS-<slug>.md` and get a row here.
- `docs/superpowers/` holds history only. Do not add new files there.
- Test baselines: Python `<fill in from T6.7>`, dashboard vitest `<fill in from T7.6>`,
  Playwright `<fill in from T9.4>`.
```

Fill the three placeholders with the numbers you measured. Verify: `grep -c "^|" docs/PLANS.md` → `7`.

**T8.3 — Fix `.gitignore` so plans stay tracked.** Pixel's file ignores `.hermes/` wholesale; that would orphan the 100 KB illustrated plan. Write the merged file:

```gitignore
node_modules/
.venv/
__pycache__/
*.pyc
.env
.env.*
!.env.example
*.pem
*.key
config/client_secret*.json
config/token*.json
data/renders/*
data/jobs/*
data/assets/*
data/*.db*
!data/renders/.gitkeep
!data/jobs/.gitkeep
!data/assets/.gitkeep
dist/
build/
out/
.next/
*.log
.remotion/
tsconfig.tsbuildinfo
.pytest_cache/
.ruff_cache/
packages/video/public/jobs/
apps/dashboard/playwright-report/
apps/dashboard/test-results/

# Agent scratch. The plan inbox is the one tracked exception: plans are
# deliverables, not scratch (see docs/PLANS.md).
.hermes/*
!.hermes/plans/

# Operator-authored studio config (no secrets) and its version history.
config/studio.json
config/studio.json.tmp
config/studio-history/
```

Verify — the plan must still be tracked and a new file must be visible to git:

```bash
git check-ignore -v .hermes/plans/2026-10-21_164433-illustrated-animation-studio.md || echo "tracked OK"
git status --short .hermes/                          # → shows this plan as untracked
```

**T8.4 — Update the root `AGENTS.md`** for the merged reality. Replace the provider-policy row and add three sections. Exact edits:

Replace the `ClaudeCliProvider` row in §9 with:

```markdown
| `StrategistHttpProvider` | OpenAI-compatible HTTP | the only strategist path; endpoint + model editable from the web UI |
```

and add one line under that table:

```markdown
The `claude`/`codex` CLI adapters were retired in the merge. A CLI can report
healthy while its model is dead, which produced green providers that failed
every call. Do not reintroduce them; add another HTTP endpoint instead.
```

Append after §12:

```markdown
## 12b. Studio configuration layer

`config/studio.json` (gitignored, no secrets) overrides environment for
non-secret runtime values: per-agent model/temperature/prompt, budget,
production parameters, provider endpoints, runner defaults and the recurring
schedule. Precedence: `studio.json` > environment > built-in default.
Versioned history lives in `config/studio-history/` — also gitignored, so it is
a local rollback buffer, not a shared audit trail. Rollback from the UI reads
those local files only.

## 12c. Five things called "schedule"

Do not consolidate these; they answer different questions.

| Concept | Module | Consumer |
|---|---|---|
| Cross-job event feed | `packages/core/observability/` | `/api/studio/stream` |
| Per-job activity | `packages/core/activity.py` | `/api/jobs/{id}` |
| Recurring production control | `packages/core/scheduler.py` | `/api/schedule*` |
| Schedule projection | `packages/core/observability/schedule.py` | `/api/studio/schedule` |
| 7-day plans + dispatch leases | `packages/core/orchestration/{planner,scheduler}.py` | `scripts/schedule.py` |

## 12d. One port, one entry point

`http://127.0.0.1:3018` is the only address an operator types. The dashboard
rewrites `/api/*` to the API on `127.0.0.1:8018`, which binds loopback and is
internal: it is never bookmarked, never opened in a browser, and never appears
in a launcher. Ports 3000, 3201 and 8000 are retired.

## 12e. Where plans live

`.hermes/plans/` is the only inbox; `docs/PLANS.md` is the index. `docs/superpowers/`
is history and takes no new files.
```

**T8.5 — `.env.example`: keep the merged version, do not re-copy it.** T4.3c already appended the `STRATEGIST_*` keys to the pixel-sourced `.env.example`. Copying pixel's file again here would silently delete them.

```bash
grep -n "STUDIO_API_ORIGIN\|STUDIO_HOST\|STUDIO_TOKEN" .env.example
grep -n "^STRATEGIST" .env.example
grep -n "CLAUDE_CLI\|CODEX_CLI" .env.example || echo "no CLI vars"
```

Expected: three `STUDIO_*` lines, two `STRATEGIST_*` lines, then `no CLI vars`. If the `STRATEGIST_*` lines are missing, re-run T4.3c — nothing else in Phase 8 touches this file.

---

### Phase 9 — Verification gates

**T9.1 — Python.**

```bash
cd "C:/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI"
uv run pytest -q 2>&1 | tail -3
```

Expected: `≥ 480 passed`, `0 failed`. Any failure is a merge defect — do not lower the gate.

**T9.2 — Secrets and schemas.**

```bash
uv run python scripts/check_secrets.py
uv run python scripts/export_schemas.py && git diff --stat config/schemas/ || echo "schemas stable"
```

Expected: no secret findings; either no schema diff or only the intended additions.

**T9.3 — Renderer smoke (unchanged by the merge, must stay green).**

```bash
cd packages/video && npx tsc --noEmit && node scripts/still-smoke.mjs 2>&1 | tail -5
```

Expected: `tsc` silent; the smoke prints one success line per template (7 templates).

**T9.4 — Dashboard end-to-end.** Start the API first, then Playwright:

```bash
cd "C:/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI"
uv run uvicorn apps.api.server:app --host 127.0.0.1 --port 8018 &
cd apps/dashboard && npx playwright test 2>&1 | tail -12
```

Expected: all specs pass, including `geometry.spec.ts` (every avatar inside its station, twelve distinct accessory shapes) and the 5-width axe sweep. The suite stubs `/api/**`, so it cannot reach the real DB.

**T9.5 — Live smoke against real data.**

```bash
curl -s http://127.0.0.1:8018/api/health | head -c 200; echo
curl -s "http://127.0.0.1:8018/api/studio/snapshot" | python -c "import json,sys; d=json.load(sys.stdin); print(len(d['agents']), len(d['jobs']))"
curl -s http://127.0.0.1:8018/api/schedule | head -c 200; echo
```

Expected: `{"status":"ok",...}`; `12 <n>` where `n` is the merged job count (apex 13 + pixel 18 ≈ 31, minus any overlap); a schedule payload with `"running": false`.

**T9.6 — Migrate pixel's runtime data in.** Dry-run first, then copy without clobbering:

```bash
rsync -avn "$HOME/sf-pixel-backup/data/jobs/" data/jobs/ | tail -5     # dry run
rsync -av  "$HOME/sf-pixel-backup/data/jobs/" data/jobs/
cp -n "$HOME/sf-pixel-backup/config/studio.json" config/studio.json 2>/dev/null || true
cp -rn "$HOME/sf-pixel-backup/config/studio-history/." config/studio-history/ 2>/dev/null || true
```

Verify: `ls data/jobs | wc -l` ≥ 31; `curl -s http://127.0.0.1:8018/api/jobs | python -c "import json,sys;print(len(json.load(sys.stdin)['jobs']))"` matches.

**T9.7 — Final commit and cleanup.**

```bash
cd "C:/Users/cubeb/OneDrive/Documents/coding/projects/ShortsFactoryAI"
git add -A
git commit -m "feat(studio): merge Pixel Studio UI onto the illustrated pipeline

One FastAPI app (create_app keeps the injectable store), one dashboard on 3018
with the Pixel Studio shell: sidebar, pixel office, studio/jobs/providers/usage
pages, plus the approval gate and the read-only schedule projection.

Core files resolved apex-first; pixel's studio.json config layer, personas,
activity telemetry and recurring-schedule control layered on top. Strategist
chain is HTTP (operator-editable) -> Claude CLI -> Codex CLI -> mock.

Plans now have one index: docs/PLANS.md."
git worktree remove ../sf-pixel-ref
git log --oneline -1
```

---

## Tests / validation

| Gate | Command | Expected |
|---|---|---|
| Python suite | `uv run pytest -q` | `≈ 552 passed`, 0 failed |
| CLI retired | `uv run pytest --collect-only -q \| grep -ci "claude\|codex"` | `0` |
| Stop points | `uv run pytest tests/test_stop_points.py -q` | 1 passed |
| Activity persistence | `uv run pytest tests/test_jobstore_activity.py -q` | 2 passed |
| Telemetry fan-out | `uv run pytest tests/test_telemetry_fanout.py -q` | 1 passed |
| Route union | T6.2 snippet | `missing: []` |
| Dashboard typecheck | `cd apps/dashboard && npm run typecheck` | silent |
| Dashboard unit | `npm test` | 0 failed |
| Dashboard e2e + axe | `npx playwright test` | all pass, 5 widths |
| Renderer | `cd packages/video && npx tsc --noEmit && node scripts/still-smoke.mjs` | silent + 7 templates |
| Secrets | `uv run python scripts/check_secrets.py` | clean |
| Strategist wired | T4.3b python check | `configured: True`, `key_origin_mismatch: False` |
| Live API | T9.5 curls | `12` agents, `ok`, `running:false` |

TDD discipline per task: T2.2, T2.5, T5.2 write the failing test first, run it to see the exact failure, then implement. Every task ends with a commit or is folded into the phase commit at T9.7 — never leave the tree half-merged across phases.

---

## Risks, tradeoffs, and open questions

**Risks**

1. **The pixel branch commit is unusable as-is.** `apps/api/app.py` at `8543ea2` has `***` where `|` belongs. Any `git checkout feature/pixel-studio` restores broken Python. Mitigation: T0.6 copies the good working-tree file immediately after checkout, and every later step reads from `../sf-pixel-ref`. If that worktree is ever deleted before T0.1, the good copy is gone.
2. **The Orca worktree has no `.git`.** It is unrecoverable as a git checkout; only its *content* is salvageable. `git worktree repair` cannot help. Accept that and treat it as a plain directory; remove it from Orca's list manually afterwards.
3. **HTTP-only makes the strategist a single point of failure.** `AGENTS.md §12` records `claude` v2.1.303 as verified working; after T4.5 that safety net is gone. The local router at `localhost:20128` **is** alive (verified: `200`, 102 models, `cx/gpt-6.1-sol` present) but a live *completion* through it was not exercised in this session. Mitigation: T4.3b proves `configured: True` and `key_origin_mismatch: False`; T9.5's `/api/providers` call proves health. If the endpoint is down at run time the job lands `BLOCKED`/`FAILED` loudly rather than silently degrading — correct, but it means one process is now load-bearing for every stage.
4. **Two schedulers, two telemetry writers.** Deliberate, documented in `AGENTS.md §12c` and `docs/STUDIO.md`. The cost is one extra DB table pair and one extra payload key; the benefit is that neither consumer has to be rewritten. If someone later "unifies" them, `test_api_schedule.py` and `test_studio_stream_live.py` will both fail — that is the intended tripwire.
5. **`data/` merge is not transactional.** `rsync` without `--delete` and `cp -n` cannot lose data, but a half-copied job directory would make `validate_artifact` raise on that job. Mitigation: dry run first (T9.6), and the snapshot in T0.1 is the rollback.
6. **Port 3000 and 8000 will keep coming back.** `npm run dev` in the Orca worktree and `run_studio_api.py`'s old default both used them. After the merge, only `3018`/`8018` are documented; if a stray server reappears, `netstat -ano | grep -E ":(3000|8000)\s+.*LISTENING"` names the PID.

**Tradeoffs**

- **Pixel's polling floor beats apex's SSE for the UI, for now.** Apex's SSE is strictly better engineering (cursor-based, no poll), but wiring it into the pixel office would mean rewriting `geometry.spec.ts` and `studio.spec.ts`, which are the tests that actually prove the avatars render. Decision: keep the SSE *endpoint and its 6 test files*, keep pixel's polling floor, and leave "move the floor to SSE" as a named follow-up. Cost: 2.5 s latency and a small amount of duplicate transport code.
- **`try_lock` and leases both survive.** Apex's `LeaseKeeper` is used by the runner; pixel's `try_lock` remains in the store because pixel's `test_run_cancel.py` and the scheduler's staleness check use it. Removing either is a separate, riskier refactor.
- **Pixel's `activity.py` is kept rather than folded into `observability/`.** It is ~90 lines and already tested twice (`test_activity.py`, `test_pipeline_activity.py`); folding it in would mean re-deriving the `studio_activity` payload the UI reads.
- **Deleting 8 CLI tests lowers the raw test count.** The suite gets *narrower* before it gets wider. That is the point of the decision, but it means the number `552` is not comparable to apex's `480` as a coverage measure — 8 of those tests were guarding an adapter that no longer ships.

**Decisions already taken (do not re-litigate)**

| Question | Answer |
|---|---|
| `config/studio-history/` in git? | **No.** Ignored. Local rollback buffer only. |
| Delete `docs/superpowers/`? | **No.** Kept as history; `docs/PLANS.md` indexes it. |
| Strategist provider | **HTTP only.** CLI adapters deleted in T4.5. |
| How many ports? | **One** operator-facing port: `3018`. `8018` is internal loopback only. |

**Open questions**

1. **Has a live strategist completion been proven?** T4.3b proves configuration and T9.5 proves health, but neither sends a real completion. Run `uv run python scripts/probe_providers.py --live` once after Phase 4 to close that gap — it is the only step in this plan that spends money.
2. **Should `8018` be renamed?** It is internal now, so the number is arbitrary. Leaving it means apex's `playwright.config.ts`, `start-studio.bat` and `docs/STUDIO.md` keep working unedited. Renaming costs three files and buys nothing.

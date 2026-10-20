# Pixel Production Studio — Additive Proof of Concept

## Intent and scope

Implement the operator's supplied Pixel Production Studio brief inside the existing Shorts Factory AI monorepo. Python remains authoritative; logical agents are not extra LLM processes. Preserve provider routing, the job state allow-list, persisted artifacts, rendering, and approval authority. The first deliverable is a real local dashboard with an instrumented worker/event/SSE vertical slice, not an image of a dashboard. Existing global Hermes and Orca installations remain untouched.

## Audit decision / ADR-001

Pixel Agents release v1.5.0 resolves to `b1bafd02896d90d83457266575a1e8e5011ce997`. Its provider registry contains Claude only. PR #399 (`df2ee08fa6f4e43c032fbe8edaabba6cc86752a0`) remains open and unmerged at audit time. The standalone includes hooks, persistence, transcript discovery, and optional PTY/control features that this domain does not need. MIT code is reusable with notice, but bundled font and icon licenses differ; optional external packs have their own terms.

Choose an original lightweight SVG/CSS pixel office rather than installing the standalone or carrying its server, installer, or token protocol. Trade-off: fewer office-editor/customization features, but no extra orchestration runtime, global hook writes, PTY, or redistributed third-party art/font bundle. Six original characters group the twelve required logical roles. All information uses readable system fonts. A separate audit records immutable sources and runtime limitations.

## Data flow / ADR-002

`PipelineRunner -> StudioEventStore (same SQLite/WAL file as jobs) -> StudioService -> FastAPI -> same-origin Next.js proxy -> SSE -> office/inspector/queue/review`.

The new SQLite schema is additive and versioned. The existing `jobs` and `job_events` tables and state machine remain unchanged. Each event has an increasing integer `event_id`, canonical `job_id`, one of the twelve `agent_id` values, typed event/status/source, UTC timestamp, safe description, and optional progress/model/stage/run identifier. A monotonic cursor and transactionally consistent snapshots support replay and reconnect. History is bounded per response, not silently lost from storage.

A stage emits working only immediately before real execution, and completed only after artifact validation. Resume emits artifact-reused without a fake working phase. Render progress comes exclusively from actual Remotion rendered/encoded frame counters; 100% is reserved for validated output. A persisted worker lease/heartbeat makes interrupted work stale/waiting rather than working forever. Reconnect refreshes the snapshot and preserves history without duplicates.

## Public contract

All frontend requests use relative same-origin URLs, with no session token or API key:

- `GET /api/studio/snapshot?job_id=<optional canonical ID>&demo=<optional true>` -> `StudioSnapshot`.
- `GET /api/events?after=0&limit=100&job_id=<optional ID>&demo=<optional true>` -> `{events: StudioEvent[], cursor: number}`.
- `GET /api/events/stream?after=<cursor>&demo=<optional true>` -> SSE `snapshot` messages containing `StudioSnapshot`; individual `studio` events have the same `StudioEvent` shape. Honor `Last-Event-ID` and query cursor. Periodic snapshots also refresh lease freshness when no stage event arrives.
- `GET /api/jobs/<id>/video?demo=<optional true>` -> only a confined, existing, hash-matching validated video artifact, with byte-range support.
- `GET /api/health` -> local API health only; it never probes or calls an LLM.
- `POST /api/integrations/hermes/events` -> disabled unless a server-only environment secret is explicitly supplied; native signed metadata receiver only, no tools/approvals/commands/write-back.

```typescript
export type AgentStatus = 'idle' | 'working' | 'waiting' | 'blocked' | 'completed' | 'failed';
export type EventSource = 'production' | 'mock' | 'demo_fixture';
export type StudioEvent = {
  event_id: number; job_id: string; agent_id: string;
  event_type: string; status: AgentStatus; timestamp: string;
  description: string; progress: number | null; model: string | null;
  stage: string | null; run_id: string | null; source: EventSource;
};
export type AgentView = StudioEvent & {stale: boolean};
export type JobView = {
  id: string; title: string; state: string; source: EventSource;
  created_at: string; updated_at: string; approval_required: boolean;
  video: {available: boolean; url: string | null; duration_ms: number | null};
  quality: {technical: boolean | null; editorial: boolean | null; verification: string; checks: Record<string, boolean>};
};
export type StudioSnapshot = {
  cursor: number; timestamp: string; mode: 'production' | 'demo';
  agents: AgentView[]; jobs: JobView[]; events: StudioEvent[];
  health: {database: 'ok'; hermes: 'not_connected' | 'connected' | 'stale'; hermes_last_seen: string | null};
};
```

Idle agent views use `event_id=0`, `job_id=''`, `event_type='idle'`, `status='idle'`, `source='production'` (or `demo_fixture` in isolated demo mode), and nullable progress/model/stage/run fields. They do not represent fabricated work. A filtered snapshot still includes all twelve logical roles. The default snapshot aggregates the latest tasks, preferring genuinely running tasks. Every job retains its own events; one job cannot overwrite another's history.

## Office and UI contract

| Workstation / character | Logical roles |
|---|---|
| Operations | FactoryOrchestrator |
| Research | ResearchAgent, TopicSelectionAgent |
| Editorial | ScriptAgent, CreativeDirectorAgent |
| Visuals | StoryboardAgent, AssetAgent |
| Media | AudioAgent, RenderAgent |
| Review / publishing | QualityAgent, MetadataAgent, PublishAgent |

The screen has a compact health/source/queue header, primary office, right inspector, production queue, pipeline, quality checklist, and real video preview. A character selects its current logical role; the inspector also permits explicit selection of every required identifier. No unsupported publish/approve buttons pretend to work.

Characters move between their rest spot and workstation on actual state changes. Idle has no working animation. CSS transforms/opacity only; no animation loop in React. Reduced-motion, an explicit animation toggle, and automatic render-economy mode disable movement while retaining status and keyboard access. Disconnect preserves the last snapshot, labels it stale, and stops work animations. Errors and empty/loading states appear in place, with a reconnect action.

Original pixel assets are authored specifically for this repository and marked CC0-1.0 in an asset ledger; no upstream sprite, external paid tileset, custom font, or upstream token URL is copied. Dark navy structure, muted teal accents, warm wood office floor, limited status colors, clear focus rings, and responsive scroll-contained office at narrow widths follow the supplied art direction.

## Demo and execution boundaries

An isolated, explicitly labeled `data/studio-demo/` store supplies visual fixtures only. Production mode never falls back to demo. The actual mock-LLM PipelineRunner can also be executed locally to prove ResearchAgent/ScriptAgent events without paid calls; its events are labeled `mock`, not live-researched content. A real Remotion render of a new local job can reuse approved sample narration/artifacts without changing the existing verified sample. Its progress remains actual renderer output, not fixture percentages.

Hermes native `hooks.outbound` is notify-only and best-effort, not a persistent production event store. The optional receiver verifies raw-body HMAC, header/body agreement, timestamp freshness, bounded body, and persistent replay rejection before retaining only allowlisted event names/timestamps and hashed session identity. It never stores tool payloads, prompts, commands, paths, or tokens, and never maps unrelated Hermes sessions to production logical-agent work. No Hermes CLI run or global configuration activation is part of this POC. UI must say not connected until a verified feed actually arrives.

## Acceptance and evidence

Verify typed persistence/replay, concurrent jobs, stale leases, lifecycle/reuse/failure/budget semantics, real progress parsing and completion validation, API origin/path/secret boundaries, signed-webhook rejection/dedupe, and media ranges. Run existing Python, Ruff, JSON Schema, video TypeScript, and secret gates plus dashboard typecheck/build/unit/E2E. Inspect desktop/tablet/mobile screenshots. Measure response/interactivity while an actual local Remotion render runs, reporting measurements rather than claiming universal performance. Verify the global Hermes config hash is unchanged and existing Orca processes/listeners remain present; do not claim full Orca functional E2E from process presence alone.

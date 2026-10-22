import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import type { PersonaInfo, StudioPayload, JobDetail } from "../src/lib/api";

const TEAM = JSON.parse(execFileSync("uv", ["run", "--frozen", "python", "-B", "-c",
  "import json; from packages.core.personas import TEAM; print(json.dumps(TEAM))"], {
  cwd: path.resolve(__dirname, "../../.."), encoding: "utf8",
})) as Record<string, PersonaInfo>;
const SAVED: StudioPayload = { version: 1, agents: {}, budget: {}, production: {},
  runner: { default_mode: "mock", default_stop: "storyboard" } };
const EFFECTIVE = { budget: { max_daily_tokens: 10000, max_daily_cost_usd: 2, max_retries: 3 },
  production: { fps: 30, target_duration_s: 40, videos_per_day: 1,
    tts_voice: "id-ID-ArdiNeural", tts_rate: "+0%" } };
const JOB: JobDetail = {
  record: { id: "a".repeat(16), title: "Cerita uji studio", state: "TOPIC_SELECTED", attempts: 0,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_error: null,
    payload: { provider_mode: "mock", studio_activity: { token: "b".repeat(32), agent: "ScriptAgent",
      stage: "SCRIPT_GENERATED", phase: "running", updated_at: "2026-01-01T00:00:00Z",
      completed: { ResearchAgent: "research.json", TopicSelectionAgent: "topic.json" } } } },
  artifacts: ["research.json", "topic.json"],
  events: [{ from_state: "IDEA_DISCOVERY", to_state: "TOPIC_SELECTED", detail: "topic.json validated", created_at: "2026-01-01T00:00:00Z" }],
  run: { running: true, activity_token: "b".repeat(32), mode: "mock", stop: "storyboard" },
};

async function installApi(page: Page, options: { withJob?: boolean; stale?: boolean } = {}) {
  let saved = structuredClone(SAVED);
  const job = structuredClone(JOB);
  if (options.stale) job.run = { running: false };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    if (pathname === "/api/studio" && request.method() === "PUT") {
      saved = request.postDataJSON();
      return route.fulfill({ json: { saved, effective: EFFECTIVE } });
    }
    if (pathname === "/api/studio") return route.fulfill({ json: {
      saved, effective: EFFECTIVE, team: TEAM,
      personas: Object.fromEntries(Object.entries(TEAM).filter(([, p]) => p.editable)),
      agent_keys: Object.keys(TEAM).filter((id) => TEAM[id].editable),
      default_prompts: Object.fromEntries(Object.keys(TEAM).map((id) => [id, "Default system prompt"])),
      runner_stops: ["research", "script", "creative", "storyboard", "audio", "render"],
      studio_path: "config/studio.json", studio_exists: true,
    } });
    if (pathname === "/api/studio/models") return route.fulfill({ json: { models: [], source: null, error: null } });
    if (pathname === "/api/studio/history") return route.fulfill({ json: { history: [] } });
    if (pathname === "/api/jobs" && request.method() === "GET") return route.fulfill({ json: {
      jobs: options.withJob ? [job.record] : [], states: ["TOPIC_SELECTED", "BLOCKED", "FAILED"],
      running: options.withJob ? { [job.record.id]: job.run.running } : {},
    } });
    if (pathname === `/api/jobs/${job.record.id}`) return route.fulfill({ json: job });
    if (pathname.endsWith("/artifact/research.json")) return route.fulfill({ json: { candidates: [], fixture: true } });
    if (pathname === "/api/usage/today") return route.fulfill({ json: { tokens: 120, cost: 0.01, calls: 1,
      budget: EFFECTIVE.budget, by_agent: [{ agent: "ScriptAgent", provider: "mock", model: "fixture", calls: 1, tokens: 120, cost: 0.01 }] } });
    if (pathname === "/api/providers") return route.fulfill({ json: { health: [{ ref: "mock", healthy: true, model: "fixture" }],
      mode: { worker_configured: false, worker_base_url: null, strategist_model: "not-probed" } } });
    return route.fulfill({ status: 501, json: { detail: `Unmocked test endpoint: ${request.method()} ${pathname}` } });
  });
}

test("navigation fits a phone and exposes all routes", async ({ page }) => {
  await installApi(page);
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/studio");
  await expect(page.getByRole("heading", { name: "Studio", exact: true })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Navigasi utama" });
  await expect(nav.getByRole("link")).toHaveCount(5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByRole("link", { name: "Lewati ke konten" })).toHaveAttribute("href", "#main-content");
});

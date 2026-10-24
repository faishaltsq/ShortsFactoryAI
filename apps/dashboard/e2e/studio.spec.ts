import AxeBuilder from "@axe-core/playwright";
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
      runner_stops: ["research", "script", "creative", "storyboard", "audio", "render", "editorial", "approval"],
      studio_path: "config/studio.json", studio_exists: true,
    } });
    if (pathname === "/api/studio/models") return route.fulfill({ json: { models: [], source: null, error: null } });
    if (pathname === "/api/studio/history") return route.fulfill({ json: { history: [] } });
    if (pathname === "/api/studio/schedule") return route.fulfill({ json: {
      generated_at: "2026-01-01T00:00:00Z", total: 0,
      counts: { "ON GOING": 0, RESEARCHING: 0, UPCOMING: 0, SELESAI: 0, GAGAL: 0, TERTAHAN: 0 },
      entries: [],
    } });
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
  await expect(nav.getByRole("link")).toHaveCount(6);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByRole("link", { name: "Lewati ke konten" })).toHaveAttribute("href", "#main-content");
});

test("every persona can be selected with keyboard and inspected", async ({ page }) => {
  await installApi(page);
  await page.goto("/studio");
  const office = page.getByRole("region", { name: "Lantai studio" });
  await expect(office.getByRole("button")).toHaveCount(Object.keys(TEAM).length);
  const people = Object.values(TEAM);
  await office.getByRole("button").first().focus();
  for (const [index, person] of people.entries()) {
    const seat = office.getByRole("button", { name: new RegExp(`^${person.persona} ·`) });
    await expect(seat).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(seat).toHaveAttribute("aria-pressed", "true");
    const inspector = page.getByRole("region", { name: `Profil ${person.persona}` });
    await expect(inspector.getByRole("heading", { name: person.persona, exact: true })).toBeVisible();
    await expect(inspector.getByText("Motto", { exact: true })).toBeVisible();
    if (person.editable) await expect(inspector.getByRole("textbox", { name: "System prompt" })).toBeVisible();
    else await expect(inspector.getByRole("textbox")).toHaveCount(0);
    if (index < people.length - 1) await page.keyboard.press("Tab");
  }
  await expect(page.getByRole("button", { name: /publikasikan|upload|terbitkan/i })).toHaveCount(0);
});

test("drafts survive agent changes and save makes exactly one PUT", async ({ page }) => {
  await installApi(page);
  let puts = 0;
  page.on("request", (r) => { if (r.method() === "PUT" && new URL(r.url()).pathname === "/api/studio") puts += 1; });
  await page.goto("/studio");
  const office = page.getByRole("region", { name: "Lantai studio" });
  await office.getByRole("button", { name: /^Sora ·/ }).click();
  await page.getByLabel(/Temperature/).fill("0.4");
  await page.getByRole("textbox", { name: "System prompt" }).fill("Naskah uji operator");
  await office.getByRole("button", { name: /^Raka ·/ }).click();
  await page.getByLabel(/Temperature/).fill("0.8");
  await office.getByRole("button", { name: /^Sora ·/ }).click();
  await expect(page.getByLabel(/Temperature/)).toHaveValue("0.4");
  await expect(page.getByRole("textbox", { name: "System prompt" })).toHaveValue("Naskah uji operator");
  expect(puts).toBe(0);
  const saved = page.waitForResponse((r) => r.request().method() === "PUT" && new URL(r.url()).pathname === "/api/studio");
  await page.getByRole("button", { name: "Simpan perubahan" }).click();
  const response = await saved;
  expect(response.request().postDataJSON().agents).toMatchObject({
    ScriptAgent: { temperature: 0.4, prompt: "Naskah uji operator" }, ResearchAgent: { temperature: 0.8 },
  });
  await expect(page.getByRole("button", { name: "Simpan perubahan" })).toBeDisabled();
  expect(puts).toBe(1);
});

test("schedule fields send posting hours as integers and default the stop to approval", async ({ page }) => {
  await installApi(page);
  await page.goto("/studio");
  const schedule = page.getByRole("heading", { name: "Jadwal otomatis" }).locator("..");
  // No saved stop: the select must show the real default, not the unusable `render`.
  await expect(schedule.getByLabel("Berhenti di stage")).toHaveValue("approval");
  await schedule.getByLabel(/Batas menunggu review/).fill("5");
  await schedule.getByLabel(/Jam tayang/).fill("7,12,19");
  const saved = page.waitForResponse((r) => r.request().method() === "PUT" && new URL(r.url()).pathname === "/api/studio");
  await page.getByRole("button", { name: "Simpan perubahan" }).click();
  const body = (await saved).request().postDataJSON();
  expect(body.schedule).toMatchObject({ max_pending_approval: 5, posting_hours: [7, 12, 19] });
  expect(body.schedule.posting_hours.every((h: unknown) => typeof h === "number")).toBe(true);
});

test("pause and reduced motion stop decoration without losing status", async ({ page }) => {
  await installApi(page, { withJob: true });
  await page.goto("/studio");
  const office = page.getByRole("region", { name: "Lantai studio" });
  const sora = office.getByRole("button", { name: /^Sora ·.*Sedang bekerja/ });
  await expect(sora).toBeVisible();
  await page.getByRole("button", { name: "Jeda animasi" }).click();
  await expect(page.getByRole("button", { name: "Jeda animasi" })).toHaveAttribute("aria-pressed", "true");
  expect(await sora.locator(".px-avatar-tool").evaluate((el) => getComputedStyle(el).animationPlayState)).toBe("paused");
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await sora.locator(".px-avatar-tool").evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
  await expect(sora).toContainText("Sedang bekerja");
});

test("a restarted API never keeps an agent pretending to work", async ({ page }) => {
  await installApi(page, { withJob: true, stale: true });
  await page.goto("/studio");
  const office = page.getByRole("region", { name: "Lantai studio" });
  await expect(office.getByRole("button", { name: /^Sora ·.*Tidak terpantau/ })).toBeVisible();
  await expect(office.locator('.px-status[data-kind="working"]')).toHaveCount(0);
});

test("network loss preserves draft and marks observed data stale", async ({ page }) => {
  await installApi(page, { withJob: true });
  await page.goto("/studio");
  await page.getByRole("button", { name: /^Sora ·.*Sedang bekerja/ }).click();
  await page.getByRole("textbox", { name: "System prompt" }).fill("Jangan hilangkan draft ini");
  await page.route("**/api/jobs", (route) => route.fulfill({ status: 503, json: { detail: "offline fixture" } }));
  await expect(page.getByText("Aktivitas belum bisa diperbarui. Data terakhir tetap ditampilkan.")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "System prompt" })).toHaveValue("Jangan hilangkan draft ini");
  await expect(page.getByRole("region", { name: "Lantai studio" }).locator('.px-status[data-kind="working"]')).toHaveCount(0);
});

test("focus job selector does not mix simultaneous jobs", async ({ page }) => {
  await installApi(page, { withJob: true });
  const other = structuredClone(JOB);
  other.record.id = "e".repeat(16);
  other.record.title = "Job kedua";
  other.record.payload.studio_activity = { token: "f".repeat(32), agent: "AudioAgent", phase: "running", completed: {} };
  other.run = { running: true, activity_token: "f".repeat(32) };
  await page.route("**/api/jobs", (r) => r.fulfill({ json: { jobs: [JOB.record, other.record], states: [],
    running: { [JOB.record.id]: true, [other.record.id]: true } } }));
  await page.route(`**/api/jobs/${other.record.id}`, (r) => r.fulfill({ json: other }));
  await page.goto("/studio");
  await page.getByLabel("Pantau job terbaru").selectOption(other.record.id);
  const office = page.getByRole("region", { name: "Lantai studio" });
  await expect(office.getByRole("button", { name: /^Nada ·.*Sedang bekerja/ })).toBeVisible();
  await expect(office.getByRole("button", { name: /^Sora ·.*Siap membantu/ })).toBeVisible();
});

for (const [phase, label] of [["blocked", "Terhambat"], ["failed", "Perlu diperiksa"]]) {
  test(`failed work is static and explicit: ${phase}`, async ({ page }) => {
    await installApi(page, { withJob: true });
    const job = structuredClone(JOB);
    job.run.running = false;
    job.record.payload.studio_activity = { token: "b".repeat(32), agent: "ScriptAgent", phase, completed: {} };
    await page.route(`**/api/jobs/${JOB.record.id}`, (r) => r.fulfill({ json: job }));
    await page.goto("/studio");
    const seat = page.getByRole("region", { name: "Lantai studio" }).getByRole("button", { name: new RegExp(`^Sora ·.*${label}`) });
    await expect(seat).toBeVisible();
    expect(await seat.locator(".px-avatar-body").evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
  });
}

test("loading and configuration failure are recoverable", async ({ page }) => {
  await installApi(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/studio", async (route) => {
    await gate;
    await route.fulfill({ status: 503, json: { detail: "offline fixture" } });
  });
  await page.goto("/studio");
  await expect(page.getByText("Memuat konfigurasi studio…")).toBeVisible();
  release();
  await expect(
    page.getByRole("alert").filter({ hasText: "Konfigurasi tidak bisa dimuat" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Coba lagi", exact: true })).toBeVisible();
});

test("create and cancel retain their API payloads without real work", async ({ page }) => {
  await installApi(page);
  let running = true;
  await page.route("**/api/jobs", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    expect(route.request().postDataJSON()).toEqual({ title: "Judul baru" });
    return route.fulfill({ status: 202, json: { job_id: JOB.record.id, mode: "mock", stop: "storyboard" } });
  });
  await page.route(`**/api/jobs/${JOB.record.id}`, (route) => route.fulfill({ json: {
    ...JOB, record: { ...JOB.record, title: "Judul baru" }, run: { ...JOB.run, running },
  } }));
  await page.route(`**/api/jobs/${JOB.record.id}/cancel`, (route) => {
    expect(route.request().method()).toBe("POST");
    running = false;
    return route.fulfill({ json: { ok: true, status: "cancellation requested" } });
  });
  await page.goto("/jobs");
  await page.getByLabel("Judul video").fill("Judul baru");
  await page.getByRole("button", { name: "Buat job", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Judul baru" })).toBeVisible();
  await page.getByRole("button", { name: "Batalkan run", exact: true }).click();
  await expect(page.getByRole("button", { name: "Jalankan / lanjutkan", exact: true })).toBeEnabled();
});

for (const width of [320, 390, 768, 1024, 1440]) {
  test(`all routes fit ${width}px and pass accessibility checks`, async ({ page }, testInfo) => {
    test.setTimeout(120000);
    await installApi(page, { withJob: true });
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const routes = ["/", "/studio", "/jobs", `/jobs/${JOB.record.id}`, "/schedule", "/providers", "/usage"];
    const exceptions: string[] = [];
    page.on("pageerror", (error) => exceptions.push(error.message));
    for (const route of routes) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      if (route === "/studio") {
        await expect(page.getByRole("region", { name: "Lantai studio" }).getByRole("button")).toHaveCount(Object.keys(TEAM).length);
        await page.getByRole("region", { name: "Lantai studio" }).getByRole("button", { name: /^Sora ·/ }).click();
        await expect(page.getByRole("textbox", { name: "System prompt" })).toBeVisible();
      }
      if (route === "/usage") await expect(page.getByRole("table")).toBeVisible();
      if (route === "/schedule") await expect(page.getByRole("heading", { name: "Production schedule" })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      expect(results.violations).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath(`${route.replaceAll("/", "-") || "overview"}.png`), fullPage: true });
    }
    expect(exceptions).toEqual([]);
  });
}


test("long job titles wrap and unknown usage agents remain visible", async ({ page }) => {
  await installApi(page);
  const title = "JudulSangatPanjang".repeat(30);
  await page.route("**/api/jobs", (r) => r.fulfill({ json: {
    jobs: [{ ...JOB.record, title }], states: [], running: {},
  } }));
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/jobs");
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.route("**/api/usage/today", (r) => r.fulfill({ json: {
    tokens: 1, cost: 0, calls: 1, budget: EFFECTIVE.budget,
    by_agent: [{ agent: "HistoricalAgent", provider: "mock", model: "fixture", tokens: 1, cost: 0, calls: 1 }],
  } }));
  await page.goto("/usage");
  await expect(page.getByRole("cell", { name: "HistoricalAgent", exact: true })).toBeVisible();
});

test("overview is a lobby and retains its factual metrics", async ({ page }) => {
  await installApi(page);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Lantai studio" }).getByRole("button")).toHaveCount(Object.keys(TEAM).length);
  await expect(page.getByText("Token hari ini", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Buka Jobs", exact: true })).toBeVisible();
});
test("jobs is a card queue with the original detail action", async ({ page }) => {
  await installApi(page, { withJob: true });
  await page.goto("/jobs");
  const queue = page.getByRole("list", { name: "Antrean produksi" });
  await expect(queue.getByRole("heading", { name: "Cerita uji studio" })).toBeVisible();
  await queue.getByRole("link", { name: "Buka" }).click();
  await expect(page).toHaveURL(new RegExp(`/jobs/${JOB.record.id}$`));
});

test("detail exposes observed activity separately from persisted stages", async ({ page }) => {
  await installApi(page, { withJob: true });
  await page.goto(`/jobs/${JOB.record.id}`);
  const team = page.getByRole("region", { name: "Tim pada job ini" });
  await expect(team.getByText("Sora", { exact: true })).toBeVisible();
  await expect(team.locator('.px-status[data-kind="working"]')).toHaveCount(2);
  await page.getByRole("button", { name: "research.json", exact: true }).click();
  await expect(page.getByRole("region", { name: "Isi artifact" })).toContainText('"fixture": true');
});
test("operator rejection requires a reason and updates the persisted state", async ({ page }) => {
  await installApi(page);
  const job = structuredClone(JOB);
  job.record.state = "READY_FOR_APPROVAL";
  job.run = { running: false };
  let state = "READY_FOR_APPROVAL";
  let posted: unknown;
  await page.route(`**/api/jobs/${job.record.id}`, (route) => route.fulfill({
    json: { ...job, record: { ...job.record, state } },
  }));
  await page.route(`**/api/jobs/${job.record.id}/reject`, async (route) => {
    posted = route.request().postDataJSON();
    state = "REJECTED";
    return route.fulfill({ json: { job_id: job.record.id, state, reason: "perlu revisi" } });
  });
  await page.goto(`/jobs/${job.record.id}`);
  await expect(page.getByTestId("approval-controls")).toBeVisible();
  await expect(page.getByRole("button", { name: "Tolak job" })).toBeDisabled();
  await page.getByLabel("Alasan penolakan").fill("perlu revisi");
  await page.getByRole("button", { name: "Tolak job" }).click();
  await expect(page.getByText("REJECTED", { exact: true })).toBeVisible();
  expect(posted).toEqual({ operator: "local-operator", reason: "perlu revisi" });
  await expect(page.getByTestId("approval-controls")).toHaveCount(0);
});

test("providers and usage retain operational data with team attribution", async ({ page }) => {
  await installApi(page);
  await page.goto("/providers");
  await expect(page.getByRole("region", { name: "Rak provider" })).toContainText("mock");
  await expect(page.getByRole("button", { name: "Periksa ulang" })).toBeEnabled();
  await page.getByRole("link", { name: /Usage/ }).click();
  const ledger = page.getByRole("region", { name: "Rincian pemakaian per agent" });
  await expect(ledger.getByText("Sora", { exact: true })).toBeVisible();
  await expect(ledger.getByText("ScriptAgent", { exact: true })).toBeVisible();
  await expect(ledger.getByText("fixture", { exact: true })).toBeVisible();
});

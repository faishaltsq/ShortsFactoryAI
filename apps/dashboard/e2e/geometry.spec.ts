import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import type { PersonaInfo, StudioPayload } from "../src/lib/api";

const TEAM = JSON.parse(execFileSync("uv", ["run", "--frozen", "python", "-B", "-c",
  "import json; from packages.core.personas import TEAM; print(json.dumps(TEAM))"], {
  cwd: path.resolve(__dirname, "../../.."), encoding: "utf8",
})) as Record<string, PersonaInfo>;
const SAVED: StudioPayload = { version: 1, agents: {}, budget: {}, production: {},
  runner: { default_mode: "mock", default_stop: "storyboard" } };
const EFFECTIVE = { budget: { max_daily_tokens: 10000, max_daily_cost_usd: 2, max_retries: 3 },
  production: { fps: 30, target_duration_s: 40, videos_per_day: 1,
    tts_voice: "id-ID-ArdiNeural", tts_rate: "+0%" } };

async function installApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/studio") return route.fulfill({ json: {
      saved: SAVED, effective: EFFECTIVE, team: TEAM,
      personas: Object.fromEntries(Object.entries(TEAM).filter(([, p]) => p.editable)),
      agent_keys: Object.keys(TEAM).filter((id) => TEAM[id].editable),
      default_prompts: Object.fromEntries(Object.keys(TEAM).map((id) => [id, "Default"])),
      runner_stops: ["research", "script", "storyboard"], studio_path: "config/studio.json",
      studio_exists: true } });
    if (pathname === "/api/studio/models") return route.fulfill({ json: { models: [], source: null, error: null } });
    if (pathname === "/api/studio/history") return route.fulfill({ json: { history: [] } });
    if (pathname === "/api/jobs") return route.fulfill({ json: { jobs: [], states: [], running: {} } });
    return route.fulfill({ status: 501, json: { detail: `unmocked ${pathname}` } });
  });
}

// Geometry review in place of an eyeball pass: every character must be fully
// inside its station, the desk must not cover the face or the accessory, and no
// label may overflow its own box.
test("characters are fully visible and never occluded by the desk", async ({ page }) => {
  await installApi(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/studio");
  const office = page.getByRole("region", { name: "Lantai studio" });
  await expect(office.getByRole("button")).toHaveCount(Object.keys(TEAM).length);

  const report = await office.evaluate((root) => {
    const problems: string[] = [];
    const stations = Array.from(root.querySelectorAll<HTMLElement>(".px-station"));
    for (const station of stations) {
      const label = station.getAttribute("aria-label") ?? "?";
      const box = station.getBoundingClientRect();
      const svg = station.querySelector<SVGElement>(".px-avatar");
      const desk = station.querySelector<HTMLElement>(".px-desk");
      const tool = station.querySelector<SVGGElement>(".px-avatar-tool");
      const eyes = station.querySelector<SVGGElement>(".px-avatar-eyes");
      if (!svg) { problems.push(`${label}: no avatar`); continue; }
      const sprite = svg.getBoundingClientRect();
      if (sprite.width < 40) problems.push(`${label}: avatar only ${sprite.width}px wide`);
      if (sprite.left < box.left - 1 || sprite.right > box.right + 1)
        problems.push(`${label}: avatar clipped horizontally`);
      if (desk) {
        const d = desk.getBoundingClientRect();
        for (const [name, node] of [["tool", tool], ["eyes", eyes]] as const) {
          if (!node) continue;
          const r = node.getBoundingClientRect();
          const overlapX = Math.max(0, Math.min(r.right, d.right) - Math.max(r.left, d.left));
          const overlapY = Math.max(0, Math.min(r.bottom, d.bottom) - Math.max(r.top, d.top));
          if (overlapX > 1 && overlapY > 1)
            problems.push(`${label}: desk covers ${name} by ${Math.round(overlapY)}px`);
        }
      }
      for (const text of Array.from(station.querySelectorAll<HTMLElement>("strong, small, .px-status"))) {
        if (text.scrollWidth > text.clientWidth + 1)
          problems.push(`${label}: "${text.textContent}" overflows (${text.scrollWidth}>${text.clientWidth})`);
        const r = text.getBoundingClientRect();
        if (r.right > box.right + 1) problems.push(`${label}: "${text.textContent}" escapes the station`);
      }
      const status = station.querySelector<HTMLElement>(".px-status");
      if (!status || !status.textContent?.trim()) problems.push(`${label}: no status label`);
      else {
        const cs = getComputedStyle(status);
        if (parseFloat(cs.fontSize) < 12) problems.push(`${label}: status text ${cs.fontSize} < 12px`);
      }
    }
    return { count: stations.length, problems };
  });

  expect(report.count).toBe(Object.keys(TEAM).length);
  expect(report.problems).toEqual([]);
});

test("the twelve accessories render as twelve different shapes", async ({ page }) => {
  await installApi(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/studio");
  const office = page.getByRole("region", { name: "Lantai studio" });
  await expect(office.getByRole("button")).toHaveCount(Object.keys(TEAM).length);
  const shapes = await office.evaluate((root) =>
    Array.from(root.querySelectorAll<SVGGElement>(".px-avatar-tool")).map((g) => ({
      accessory: g.getAttribute("data-accessory"),
      path: g.innerHTML.replace(/\s+/g, " ").trim(),
    })),
  );
  expect(shapes).toHaveLength(Object.keys(TEAM).length);
  expect(new Set(shapes.map((s) => s.accessory)).size).toBe(Object.keys(TEAM).length);
  expect(new Set(shapes.map((s) => s.path)).size).toBe(Object.keys(TEAM).length);
});

test("body copy stays at or above the contract sizes", async ({ page }) => {
  await installApi(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/studio");
  await expect(page.getByRole("region", { name: "Lantai studio" }).getByRole("button")).toHaveCount(
    Object.keys(TEAM).length,
  );
  const sizes = await page.evaluate(() => {
    const out: { cls: string; size: number }[] = [];
    for (const sel of [".px-eyebrow", ".px-station strong", ".px-station small", ".px-status", ".px-inspector p", ".px-inspector code"]) {
      const el = document.querySelector<HTMLElement>(sel);
      if (el) out.push({ cls: sel, size: parseFloat(getComputedStyle(el).fontSize) });
    }
    return out;
  });
  expect(sizes.length).toBeGreaterThan(3);
  for (const item of sizes) expect(item.size, item.cls).toBeGreaterThanOrEqual(12);
});

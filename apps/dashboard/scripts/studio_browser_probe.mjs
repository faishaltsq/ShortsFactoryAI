// Browser-side responsiveness probe for the studio, run against a live API.
// Reports numbers only; thresholds stay with the reader. Usage:
//   node scripts/studio_browser_probe.mjs [--base http://127.0.0.1:3018] [--out evidence/studio-browser.json]
import { chromium } from '@playwright/test';
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';

const args = process.argv.slice(2);
const base = args[args.indexOf('--base') + 1] ?? 'http://127.0.0.1:3018';
const out = args[args.indexOf('--out') + 1] ?? 'evidence/studio-browser.json';
const outDir = dirname(out);
const screenshot = join(outDir, 'studio-desktop.png');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

const started = Date.now();
await page.goto(base);
await page.waitForSelector('[data-testid="cursor"]');
const readyMs = Date.now() - started;

await page.waitForFunction(
  () => document.querySelector('[data-testid="pill-stream"]')?.textContent?.includes('connected'),
  undefined,
  { timeout: 30_000 },
);
const connectedMs = Date.now() - started;

const clicks = [];
for (const id of ['station-audio', 'station-render', 'station-research', 'station-control']) {
  const t = Date.now();
  await page.locator(`[data-testid="${id}"]`).click();
  await page.waitForSelector('[data-testid="inspector"]');
  clicks.push(Date.now() - t);
}

const navTiming = await page.evaluate(() => {
  const [entry] = performance.getEntriesByType('navigation');
  return entry ? { domContentLoaded: Math.round(entry.domContentLoadedEventEnd), load: Math.round(entry.loadEventEnd) } : null;
});

const sorted = [...clicks].sort((a, b) => a - b);
const metrics = {
  base,
  ready_ms: readyMs,
  stream_connected_ms: connectedMs,
  click_to_inspector_ms: { samples: clicks.length, p50: sorted[Math.floor(sorted.length / 2)], max: sorted.at(-1) },
  navigation: navTiming,
  screenshot,
};
mkdirSync(outDir, { recursive: true });
await page.screenshot({ path: screenshot, fullPage: true });
writeFileSync(out, `${JSON.stringify(metrics, null, 2)}\n`);
console.log(JSON.stringify(metrics, null, 2));
await browser.close();

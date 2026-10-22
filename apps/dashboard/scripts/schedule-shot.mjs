import { chromium } from '@playwright/test';

const out = process.argv[2];
if (!out) throw new Error('pass an output png path');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.goto('http://127.0.0.1:3018/', { waitUntil: 'networkidle' });
await page.getByTestId('menu-schedule').click();
await page.locator('[data-testid^="schedule-row-"]').first().waitFor();
await page.waitForTimeout(600);
await page.screenshot({ path: out, fullPage: false });

const rows = await page.locator('[data-testid^="schedule-row-"]').evaluateAll(nodes =>
  nodes.map(node => ({
    status: node.getAttribute('data-status'),
    text: (node.textContent ?? '').replace(/\s+/g, ' ').trim(),
  })));
console.log(JSON.stringify({ total: await page.getByTestId('schedule-total').innerText(), rows }, null, 2));
await browser.close();

import { chromium } from '@playwright/test';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.goto('http://127.0.0.1:3018/', { waitUntil: 'networkidle' });
await page.getByTestId('menu-schedule').click();
await page.locator('[data-testid^="schedule-row-"]').first().waitFor();
await page.waitForTimeout(400);

const layout = await page.evaluate(() => {
  const list = document.querySelector('.schedule__list');
  const foot = document.querySelector('.schedule__foot');
  const panel = document.querySelector('.schedule');
  const last = document.querySelectorAll('[data-testid^="schedule-row-"]');
  return {
    listScrollable: list ? list.scrollHeight > list.clientHeight : null,
    listClientHeight: list?.clientHeight ?? null,
    listScrollHeight: list?.scrollHeight ?? null,
    footerVisible: foot ? foot.getBoundingClientRect().bottom <= window.innerHeight : null,
    panelBottom: panel ? Math.round(panel.getBoundingClientRect().bottom) : null,
    viewport: window.innerHeight,
    rowCount: last.length,
    docOverflowX: document.documentElement.scrollWidth > window.innerWidth,
  };
});

// Scroll the list to its end and confirm the last row is reachable.
await page.evaluate(() => {
  const list = document.querySelector('.schedule__list');
  if (list) list.scrollTop = list.scrollHeight;
});
await page.waitForTimeout(300);
const lastRowVisible = await page.locator('[data-testid^="schedule-row-"]').last().isVisible();
const lastStatus = await page.locator('[data-testid^="schedule-row-"]').last().getAttribute('data-status');

// Narrow viewport: the rows must reflow, not overflow horizontally.
await page.setViewportSize({ width: 720, height: 900 });
await page.waitForTimeout(400);
const narrow = await page.evaluate(() => ({
  overflowX: document.documentElement.scrollWidth > window.innerWidth,
  scrollWidth: document.documentElement.scrollWidth,
  innerWidth: window.innerWidth,
}));
await page.screenshot({ path: process.argv[2].replace('.png', '-narrow.png') });

console.log(JSON.stringify({ layout, lastRowVisible, lastStatus, narrow }, null, 2));
await browser.close();

import { expect, test, type Page } from '@playwright/test';

const waitConnected = (page: Page) =>
  expect(page.getByTestId('pill-stream')).toContainText('Stream: connected', { timeout: 30_000 });

test.describe('Pixel Production Studio', () => {
  test('serves the office, queue, pipeline and preview from the live API', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Shorts Factory').first()).toBeVisible();
    await expect(page.locator('.office')).toBeVisible();
    await expect(page.locator('[data-testid^="station-"]')).toHaveCount(6);
    await expect(page.locator('[data-testid="queue-count"]')).toBeVisible();
    await expect(page.locator('[data-testid="pipeline"] .stage')).toHaveCount(7);
    await expect(page.getByTestId('job-active')).toBeVisible();
    await waitConnected(page);
    await expect(page.getByTestId('video-frame')).toBeVisible();
  });

  test('a workstation click moves the inspector onto that station role', async ({ page }) => {
    await page.goto('/');
    await waitConnected(page);
    await page.locator('[data-testid="station-audio"]').click();
    await expect(page.getByTestId('inspector')).toContainText('AudioAgent');
    await page.locator('[data-testid="station-render"]').click();
    await expect(page.getByTestId('inspector')).toContainText('RenderAgent');
  });

  test('mode switch reloads the matching evidence and drops the other mode', async ({ page }) => {
    await page.goto('/');
    await waitConnected(page);
    await expect(page.getByTestId('pill-mode')).toContainText('Mode: production');
    await page.getByTestId('mode-toggle').click();
    await expect(page.getByTestId('pill-mode')).toContainText('Mode: demo');
    await expect(page.getByTestId('pill-mode')).not.toContainText('production');
    await page.getByTestId('mode-toggle').click();
    await expect(page.getByTestId('pill-mode')).toContainText('Mode: production');
  });

  test('the stream reconnects after a dropped feed without losing accepted evidence', async ({ page }) => {
    let attempts = 0;
    await page.route('**/api/studio/stream*', async route => {
      attempts += 1;
      if (attempts <= 2) return route.abort('connectionrefused');
      return route.continue();
    });
    await page.goto('/');
    await expect(page.locator('[data-testid="history"]')).toBeAttached();
    await waitConnected(page);
    expect(attempts).toBeGreaterThanOrEqual(3);
    await expect(page.getByTestId('logs')).toContainText('percobaan ulang');
    await expect(page.getByTestId('cursor')).toContainText('event #');
  });

  test('reduced motion keeps the crew still instead of faking work', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    await waitConnected(page);
    await expect(page.getByTestId('economy-toggle')).toContainText('Ekonomi render: aktif');
    await expect(page.locator('.figure--work')).toHaveCount(0);
  });

  test('the schedule menu lists produced content with ON GOING / RESEARCHING / UPCOMING', async ({ page }) => {
    await page.goto('/');
    await waitConnected(page);
    await page.getByTestId('menu-schedule').click();
    await expect(page.getByTestId('menu-schedule')).toHaveAttribute('aria-current', 'page');

    const list = page.getByTestId('schedule-list');
    await expect(list).toBeVisible();
    await expect(page.getByTestId('schedule-total')).toContainText('konten');

    // Every rendered row carries one of the operator-facing statuses.
    const statuses = await page.locator('[data-testid^="schedule-row-"]').evaluateAll(
      rows => rows.map(row => row.getAttribute('data-status')));
    expect(statuses.length).toBeGreaterThan(0);
    for (const status of statuses) {
      expect(['ON GOING', 'RESEARCHING', 'UPCOMING', 'SELESAI', 'GAGAL', 'TERTAHAN']).toContain(status);
    }
    expect(statuses).toContain('ON GOING');

    // Filtering narrows the list without inventing rows.
    await page.getByTestId('schedule-filter-on-going').click();
    await expect(page.getByTestId('schedule-filter-on-going')).toHaveAttribute('aria-pressed', 'true');
    const filtered = await page.locator('[data-testid^="schedule-row-"]').evaluateAll(
      rows => rows.map(row => row.getAttribute('data-status')));
    expect(filtered.every(status => status === 'ON GOING')).toBe(true);

    await page.getByTestId('schedule-filter-semua').click();
    await expect(page.locator('[data-testid^="schedule-row-"]')).toHaveCount(statuses.length);
  });

  test('a schedule row opens that job in the studio view', async ({ page }) => {
    await page.goto('/');
    await waitConnected(page);
    await page.getByTestId('menu-schedule').click();
    const first = page.locator('[data-testid^="schedule-row-"]').first();
    await expect(first).toBeVisible();
    const jobId = (await first.getAttribute('data-testid'))!.replace('schedule-row-', '');
    await first.click();
    await expect(page.getByTestId('menu-studio')).toHaveAttribute('aria-current', 'page');
    await expect(page.getByTestId('queue-count')).toBeVisible();
    await expect(page.locator('.jobs')).toContainText(jobId.slice(0, 8));
  });
});

import { test, expect } from '@playwright/test';

test('approval controls are reachable in the preview panel', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('approval-controls')).toBeVisible();
  await expect(page.getByTestId('approve')).toBeVisible();
  await expect(page.getByTestId('reject')).toBeVisible();
  await page.getByTestId('operator-name').fill('lo');
  await page.getByTestId('reject').click();
  await expect(page.getByTestId('reject-confirm')).toBeVisible();
});

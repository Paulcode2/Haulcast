import { test, expect } from '@playwright/test';
import { writeFile } from 'node:fs/promises';

test('live trip planner reaches HERE and Open-Meteo through Django', async ({ page }, testInfo) => {
  test.skip(process.env.RUN_LIVE_TRIP !== '1', 'Opt in with RUN_LIVE_TRIP=1; requires Django and a valid backend HERE key.');
  test.setTimeout(150000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Use demo trip' }).click();
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/trips/analyze') && response.request().method() === 'POST', { timeout: 125000 });
  await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const result = await response.json();
  expect(result.routes.length).toBeGreaterThan(0);
  await expect(page.locator('.route-card')).toHaveCount(result.routes.length);
  await expect(page.getByTestId('trip-map')).toHaveAttribute('data-ready', 'true');
  const index = Math.min(2, result.routes.length);
  await page.getByTestId(`route-card-${index}`).getByRole('button').click();
  await expect(page.getByTestId('trip-map')).toHaveAttribute('data-selected-route', result.routes[index - 1].id);
  await page.getByRole('button', { name: /^Inspect checkpoint 2:/ }).click();
  await expect(page.getByRole('dialog', { name: 'Checkpoint 2 details' })).toContainText('Triggering rule:');
  await page.screenshot({ path: testInfo.outputPath('planner-live-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('.route-card')).toHaveCount(result.routes.length);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('planner-live-mobile.png'), fullPage: true });
  await writeFile(testInfo.outputPath('trip-response.json'), JSON.stringify(result, null, 2));
});

import { test, expect } from '@playwright/test';
import { tripFixture, mockBase } from './fixtures';

async function demo(page) { await page.goto('/'); await page.getByRole('button', { name: 'Use demo trip' }).click(); }
test.beforeEach(async ({ page }) => mockBase(page));

test('keyboard: tab order, slider arrows, card selection via keyboard', async ({ page }) => {
  await page.route('**/api/trips/analyze', route => route.fulfill({ json: tripFixture() }));
  await demo(page);
  await page.getByLabel('Origin', { exact: true }).click();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Destination', { exact: true })).toBeFocused();
  const submit = page.getByRole('button', { name: 'Analyze trip', exact: true });
for (let i = 0; i < 12; i++) { await page.keyboard.press('Tab'); if (await submit.evaluate(el => el === document.activeElement)) break; }
  await expect(page.getByRole('button', { name: 'Analyze trip', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: '3 routes to compare' })).toBeVisible();
  const slider = page.getByLabel(/Forecast hour:/);
  await slider.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('trip-map')).toHaveAttribute('data-forecast-hour', '1');
  await page.keyboard.press('ArrowLeft');
  await expect(page.getByTestId('trip-map')).toHaveAttribute('data-forecast-hour', '0');
  await page.getByTestId('route-card-2').getByRole('button').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('trip-map')).toHaveAttribute('data-selected-route', 'route-2');
});

test('loading state disables form and announces progress', async ({ page }) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/api/trips/analyze', async route => { await gate; await route.fulfill({ json: tripFixture() }); });
  await demo(page);
  await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Analyzing trip…' })).toBeDisabled();
  await expect(page.locator('p.notice[role="status"]')).toContainText('Finding truck routes');
  await expect(page.getByLabel('Origin', { exact: true })).toBeDisabled();
  release();
  await expect(page.getByRole('heading', { name: '3 routes to compare' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Analyze trip', exact: true })).toBeEnabled();
});

test('desktop layout shows map controls, legends and no overflow', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.route('**/api/trips/analyze', route => route.fulfill({ json: tripFixture() }));
  await demo(page);
  await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
  await expect(page.getByRole('heading', { name: '3 routes to compare' })).toBeVisible();
  await expect(page.getByTestId('trip-map')).toHaveAttribute('data-ready', 'true');
  await expect(page.locator('.maplibregl-ctrl-zoom-in')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Fit trip', exact: true })).toBeVisible();
  await expect(page.getByText('Checkpoint risk')).toBeVisible();
  await expect(page.getByText('Heat intensity')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('mobile success layout keeps controls usable and no overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/trips/analyze', route => route.fulfill({ json: tripFixture() }));
  await demo(page);
  await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
  await expect(page.getByRole('heading', { name: '3 routes to compare' })).toBeVisible();
  await expect(page.getByTestId('trip-map')).toHaveAttribute('data-ready', 'true');
  await expect(page.getByRole('button', { name: 'Fit trip', exact: true })).toBeVisible();
  await expect(page.getByText('Checkpoint risk')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

import { test, expect } from '@playwright/test';
import { tripFixture, mockBase } from './fixtures';

async function demo(page) { await page.goto('/'); await page.getByRole('button', { name: 'Use demo trip' }).click(); }
test.beforeEach(async ({ page }) => mockBase(page));

test('submit explicit offset, select routes both ways, inspect map checkpoint', async ({ page }) => {
let sent;
await page.route('**/api/trips/analyze', route => { sent = route.request().postDataJSON(); return route.fulfill({ json: tripFixture() }); });
await demo(page);
await page.getByLabel('Departure date and time').fill('2026-11-25T09:00');
await page.getByLabel('Departure UTC offset').selectOption('+01:00');
await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
await expect(page.getByRole('heading', { name: '3 routes to compare' })).toBeVisible();
expect(sent.departure_time).toBe('2026-11-25T09:00:00+01:00');
expect(sent.load_weight_lbs).toBe(12000); expect(sent.checkpoint_interval_miles).toBe(25);
await expect(page.getByTestId('trip-map')).toHaveAttribute('data-ready', 'true');
await page.getByTestId('route-card-2').getByRole('button').click();
await expect(page.getByTestId('trip-map')).toHaveAttribute('data-selected-route', 'route-2');
await page.getByRole('button', { name: 'Select route 3 on map', exact: true }).click();
await expect(page.getByTestId('route-card-3').getByRole('button')).toHaveAttribute('aria-pressed', 'true');
await page.getByRole('button', { name: 'Inspect checkpoint 2: High', exact: true }).click();
const popup = page.getByRole('dialog', { name: 'Checkpoint 2 details' });
await expect(popup).toContainText('Wind: 35.00 mph'); await expect(popup).toContainText('Rain: 0.02 in/hr');
await expect(popup).toContainText('ETA: 2026-11-25 09:00:00 UTC'); await expect(popup).toContainText('Triggering rule: Wind 35 mph: High.');
const popupBox = await page.locator('.maplibregl-popup-content').boundingBox();
const mapBox = await page.getByTestId('trip-map').boundingBox();
expect(popupBox.y).toBeGreaterThanOrEqual(mapBox.y);
expect(popupBox.y + popupBox.height).toBeLessThanOrEqual(mapBox.y + mapBox.height);
await page.getByRole('button', { name: 'Fit trip', exact: true }).click();
await expect(popup).toHaveCount(0);
});

test('forecast slider scrubs loaded hours without new requests and keeps selection', async ({ page }) => {
let calls = 0;
await page.route('**/api/trips/analyze', route => { calls++; return route.fulfill({ json: tripFixture() }); });
await demo(page);
await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
await expect(page.getByRole('heading', { name: '3 routes to compare' })).toBeVisible();
const slider = page.getByLabel(/Forecast hour:/);
await expect(slider).toHaveAttribute('max', '48');
await expect(page.getByTestId('trip-map')).toHaveAttribute('data-forecast-hour', '0');
await expect(page.getByTestId('forecast-status')).toContainText('3 of 3 corridor points have a forecast at hour 0');
await expect(page.getByText('Recommended: Route 1')).toBeVisible();
await page.getByTestId('route-card-2').getByRole('button').click();
for (const hour of [24, 48, 0]) {
await slider.fill(String(hour));
await expect(page.getByTestId('trip-map')).toHaveAttribute('data-forecast-hour', String(hour));
}
await expect(page.getByTestId('forecast-status')).toContainText('3 of 3 corridor points have a forecast at hour 0');
await slider.fill('48');
await expect(page.getByTestId('forecast-status')).toContainText('Unavailable hour');
await expect(page.getByTestId('route-card-2').getByRole('button')).toHaveAttribute('aria-pressed', 'true');
await expect(page.getByText('Recommended: Route 1')).toBeVisible();
expect(calls).toBe(1);
});

test('new trip replaces stale heatmap data', async ({ page }) => {
let count = 0;
await page.route('**/api/trips/analyze', route => {
count++;
const fixture = tripFixture(count === 1 ? 3 : 1);
return route.fulfill({ json: fixture });
});
await demo(page);
await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
await expect(page.getByRole('heading', { name: '3 routes to compare' })).toBeVisible();
await page.getByLabel(/Forecast hour:/).fill('24');
await expect(page.getByTestId('trip-map')).toHaveAttribute('data-forecast-hour', '24');
await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
await expect(page.getByRole('heading', { name: '1 route to compare' })).toBeVisible();
await expect(page.getByTestId('trip-map')).toHaveAttribute('data-forecast-hour', '0');
await expect(page.getByTestId('forecast-status')).toContainText('3 of 3 corridor points have a forecast at hour 0');
expect(count).toBe(2);
});

test('invalid form blocks request and shows field errors', async ({ page }) => {
let calls = 0; await page.route('**/api/trips/analyze', route => { calls++; return route.fulfill({ json: tripFixture() }); });
await page.goto('/'); await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
await expect(page.getByLabel('Origin', { exact: true })).toHaveAttribute('aria-invalid', 'true');
await expect(page.getByText('Enter a finite cargo weight greater than zero.')).toBeVisible();
await page.getByRole('button', { name: 'Use demo trip' }).click(); await page.getByLabel('Cargo load (lb)').fill('-1');
await page.getByRole('button', { name: 'Analyze trip', exact: true }).click(); expect(calls).toBe(0);
});

test('pending request prevents duplicate submission and fewer routes stay fewer', async ({ page }) => {
let calls = 0, release;
const gate = new Promise(resolve => { release = resolve; });
await page.route('**/api/trips/analyze', async route => { calls++; await gate; await route.fulfill({ json: tripFixture(1) }); });
await demo(page); await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
await expect(page.getByRole('button', { name: 'Analyzing trip…' })).toBeDisabled();
await page.locator('form').evaluate(form => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
expect(calls).toBe(1); release();
await expect(page.getByRole('heading', { name: '1 route to compare' })).toBeVisible();
await expect(page.locator('.route-card')).toHaveCount(1);
});

test('provider and backend field errors shown, retry can return empty', async ({ page }) => {
let count = 0;
await page.route('**/api/trips/analyze', route => {
count++;
if (count === 1) return route.fulfill({ status: 502, json: { error: { message: 'HERE rejected the API key (HTTP 401).' } } });
if (count === 2) return route.fulfill({ status: 400, json: { error: { message: 'Check the request fields.', fields: { origin: ['Use a more specific origin.'] } } } });
return route.fulfill({ json: tripFixture(0) });
});
await demo(page); await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
await expect(page.getByRole('alert')).toContainText('HERE rejected');
await page.getByRole('button', { name: 'Analyze trip', exact: true }).click(); await expect(page.getByText('Use a more specific origin.')).toBeVisible();
await page.getByRole('button', { name: 'Analyze trip', exact: true }).click(); await expect(page.getByText('No routes returned.', { exact: false })).toBeVisible();
});

test('mobile no recommendation, unknown popup, no horizontal overflow', async ({ page }) => {
await page.setViewportSize({ width: 390, height: 844 });
await page.route('**/api/trips/analyze', route => route.fulfill({ json: tripFixture(2, true) }));
await demo(page); await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
await expect(page.getByText('No recommendation', { exact: true })).toBeVisible();
await expect(page.locator('.excluded')).toHaveCount(2);
await page.getByTestId('route-card-2').getByRole('button').click();
await page.getByRole('button', { name: '2 · 50.0 mi · Unknown · Incomplete', exact: true }).click();
await expect(page.locator('.inspection')).toContainText('Wind: Unavailable');
await expect(page.locator('.inspection')).toContainText('Risk: Unknown');
expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
await page.screenshot({ path: 'test-results/planner-mobile.png', fullPage: true });
});

test('network failure is actionable and form can retry', async ({ page }) => {
await page.route('**/api/trips/analyze', route => route.abort()); await demo(page);
await page.getByRole('button', { name: 'Analyze trip', exact: true }).click();
await expect(page.getByRole('alert')).toContainText('Cannot reach the backend');
await expect(page.getByRole('button', { name: 'Analyze trip', exact: true })).toBeEnabled();
});

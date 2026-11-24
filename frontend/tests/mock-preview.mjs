// Isolated manual test browser. No mock routes are shipped with the app.
import { chromium } from '@playwright/test';
import { mockBase, tripFixture } from './fixtures.js';

const scenario = process.argv[2] || 'success';
const allowed = ['success', 'fewer', 'no-recommendation', 'provider-error', 'empty', 'field-error', 'slow'];
if (!allowed.includes(scenario)) throw new Error(`Choose: ${allowed.join(', ')}`);
const browser = await chromium.launch({ headless: false, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await mockBase(page);
await page.route('**/api/trips/analyze', async route => {
  if (scenario === 'slow') await new Promise(resolve => setTimeout(resolve, 5000));
  if (scenario === 'provider-error') return route.fulfill({ status: 502, json: { error: { message: 'HERE rejected the API key (HTTP 401). Replace the backend key and restart Django.' } } });
  if (scenario === 'field-error') return route.fulfill({ status: 400, json: { error: { message: 'Check the request fields.', fields: { origin: ['Use a more specific origin.'] } } } });
  return route.fulfill({ json: tripFixture(scenario === 'empty' ? 0 : scenario === 'fewer' ? 1 : 3, scenario === 'no-recommendation') });
});
await page.goto('http://127.0.0.1:5173');
await page.getByRole('button', { name: 'Use demo trip' }).click();
console.log(`Manual fixture: ${scenario}. Submit the form in the opened browser. Close the browser to finish.`);
await new Promise(resolve => browser.on('disconnected', resolve));

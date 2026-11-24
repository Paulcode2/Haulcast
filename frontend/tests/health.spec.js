import { test, expect } from '@playwright/test';
test('React reaches the real Django backend across origins', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('status')).toHaveText('Backend connected');
  await page.getByRole('button', { name: 'Check connection' }).click();
  await expect(page.getByRole('status')).toHaveText('Backend connected');
});

import { test, expect } from '@playwright/test';

test('idle state shows No execution yet', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('text=No execution yet.')).toBeVisible();
});

test('planning state shows Planning workflow placeholder then hydrates', async ({ page }) => {
  test.setTimeout(120000);
  await page.goto('/');

  const textarea = page.getByPlaceholder('Enter instruction…');
  await textarea.fill('Calculate 12 plus 8. Then stop.');

  const sendBtn = page.getByRole('button', { name: 'Send →' });
  await sendBtn.click();

  // Immediately after sending, the WorkflowPanel should show the placeholder
  await expect(page.locator('text=Planning workflow…')).toBeVisible({ timeout: 2000 });

  // Eventually normal workflow panel should appear (placeholder disappears implicitly)
  await expect(page.locator('.step-list')).toBeVisible({ timeout: 90000 });
});

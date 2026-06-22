import { test, expect } from '@playwright/test';

test('planning telemetry visible in Current Activity during pending stream', async ({ page }) => {
  test.setTimeout(120000);
  await page.goto('/');

  const textarea = page.getByPlaceholder('Enter instruction…');
  await textarea.fill('Calculate 12 plus 8. Then stop.');

  const sendBtn = page.getByRole('button', { name: 'Send →' });
  await sendBtn.click();

  // During the planning window, Current Activity should show planner telemetry
  await expect(page.locator('text=Calling planner model…')).toBeVisible({ timeout: 15000 });

  // Eventually normal workflow panel should appear (placeholder disappears implicitly)
  await expect(page.locator('.step-list')).toBeVisible({ timeout: 90000 });
});

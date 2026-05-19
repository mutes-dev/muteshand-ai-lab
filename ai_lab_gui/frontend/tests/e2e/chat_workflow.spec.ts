import { test, expect } from '@playwright/test';

test('submit simple workflow and observe planning state', async ({ page }) => {
  await page.goto('/');

  const textarea = page.getByPlaceholder('Enter instruction…');
  const sendBtn = page.getByRole('button', { name: 'Send →' });

  // Button disabled when input empty, enabled after fill
  await expect(sendBtn).toBeDisabled();
  await textarea.fill('Add 5 and 3.');
  await expect(sendBtn).toBeEnabled();

  await sendBtn.click();

  // Verify workflow execution starts by waiting for active indicator
  await expect(page.locator('.status-pill.ACTIVE, .running-indicator').first()).toBeVisible({ timeout: 15000 });
});

test('duplicate submission is blocked while executing', async ({ page }) => {
  await page.goto('/');

  const textarea = page.getByPlaceholder('Enter instruction…');
  const sendBtn = page.getByRole('button', { name: 'Send →' });

  // Start a workflow
  await textarea.fill('Add 1 and 2.\nMultiply by 3.\nDivide by 2.\nAdd 10.\nMultiply by 5.');
  await sendBtn.click();

  // Verify workflow execution starts (prevents duplicate submission)
  await expect(page.locator('.status-pill.ACTIVE, .running-indicator').first()).toBeVisible({ timeout: 15000 });

  // While executing, textarea should be disabled (locked)
  await expect(page.getByPlaceholder('Enter instruction…')).toBeDisabled({ timeout: 5000 });
});

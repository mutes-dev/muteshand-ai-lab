import { test, expect } from '@playwright/test';

test('submit simple workflow and observe planning state', async ({ page }) => {
  await page.goto('/');

  const textarea = page.getByPlaceholder('Enter instruction…');
  const sendBtn = page.getByRole('button', { name: 'Send →' });

  await textarea.fill('Add 5 and 3.');
  await sendBtn.click();

  // After click, button should show submitting/planning state
  await expect(
    page.getByRole('button', { name: /Submitting|Planning|Running/ })
  ).toBeVisible();

  // Wait for workflow to become active (upper Workflow panel)
  // The "Planning workflow…" banner may appear briefly
  await page.waitForSelector('[role="status"]', { timeout: 5000 }).catch(() => {
    // Banner may disappear quickly; that's okay
  });
});

test('duplicate submission is blocked while executing', async ({ page }) => {
  await page.goto('/');

  const textarea = page.getByPlaceholder('Enter instruction…');
  const sendBtn = page.getByRole('button', { name: 'Send →' });

  // Start a long workflow
  await textarea.fill('Add 1 and 2.\nMultiply by 3.\nDivide by 2.\nAdd 10.\nMultiply by 5.');
  await sendBtn.click();

  // Button should now be disabled (locked while submitting/executing)
  // FIX: Don't assume button text changes to "Submitting|Planning|Running".
  // The button may retain "Send" label but become disabled via state.
  const sendBtnAfterClick = page.locator('button').filter({ hasText: /Send|Submitting|Planning|Running/ }).first();
  await expect(sendBtnAfterClick).toBeDisabled();

  // Try to submit again — should be blocked
  await textarea.fill('Another request');
  await expect(sendBtnAfterClick).toBeDisabled();
});

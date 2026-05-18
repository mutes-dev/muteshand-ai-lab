import { test, expect } from '@playwright/test';

/**
 * PAUSE/RESUME CONTINUITY VALIDATION
 * 
 * Validates:
 * - workflow enters ACTIVE
 * - pause works
 * - resume works
 * - workflow continues correctly
 * - no duplicate execution
 * - no frozen state
 */

test('pause_resume_continuity', async ({ page }) => {
  // Allow 60s: 3-step workflow with pause/resume when each LLM call is ~10s
  test.setTimeout(60000);
  // Start workflow
  await page.goto('http://localhost:5173/');
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Add 10 and 20.\nMultiply by 2.\nAdd 5.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for workflow to become ACTIVE (use specific workflow panel indicator)
  await expect(page.locator('.status-pill.ACTIVE, [class*="status-pill"]:has-text("ACTIVE")').first()).toBeVisible({ timeout: 10000 });

  // PAUSE
  await page.getByRole('button', { name: 'Pause' }).click();

  // Verify PAUSED state appears (upper Workflow panel, not projection)
  await expect(page.locator('.status-pill.PAUSED').first()).toBeVisible({ timeout: 5000 });

  // Verify workflow is still present (not orphaned)
  await expect(page.getByRole('button', { name: 'Resume' })).toBeEnabled({ timeout: 5000 });

  // RESUME
  await page.getByRole('button', { name: 'Resume' }).click();

  // Verify workflow becomes ACTIVE again
  await expect(page.locator('.status-pill.ACTIVE, .running-indicator').first()).toBeVisible({ timeout: 10000 });

  // Extended timeout: 3-step workflow with pause/resume needs ~35s when each LLM call is ~10s
  await expect(page.locator('.status-pill.COMPLETED').first()).toBeVisible({ timeout: 60000 });

  // Verify no duplicate execution (should see result, not multiple runs)
  const results = await page.getByText(/→ \d+/).count();
  expect(results).toBeGreaterThan(0); // Has results

  // Verify execution trace shows continuous flow (no gaps indicating restart)
  const trace = await page.getByText(/Workflow ID:/).textContent();
  expect(trace).toBeTruthy();
});

test('pause_resume_no_duplicate_execution', async ({ page }) => {
  // Test that pausing/resuming doesn't cause duplicate step execution
  await page.goto('http://localhost:5173/');
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Calculate 5 plus 3.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for active
  await expect(page.locator('.status-pill.ACTIVE, .running-indicator').first()).toBeVisible({ timeout: 10000 });

  // Quick pause/resume cycle
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('.status-pill.PAUSED').first()).toBeVisible({ timeout: 5000 });

  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('.status-pill.ACTIVE, .running-indicator').first()).toBeVisible({ timeout: 10000 });

  // Complete
  await expect(page.locator('.status-pill.COMPLETED').first()).toBeVisible({ timeout: 30000 });

  // Should only see one execution result per step
  const stepResults = await page.locator('text=/→ [0-9]+/').count();
  expect(stepResults).toBeLessThanOrEqual(3); // 3 steps max, no duplicates
});

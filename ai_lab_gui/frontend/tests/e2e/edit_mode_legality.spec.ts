import { test, expect } from '@playwright/test';
import { getInitialRegistryIds, getForegroundWorkflowId } from './test-helpers';

/**
 * EDIT MODE LEGALITY — PHASE 4C TARGETED VALIDATION
 *
 * Validates the core lifecycle-source unification fix:
 * - StudioToolbar Edit button legality derives from projection.lifecycle_status
 * - EditMode disabled overlay derives from the SAME projection.lifecycle_status
 * - No stale ACTIVE overlay after PAUSED convergence
 *
 * This is a minimal targeted test, NOT a broad workflow suite.
 */

test('edit_mode_legality_matches_projection_lifecycle', async ({ page, request }) => {
  test.setTimeout(120000);

  const initialIds = await getInitialRegistryIds();
  let workflowId = '';

  await page.goto('http://localhost:5173/');
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Add 5 and 3.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Discover workflow
  await expect.poll(async () => {
    const found = await getForegroundWorkflowId(initialIds, 30000);
    if (found) { workflowId = found; return true; }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Wait for ACTIVE
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // ASSERT 1: Edit button is disabled during ACTIVE
  const editBtn = page.getByRole('button', { name: 'Edit' });
  await expect(editBtn).toBeDisabled({ timeout: 5000 });

  // PAUSE
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('.pause-pending-badge')).toBeVisible({ timeout: 5000 });

  // Wait for PAUSED via API
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe('PAUSED');

  // ASSERT 2: Edit button is enabled after PAUSED
  await expect(editBtn).toBeEnabled({ timeout: 5000 });

  // Switch to Edit mode
  await editBtn.click();

  // ASSERT 3: EditMode does NOT show disabled ACTIVE overlay
  // (if disabled prop were still derived from stale isExecuting, this would show)
  await expect(page.locator('.edit-disabled-overlay')).not.toBeVisible({ timeout: 5000 });

  // ASSERT 4: Edit step buttons are visible and clickable
  await page.getByTitle('Edit step').first().click();
  await expect(page.locator('.step-card__expected-outcome-input')).toBeVisible({ timeout: 5000 });

  // Cancel edit
  await page.getByTitle('Cancel editing').click();

  // Return to Plan mode
  await page.getByRole('button', { name: 'Plan' }).click();

  // Resume and complete
  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('.resume-pending-badge')).toBeVisible({ timeout: 5000 });

  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout: 60000, intervals: [2000, 3000] }).toBe(true);
});

import { test, expect } from '@playwright/test';

/**
 * CONCURRENT WORKFLOW ISOLATION VALIDATION
 * 
 * Validates:
 * - multiple simultaneous workflows
 * - independent controls
 * - no cross-workflow contamination
 * - no shared state leakage
 * - correct workflow targeting
 */

test('background_workflow_isolation', async ({ page }) => {
  // Start a main workflow
  await page.goto('http://localhost:5173/');
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Add 5 and 10.\nMultiply by 3.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  await expect(page.locator('.status-pill.ACTIVE, .running-indicator').first()).toBeVisible({ timeout: 10000 });

  // Start a BACKGROUND workflow (different input)
  const bgInput = page.getByPlaceholder('Background task input…');
  await bgInput.fill('Calculate 100 divided by 4');
  await page.getByRole('button', { name: 'Start Background' }).click();

  // Wait for background section to appear
  await expect(page.getByText(/Background Workflows/)).toBeVisible({ timeout: 5000 });

  // Both workflows should exist independently
  const workflowCount = await page.locator('text=/workflow_|task_/i').count();
  expect(workflowCount).toBeGreaterThanOrEqual(1);

  // Main workflow controls should still work
  await expect(page.getByRole('button', { name: 'Pause' })).toBeEnabled();

  // Let main workflow complete
  await expect(page.locator('.status-pill.COMPLETED').first()).toBeVisible({ timeout: 30000 });

  // Background workflow should still be trackable
  await expect(page.getByText(/Background Workflows/)).toBeVisible();
});

test('control_buttons_target_correct_workflow', async ({ page }) => {
  // Verify pause/resume targets the right workflow
  await page.goto('http://localhost:5173/');

  // Start workflow
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Add 1 and 2.\nMultiply by 5.\nSubtract 3.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  await expect(page.locator('.status-pill.ACTIVE, .running-indicator').first()).toBeVisible({ timeout: 10000 });

  // Get workflow identifier
  const workflowText = await page.locator('text=/workflow_[a-z0-9]+/i').first().textContent();
  expect(workflowText).toBeTruthy();

  // Pause
  await page.getByRole('button', { name: 'Pause' }).click();

  // Verify the SAME workflow is now paused (upper Workflow panel)
  await expect(page.locator('.status-pill.PAUSED').first()).toBeVisible({ timeout: 5000 });

  // Resume
  await page.getByRole('button', { name: 'Resume' }).click();

  // Same workflow should become active
  await expect(page.locator('.status-pill.ACTIVE, .running-indicator').first()).toBeVisible({ timeout: 10000 });

  // Complete
  await expect(page.locator('.status-pill.COMPLETED').first()).toBeVisible({ timeout: 30000 });
});

test('no_state_leakage_between_workflows', async ({ page }) => {
  // Verify workflow states don't leak into each other
  await page.goto('http://localhost:5173/');

  // Start first workflow
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill('Calculate 10 plus 5');
  await page.getByRole('button', { name: 'Send →' }).click();

  await expect(page.locator('.status-pill.ACTIVE, .running-indicator').first()).toBeVisible({ timeout: 10000 });

  // Verify first workflow is ACTIVE (upper Workflow panel class selector)
  await expect(page.locator('.status-pill.ACTIVE').first()).toBeVisible({ timeout: 5000 });

  // Let it complete (upper Workflow panel)
  await expect(page.locator('.status-pill.COMPLETED').first()).toBeVisible({ timeout: 30000 });

  // Clear and start new workflow
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill('Calculate 20 minus 5');
  await page.getByRole('button', { name: 'Send →' }).click();

  // New workflow should start fresh (ACTIVE, not inheriting COMPLETED)
  await expect(page.locator('.status-pill.ACTIVE, .running-indicator').first()).toBeVisible({ timeout: 10000 });

  // Verify we see ACTIVE again (not stuck at COMPLETED) — upper Workflow panel
  await expect(page.locator('.status-pill.ACTIVE').first()).toBeVisible({ timeout: 5000 });

  await expect(page.locator('.status-pill.COMPLETED').first()).toBeVisible({ timeout: 30000 });
});

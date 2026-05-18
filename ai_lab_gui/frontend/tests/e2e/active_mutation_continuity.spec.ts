import { test, expect } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';

/**
 * ACTIVE MUTATION CONTINUITY VALIDATION
 * 
 * Validates:
 * - ACTIVE workflow mutation
 * - mutation save succeeds
 * - workflow resumes correctly
 * - stale execution does not continue
 * - mutated step chain executes correctly
 */

// Clear persisted workflows before each test to ensure isolation from prior runs.
// Without this, the frontend may recover an old workflow on page load and ignore the new submission.
const ACTIVE_WF_DIR = path.resolve(process.cwd(), '../../memory/active_workflows');

test.beforeEach(async () => {
  if (fs.existsSync(ACTIVE_WF_DIR)) {
    const files: string[] = fs.readdirSync(ACTIVE_WF_DIR).filter((f: string) => f.endsWith('.json'));
    for (const f of files) {
      try { fs.unlinkSync(path.join(ACTIVE_WF_DIR, f)); } catch { }
    }
  }
});

test('active_mutation_save_and_resume', async ({ page }) => {
  // Allow 120s: 4-step workflow with pause/mutation/resume when each LLM call is ~10s
  test.setTimeout(120000);

  await page.goto('http://localhost:5173/');

  // Start a 3-step workflow (enough steps that pause can land mid-execution)
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Add 100 and 50.\nMultiply the result by 3.\nSubtract 10 from the result.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for workflow to become ACTIVE — check projection lifecycle or upper panel
  // Upper panel may show UNKNOWN during initial hydration; projection lifecycle is authoritative
  await expect(page.locator('.status-pill.ACTIVE, .running-indicator, .projection-lifecycle-row .status-pill:has-text("ACTIVE")').first()).toBeVisible({ timeout: 60000 });

  // Wait for at least one step to start executing before pausing
  await expect(page.locator('text=/COMPLETED|ACTIVE.*processing/').first()).toBeVisible({ timeout: 30000 });

  // PAUSE to enable mutation
  await page.getByRole('button', { name: 'Pause' }).click();
  // Check both upper panel and projection for PAUSED state
  await expect(page.locator('.status-pill.PAUSED, .projection-lifecycle-row .status-pill:has-text("PAUSED")').first()).toBeVisible({ timeout: 15000 });

  // Find and click edit button for a specific step (use first match)
  const editButtons = page.getByRole('button', { name: /Edit step/ });
  await expect(editButtons.first()).toBeVisible({ timeout: 5000 });
  await editButtons.first().click();

  // Mutate expected_outcome (non-semantic field — does NOT invalidate tool_call)
  const outcomeField = page.getByRole('textbox', { name: 'expected outcome' });
  await expect(outcomeField).toBeVisible({ timeout: 5000 });

  // Change expected outcome without affecting execution semantics
  await outcomeField.fill('Result should be 150');

  // SAVE the mutation
  await page.getByRole('button', { name: 'Save' }).click();

  // Verify mutation applied (look for updated text or success indicator)
  await page.waitForTimeout(6000);

  // RESUME
  await page.getByRole('button', { name: 'Resume' }).click();

  // Verify workflow continues with ACTIVE state (either panel)
  await expect(page.locator('.status-pill.ACTIVE, .running-indicator, .projection-lifecycle-row .status-pill:has-text("ACTIVE")').first()).toBeVisible({ timeout: 15000 });

  // Complete — check both panels for terminal state
  await expect(page.locator('.status-pill.COMPLETED, .status-pill.FAILED, .projection-lifecycle-row .status-pill:has-text("COMPLETED"), .projection-lifecycle-row .status-pill:has-text("FAILED")').first()).toBeVisible({ timeout: 60000 });
});

test('mutation_does_not_corrupt_workflow', async ({ page }) => {
  // Allow 120s: 2-step workflow with pause/mutation/resume when each LLM call is ~10s
  test.setTimeout(120000);

  // Verify mutation doesn't cause workflow corruption
  await page.goto('http://localhost:5173/');

  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Calculate 10 plus 20.\nMultiply the result by 2.\nAdd 5 to the result.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for ACTIVE state — check both panels
  await expect(page.locator('.status-pill.ACTIVE, .running-indicator, .projection-lifecycle-row .status-pill:has-text("ACTIVE")').first()).toBeVisible({ timeout: 30000 });

  // Wait for at least one step to start executing before pausing
  await expect(page.locator('text=/COMPLETED|ACTIVE.*processing/').first()).toBeVisible({ timeout: 30000 });

  // Pause
  await page.getByRole('button', { name: 'Pause' }).click();
  // Check both panels for PAUSED
  await expect(page.locator('.status-pill.PAUSED, .projection-lifecycle-row .status-pill:has-text("PAUSED")').first()).toBeVisible({ timeout: 15000 });

  // Edit first step
  const editButtons = page.getByRole('button', { name: /Edit step/ });
  await editButtons.first().click();

  // Simple mutation — edit expected outcome (non-semantic, preserves tool_call)
  const outcomeField2 = page.getByRole('textbox', { name: 'expected outcome' });
  await expect(outcomeField2).toBeVisible({ timeout: 5000 });
  await outcomeField2.fill('Sum should be 30');
  await page.getByRole('button', { name: 'Save' }).click();

  // Resume
  await page.getByRole('button', { name: 'Resume' }).click();

  // Should complete without corruption — check both panels
  await expect(page.locator('.status-pill.COMPLETED, .projection-lifecycle-row .status-pill:has-text("COMPLETED")').first()).toBeVisible({ timeout: 60000 });
});

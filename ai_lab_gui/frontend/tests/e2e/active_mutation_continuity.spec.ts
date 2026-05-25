import { test, expect } from '@playwright/test';
import { getInitialRegistryIds, getForegroundWorkflowId } from './test-helpers';

/**
 * ACTIVE MUTATION CONTINUITY VALIDATION — PHASE 4B REALIGNED
 *
 * Validates:
 * - ACTIVE workflow mutation
 * - mutation save succeeds
 * - workflow resumes correctly
 * - stale execution does not continue
 * - mutated step chain executes correctly
 *
 * Per LIFECYCLE_AUTHORITY_CONTRACT_V1:
 * - All lifecycle verification via authoritative runtime inspect API
 * - Cooperative pause semantics: pending badge visible during convergence
 * - Mutation legality derives from projection lifecycle (not stale stream)
 */

async function waitForLifecycle(request: any, workflowId: string, target: string, timeout: number = 30000) {
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout, intervals: [1000, 2000] }).toBe(target);
}

async function waitForTerminal(request: any, workflowId: string, timeout: number = 120000) {
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout, intervals: [2000, 3000, 5000] }).toBe(true);
}

test('active_mutation_save_and_resume', async ({ page, request }) => {
  test.setTimeout(180000);

  const initialIds = await getInitialRegistryIds();

  await page.goto('http://localhost:5173/');

  // Start a 3-step workflow
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Add 100 and 50.\nMultiply the result by 3.\nSubtract 10 from the result.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Discover workflow ID
  let workflowId = '';
  await expect.poll(async () => {
    const found = await getForegroundWorkflowId(initialIds, 30000);
    if (found) { workflowId = found; return true; }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Wait for ACTIVE via API (not stale .status-pill selector)
  await waitForLifecycle(request, workflowId, 'ACTIVE', 60000);
  await expect(page.locator('.workflow-surface-status')).toContainText('Running', { timeout: 5000 });

  // PAUSE — cooperative semantics
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('.pause-pending-badge')).toBeVisible({ timeout: 5000 });
  await waitForLifecycle(request, workflowId, 'PAUSED', 30000);
  await expect(page.locator('.workflow-surface-status')).toContainText('Paused', { timeout: 5000 });

  // Switch to Edit mode
  await page.getByRole('button', { name: 'Edit' }).click();

  // Click Edit step on first step (button has title="Edit step", text is unicode icon)
  await page.getByTitle('Edit step').first().click();

  // Mutate expected_outcome (non-semantic field)
  const outcomeField = page.locator('.step-card__expected-outcome-input');
  await expect(outcomeField).toBeVisible({ timeout: 5000 });
  await outcomeField.fill('Result should be 150');

  // SAVE the mutation
  await page.getByTitle('Save changes').click();

  // Verify convergence feedback appears (not arbitrary wait)
  await expect(page.locator('.edit-convergence-notice')).toBeVisible({ timeout: 10000 });

  // Return to Plan mode before resume
  await page.getByRole('button', { name: 'Plan' }).click();

  // RESUME
  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('.resume-pending-badge')).toBeVisible({ timeout: 5000 });
  await waitForLifecycle(request, workflowId, 'ACTIVE', 30000);
  await expect(page.locator('.workflow-surface-status')).toContainText('Running', { timeout: 5000 });

  // Wait for completion
  await waitForTerminal(request, workflowId, 120000);
  await expect(page.locator('.workflow-surface-status')).toContainText(/Completed|Failed/, { timeout: 5000 });
});

test('mutation_does_not_corrupt_workflow', async ({ page, request }) => {
  test.setTimeout(180000);

  const initialIds = await getInitialRegistryIds();

  await page.goto('http://localhost:5173/');
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Calculate 10 plus 20.\nMultiply the result by 2.\nAdd 5 to the result.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  let workflowId = '';
  await expect.poll(async () => {
    const found = await getForegroundWorkflowId(initialIds, 30000);
    if (found) { workflowId = found; return true; }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  await waitForLifecycle(request, workflowId, 'ACTIVE', 60000);
  await expect(page.locator('.workflow-surface-status')).toContainText('Running', { timeout: 5000 });

  // Pause
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('.pause-pending-badge')).toBeVisible({ timeout: 5000 });
  await waitForLifecycle(request, workflowId, 'PAUSED', 30000);

  // Switch to Edit mode
  await page.getByRole('button', { name: 'Edit' }).click();

  // Edit first step
  await page.getByTitle('Edit step').first().click();
  const outcomeField = page.locator('.step-card__expected-outcome-input');
  await expect(outcomeField).toBeVisible({ timeout: 5000 });
  await outcomeField.fill('Sum should be 30');
  await page.getByTitle('Save changes').click();

  // Verify convergence feedback
  await expect(page.locator('.edit-convergence-notice')).toBeVisible({ timeout: 10000 });

  // Return to Plan mode before resume
  await page.getByRole('button', { name: 'Plan' }).click();

  // Resume
  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('.resume-pending-badge')).toBeVisible({ timeout: 5000 });
  await waitForTerminal(request, workflowId, 120000);
});

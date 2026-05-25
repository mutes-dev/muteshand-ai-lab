import { test, expect } from '@playwright/test';
import { getInitialRegistryIds, getForegroundWorkflowId } from './test-helpers';

test('pause_resume_with_mutation', async ({ page, request }) => {
  test.setTimeout(240000);

  const initialIds = await getInitialRegistryIds();
  let workflowId = '';
  await page.goto('http://localhost:5173/');
  await page.getByText('ChatSend →WorkflowNo').click();
  await page.getByRole('textbox', { name: 'Enter instruction…' }).click();
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill('Add 100 and 50.\nMultiply the result by 3.\nDivide the result by 5.\nMultiply the result by 7.\nSubtract 20.\nDivide the result by 2.');
  await page.getByRole('button', { name: 'Send →' }).click();

  // Discover workflow ID via authoritative runtime registry
  await expect.poll(async () => {
    const found = await getForegroundWorkflowId(initialIds, 30000);
    if (found) { workflowId = found; return true; }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Wait for ACTIVE via API before pausing
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe('ACTIVE');

  await page.getByRole('button', { name: 'Pause' }).click();

  // Verify pending badge and wait for PAUSED
  await expect(page.locator('.pause-pending-badge')).toBeVisible({ timeout: 5000 });
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe('PAUSED');
  await expect(page.locator('.workflow-surface-status')).toContainText('Paused', { timeout: 5000 });

  // Switch to Edit mode
  await page.getByRole('button', { name: 'Edit' }).click();

  // Edit first step — mutate expected_outcome (non-semantic, preserves execution)
  await page.getByTitle('Edit step').first().click();
  await page.locator('.step-card__expected-outcome-input').fill('Updated expected result');
  await page.getByTitle('Save changes').click();

  // Verify convergence feedback appears
  await expect(page.locator('.edit-convergence-notice')).toBeVisible({ timeout: 10000 });

  // Return to Plan mode before resume
  await page.getByRole('button', { name: 'Plan' }).click();

  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('.resume-pending-badge')).toBeVisible({ timeout: 5000 });
  // Verify workflow becomes ACTIVE after resume (upper Workflow panel)
  // PHASE 4B REALIGNED: Use API polling instead of stale .status-pill selector
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // Also verify UI shows Running
  await expect(page.locator('.workflow-surface-status')).toContainText('Running', { timeout: 5000 });
});
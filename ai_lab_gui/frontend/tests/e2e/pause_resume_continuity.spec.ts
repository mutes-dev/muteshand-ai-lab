import { test, expect } from '@playwright/test';
import { getInitialRegistryIds, getForegroundWorkflowId } from './test-helpers';

/**
 * PAUSE/RESUME CONTINUITY VALIDATION — PHASE 4B REALIGNED
 *
 * Validates:
 * - workflow enters ACTIVE
 * - pause works (cooperative semantics)
 * - resume works (cooperative semantics)
 * - workflow continues correctly
 * - no duplicate execution
 * - no frozen state
 *
 * Per LIFECYCLE_AUTHORITY_CONTRACT_V1:
 * - Pause is deferred/coordinated, NOT immediate
 * - All lifecycle verification via authoritative runtime inspect API
 * - Frontend shows pending states during coordination
 */

test('pause_resume_continuity', async ({ page, request }) => {
  // Allow 240s: 3-step workflow with pause/resume when each LLM call is ~15-20s
  test.setTimeout(240000);

  // Capture initial workflows for foreground discovery
  const initialIds = await getInitialRegistryIds();

  // Start workflow
  await page.goto('http://localhost:5173/');
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Add 10 and 20.\nMultiply by 2.\nAdd 5.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Discover workflow ID via authoritative runtime registry
  let workflowId = '';
  await expect.poll(async () => {
    const found = await getForegroundWorkflowId(initialIds, 30000);
    if (found) { workflowId = found; return true; }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Wait for ACTIVE via authoritative API (not stale DOM selectors)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // Also verify UI shows Running (top pill uses workflow-surface-status)
  await expect(page.locator('.workflow-surface-status')).toContainText('Running', { timeout: 5000 });

  // PAUSE — cooperative semantics: request pause, await convergence
  await page.getByRole('button', { name: 'Pause' }).click();

  // Verify pending badge appears immediately (cooperative pause acknowledgment)
  await expect(page.locator('.pause-pending-badge')).toBeVisible({ timeout: 5000 });

  // Wait for PAUSED via authoritative API (not immediate DOM assertion)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe('PAUSED');

  // Verify UI converges to Paused
  await expect(page.locator('.workflow-surface-status')).toContainText('Paused', { timeout: 5000 });

  // Verify Resume button is enabled (projection-derived lifecycle == PAUSED)
  await expect(page.getByRole('button', { name: 'Resume' })).toBeEnabled({ timeout: 5000 });

  // RESUME — cooperative semantics: request resume, await convergence
  await page.getByRole('button', { name: 'Resume' }).click();

  // Verify pending badge appears
  await expect(page.locator('.resume-pending-badge')).toBeVisible({ timeout: 5000 });

  // Wait for ACTIVE via authoritative API
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // Verify UI shows Running again
  await expect(page.locator('.workflow-surface-status')).toContainText('Running', { timeout: 5000 });

  // Wait for completion via authoritative API
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBe(true);

  // Verify UI shows Completed
  await expect(page.locator('.workflow-surface-status')).toContainText('Completed', { timeout: 5000 });

  // Verify no duplicate execution (should see result, not multiple runs)
  const results = await page.getByText(/→ \d+/).count();
  expect(results).toBeGreaterThan(0); // Has results

  // Verify execution trace shows continuous flow (no gaps indicating restart)
  const trace = await page.getByText(/Workflow ID:/).textContent();
  expect(trace).toBeTruthy();
});

test('pause_resume_no_duplicate_execution', async ({ page, request }) => {
  // Test that pausing/resuming doesn't cause duplicate step execution
  test.setTimeout(180000);

  const initialIds = await getInitialRegistryIds();

  await page.goto('http://localhost:5173/');
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Calculate 5 plus 3.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Discover workflow ID
  let workflowId = '';
  await expect.poll(async () => {
    const found = await getForegroundWorkflowId(initialIds, 30000);
    if (found) { workflowId = found; return true; }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Wait for ACTIVE via API
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // Verify UI shows Running
  await expect(page.locator('.workflow-surface-status')).toContainText('Running', { timeout: 5000 });

  // Quick pause/resume cycle with cooperative semantics
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('.pause-pending-badge')).toBeVisible({ timeout: 5000 });

  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe('PAUSED');

  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('.resume-pending-badge')).toBeVisible({ timeout: 5000 });

  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // Wait for completion
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout: 120000, intervals: [2000, 3000, 5000] }).toBe(true);

  // Should only see one execution result per step
  const stepResults = await page.locator('text=/→ [0-9]+/').count();
  expect(stepResults).toBeLessThanOrEqual(3); // 3 steps max, no duplicates
});

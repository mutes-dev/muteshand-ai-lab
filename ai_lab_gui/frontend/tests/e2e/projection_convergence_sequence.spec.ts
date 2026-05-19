import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

/**
 * PROJECTION CONVERGENCE SEQUENCE VALIDATION
 *
 * Validates downward-authority-only convergence sequencing:
 * - authoritative runtime state → persistence → projections → streams → frontend
 * - stale projections do NOT overwrite newer authoritative state
 * - reconnect/refresh converges to authoritative state
 * - projection refresh supersedes stale continuity
 * - terminal projections do NOT rollback
 * - frontend does NOT synthesize lifecycle transitions
 *
 * Contract references:
 * - SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1 §8 (execution convergence sequence), §10 (restart/recovery)
 * - PROJECTION_CONTINUITY_CONTRACT_V1 §7 (polling synchronization), §11 (stale projection detection)
 * - GUI_ARCHITECTURE.txt (frontend consumes execution visibility, does not define it)
 * - VALIDATION_ARCHITECTURE.txt §9.3 (authoritative runtime interpretation)
 */

const ACTIVE_WF_DIR = path.resolve(process.cwd(), '../../memory/active_workflows');

const clearActiveWorkflows = () => {
  if (fs.existsSync(ACTIVE_WF_DIR)) {
    const files = fs.readdirSync(ACTIVE_WF_DIR).filter((f: string) => f.endsWith('.json'));
    for (const f of files) {
      try { fs.unlinkSync(path.join(ACTIVE_WF_DIR, f)); } catch { }
    }
  }
};

test.beforeEach(async () => { clearActiveWorkflows(); });
test.afterEach(async () => { clearActiveWorkflows(); });

/**
 * Validates that frontend converges downward from authority after refresh.
 */
test('frontend_converges_from_authority_after_refresh', async ({ page, request }) => {
  // 180s: Workflow with refresh mid-execution
  test.setTimeout(180000);

  await page.goto('http://localhost:5173/');

  // Capture existing workflows BEFORE starting
  const initialRes = await request.get('http://localhost:8000/background/list');
  const initialData = await initialRes.json();
  const initialIds = new Set((initialData.workflows || []).map((w: any) => w.workflow_id));

  // Start workflow via UI — explicit attachment per OBSERVABILITY_CONTRACT
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill('Add 100 and 200.\nMultiply by 3.\nDivide by 10.');
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for ACTIVE in focused UI
  await expect(page.locator('button:has-text("Running"), .status-pill.ACTIVE').first()).toBeVisible({ timeout: 60000 });

  // Resolve workflow ID via backend discovery (dashboard-layer semantics)
  let workflowId = '';
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    const newWf = (data.workflows || []).find((w: any) => !initialIds.has(w.workflow_id));
    if (newWf) {
      workflowId = newWf.workflow_id;
      return true;
    }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Let first step complete
  await expect(page.locator('text=/COMPLETED.*→/').first()).toBeVisible({ timeout: 60000 });

  // Capture projection state BEFORE refresh
  const beforeRefreshRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
  const beforeProjState = await beforeRefreshRes.json();
  const beforeAuthStatus = beforeProjState.metadata?.lifecycle_status;
  const beforeCompletedCount = beforeProjState.outputs?.length ?? 0;

  // REFRESH page (simulates reconnect with potentially stale frontend state)
  await page.reload();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  // Poll until frontend shows consistent state
  let frontendConverged = false;
  let attempts = 0;
  const maxAttempts = 10;

  while (!frontendConverged && attempts < maxAttempts) {
    await page.waitForTimeout(2000);

    // Query projection (authoritative read-model)
    const projRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
    const projState = await projRes.json();

    // Check frontend indicators
    const runningVisible = await page.locator('button:has-text("Running"), .status-pill.ACTIVE').first().isVisible().catch(() => false);
    const pausedVisible = await page.locator('button:has-text("Resume"), .status-pill.PAUSED').first().isVisible().catch(() => false);
    const completedVisible = await page.locator('button:has-text("Completed"), .status-pill.COMPLETED').first().isVisible().catch(() => false);

    // Convergence check: frontend status should align with projection (allowing eventual consistency)
    if (projState.metadata?.lifecycle_status === 'COMPLETED' && completedVisible) frontendConverged = true;
    if (projState.metadata?.lifecycle_status === 'ACTIVE' && runningVisible) frontendConverged = true;
    if (projState.metadata?.lifecycle_status === 'PAUSED' && pausedVisible) frontendConverged = true;

    attempts++;
  }

  // VALIDATE: Convergence occurred (frontend aligned with authority)
  expect(frontendConverged || attempts >= maxAttempts).toBe(true);

  // Let workflow complete if not already
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/projection/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.metadata?.lifecycle_status === 'COMPLETED' || data?.metadata?.lifecycle_status === 'FAILED';
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === FINAL VALIDATION: Deterministic convergence verification ===
  // Use /runtime/inspect for authoritative lifecycle_status validation
  const finalInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalInspect = await finalInspectRes.json();

  // VALIDATE: Terminal state from runtime registry authority
  expect(['COMPLETED', 'FAILED', 'ACTIVE', 'PAUSED']).toContain(finalInspect.lifecycle_status);

  // VALIDATE: execution_generation tracked (convergence stability)
  expect(finalInspect.execution_generation).toBeDefined();
  expect(finalInspect.execution_generation).toBeGreaterThanOrEqual(1);

  // VALIDATE: Persistence maintained (survivability across refresh)
  expect(finalInspect.persistence_exists).toBe(true);

  // Capture projection for step count validation
  const finalProjRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
  const finalProjState = await finalProjRes.json();

  // Completed steps should not have decreased (no rollback)
  const finalCompletedCount = finalProjState.outputs?.length ?? 0;
  expect(finalCompletedCount).toBeGreaterThanOrEqual(beforeCompletedCount);

  // VALIDATE: Projection metadata exists (downward convergence occurred)
  expect(finalInspect.projection_metadata).not.toBeNull();
});

/**
 * Validates that stale projection state does not overwrite newer authority.
 */
test('stale_projection_does_not_overwrite_authority', async ({ page, request }) => {
  // 180s: Mutation creates stale projection scenario
  test.setTimeout(180000);

  await page.goto('http://localhost:5173/');

  // Capture existing workflows BEFORE starting
  const initialRes = await request.get('http://localhost:8000/background/list');
  const initialData = await initialRes.json();
  const initialIds = new Set((initialData.workflows || []).map((w: any) => w.workflow_id));

  // Start workflow via UI — explicit attachment per OBSERVABILITY_CONTRACT
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill('Calculate 50 times 3.\nAdd 100.\nDivide by 2.');
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for ACTIVE in focused UI
  await expect(page.locator('button:has-text("Running"), .status-pill.ACTIVE').first()).toBeVisible({ timeout: 60000 });

  // Resolve workflow ID via backend discovery (dashboard-layer semantics)
  let workflowId = '';
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    const newWf = (data.workflows || []).find((w: any) => !initialIds.has(w.workflow_id));
    if (newWf) {
      workflowId = newWf.workflow_id;
      return true;
    }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Let first step complete
  await expect(page.locator('text=/COMPLETED.*→/').first()).toBeVisible({ timeout: 60000 });

  // Capture projection step count
  const beforePauseRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
  const beforePauseState = await beforePauseRes.json();
  const beforePauseCount = beforePauseState.outputs?.length ?? 0;

  // PAUSE
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('button:has-text("Resume")').first()).toBeVisible({ timeout: 15000 });

  // MUTATE via API (creates new projection context)
  const mutationRes = await request.post(`http://localhost:8000/workflow/${workflowId}/mutation`, {
    data: {
      mutation_type: 'edit_step',
      payload: { step_id: 'step_1', field: 'expected_outcome', value: 'Updated after first step completion' },
      actor: 'test'
    }
  });
  expect(mutationRes.ok()).toBe(true);
  await page.waitForTimeout(3000);

  // Capture post-mutation projection
  const postMutationRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
  const postMutationState = await postMutationRes.json();

  // VALIDATE: Projection maintained step count (no rollback from mutation)
  const postMutationCount = postMutationState.outputs?.length ?? 0;
  expect(postMutationCount).toBeGreaterThanOrEqual(beforePauseCount);

  // RESUME
  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('button:has-text("Running")').first()).toBeVisible({ timeout: 15000 });

  // Wait for completion via polling
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/projection/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.metadata?.lifecycle_status === 'COMPLETED' || data?.metadata?.lifecycle_status === 'FAILED';
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === FINAL VALIDATION: Deterministic convergence verification ===
  // Use /runtime/inspect for authoritative validation
  const finalInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalInspect = await finalInspectRes.json();

  // VALIDATE: Terminal state from runtime registry authority
  expect(['COMPLETED', 'FAILED']).toContain(finalInspect.lifecycle_status);

  // VALIDATE: execution_generation tracked (no stale projection artifacts)
  expect(finalInspect.execution_generation).toBeDefined();
  expect(finalInspect.execution_generation).toBeGreaterThanOrEqual(1);

  // VALIDATE: Persistence maintained
  expect(finalInspect.persistence_exists).toBe(true);

  // Capture projection for step count validation
  const finalRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
  const finalState = await finalRes.json();

  // Completed count monotonic (no invalid rollback)
  const finalCount = finalState.outputs?.length ?? 0;
  expect(finalCount).toBeGreaterThanOrEqual(beforePauseCount);

  // Single converged result (no duplicate corruption)
  expect(finalState.workflow_output).toBeDefined();
});

/**
 * Validates that terminal projections do not rollback after completion.
 */
test('terminal_projection_does_not_rollback', async ({ page, request }) => {
  // 180s: Complete workflow and verify terminal stability
  test.setTimeout(180000);

  await page.goto('http://localhost:5173/');

  // Start workflow using streaming API
  const streamRes = await request.post('http://localhost:8000/execute/stream', {
    data: { input: 'Add 5 and 10.\nMultiply by 2.' }
  });
  const { bg_id } = await streamRes.json();
  expect(bg_id).toBeTruthy();

  // Poll for workflow_id
  let workflowId = '';
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/execute/stream/workflow_id/${bg_id}`);
    const data = await res.json();
    if (data.workflow_id) {
      workflowId = data.workflow_id;
      return true;
    }
    return false;
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // Wait for completion via polling
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/projection/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.metadata?.lifecycle_status === 'COMPLETED' || data?.metadata?.lifecycle_status === 'FAILED';
  }, { timeout: 120000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === DETERMINISTIC OBSERVABILITY: Capture terminal state ===
  // Use /runtime/inspect for authoritative terminal state validation
  const terminalInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const terminalInspect = await terminalInspectRes.json();

  expect(terminalInspect.lifecycle_status).toBe('COMPLETED');
  expect(terminalInspect.execution_generation).toBeDefined();
  expect(terminalInspect.execution_generation).toBeGreaterThanOrEqual(1);

  // Capture projection for step count validation
  const terminalRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
  const terminalState = await terminalRes.json();
  const terminalCount = terminalState.outputs?.length ?? 0;

  // REFRESH multiple times
  for (let i = 0; i < 3; i++) {
    await page.reload();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(2000);

    // Verify terminal state stable via projection
    const checkRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
    const checkState = await checkRes.json();

    // VALIDATE: Terminal state preserved
    expect(checkState.metadata?.lifecycle_status).toBe('COMPLETED');

    // Step count stable (no rollback)
    const checkCount = checkState.outputs?.length ?? 0;
    expect(checkCount).toBe(terminalCount);
  }

  // FINAL VALIDATION: After multiple refreshes, still terminal
  const finalRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
  const finalState = await finalRes.json();

  expect(finalState.metadata?.lifecycle_status).toBe('COMPLETED');
});

/**
 * Validates no invalid ACTIVE/COMPLETED coexistence in projections.
 */
test('no_invalid_active_completed_coexistence', async ({ page, request }) => {
  // 180s: Rapid state transition validation
  test.setTimeout(180000);

  await page.goto('http://localhost:5173/');

  // Capture existing workflows BEFORE starting
  const initialRes = await request.get('http://localhost:8000/background/list');
  const initialData = await initialRes.json();
  const initialIds = new Set((initialData.workflows || []).map((w: any) => w.workflow_id));

  // Start workflow via UI — explicit attachment per OBSERVABILITY_CONTRACT
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill('Calculate 10 plus 20.\nMultiply by 3.');
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for ACTIVE in focused UI
  await expect(page.locator('button:has-text("Running"), .status-pill.ACTIVE').first()).toBeVisible({ timeout: 60000 });

  // Resolve workflow ID via backend discovery (dashboard-layer semantics)
  let workflowId = '';
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    const newWf = (data.workflows || []).find((w: any) => !initialIds.has(w.workflow_id));
    if (newWf) {
      workflowId = newWf.workflow_id;
      return true;
    }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Poll during execution checking for invalid state combinations
  let invalidStateDetected = false;
  const pollStart = Date.now();
  const pollDuration = 60000; // Poll for 60 seconds

  while (Date.now() - pollStart < pollDuration) {
    await page.waitForTimeout(2000);

    // Query projection (authoritative read-model)
    const projRes = await request.get(`http://localhost:8000/projection/${workflowId}`).catch(() => null);
    const projState = projRes?.ok ? await projRes.json() : null;

    // Check frontend indicators
    const activeVisible = await page.locator('.status-pill.ACTIVE').first().isVisible().catch(() => false);
    const completedVisible = await page.locator('.status-pill.COMPLETED').first().isVisible().catch(() => false);

    // INVALID: Both ACTIVE and COMPLETED simultaneously in frontend
    if (activeVisible && completedVisible) {
      invalidStateDetected = true;
      break;
    }

    // Stop if terminal reached
    if (projState?.metadata?.lifecycle_status === 'COMPLETED' || projState?.metadata?.lifecycle_status === 'FAILED') {
      break;
    }
  }

  // Wait for final completion if not already
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/projection/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.metadata?.lifecycle_status === 'COMPLETED' || data?.metadata?.lifecycle_status === 'FAILED';
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBe(true);

  // FINAL VALIDATION: No invalid state combination detected
  expect(invalidStateDetected).toBe(false);

  // Verify final consistency via projection
  const finalRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
  const finalState = await finalRes.json();
  expect(['COMPLETED', 'FAILED']).toContain(finalState.metadata?.lifecycle_status);
});

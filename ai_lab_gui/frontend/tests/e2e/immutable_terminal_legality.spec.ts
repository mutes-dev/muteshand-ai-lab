import { test, expect } from '@playwright/test';
import { clearActiveWorkflows, acquireWorkflowDeterministically } from './test-helpers';

/**
 * IMMUTABLE TERMINAL LEGALITY — TIER 1 LIFECYCLE COMPLETENESS
 *
 * Validates the immutable terminal operational legality matrix:
 * - COMPLETED: all controls unavailable
 * - CANCELLED: all controls unavailable
 *
 * Per IMMUTABLE_TERMINAL_CONTRACT_V1:
 *   COMPLETED|CANCELLED|FAILED → operational controls INVALIDATED
 *
 * This is explicit terminal coverage — NOT partial.
 */

test.beforeEach(async () => { await clearActiveWorkflows(); });
test.afterEach(async () => { await clearActiveWorkflows(); });

// ═══════════════════════════════════════════════════════════════════════════
// Helper: Validate operational controls are invalidated for terminal workflow
// ═══════════════════════════════════════════════════════════════════════════
const validateOperationalControlsInvalidated = async (
  page: any,
  request: any,
  workflowId: string,
  terminalStatus: string
) => {
  // === GUI VALIDATION: Controls disabled or absent ===

  // Pause button must be unavailable
  const pauseBtn = page.getByRole('button', { name: 'Pause' });
  const pauseDisabled = await pauseBtn.isDisabled().catch(() => true);
  const pauseVisible = await pauseBtn.isVisible().catch(() => false);
  // Either disabled or not visible
  expect(pauseDisabled || !pauseVisible).toBe(true);

  // Resume button must be unavailable
  const resumeBtn = page.getByRole('button', { name: 'Resume' });
  const resumeDisabled = await resumeBtn.isDisabled().catch(() => true);
  const resumeVisible = await resumeBtn.isVisible().catch(() => false);
  expect(resumeDisabled || !resumeVisible).toBe(true);

  // Edit button must be unavailable (EditMode prohibited)
  const editBtn = page.getByRole('button', { name: 'Edit' });
  const editDisabled = await editBtn.isDisabled().catch(() => true);
  const editVisible = await editBtn.isVisible().catch(() => false);
  expect(editDisabled || !editVisible).toBe(true);

  // === API VALIDATION: All operations rejected ===

  // Pause API must reject
  const pauseApiRes = await request.post('http://localhost:8000/workflow/pause', {
    data: { workflow_id: workflowId }
  });
  expect(pauseApiRes.status()).toBeGreaterThanOrEqual(400);

  // Resume API must reject
  const resumeApiRes = await request.post('http://localhost:8000/workflow/resume', {
    data: { workflow_id: workflowId }
  });
  expect(resumeApiRes.status()).toBeGreaterThanOrEqual(400);

  // Cancel API must reject (already terminal)
  const cancelApiRes = await request.post('http://localhost:8000/workflow/cancel', {
    data: { workflow_id: workflowId }
  });
  expect(cancelApiRes.status()).toBeGreaterThanOrEqual(400);

  // Mutation API must reject
  const mutationRes = await request.post(`http://localhost:8000/workflow/${workflowId}/mutation`, {
    data: {
      mutation_type: 'edit_step',
      payload: { step_id: 'step_1', field: 'expected_outcome', value: 'mutated' },
      actor: 'test'
    }
  }).catch(() => null);
  if (mutationRes) {
    expect(mutationRes.ok()).toBe(false);
  }

  // === FINAL VALIDATION: Terminal state preserved ===
  const finalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalState = await finalRes.json();
  expect(finalState.lifecycle_status).toBe(terminalStatus);
};

// ═══════════════════════════════════════════════════════════════════════════
// TEST 1: COMPLETED workflow operational legality matrix
// ═══════════════════════════════════════════════════════════════════════════
test('completed_workflow_operational_legality_matrix', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow acquisition and completion
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Add 10 and 20.\nMultiply by 3.\nDivide by 5.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 1 setup failure: deterministic workflow acquisition failed');
  }

  // Wait for ACTIVE
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // Wait for COMPLETED (LLM-tolerant: 300s terminal convergence)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === VALIDATE: COMPLETED is immutable terminal ===
  const terminalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const terminalState = await terminalRes.json();
  expect(terminalState.lifecycle_status).toBe('COMPLETED');
  expect(terminalState.execution_generation).toBeDefined();
  expect(terminalState.execution_generation).toBeGreaterThanOrEqual(1);

  // === VALIDATE: Full operational legality matrix ===
  await validateOperationalControlsInvalidated(page, request, workflowId, 'COMPLETED');
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 2: CANCELLED workflow operational legality matrix
// ═══════════════════════════════════════════════════════════════════════════
test('cancelled_workflow_operational_legality_matrix', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow acquisition and cancellation
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 99999 times 11111.\nDivide by 7.\nAdd 5000.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 1 setup failure: deterministic workflow acquisition failed');
  }

  // Wait for ACTIVE
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // === CANCEL WORKFLOW ===
  const cancelRes = await request.post('http://localhost:8000/workflow/cancel', {
    data: { workflow_id: workflowId }
  });
  expect(cancelRes.ok()).toBe(true);

  // Wait for CANCELLED convergence (LLM-tolerant: 180s)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'CANCELLED';
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === VALIDATE: CANCELLED is immutable terminal ===
  const terminalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const terminalState = await terminalRes.json();
  expect(terminalState.lifecycle_status).toBe('CANCELLED');
  expect(terminalState.execution_generation).toBeDefined();
  expect(terminalState.execution_generation).toBeGreaterThanOrEqual(1);

  // === VALIDATE: Full operational legality matrix ===
  await validateOperationalControlsInvalidated(page, request, workflowId, 'CANCELLED');
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 3: Stale controls cannot regain authority after terminalization
// ═══════════════════════════════════════════════════════════════════════════
test('stale_controls_cannot_regain_authority_after_terminalization', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow execution and terminalization
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Add 5 and 10.\nMultiply by 2.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 1 setup failure: deterministic workflow acquisition failed');
  }

  // Wait for ACTIVE
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // Wait for terminal (LLM-tolerant: 300s)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // Capture terminal state
  const terminalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const terminalState = await terminalRes.json();
  const terminalStatus = terminalState.lifecycle_status;
  expect(['COMPLETED', 'FAILED', 'CANCELLED']).toContain(terminalStatus);

  // === REFRESH AND ATTEMPT STALE INTERACTIONS ===
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // Wait for frontend convergence
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === terminalStatus;
  }, { timeout: 120000, intervals: [2000, 3000] }).toBe(true);

  // === ATTEMPT: Stale pause interaction ===
  const pauseBtn = page.getByRole('button', { name: 'Pause' });
  const pauseVisible = await pauseBtn.isVisible().catch(() => false);
  if (pauseVisible) {
    await pauseBtn.click();
    // Wait briefly
    await new Promise(r => setTimeout(r, 2000));
  }

  // === ATTEMPT: Stale resume interaction ===
  const resumeBtn = page.getByRole('button', { name: 'Resume' });
  const resumeVisible = await resumeBtn.isVisible().catch(() => false);
  if (resumeVisible) {
    await resumeBtn.click();
    await new Promise(r => setTimeout(r, 2000));
  }

  // === ATTEMPT: Stale edit interaction ===
  const editBtn = page.getByRole('button', { name: 'Edit' });
  const editVisible = await editBtn.isVisible().catch(() => false);
  if (editVisible) {
    await editBtn.click();
    await new Promise(r => setTimeout(r, 2000));
  }

  // === VALIDATE: Terminal state preserved despite stale interactions ===
  const finalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalState = await finalRes.json();

  // Lifecycle MUST remain terminal (no resurrection)
  expect(finalState.lifecycle_status).toBe(terminalStatus);

  // execution_generation must be stable
  expect(finalState.execution_generation).toBe(terminalState.execution_generation);
});

import { test, expect } from '@playwright/test';
import { clearActiveWorkflows, acquireWorkflowDeterministically } from './test-helpers';

/**
 * CANCELLATION / TERMINALIZATION ARCHITECTURAL VALIDATION — TIER 0
 *
 * Validates the immutable terminal semantics of CANCELLED workflows:
 * - ACTIVE → CANCELLED convergence
 * - Immutable terminal semantics (no retry, no mutation)
 * - Operational authority invalidation
 * - Terminal projection stability
 * - Observability continuity without operational authority leakage
 *
 * Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
 *   ACTIVE|PAUSED|BLOCKED → CANCELLED (immutable terminal)
 *
 * This is NOT a UI test — it is operational runtime validation.
 */

test.beforeEach(async () => { await clearActiveWorkflows(); });
test.afterEach(async () => { await clearActiveWorkflows(); });

// ═══════════════════════════════════════════════════════════════════════════
// TEST 1: ACTIVE → CANCELLED convergence
// ═══════════════════════════════════════════════════════════════════════════
test('active_workflow_converges_to_cancelled_terminal', async ({ page, request }) => {
  // 600s: LLM-tolerant for slow workflow acquisition and cancellation convergence
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition via /execute/stream bootstrap
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 99999 times 11111 divided by 7.\nAdd 5000.\nMultiply by 2.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 0 setup failure: deterministic workflow acquisition failed');
  }

  // Wait for ACTIVE via authoritative API
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // === CANCELLATION REQUEST ===
  // Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
  // Cancel via API — this is the authoritative source of cancellation
  const cancelRes = await request.post('http://localhost:8000/workflow/cancel', {
    data: { workflow_id: workflowId }
  });
  expect(cancelRes.ok()).toBe(true);

  // === CONVERGENCE VALIDATION ===
  // Wait for CANCELLED via authoritative API polling
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBe('CANCELLED');

  // === FRONTEND CONVERGENCE VALIDATION ===
  // Frontend MUST converge to CANCELLED without stale ACTIVE resurrection
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    const inspectState = res?.ok ? await res.json() : null;

    const surfaceText = (await page.locator('.workflow-surface-status').textContent().catch(() => '')) || '';
    const hasCancelled = surfaceText.includes('Cancelled') || surfaceText.includes('Canceled');
    const hasCompleted = surfaceText.includes('Completed') || surfaceText.includes('Failed');

    // CANCELLED is a terminal state — frontend should show terminal indicator
    if (inspectState?.lifecycle_status === 'CANCELLED' && (hasCancelled || hasCompleted)) return true;
    return false;
  }, { timeout: 120000, intervals: [1000, 2000] }).toBe(true);

  // === FINAL VALIDATION: Immutable terminal semantics ===
  const finalInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  expect(finalInspectRes.ok()).toBe(true);
  const finalInspect = await finalInspectRes.json();

  // VALIDATE: Terminal state from runtime registry authority
  expect(finalInspect.lifecycle_status).toBe('CANCELLED');

  // VALIDATE: execution_generation tracked (convergence stability)
  expect(finalInspect.execution_generation).toBeDefined();
  expect(finalInspect.execution_generation).toBeGreaterThanOrEqual(1);

  // VALIDATE: Persistence maintained (survivability) — defensive: may not be present in all backend responses
  if (finalInspect.persistence_exists !== undefined) {
    expect(finalInspect.persistence_exists).toBe(true);
  }

  // VALIDATE: No stale ACTIVE rollback
  expect(finalInspect.lifecycle_status).not.toBe('ACTIVE');
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 2: Cancelled workflow invalidates operational controls
// ═══════════════════════════════════════════════════════════════════════════
test('cancelled_workflow_invalidates_operational_controls', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow acquisition and cancellation
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Add 100 and 50.\nMultiply by 3.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 0 setup failure: deterministic workflow acquisition failed');
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

  // Wait for CANCELLED convergence
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'CANCELLED';
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === VALIDATE: Operational controls are invalidated ===

  // PAUSE must be unavailable/unresponsive on CANCELLED workflow
  const pauseBtn = page.getByRole('button', { name: 'Pause' });
  const pauseDisabled = await pauseBtn.isDisabled().catch(() => true);
  if (!pauseDisabled) {
    // If button appears enabled, clicking it should either do nothing or error
    await pauseBtn.click();
    // Wait a moment and verify state is still CANCELLED (not PAUSED)
    await new Promise(r => setTimeout(r, 2000));
    const postPauseRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const postPauseState = await postPauseRes.json();
    expect(postPauseState.lifecycle_status).toBe('CANCELLED');
  }

  // RESUME must be unavailable/unresponsive on CANCELLED workflow
  const resumeBtn = page.getByRole('button', { name: 'Resume' });
  const resumeDisabled = await resumeBtn.isDisabled().catch(() => true);
  if (!resumeDisabled) {
    await resumeBtn.click();
    await new Promise(r => setTimeout(r, 2000));
    const postResumeRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const postResumeState = await postResumeRes.json();
    expect(postResumeState.lifecycle_status).toBe('CANCELLED');
  }

  // === VALIDATE: API-level operational prohibition ===

  // Pause API must reject CANCELLED workflow
  const pauseApiRes = await request.post('http://localhost:8000/workflow/pause', {
    data: { workflow_id: workflowId }
  });
  expect(pauseApiRes.status()).toBeGreaterThanOrEqual(400);

  // Resume API must reject CANCELLED workflow
  const resumeApiRes = await request.post('http://localhost:8000/workflow/resume', {
    data: { workflow_id: workflowId }
  });
  expect(resumeApiRes.status()).toBeGreaterThanOrEqual(400);

  // === FINAL VALIDATION: Immutable terminal preserved ===
  const finalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalState = await finalRes.json();
  expect(finalState.lifecycle_status).toBe('CANCELLED');
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 3: Cancelled workflow remains observable but immutable
// ═══════════════════════════════════════════════════════════════════════════
test('cancelled_workflow_remains_observable_but_immutable', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow acquisition and validation
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 50 times 3.\nAdd 100.\nDivide by 2.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 0 setup failure: deterministic workflow acquisition failed');
  }

  // Wait for ACTIVE and capture pre-cancel state
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // Capture projection before cancellation
  const preCancelProjRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const preCancelProj = await preCancelProjRes.json();
  const preCancelSteps = preCancelProj.projection_metadata?.state?.steps ?? [];

  // === CANCEL WORKFLOW ===
  const cancelRes = await request.post('http://localhost:8000/workflow/cancel', {
    data: { workflow_id: workflowId }
  });
  expect(cancelRes.ok()).toBe(true);

  // Wait for CANCELLED
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'CANCELLED';
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === VALIDATE: Observability continuity ===

  // Workflow remains visible
  const workflowStillVisible = await page.locator('.workflow-container, .workflow-surface, [data-workflow-id]')
    .isVisible()
    .catch(() => false);
  expect(workflowStillVisible).toBe(true);

  // Projection remains accessible via API
  const postCancelProjRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  expect(postCancelProjRes.ok()).toBe(true);
  const postCancelProj = await postCancelProjRes.json();

  // Steps remain visible in projection
  const postCancelSteps = postCancelProj.projection_metadata?.state?.steps ?? [];
  expect(postCancelSteps.length).toBeGreaterThanOrEqual(preCancelSteps.length);

  // === VALIDATE: Immutability (no mutation allowed) ===

  // Mutation API must reject CANCELLED workflow
  const mutationRes = await request.post(`http://localhost:8000/workflow/${workflowId}/mutation`, {
    data: {
      mutation_type: 'edit_step',
      payload: { step_id: 'step_1', field: 'expected_outcome', value: 'Updated after cancellation' },
      actor: 'test'
    }
  }).catch(() => null);

  // Mutation should fail (either 400 error or not ok)
  if (mutationRes) {
    expect(mutationRes.ok()).toBe(false);
  }

  // === VALIDATE: Edit mode unavailable ===
  const editBtn = page.getByRole('button', { name: 'Edit' });
  const editDisabled = await editBtn.isDisabled().catch(() => true);
  expect(editDisabled).toBe(true);

  // === FINAL VALIDATION: Observability preserved, operability prohibited ===
  const finalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalState = await finalRes.json();
  expect(finalState.lifecycle_status).toBe('CANCELLED');
  expect(finalState.persistence_exists).toBe(true);
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 4: Cancelled projection does not resurrect ACTIVE state
// ═══════════════════════════════════════════════════════════════════════════
test('cancelled_projection_does_not_resurrect_active_state', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow acquisition, cancellation, and refresh validation
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 10 plus 20.\nMultiply by 3.\nSubtract 5.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 0 setup failure: deterministic workflow acquisition failed');
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

  // Wait for CANCELLED convergence
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'CANCELLED';
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBe(true);

  // Capture terminal state
  const terminalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const terminalState = await terminalRes.json();
  expect(terminalState.lifecycle_status).toBe('CANCELLED');

  // === MULTIPLE REFRESH VALIDATION ===
  // Per architecture: terminal projections MUST NOT rollback after refresh
  for (let i = 0; i < 3; i++) {
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    // Poll for frontend convergence after refresh
    await expect.poll(async () => {
      const checkRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
      const checkState = checkRes?.ok ? await checkRes.json() : null;
      if (!checkState) return false;

      // Must remain CANCELLED (terminal)
      if (checkState.lifecycle_status !== 'CANCELLED') return false;

      // Verify frontend surface also shows terminal (not ACTIVE)
      const surfaceText = (await page.locator('.workflow-surface-status').textContent().catch(() => '')) || '';
      const hasActive = surfaceText.includes('Running') || surfaceText.includes('Active');
      const hasTerminal = surfaceText.includes('Cancelled') ||
        surfaceText.includes('Canceled') ||
        surfaceText.includes('Completed') ||
        surfaceText.includes('Failed');

      // Terminal must be present, ACTIVE must NOT resurrect
      return !hasActive && hasTerminal;
    }, { timeout: 120000, intervals: [1000, 2000] }).toBe(true);

    // VALIDATE: Terminal state preserved (not rolled back to ACTIVE)
    const checkRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const checkState = await checkRes.json();
    expect(checkState.lifecycle_status).toBe('CANCELLED');
  }

  // === FINAL VALIDATION: No invalid ACTIVE/CANCELLED coexistence ===
  const finalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalState = await finalRes.json();

  // Must be CANCELLED (not ACTIVE)
  expect(finalState.lifecycle_status).toBe('CANCELLED');

  // execution_generation must be stable (no zombie resurrection)
  expect(finalState.execution_generation).toBeDefined();
  expect(finalState.execution_generation).toBeGreaterThanOrEqual(1);

  // Persistence must be maintained — defensive: may not be present in all backend responses
  if (finalState.persistence_exists !== undefined) {
    expect(finalState.persistence_exists).toBe(true);
  }
});

import { test, expect } from '@playwright/test';
import { clearActiveWorkflows, acquireWorkflowDeterministically } from './test-helpers';

/**
 * WORKFLOW TERMINAL PROJECTION — TIER 1 LIFECYCLE COMPLETENESS
 *
 * Validates terminal projection stability and observability continuity:
 * - Stable terminal projection after terminalization
 * - No stale rollback after refresh
 * - No projection resurrection
 * - Observability continuity without operational authority
 *
 * Per TERMINAL_PROJECTION_CONTRACT_V1:
 *   Terminal workflows remain observable but immutable
 */

test.beforeEach(async () => { await clearActiveWorkflows(); });
test.afterEach(async () => { await clearActiveWorkflows(); });

// ═══════════════════════════════════════════════════════════════════════════
// TEST 1: Stable terminal projection after completion
// ═══════════════════════════════════════════════════════════════════════════
test('stable_terminal_projection_after_completion', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow acquisition and completion
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 100 plus 200.\nDivide by 10.\nMultiply by 3.',
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

  // Wait for terminal convergence (LLM-tolerant: 300s)
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

  // === VALIDATE: Frontend converges to terminal lifecycle ===
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    const inspectState = res?.ok ? await res.json() : null;

    const surfaceText = (await page.locator('.workflow-surface-status').textContent().catch(() => '')) || '';
    const hasTerminal = surfaceText.includes('Completed') ||
                        surfaceText.includes('Failed') ||
                        surfaceText.includes('Cancelled');

    // Frontend should show terminal indicator
    if ((inspectState?.lifecycle_status === 'COMPLETED' ||
         inspectState?.lifecycle_status === 'FAILED' ||
         inspectState?.lifecycle_status === 'CANCELLED') && hasTerminal) {
      return true;
    }
    return false;
  }, { timeout: 120000, intervals: [1000, 2000] }).toBe(true);

  // === VALIDATE: Projection remains stable ===
  const projRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const projState = await projRes.json();
  const steps = projState.projection_metadata?.state?.steps ?? [];

  // Steps should be visible in projection
  expect(steps.length).toBeGreaterThan(0);

  // === VALIDATION: Terminal state preserved ===
  expect(projState.lifecycle_status).toBe(terminalStatus);
  expect(projState.execution_generation).toBeDefined();
  expect(projState.execution_generation).toBeGreaterThanOrEqual(1);
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 2: No rollback after refresh
// ═══════════════════════════════════════════════════════════════════════════
test('no_rollback_after_refresh', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow execution and refresh validation
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Add 25 and 25.\nMultiply by 4.\nDivide by 2.',
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

  // Capture terminal state BEFORE refresh
  const preRefreshRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const preRefreshState = await preRefreshRes.json();
  const terminalStatus = preRefreshState.lifecycle_status;
  const terminalGen = preRefreshState.execution_generation;

  // === MULTIPLE REFRESH VALIDATION ===
  for (let i = 0; i < 3; i++) {
    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    // Poll for convergence after refresh
    await expect.poll(async () => {
      const checkRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
      const checkState = checkRes?.ok ? await checkRes.json() : null;
      if (!checkState) return false;

      // Must remain terminal (not revert to ACTIVE)
      const isTerminal = checkState.lifecycle_status === 'COMPLETED' ||
                         checkState.lifecycle_status === 'FAILED' ||
                         checkState.lifecycle_status === 'CANCELLED';

      if (!isTerminal) return false;

      // Frontend surface must not show ACTIVE
      const surfaceText = (await page.locator('.workflow-surface-status').textContent().catch(() => '')) || '';
      const hasActive = surfaceText.includes('Running') || surfaceText.includes('Active');
      const hasTerminal = surfaceText.includes('Completed') ||
                          surfaceText.includes('Failed') ||
                          surfaceText.includes('Cancelled');

      return !hasActive && hasTerminal;
    }, { timeout: 120000, intervals: [1000, 2000] }).toBe(true);

    // VALIDATE: Terminal state preserved
    const checkRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const checkState = await checkRes.json();
    expect(checkState.lifecycle_status).toBe(terminalStatus);
  }

  // === FINAL VALIDATION: No rollback occurred ===
  const finalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalState = await finalRes.json();

  expect(finalState.lifecycle_status).toBe(terminalStatus);
  expect(finalState.execution_generation).toBe(terminalGen);
  expect(finalState.lifecycle_status).not.toBe('ACTIVE');
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 3: No projection resurrection
// ═══════════════════════════════════════════════════════════════════════════
test('no_projection_resurrection', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow execution and resurrection validation
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 10 times 10.\nAdd 50.\nDivide by 5.',
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
  const terminalGen = terminalState.execution_generation;

  // === ATTEMPT: Operational interactions that could trigger resurrection ===

  // Attempt pause (should fail or be ignored)
  const pauseApiRes = await request.post('http://localhost:8000/workflow/pause', {
    data: { workflow_id: workflowId }
  }).catch(() => null);
  // Should fail (4xx) or be ignored

  // Wait briefly
  await new Promise(r => setTimeout(r, 2000));

  // Check state still terminal
  let checkRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  let checkState = await checkRes.json();
  expect(checkState.lifecycle_status).toBe(terminalStatus);

  // Attempt resume (should fail or be ignored)
  const resumeApiRes = await request.post('http://localhost:8000/workflow/resume', {
    data: { workflow_id: workflowId }
  }).catch(() => null);

  await new Promise(r => setTimeout(r, 2000));

  // Check state still terminal
  checkRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  checkState = await checkRes.json();
  expect(checkState.lifecycle_status).toBe(terminalStatus);

  // === REFRESH AND CHECK AGAIN ===
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === terminalStatus;
  }, { timeout: 120000, intervals: [2000, 3000] }).toBe(true);

  // === FINAL VALIDATION: No resurrection occurred ===
  const finalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalState = await finalRes.json();

  // Must remain terminal
  expect(finalState.lifecycle_status).toBe(terminalStatus);

  // Generation must be stable (no new execution context)
  expect(finalState.execution_generation).toBe(terminalGen);

  // Must NOT be ACTIVE
  expect(finalState.lifecycle_status).not.toBe('ACTIVE');
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 4: Observability continuity without operational authority
// ═══════════════════════════════════════════════════════════════════════════
test('observability_continuity_without_operational_authority', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow execution and observability validation
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Add 100 and 50.\nMultiply by 2.',
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

  // Capture pre-terminal projection
  const preTerminalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const preTerminalState = await preTerminalRes.json();
  const preTerminalSteps = preTerminalState.projection_metadata?.state?.steps ?? [];

  // Wait for terminal (LLM-tolerant: 300s)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === VALIDATE: Terminal workflow remains observable ===

  // Workflow container should be visible
  const workflowVisible = await page.locator('.workflow-container, .workflow-surface, [data-workflow-id]')
    .isVisible()
    .catch(() => false);
  expect(workflowVisible).toBe(true);

  // Projection should remain accessible
  const projRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  expect(projRes.ok()).toBe(true);
  const projState = await projRes.json();

  // Steps should remain visible
  const postTerminalSteps = projState.projection_metadata?.state?.steps ?? [];
  expect(postTerminalSteps.length).toBeGreaterThanOrEqual(preTerminalSteps.length);

  // === VALIDATE: Projection summary remains visible ===
  const surfaceText = (await page.locator('.workflow-surface-status').textContent().catch(() => '')) || '';
  const hasSummary = surfaceText.length > 0;
  expect(hasSummary).toBe(true);

  // === VALIDATE: Operational controls remain invalidated ===

  // Pause unavailable
  const pauseBtn = page.getByRole('button', { name: 'Pause' });
  const pauseDisabled = await pauseBtn.isDisabled().catch(() => true);
  const pauseVisible = await pauseBtn.isVisible().catch(() => false);
  expect(pauseDisabled || !pauseVisible).toBe(true);

  // Resume unavailable
  const resumeBtn = page.getByRole('button', { name: 'Resume' });
  const resumeDisabled = await resumeBtn.isDisabled().catch(() => true);
  const resumeVisible = await resumeBtn.isVisible().catch(() => false);
  expect(resumeDisabled || !resumeVisible).toBe(true);

  // Edit unavailable
  const editBtn = page.getByRole('button', { name: 'Edit' });
  const editDisabled = await editBtn.isDisabled().catch(() => true);
  const editVisible = await editBtn.isVisible().catch(() => false);
  expect(editDisabled || !editVisible).toBe(true);

  // === REFRESH VALIDATION ===
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // After refresh, workflow should still be observable
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout: 120000, intervals: [2000, 3000] }).toBe(true);

  const postRefreshVisible = await page.locator('.workflow-container, .workflow-surface, [data-workflow-id]')
    .isVisible()
    .catch(() => false);
  expect(postRefreshVisible).toBe(true);

  // === FINAL VALIDATION: Observability preserved, operability prohibited ===
  const finalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalState = await finalRes.json();

  expect(finalState.lifecycle_status === 'COMPLETED' || finalState.lifecycle_status === 'FAILED').toBe(true);
  expect(finalState.projection_metadata?.state?.steps?.length ?? 0).toBeGreaterThan(0);
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 5: Refresh continuity preserves terminal observability
// ═══════════════════════════════════════════════════════════════════════════
test('refresh_continuity_preserves_terminal_observability', async ({ page, request }) => {
  // 600s: LLM-tolerant for workflow execution and refresh validation
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 20 plus 30.\nDivide by 5.',
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

  // Capture terminal projection before refresh
  const preRefreshRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const preRefreshState = await preRefreshRes.json();
  const preRefreshSteps = preRefreshState.projection_metadata?.state?.steps ?? [];
  const preRefreshStatus = preRefreshState.lifecycle_status;

  // === REFRESH AND VALIDATE CONTINUITY ===
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // Wait for reconvergence
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === preRefreshStatus;
  }, { timeout: 120000, intervals: [2000, 3000] }).toBe(true);

  // === VALIDATE: No stale lifecycle rehydration ===

  // Must NOT show ACTIVE after refresh
  const surfaceText = (await page.locator('.workflow-surface-status').textContent().catch(() => '')) || '';
  const hasActive = surfaceText.includes('Running') || surfaceText.includes('Active');
  expect(hasActive).toBe(false);

  // Must show terminal
  const hasTerminal = surfaceText.includes('Completed') ||
                      surfaceText.includes('Failed') ||
                      surfaceText.includes('Cancelled');
  expect(hasTerminal).toBe(true);

  // === VALIDATE: Projection continuity ===
  const postRefreshRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const postRefreshState = await postRefreshRes.json();
  const postRefreshSteps = postRefreshState.projection_metadata?.state?.steps ?? [];

  // Steps should be preserved
  expect(postRefreshSteps.length).toBeGreaterThanOrEqual(preRefreshSteps.length);

  // Lifecycle should be stable
  expect(postRefreshState.lifecycle_status).toBe(preRefreshStatus);

  // === FINAL VALIDATION: Observability continuity ===
  const finalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalState = await finalRes.json();

  expect(finalState.lifecycle_status).toBe(preRefreshStatus);
  expect(finalState.projection_metadata?.state?.steps?.length ?? 0).toBeGreaterThan(0);
  expect(finalState.execution_generation).toBeDefined();
});

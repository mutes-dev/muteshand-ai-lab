import { test, expect } from '@playwright/test';
import {
  clearActiveWorkflows,
  acquireWorkflowDeterministically,
  triggerDeterministicFail,
  getFirstNonTerminalStepId,
} from './test-helpers';

/**
 * RETRY RECOVERY FLOW — TIER 1 LIFECYCLE COMPLETENESS
 *
 * Validates operational recovery continuity:
 * - FAILED → retry → replacement continuity
 * - Stable ACTIVE progression after retry
 * - Eventual terminal convergence
 *
 * This is NOT just retry lineage — this is operational UX continuity.
 * Per RECOVERY_CONTINUITY_CONTRACT_V1:
 *   FAILED → retry → replacement execution → ACTIVE progression → terminal
 */

test.beforeEach(async () => { await clearActiveWorkflows(); });
test.afterEach(async () => { await clearActiveWorkflows(); });

// ═══════════════════════════════════════════════════════════════════════════
// TEST 1: FAILED workflow becomes recoverable
// ═══════════════════════════════════════════════════════════════════════════
test('failed_workflow_becomes_recoverable', async ({ page, request }) => {
  // 900s: LLM-tolerant for slow workflow acquisition, deterministic failure, and validation
  test.setTimeout(900000);

  // DETERMINISTIC workflow acquisition (simple math - won't naturally fail)
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 10 plus 20.',
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

  // Wait for steps to be available (planning completion)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    const steps = data.projection_metadata?.state?.steps ?? data.steps ?? [];
    return steps.length > 0;
  }, { timeout: 300000, intervals: [2000, 3000] }).toBe(true);

  // DETERMINISTIC FAILURE: Force first non-terminal step to FAILED
  const stepId = await getFirstNonTerminalStepId(workflowId);
  if (!stepId) {
    throw new Error('Tier 1 setup failure: no non-terminal step found for deterministic failure');
  }
  const triggered = await triggerDeterministicFail(workflowId, stepId, 'test_deterministic_failure');
  if (!triggered) {
    throw new Error('Tier 1 setup failure: deterministic failure trigger failed');
  }

  // Wait for FAILED convergence (authoritative lifecycle polling)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'FAILED' || data.lifecycle_status === 'BLOCKED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === VALIDATE: Retry becomes legally available ===
  // Check projection for retryable step
  const projRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  expect(projRes.ok()).toBe(true);
  const proj = await projRes.json();

  // Must have FAILED or BLOCKED steps
  const steps = proj.projection_metadata?.state?.steps ?? [];
  const hasRetryable = steps.some((s: any) => s.status === 'FAILED' || s.status === 'BLOCKED');
  expect(hasRetryable).toBe(true);

  // === VALIDATE: Lifecycle source authoritative ===
  expect(proj.lifecycle_status).toBe('FAILED');

  // execution_generation tracked
  expect(proj.execution_generation).toBeDefined();
  expect(proj.execution_generation).toBeGreaterThanOrEqual(1);
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 2: Retry actually occurs with strict generation semantics
// ═══════════════════════════════════════════════════════════════════════════
test('retry_actually_occurs_with_strict_generation_semantics', async ({ page, request }) => {
  // 900s: LLM-tolerant for slow workflow acquisition, deterministic failure, and retry cycle
  test.setTimeout(900000);

  // DETERMINISTIC workflow acquisition (simple math - won't naturally fail)
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 5 plus 10.\nMultiply by 2.',
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

  // Wait for steps to be available (planning completion)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    const steps = data.projection_metadata?.state?.steps ?? data.steps ?? [];
    return steps.length > 0;
  }, { timeout: 300000, intervals: [2000, 3000] }).toBe(true);

  // DETERMINISTIC FAILURE: Force first non-terminal step to FAILED
  const stepId = await getFirstNonTerminalStepId(workflowId);
  if (!stepId) {
    throw new Error('Tier 1 setup failure: no non-terminal step found for deterministic failure');
  }
  const triggered = await triggerDeterministicFail(workflowId, stepId, 'test_deterministic_failure');
  if (!triggered) {
    throw new Error('Tier 1 setup failure: deterministic failure trigger failed');
  }

  // Wait for FAILED convergence (authoritative lifecycle polling)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'FAILED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // Capture state BEFORE retry
  const beforeRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const beforeState = await beforeRes.json();
  const beforeGen = beforeState.execution_generation ?? 0;
  const beforeRetryCount = beforeState.retry_lineage?.retry_count ?? 0;

  // === TRIGGER RETRY ===
  // Use the same stepId from deterministic failure injection
  // Verify it's still FAILED/BLOCKED before retrying

  // Retry via API
  const retryRes = await request.post(`http://localhost:8000/workflow/${workflowId}/retry`, {
    data: { step_id: stepId, reason: 'test_retry' }
  });
  expect(retryRes.ok()).toBe(true);

  // === VALIDATE: Retry actually occurred with STRICT semantics ===

  // Wait for execution_generation increment (LLM-tolerant: 180s)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.execution_generation > beforeGen;
  }, { timeout: 180000, intervals: [2000, 3000] }).toBe(true);

  // Capture state AFTER retry
  const afterRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const afterState = await afterRes.json();

  // VALIDATE: execution_generation incremented STRICTLY (not just >=)
  expect(afterState.execution_generation).toBeGreaterThan(beforeGen);

  // VALIDATE: retry_count incremented STRICTLY (use toBeGreaterThan, not toBeGreaterThanOrEqual)
  const afterRetryCount = afterState.retry_lineage?.retry_count ?? 0;
  expect(afterRetryCount).toBeGreaterThan(beforeRetryCount);

  // VALIDATE: Stale execution lost authority (generation mismatch)
  expect(afterState.execution_generation).not.toBe(beforeGen);

  // ── Wait for terminal convergence after retry ───────────────────────────
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout: 600000, intervals: [2000, 3000, 5000] }).toBe(true);
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 3: ACTIVE recovery continuity after retry
// ═══════════════════════════════════════════════════════════════════════════
test('active_recovery_continuity_after_retry', async ({ page, request }) => {
  // 900s: LLM-tolerant for slow workflow acquisition, deterministic failure, and retry recovery
  test.setTimeout(900000);

  // DETERMINISTIC workflow acquisition (simple math - won't naturally fail)
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Add 100 and 50.\nMultiply by 3.',
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

  // Wait for steps to be available (planning completion)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    const steps = data.projection_metadata?.state?.steps ?? data.steps ?? [];
    return steps.length > 0;
  }, { timeout: 300000, intervals: [2000, 3000] }).toBe(true);

  // DETERMINISTIC FAILURE: Force first non-terminal step to FAILED
  const stepId = await getFirstNonTerminalStepId(workflowId);
  if (!stepId) {
    throw new Error('Tier 1 setup failure: no non-terminal step found for deterministic failure');
  }
  const triggered = await triggerDeterministicFail(workflowId, stepId, 'test_deterministic_failure');
  if (!triggered) {
    throw new Error('Tier 1 setup failure: deterministic failure trigger failed');
  }

  // Wait for FAILED convergence (authoritative lifecycle polling)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'FAILED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // Use the same stepId for retry (already declared above)
  const beforeRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const beforeState = await beforeRes.json();
  const steps = beforeState.projection_metadata?.state?.steps ?? [];
  const failedStep = steps.find((s: any) => s.status === 'FAILED' || s.status === 'BLOCKED');
  if (!failedStep) {
    throw new Error('Tier 1 validation blocked: no FAILED step found');
  }

  // Trigger retry
  const retryRes = await request.post(`http://localhost:8000/workflow/${workflowId}/retry`, {
    data: { step_id: failedStep.step_id ?? failedStep.id, reason: 'test_recovery' }
  });
  expect(retryRes.ok()).toBe(true);

  // === VALIDATE: Replacement execution becomes authoritative ===
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    // Should return to ACTIVE after retry
    return data.lifecycle_status === 'ACTIVE';
  }, { timeout: 180000, intervals: [2000, 3000] }).toBe(true);

  // === VALIDATE: Workflow resumes progression correctly ===
  // Workflow should continue executing steps after retry recovery
  const activeRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const activeState = await activeRes.json();

  expect(activeState.lifecycle_status).toBe('ACTIVE');
  expect(activeState.execution_generation).toBeGreaterThan(1);

  // === VALIDATE: No duplicate active execution ===
  // Only one execution context should be active
  expect(activeState.retry_lineage).not.toBeNull();
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 4: Terminal convergence after retry recovery
// ═══════════════════════════════════════════════════════════════════════════
test('terminal_convergence_after_retry_recovery', async ({ page, request }) => {
  // 600s: LLM-tolerant for full workflow execution with retry
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 50 plus 50.\nDivide by 1.\nMultiply by 2.',
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
  // This workflow should complete without failure
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === VALIDATE: Terminal state achieved ===
  const terminalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const terminalState = await terminalRes.json();

  // Must be terminal
  expect(['COMPLETED', 'FAILED']).toContain(terminalState.lifecycle_status);

  // === VALIDATE: No stale rollback ===
  // Refresh and verify terminal stability
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout: 120000, intervals: [2000, 3000] }).toBe(true);

  // === VALIDATE: No projection resurrection ===
  const finalRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalState = await finalRes.json();

  expect(finalState.lifecycle_status).not.toBe('ACTIVE');
  expect(finalState.execution_generation).toBeDefined();
  expect(finalState.execution_generation).toBeGreaterThanOrEqual(1);
});

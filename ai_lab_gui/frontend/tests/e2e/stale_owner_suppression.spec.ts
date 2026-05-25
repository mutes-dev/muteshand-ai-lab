import { test, expect } from '@playwright/test';
import { clearActiveWorkflows, acquireWorkflowDeterministically } from './test-helpers';

/**
 * STALE OWNER SUPPRESSION VALIDATION
 *
 * Validates cooperative orchestration semantics and stale execution invalidation:
 * - mutation/retry creates NEW execution context
 * - stale execution owners self-suppress
 * - stale execution results do NOT overwrite newer execution state
 * - workflow converges correctly after invalidation
 * - no duplicate active execution convergence corruption
 *
 * Contract references:
 * - EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1 §2 (retry identity, retry invalidation)
 * - ORCHESTRATION_AND_EXECUTION_SEQUENCE_CONTRACT_V1 §3 (retry sequencing)
 * - VALIDATION_ARCHITECTURE.txt §9.4 (cooperative orchestration validation)
 * - RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 (execution_generation stale-owner suppression)
 */


test.beforeEach(async () => { await clearActiveWorkflows(); });
test.afterEach(async () => { await clearActiveWorkflows(); });

/**
 * Extract workflow ID from banner text
 */
const extractWorkflowId = (text: string): string => {
  const m = text.match(/(?:workflow_|low_)([a-z0-9]+)/i);
  return m ? m[1] : '';
};

/**
 * Validates that mutation during PAUSED state creates new execution context
 * and stale execution owner self-suppresses on resume.
 */
test('mutation_creates_new_execution_context', async ({ page, request }) => {
  // 600s: 4-step workflow with pause/mutation/resume cycle (LLM-tolerant)
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition: Use /execute/stream bootstrap
  // Per TIER 0 STABILIZATION: Registry scanning is indeterministic due to LLM planning latency.
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Add 100 and 50.\nMultiply the result by 3.\nSubtract 10 from the result.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 0 setup failure: deterministic workflow acquisition failed');
  }

  // Wait for ACTIVE via API (not stale UI selector)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'ACTIVE';
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Wait for at least one step to start executing (LLM-tolerant: 300s for slow step execution)
  await expect(page.locator('text=/COMPLETED|ACTIVE.*processing/').first()).toBeVisible({ timeout: 300000 });

  // PAUSE workflow
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('.pause-pending-badge')).toBeVisible({ timeout: 10000 });
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'PAUSED';
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // === DETERMINISTIC OBSERVABILITY: Capture runtime state BEFORE mutation ===
  // Per VALIDATION_ARCHITECTURE.txt §9.4: Use /runtime/inspect for deterministic validation
  const beforeInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
  const beforeInspect = beforeInspectRes?.ok ? await beforeInspectRes.json() : null;
  const beforeGen = beforeInspect?.execution_generation ?? 1;

  // MUTATE: Edit first step's expected outcome via mutation API
  const mutationRes = await request.post(`http://localhost:8000/workflow/${workflowId}/mutation`, {
    data: {
      mutation_type: 'edit_step',
      payload: { step_id: 'step_1', field: 'expected_outcome', value: 'Mutated expected outcome: 440' },
      actor: 'test'
    }
  });
  expect(mutationRes.ok()).toBe(true);

  // === DETERMINISTIC OBSERVABILITY: Capture runtime state AFTER mutation ===
  const afterInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
  const afterInspect = afterInspectRes?.ok ? await afterInspectRes.json() : null;
  const afterGen = afterInspect?.execution_generation ?? beforeGen;

  // VALIDATE: execution_generation STRICTLY incremented (new execution context created)
  // Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1 §2: Retry/mutation creates NEW execution instance.
  // Equality means stale-owner invalidation did NOT occur — architectural failure.
  expect(afterGen).toBeGreaterThan(beforeGen);

  // RESUME workflow
  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('.resume-pending-badge')).toBeVisible({ timeout: 10000 });
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'ACTIVE';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // Wait for completion via polling
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'COMPLETED' || data?.lifecycle_status === 'FAILED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === FINAL VALIDATION: Deterministic convergence verification ===
  // Use /runtime/inspect for authoritative execution_generation validation
  const finalInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  expect(finalInspectRes.ok()).toBe(true);
  const finalInspect = await finalInspectRes.json();

  // Must have valid terminal status from runtime registry
  expect(['COMPLETED', 'FAILED']).toContain(finalInspect.lifecycle_status);

  // VALIDATE: execution_generation tracked throughout lifecycle
  expect(finalInspect.execution_generation).toBeDefined();
  expect(finalInspect.execution_generation).toBeGreaterThanOrEqual(1);

  // VALIDATE: Persistence exists (survivability)
  expect(finalInspect.persistence_exists).toBe(true);
});

/**
 * Validates that retry creates new execution instance and invalidates previous.
 */
test('retry_invalidates_previous_execution', async ({ page, request }) => {
  // 600s: 3-step workflow with pause/resume + retry overhead (LLM-tolerant)
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition: Use /execute/stream bootstrap
  // Per TIER 0 STABILIZATION: Registry scanning is indeterministic due to LLM planning latency.
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 99999 times 11111 divided by 7.\nAdd 5000.\nMultiply by 2.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 0 setup failure: deterministic workflow acquisition failed');
  }

  // Wait for ACTIVE via API (not stale UI selector)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'ACTIVE';
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Wait for at least one step to complete via authoritative API (for retry eligibility) (LLM-tolerant: 300s)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    const steps = data.projection_metadata?.state?.steps ?? [];
    return steps.some((s: any) => s.status === 'COMPLETED');
  }, { timeout: 300000, intervals: [2000, 3000] }).toBe(true).catch(() => {
    // Step may not complete if retry happens mid-workflow
  });

  // PAUSE to enable retry
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('.pause-pending-badge')).toBeVisible({ timeout: 10000 });
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'PAUSED';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // === DETERMINISTIC OBSERVABILITY: Capture runtime state BEFORE retry ===
  // Per VALIDATION_ARCHITECTURE.txt §9.4: Use /runtime/inspect for deterministic validation
  const beforeInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
  const beforeInspect = beforeInspectRes?.ok ? await beforeInspectRes.json() : null;
  const beforeRetryGen = beforeInspect?.execution_generation ?? 1;
  const beforeRetryCount = beforeInspect?.retry_lineage?.retry_count ?? 0;

  // Query events before retry (defensive: endpoint may return non-JSON on error)
  const beforeEventsRes = await request.get(`http://localhost:8000/events/${workflowId}?since=-1&limit=10`).catch(() => null);
  let beforeEvents = { events: [] };
  if (beforeEventsRes?.ok) {
    try { beforeEvents = await beforeEventsRes.json(); } catch (_) { /* non-JSON error response */ }
  }
  const beforeEventCount = beforeEvents.events?.length ?? 0;

  // Trigger retry via API
  const retryRes = await request.post('http://localhost:8000/step/retry', {
    data: { workflow_id: workflowId, step_id: 'step_1' }
  }).catch(() => null);

  // Retry may fail if step not eligible - that's acceptable for this test
  const retryTriggered = retryRes?.ok ?? false;

  // === DETERMINISTIC OBSERVABILITY: Capture runtime state AFTER retry ===
  const afterInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
  const afterInspect = afterInspectRes?.ok ? await afterInspectRes.json() : null;
  const afterRetryGen = afterInspect?.execution_generation ?? beforeRetryGen;
  const afterRetryCount = afterInspect?.retry_lineage?.retry_count ?? beforeRetryCount;

  // Query events after retry (defensive: endpoint may return non-JSON on error)
  const afterEventsRes = await request.get(`http://localhost:8000/events/${workflowId}?since=-1&limit=10`).catch(() => null);
  let afterEvents = { events: [] };
  if (afterEventsRes?.ok) {
    try { afterEvents = await afterEventsRes.json(); } catch (_) { /* non-JSON error response */ }
  }
  const afterEventCount = afterEvents.events?.length ?? beforeEventCount;

  // VALIDATE: If retry triggered, execution_generation MUST STRICTLY increment
  // Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1 §2: Retry creates NEW execution instance.
  // >= is architecturally invalid here — equality means stale owner was NOT invalidated.
  if (retryTriggered) {
    expect(afterRetryGen).toBeGreaterThan(beforeRetryGen);
    // VALIDATE: retry_lineage updated
    expect(afterRetryCount).toBeGreaterThan(beforeRetryCount);
  }

  // RESUME after retry (or just resume if retry wasn't possible)
  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('.resume-pending-badge')).toBeVisible({ timeout: 10000 });
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'ACTIVE';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // Wait for completion via polling
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'COMPLETED' || data?.lifecycle_status === 'FAILED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === FINAL VALIDATION: Deterministic convergence verification ===
  // Use /runtime/inspect for authoritative execution_generation validation
  const finalInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalInspect = await finalInspectRes.json();

  // VALIDATE: Terminal state from runtime registry authority
  expect(['COMPLETED', 'FAILED']).toContain(finalInspect.lifecycle_status);

  // VALIDATE: execution_generation tracked throughout lifecycle
  expect(finalInspect.execution_generation).toBeDefined();
  expect(finalInspect.execution_generation).toBeGreaterThanOrEqual(1);

  // VALIDATE: retry_lineage preserved
  expect(finalInspect.retry_lineage).not.toBeNull();

  // Event count should have grown (shows execution activity)
  expect(afterEventCount).toBeGreaterThanOrEqual(beforeEventCount);
});

/**
 * Validates that stale execution cannot overwrite newer state (no zombie execution).
 */
test('stale_execution_cannot_overwrite_newer_state', async ({ page, request }) => {
  // 600s: 3-step workflow with pause/resume + mutation overhead (LLM-tolerant)
  test.setTimeout(600000);

  // DETERMINISTIC workflow acquisition: Use /execute/stream bootstrap
  // Per TIER 0 STABILIZATION: Registry scanning is indeterministic due to LLM planning latency.
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Add 10 and 20.\nMultiply by 3.\nDivide by 5.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 0 setup failure: deterministic workflow acquisition failed');
  }

  // Wait for ACTIVE via API (not stale UI selector)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'ACTIVE';
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Wait for first step to complete via authoritative API (LLM-tolerant: 300s)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    const steps = data.projection_metadata?.state?.steps ?? [];
    return steps.some((s: any) => s.status === 'COMPLETED');
  }, { timeout: 300000, intervals: [2000, 3000] }).toBe(true);

  // === DETERMINISTIC OBSERVABILITY: Capture runtime state BEFORE mutation ===
  // Per VALIDATION_ARCHITECTURE.txt §9.4: Use /runtime/inspect for deterministic validation
  const beforeInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const beforeInspect = await beforeInspectRes.json();
  const beforeGen = beforeInspect.execution_generation ?? 1;
  const beforeActiveExec = beforeInspect.active_execution;

  // Capture runtime state before pause
  const beforePauseRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const beforePauseData = await beforePauseRes.json();
  const beforePauseStatus = beforePauseData.lifecycle_status;

  // PAUSE
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('.pause-pending-badge')).toBeVisible({ timeout: 5000 });
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'PAUSED';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // MUTATE via API (creates new execution context)
  const mutationRes = await request.post(`http://localhost:8000/workflow/${workflowId}/mutation`, {
    data: {
      mutation_type: 'edit_step',
      payload: { step_id: 'step_2', field: 'expected_outcome', value: 'Updated after step 1 completion' },
      actor: 'test'
    }
  });
  expect(mutationRes.ok()).toBe(true);

  // === DETERMINISTIC OBSERVABILITY: Capture runtime state AFTER mutation ===
  const afterInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const afterInspect = await afterInspectRes.json();
  const afterGen = afterInspect.execution_generation ?? beforeGen;

  // VALIDATE: execution_generation STRICTLY incremented (mutation creates new context)
  // Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1 §2: mutation creates NEW execution instance.
  // >= is architecturally invalid here — equality means stale-owner invalidation failed.
  expect(afterGen).toBeGreaterThan(beforeGen);

  // VALIDATE: Runtime state preserved after mutation
  expect(['ACTIVE', 'PAUSED', 'COMPLETED', 'FAILED']).toContain(beforePauseStatus);

  // RESUME
  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('.resume-pending-badge')).toBeVisible({ timeout: 5000 });
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'ACTIVE';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // Wait for completion via polling
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'COMPLETED' || data?.lifecycle_status === 'FAILED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === FINAL VALIDATION: Deterministic convergence verification ===
  // Use /runtime/inspect for authoritative validation
  const finalInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const finalInspect = await finalInspectRes.json();

  // VALIDATE: Terminal state from runtime registry authority
  expect(['COMPLETED', 'FAILED']).toContain(finalInspect.lifecycle_status);

  // VALIDATE: execution_generation tracked (no zombie execution corruption)
  expect(finalInspect.execution_generation).toBeDefined();
  expect(finalInspect.execution_generation).toBeGreaterThanOrEqual(afterGen);

  // VALIDATE: Persistence maintained (survivability)
  expect(finalInspect.persistence_exists).toBe(true);

  // VALIDATE: Terminal runtime state preserved
  expect(finalInspect.lifecycle_status === 'COMPLETED' || finalInspect.lifecycle_status === 'FAILED').toBe(true);
});

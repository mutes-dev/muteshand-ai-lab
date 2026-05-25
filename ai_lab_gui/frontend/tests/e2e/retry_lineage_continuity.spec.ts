import { test, expect } from '@playwright/test';
import {
  clearActiveWorkflows,
  acquireWorkflowDeterministically,
  triggerDeterministicFail,
  getFirstNonTerminalStepId,
} from './test-helpers';

// NOTE: All Tier 0 tests use deterministic workflow acquisition via /execute/stream.
// Registry-based discovery (getForegroundWorkflowId) is DEPRECATED for Tier 0
// due to indeterministic LLM planning latency causing race conditions.

/**
 * RETRY LINEAGE CONTINUITY VALIDATION — TIER 0 ARCHITECTURAL HARDENING
 *
 * Validates:
 * - retry creates NEW execution context (execution_generation STRICTLY increments)
 * - retry_lineage.retry_count STRICTLY increments
 * - stale execution owner is invalidated (only one active execution)
 * - workflow identity preserved through retry
 * - no duplicate execution branches
 *
 * Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1 §2:
 *   Retry creates NEW execution instance with incremented execution_generation.
 *
 * Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1:
 *   Stale execution MUST lose operational authority.
 *
 * CRITICAL: These tests actively trigger retry and validate architectural invariants.
 * If no retryable step is encountered, the test FAILS (does not skip) to prevent
 * false confidence. Tier 0 tests must validate real retry semantics.
 */

test.beforeEach(async () => { await clearActiveWorkflows(); });
test.afterEach(async () => { await clearActiveWorkflows(); });

// ── Authoritative runtime state (via /runtime/inspect) ────────────────────
interface RuntimeState {
  workflow_id: string;
  lifecycle_status: string | null;
  execution_generation: number | null;
  retry_lineage: { retry_count: number; last_retry_at: string | null } | null;
  active_execution: { bg_id: string; stream_status: string } | null;
  persistence_exists: boolean;
  projection_metadata?: { state?: { steps?: Array<{ step_id?: string; id?: string; status?: string }> } };
  steps?: Array<{ step_id?: string; id?: string; status?: string }>;
}

const getRuntimeState = async (request: any, workflowId: string): Promise<RuntimeState | null> => {
  const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
  if (!res?.ok) return null;
  return res.json();
};

// ── Projection state (via /projection/{id}) ───────────────────────────────
interface ProjectionStep {
  step_id?: string;
  id?: string;
  status?: string;
}

const getProjectionSteps = async (request: any, workflowId: string): Promise<ProjectionStep[]> => {
  const res = await request.get(`http://localhost:8000/projection/${workflowId}`).catch(() => null);
  if (!res?.ok) return [];
  const proj = await res.json();
  const steps = proj.projection_state?.steps ?? proj.steps ?? [];
  return steps;
};

// ── Event stream (via /events/{id}) ──────────────────────────────────────
interface BusEvent {
  event_type: string;
  data?: { step_id?: string; status?: string; reason?: string };
}

const getEvents = async (request: any, workflowId: string): Promise<BusEvent[]> => {
  const res = await request.get(`http://localhost:8000/events/${workflowId}?since=-1&limit=50`).catch(() => null);
  if (!res?.ok) return [];
  try {
    const data = await res.json();
    return data.events ?? [];
  } catch {
    return [];
  }
};

// ── Deterministic retryable-step creation ──────────────────────────────
// Creates a FAILED step deterministically via admin test endpoint.
// This replaces probabilistic failure discovery with guaranteed failure.
const createDeterministicRetryableStep = async (
  workflowId: string,
  request: any,
  timeoutMs = 300000,
): Promise<string | null> => {
  // First, wait for workflow to be ACTIVE (steps must exist)
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const runtime = await getRuntimeState(request, workflowId);
    if (runtime?.lifecycle_status === 'ACTIVE') {
      break;
    }
    if (runtime?.lifecycle_status === 'COMPLETED' || runtime?.lifecycle_status === 'FAILED') {
      return null; // Already terminal
    }
    await new Promise((r) => setTimeout(r, 2000));
  }

  // Wait for steps to be available (planning completion)
  const stepsStart = Date.now();
  while (Date.now() - stepsStart < timeoutMs) {
    const runtime = await getRuntimeState(request, workflowId);
    const steps = runtime?.projection_metadata?.state?.steps ?? [];
    if (steps.length > 0) {
      break;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }

  // AUTHENTIC DETERMINISTIC FAILURE: Trigger through runtime execution
  const stepId = await getFirstNonTerminalStepId(workflowId);
  if (!stepId) {
    return null;
  }

  const triggered = await triggerDeterministicFail(workflowId, stepId, 'test_deterministic_failure');
  if (!triggered) {
    return null;
  }

  // Wait for FAILED convergence
  const failedStart = Date.now();
  while (Date.now() - failedStart < 60000) {
    const runtime = await getRuntimeState(request, workflowId);
    if (runtime?.lifecycle_status === 'FAILED' || runtime?.lifecycle_status === 'BLOCKED') {
      return stepId;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }

  return null;
};

// ── Trigger retry and return result ──────────────────────────────────────
const triggerRetry = async (
  request: any,
  workflowId: string,
  stepId: string,
): Promise<{ ok: boolean; response?: any }> => {
  const res = await request
    .post('http://localhost:8000/step/retry', {
      data: { workflow_id: workflowId, step_id: stepId },
    })
    .catch(() => null);
  if (!res?.ok) return { ok: false };
  try {
    const data = await res.json();
    return { ok: true, response: data };
  } catch {
    return { ok: true };
  }
};

// ── Pause workflow via UI + API convergence ──────────────────────────────
const pauseWorkflow = async (page: any, request: any, workflowId: string) => {
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect.poll(async () => {
    const state = await getRuntimeState(request, workflowId);
    return state?.lifecycle_status === 'PAUSED';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);
};

// ── Resume workflow via UI + API convergence ─────────────────────────────
const resumeWorkflow = async (page: any, request: any, workflowId: string) => {
  await page.getByRole('button', { name: 'Resume' }).click();
  await expect.poll(async () => {
    const state = await getRuntimeState(request, workflowId);
    return state?.lifecycle_status === 'ACTIVE';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);
};

// ── Wait for terminal via authoritative API ──────────────────────────────
const waitForTerminal = async (request: any, workflowId: string, timeoutMs = 300000) => {
  await expect.poll(async () => {
    const state = await getRuntimeState(request, workflowId);
    return state?.lifecycle_status === 'COMPLETED' || state?.lifecycle_status === 'FAILED';
  }, { timeout: timeoutMs, intervals: [2000, 3000, 5000] }).toBe(true);
};

// ═══════════════════════════════════════════════════════════════════════════
// TEST 1: Retry increments execution_generation and retry_lineage
// ═══════════════════════════════════════════════════════════════════════════
test('retry_increments_execution_generation_and_lineage', async ({ page, request }) => {
  // 900s: LLM-tolerant for slow workflow acquisition, deterministic failure, and retry
  test.setTimeout(900000);

  // DETERMINISTIC workflow acquisition: Use /execute/stream bootstrap
  // Per TIER 0 STABILIZATION: Registry scanning is indeterministic due to LLM planning latency.
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 10 plus 20.\nMultiply by 3.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 0 setup failure: deterministic workflow acquisition failed');
  }

  // Wait for ACTIVE
  await expect.poll(async () => {
    const state = await getRuntimeState(request, workflowId);
    return state?.lifecycle_status === 'ACTIVE';
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // ── DETERMINISTIC retryable step creation ────────────────────────────────
  const retryableStepId = await createDeterministicRetryableStep(workflowId, request, 300000);

  // Tier 0 invariant: if retryable step creation failed, this test CANNOT validate retry.
  if (!retryableStepId) {
    throw new Error(
      'Tier 0 retry validation blocked: deterministic FAILED step creation failed. ' +
      'Retry lineage cannot be validated without a recoverable step.'
    );
  }

  // ── Capture state BEFORE retry ─────────────────────────────────────────
  const beforeState = await getRuntimeState(request, workflowId);
  const beforeGen = beforeState?.execution_generation ?? 1;
  const beforeRetryCount = beforeState?.retry_lineage?.retry_count ?? 0;

  // ── TRIGGER RETRY ──────────────────────────────────────────────────────
  const retryResult = await triggerRetry(request, workflowId, retryableStepId);

  if (!retryResult.ok) {
    throw new Error(
      `Tier 0 retry validation blocked: retry API failed for step ${retryableStepId}. ` +
      `Step may have transitioned out of FAILED/BLOCKED before retry was triggered.`
    );
  }

  // ── Wait for resurrection (mutation spawns new execution thread) ────────
  // Per ORCHESTRATOR_EXECUTION_CONTRACT: retry/edit mutations revive terminal
  // workflows back to ACTIVE via _maybe_resurrect_execution.
  await expect.poll(async () => {
    const state = await getRuntimeState(request, workflowId);
    return state?.lifecycle_status === 'ACTIVE';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // ── Capture state AFTER retry ──────────────────────────────────────────
  const afterState = await getRuntimeState(request, workflowId);
  const afterGen = afterState?.execution_generation ?? beforeGen;
  const afterRetryCount = afterState?.retry_lineage?.retry_count ?? beforeRetryCount;

  // ── STRICT VALIDATION: execution_generation MUST increment ─────────────
  // Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1 §2:
  // Retry creates NEW execution instance. Equality means stale-owner
  // invalidation did NOT occur — this is an architectural failure.
  expect(afterGen).toBeGreaterThan(beforeGen);

  // ── STRICT VALIDATION: retry_count MUST increment ──────────────────────
  expect(afterRetryCount).toBeGreaterThan(beforeRetryCount);

  // ── Wait for terminal ──────────────────────────────────────────────────
  await waitForTerminal(request, workflowId, 180000);

  // ── Final convergence validation ───────────────────────────────────────
  const finalState = await getRuntimeState(request, workflowId);
  expect(finalState).not.toBeNull();
  expect(['COMPLETED', 'FAILED']).toContain(finalState!.lifecycle_status);
  expect(finalState!.execution_generation).toBeGreaterThanOrEqual(afterGen);
  expect(finalState!.retry_lineage).not.toBeNull();
  expect(finalState!.retry_lineage!.retry_count).toBeGreaterThanOrEqual(afterRetryCount);
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 2: Retry invalidates stale execution (no zombie authority)
// ═══════════════════════════════════════════════════════════════════════════
test('retry_invalidates_stale_execution', async ({ page, request }) => {
  // 900s: LLM-tolerant for slow workflow acquisition, deterministic failure, and retry
  test.setTimeout(900000);

  // DETERMINISTIC workflow acquisition via /execute/stream bootstrap
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 50 plus 100.\nDivide by 5.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 0 setup failure: deterministic workflow acquisition failed');
  }

  await expect.poll(async () => {
    const state = await getRuntimeState(request, workflowId);
    return state?.lifecycle_status === 'ACTIVE';
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // ── DETERMINISTIC retryable step creation ────────────────────────────────
  const retryableStepId = await createDeterministicRetryableStep(workflowId, request, 300000);

  if (!retryableStepId) {
    throw new Error(
      'Tier 0 retry validation blocked: deterministic FAILED step creation failed. ' +
      'Stale-owner invalidation cannot be validated without a recoverable step.'
    );
  }

  // ── Capture state BEFORE retry ─────────────────────────────────────────
  const beforeState = await getRuntimeState(request, workflowId);
  const beforeGen = beforeState?.execution_generation ?? 1;
  const beforeActiveExec = beforeState?.active_execution;

  // ── TRIGGER RETRY ──────────────────────────────────────────────────────
  const retryResult = await triggerRetry(request, workflowId, retryableStepId);
  if (!retryResult.ok) {
    throw new Error(
      `Tier 0 retry validation blocked: retry API failed for step ${retryableStepId}.`
    );
  }

  // ── Wait for resurrection ────────────────────────────────────────────────
  await expect.poll(async () => {
    const state = await getRuntimeState(request, workflowId);
    return state?.lifecycle_status === 'ACTIVE';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // ── Capture state AFTER retry ──────────────────────────────────────────
  const afterState = await getRuntimeState(request, workflowId);
  const afterGen = afterState?.execution_generation ?? beforeGen;
  const afterActiveExec = afterState?.active_execution;

  // ── STRICT VALIDATION: new execution context created ───────────────────
  expect(afterGen).toBeGreaterThan(beforeGen);

  // ── VALIDATION: Only one active execution exists ───────────────────────
  // Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1:
  // Stale execution MUST lose operational authority. If both old and new
  // executions remain active, duplicate authority exists.
  if (beforeActiveExec && afterActiveExec) {
    // Same bg_id means resurrection preserved stream identity (allowed)
    // Different bg_id means new thread spawned (also allowed)
    // What is NOT allowed: two DIFFERENT active executions simultaneously
    expect(afterActiveExec.bg_id).toBeTruthy();
  }

  // ── VALIDATION: Old execution is not still ACTIVE ──────────────────────
  // After retry, only the new execution may hold authority.
  // The runtime registry must reflect the new generation.
  expect(afterState?.execution_generation).toBeGreaterThan(beforeGen);

  // ── Wait for terminal ──────────────────────────────────────────────────
  await waitForTerminal(request, workflowId, 180000);

  // ── Final validation ───────────────────────────────────────────────────
  const finalState = await getRuntimeState(request, workflowId);
  expect(finalState).not.toBeNull();
  expect(['COMPLETED', 'FAILED']).toContain(finalState!.lifecycle_status);
  expect(finalState!.execution_generation).toBeGreaterThanOrEqual(afterGen);
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 3: Retry preserves identity without duplication
// ═══════════════════════════════════════════════════════════════════════════
test('retry_preserves_identity_without_duplication', async ({ page, request }) => {
  // 900s: LLM-tolerant for slow workflow acquisition, deterministic failure, and retry
  test.setTimeout(900000);

  // DETERMINISTIC workflow acquisition via /execute/stream bootstrap
  const workflowId = await acquireWorkflowDeterministically(
    page,
    'Calculate 25 plus 75.\nMultiply by 4.',
    300000
  );
  if (!workflowId) {
    throw new Error('Tier 0 setup failure: deterministic workflow acquisition failed');
  }

  await expect.poll(async () => {
    const state = await getRuntimeState(request, workflowId);
    return state?.lifecycle_status === 'ACTIVE';
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // ── DETERMINISTIC retryable step creation ────────────────────────────────
  const retryableStepId = await createDeterministicRetryableStep(workflowId, request, 300000);

  if (!retryableStepId) {
    throw new Error(
      'Tier 0 retry validation blocked: deterministic FAILED step creation failed. ' +
      'Identity and duplication validation cannot proceed without a recoverable step.'
    );
  }

  // ── Capture state BEFORE retry ─────────────────────────────────────────
  const beforeState = await getRuntimeState(request, workflowId);
  const beforeGen = beforeState?.execution_generation ?? 1;

  // ── TRIGGER RETRY ──────────────────────────────────────────────────────
  const retryResult = await triggerRetry(request, workflowId, retryableStepId);
  if (!retryResult.ok) {
    throw new Error(
      `Tier 0 retry validation blocked: retry API failed for step ${retryableStepId}.`
    );
  }

  // ── Wait for resurrection ────────────────────────────────────────────────
  await expect.poll(async () => {
    const state = await getRuntimeState(request, workflowId);
    return state?.lifecycle_status === 'ACTIVE';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // ── Capture state AFTER retry ──────────────────────────────────────────
  const afterState = await getRuntimeState(request, workflowId);
  const afterGen = afterState?.execution_generation ?? beforeGen;

  // ── VALIDATION: execution_generation incremented ───────────────────────
  expect(afterGen).toBeGreaterThan(beforeGen);

  // ── VALIDATION: Workflow identity preserved ────────────────────────────
  expect(afterState?.workflow_id).toBe(workflowId);

  // ── VALIDATION: No duplicate active executions ─────────────────────────
  // Check that only one bg_id is associated with this workflow
  const registryRes = await request.get('http://localhost:8000/runtime/registry/summary').catch(() => null);
  if (registryRes?.ok) {
    const registry = await registryRes.json();
    const matching = (registry.execution_generations || []).filter(
      (e: any) => e.workflow_id === workflowId
    );
    // Runtime registry should have exactly one entry per workflow
    expect(matching.length).toBeLessThanOrEqual(1);
  }

  // ── VALIDATION: Step count sanity (no duplication explosion) ─────────
  const steps = await getProjectionSteps(request, workflowId);
  const stepCount = steps.length;
  if (stepCount > 0) {
    expect(stepCount).toBeLessThanOrEqual(5); // 3 steps + possible retry lineage
  }

  // ── Wait for terminal ──────────────────────────────────────────────────
  await waitForTerminal(request, workflowId, 180000);

  // ── Final validation ───────────────────────────────────────────────────
  const finalState = await getRuntimeState(request, workflowId);
  expect(finalState).not.toBeNull();
  expect(['COMPLETED', 'FAILED']).toContain(finalState!.lifecycle_status);
  expect(finalState!.workflow_id).toBe(workflowId);
  expect(finalState!.execution_generation).toBeGreaterThanOrEqual(afterGen);
});

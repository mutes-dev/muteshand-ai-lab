/**
 * TEST HELPERS — Authoritative Runtime Reset
 *
 * Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1:
 *   Reset tooling must coordinate through runtime/orchestrator authority.
 *
 * EMERGENCY FIX (2026-06-22):
 *   Direct filesystem cleanup of production active workflows has been REMOVED.
 *   Previous implementation deleted ALL .json files under
 *   memory/active_workflows/ when the backend /admin/test/reset_runtime
 *   endpoint was disabled (the default). This caused total loss of
 *   resumable workflows. See:
 *   tmp/Emergency_Playwright_Active_Workflow_Cleanup_Hardening_Report.md
 *
 *   Tests MUST use a dedicated sandbox memory directory (e.g. via env var
 *   or monkeypatch) OR enable admin test endpoints
 *   (MH_ENABLE_ADMIN_TEST_ENDPOINTS=1) with a backend reset.
 *   Direct filesystem cleanup bypasses backend lifecycle authority and is
 *   FORBIDDEN.
 */

const BACKEND_RESET_URL = 'http://localhost:8000/admin/test/reset_runtime';

/**
 * Production path that must NEVER be touched by test helpers.
 * Any cleanup targeting this path is a data-loss bug.
 */
const PROTECTED_ACTIVE_WF_DIR = 'memory/active_workflows';

export const clearActiveWorkflows = async (): Promise<void> => {
  // PHASE 1: Authoritative backend reset ONLY.
  // Per EMERGENCY hardening: no fallback filesystem deletion.
  // If the endpoint is disabled or unreachable, the test MUST fail closed
  // rather than silently wipe production workflow state.
  let res: Response;
  try {
    res = await fetch(BACKEND_RESET_URL, { method: 'POST' });
  } catch (err) {
    const msg =
      `[test-helpers] Backend reset unreachable. ` +
      `Ensure the backend is running with MH_ENABLE_ADMIN_TEST_ENDPOINTS=1 ` +
      `or use a sandboxed test memory directory. ` +
      `Direct filesystem cleanup is DISABLED to prevent data loss.`;
    console.error(msg, err);
    throw new Error(msg);
  }

  if (!res.ok) {
    const msg =
      `[test-helpers] Backend reset returned ${res.status}. ` +
      `Enable MH_ENABLE_ADMIN_TEST_ENDPOINTS=1 on the backend ` +
      `or use a sandboxed test memory directory. ` +
      `Direct filesystem cleanup is DISABLED to prevent data loss.`;
    console.error(msg);
    throw new Error(msg);
  }

  // Allow executor recreation and registry stabilization before next test
  await new Promise((r) => setTimeout(r, 2000));
};

/**
 * Capture the set of workflow IDs currently visible in /background/list
 * so that a test can filter to only NEW workflows started during the test.
 */
export const getInitialWorkflowIds = async (): Promise<Set<string>> => {
  try {
    const res = await fetch('http://localhost:8000/background/list');
    if (!res.ok) return new Set();
    const data = await res.json() as { workflows?: Array<{ workflow_id: string }> };
    return new Set((data.workflows || []).map((w) => w.workflow_id));
  } catch {
    return new Set();
  }
};

/**
 * Discover a foreground workflow ID via /runtime/registry/summary.
 * Foreground workflows (started via /execute/stream) do NOT appear in
 * /background/list. Use this helper to discover them from the authoritative
 * runtime registry instead.
 */
export const getForegroundWorkflowId = async (
  initialIds: Set<string>,
  timeoutMs: number = 60000,
): Promise<string | null> => {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch('http://localhost:8000/runtime/registry/summary');
      if (!res.ok) { await new Promise(r => setTimeout(r, 1000)); continue; }
      const data = await res.json() as {
        execution_generations?: Array<{ workflow_id: string; status: string }>;
      };
      const entries = data.execution_generations || [];
      const newEntry = entries.find((e) => !initialIds.has(e.workflow_id));
      if (newEntry) {
        return newEntry.workflow_id;
      }
    } catch {
      // ignore
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return null;
};

/**
 * Capture the current runtime registry workflow IDs.
 */
export const getInitialRegistryIds = async (): Promise<Set<string>> => {
  try {
    const res = await fetch('http://localhost:8000/runtime/registry/summary');
    if (!res.ok) return new Set();
    const data = await res.json() as {
      execution_generations?: Array<{ workflow_id: string }>;
    };
    return new Set((data.execution_generations || []).map((e) => e.workflow_id));
  } catch {
    return new Set();
  }
};

// =============================================================================
// PHASE 4A.2 — DETERMINISTIC WORKFLOW DISCOVERY (Tier 0 Stabilization)
// =============================================================================
// Per TIER 0 PLAYWRIGHT EXECUTION STABILIZATION:
// Registry-based discovery is INDETERMINISTIC due to LLM planning latency.
// Use /execute/stream bootstrap for deterministic workflow identity acquisition.
// =============================================================================

interface StreamStartResponse {
  bg_id: string;
  status: string;
}

interface StreamWorkflowIdResponse {
  bg_id: string;
  workflow_id: string | null;
  status: string;
  result?: unknown;
}

/**
 * Start workflow via /execute/stream API and return deterministic bg_id.
 * This is the FIRST step of deterministic workflow identity acquisition.
 */
export const startWorkflowStream = async (input: string): Promise<string | null> => {
  try {
    const res = await fetch('http://localhost:8000/execute/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input }),
    });
    if (!res.ok) {
      console.warn(`[test-helpers] stream start failed: ${res.status}`);
      return null;
    }
    const data = await res.json() as StreamStartResponse;
    return data.bg_id || null;
  } catch (err) {
    console.warn('[test-helpers] stream start error:', err);
    return null;
  }
};

/**
 * Poll /execute/stream/workflow_id/{bg_id} until workflow_id is available.
 * This is the SECOND step of deterministic workflow identity acquisition.
 * Returns workflow_id once planning completes (deterministic because bg_id is known).
 */
export const pollStreamWorkflowId = async (
  bgId: string,
  timeoutMs: number = 300000,  // LLM-tolerant: 300s for slow local planning
): Promise<string | null> => {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`http://localhost:8000/execute/stream/workflow_id/${bgId}`);
      if (!res.ok) {
        await new Promise((r) => setTimeout(r, 1000));
        continue;
      }
      const data = await res.json() as StreamWorkflowIdResponse;
      if (data.workflow_id) {
        return data.workflow_id;
      }
      // Still planning (status: PENDING) — continue polling
    } catch {
      // ignore and retry
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return null;
};

/**
 * DETERMINISTIC workflow identity acquisition (hybrid API + GUI).
 *
 * 1. Start workflow via /execute/stream API (deterministic bg_id)
 * 2. Poll for workflow_id (deterministic identity once planning completes)
 * 3. Navigate GUI to workflow (preserves GUI operational validation)
 *
 * This replaces the INDETERMINISTIC registry-scanning approach.
 */
export const acquireWorkflowDeterministically = async (
  page: any,
  input: string,
  timeoutMs: number = 300000,  // LLM-tolerant: 300s for slow local planning
): Promise<string | null> => {
  // STEP 1: Start stream via API (deterministic bg_id)
  const bgId = await startWorkflowStream(input);
  if (!bgId) {
    console.error('[test-helpers] failed to start workflow stream');
    return null;
  }

  // STEP 2: Poll for workflow_id (deterministic identity)
  const workflowId = await pollStreamWorkflowId(bgId, timeoutMs);
  if (!workflowId) {
    console.error('[test-helpers] timeout waiting for workflow_id');
    return null;
  }

  // STEP 3: Navigate GUI to the workflow (preserves GUI validation surface)
  await page.goto(`http://localhost:5173/?workflow=${workflowId}`);

  return workflowId;
};

// =============================================================================
// PHASE DETERMINISTIC-FAILURE — DETERMINISTIC STEP FAILURE GENERATION
// =============================================================================
// Per DETERMINISTIC_FAILURE_GENERATION_CONTRACT_V1:
//   Reliable FAILED state generation WITHOUT LLM semantic dependency.
// =============================================================================

/**
 * AUTHENTIC deterministic failure through runtime execution.
 *
 * Routes through mutation manager → runtime naturally executes → fails authentically.
 * Per AUTHENTIC_FAILURE_CONTRACT:
 *   - NO synthetic state mutation
 *   - NO direct lifecycle writes
 *   - REAL runtime failure propagation
 *   - REAL event/projection reconciliation
 *   - REAL retry legality
 *
 * NOTE: Requires runtime support for _test_fail_trigger marker.
 * The runtime must check for _test_fail_trigger and raise an exception when present.
 *
 * Returns true if failure trigger was successfully injected, false otherwise.
 * Actual failure occurs during natural runtime execution.
 */
export const triggerDeterministicFail = async (
  workflowId: string,
  stepId: string,
  reason: string = "test_deterministic_failure",
): Promise<boolean> => {
  try {
    const res = await fetch('http://localhost:8000/admin/test/execute_deterministic_fail', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        workflow_id: workflowId,
        step_id: stepId,
        reason,
      }),
    });

    if (!res.ok) {
      console.warn(`[test-helpers] deterministic_fail trigger failed: ${res.status} ${res.statusText}`);
      return false;
    }

    const data = await res.json();
    console.log(`[test-helpers] deterministic fail triggered: ${data.workflow_id}/${data.step_id}`);
    return data.status === 'fail_triggered';
  } catch (err) {
    console.error('[test-helpers] deterministic_fail error:', err);
    return false;
  }
};

/**
 * Get the first non-terminal step ID from a workflow.
 * Useful for deterministic failure injection.
 */
export const getFirstNonTerminalStepId = async (
  workflowId: string,
): Promise<string | null> => {
  try {
    const res = await fetch(`http://localhost:8000/runtime/inspect/${workflowId}`);
    if (!res.ok) return null;

    const data = await res.json();
    const steps = data.projection_metadata?.state?.steps ?? data.steps ?? [];

    for (const step of steps) {
      const status = step.status ?? 'PENDING';
      if (!['COMPLETED', 'FAILED', 'CANCELLED'].includes(status)) {
        return step.step_id ?? step.id ?? null;
      }
    }
    return null;
  } catch {
    return null;
  }
};

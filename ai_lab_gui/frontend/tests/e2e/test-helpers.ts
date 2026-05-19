/**
 * TEST HELPERS — Authoritative Runtime Reset
 *
 * Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1:
 *   Reset tooling must coordinate through runtime/orchestrator authority.
 *
 * clearActiveWorkflows() calls the backend authoritative reset endpoint
 * (POST /admin/test/reset_runtime) which safely terminates active workflows,
 * clears runtime coordination state, and recreates the execution executor.
 * It also performs fallback filesystem cleanup for orphaned disk artifacts.
 */

import * as fs from 'fs';
import * as path from 'path';

const ACTIVE_WF_DIR = path.resolve(process.cwd(), '../../memory/active_workflows');
const BACKEND_RESET_URL = 'http://localhost:8000/admin/test/reset_runtime';

export const clearActiveWorkflows = async (): Promise<void> => {
  // PHASE 1: Authoritative backend reset (terminates active workflows, clears registries, recreates executor)
  try {
    const res = await fetch(BACKEND_RESET_URL, { method: 'POST' });
    if (!res.ok) {
      console.warn(`[test-helpers] reset endpoint returned ${res.status}: ${res.statusText}`);
    }
  } catch (err) {
    console.warn('[test-helpers] reset endpoint unreachable:', err);
  }

  // Allow executor recreation and registry stabilization before next test
  await new Promise((r) => setTimeout(r, 2000));

  // PHASE 2: Fallback filesystem cleanup (handles any orphaned disk artifacts)
  try {
    if (fs.existsSync(ACTIVE_WF_DIR)) {
      const files = fs.readdirSync(ACTIVE_WF_DIR).filter((f: string) => f.endsWith('.json'));
      for (const f of files) {
        try {
          fs.unlinkSync(path.join(ACTIVE_WF_DIR, f));
        } catch {
          // ignore
        }
      }
    }
  } catch {
    // ignore
  }
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

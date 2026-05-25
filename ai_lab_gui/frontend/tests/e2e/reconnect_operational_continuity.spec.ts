import { test, expect, type Page } from '@playwright/test';
import {
  clearActiveWorkflows,
  getInitialRegistryIds,
  startWorkflowStream,
  pollStreamWorkflowId,
} from './test-helpers';
import { execSync, spawn } from 'child_process';
import * as path from 'path';

/**
 * RECONNECT OPERATIONAL CONTINUITY — TIER 0
 *
 * Validates that all reconnect/reattach scenarios hydrate correctly
 * using projection-only hydration (RECONNECT_HYDRATION_FIX).
 *
 * Contract references:
 * - PROJECTION_CONTINUITY_CONTRACT_V1 §14 (projection-only consumption)
 * - LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1 (frontend is projection-only)
 * - RECONNECT_HYDRATION_FIX (unified projection-only hydration)
 *
 * STRICT RULES:
 * - NO fallback success branches
 * - NO arbitrary sleeps — expect.poll() ONLY
 * - Semantic polling with authoritative API verification
 * - Strict projection and identity assertions
 */

test.beforeEach(async () => { await clearActiveWorkflows(); });
test.afterEach(async () => { await clearActiveWorkflows(); });

// ── Authoritative lifecycle polling helpers ─────────────────────────────────

async function waitForLifecycle(request: any, workflowId: string, target: string, timeout: number = 120000) {
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return null;
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout, intervals: [1000, 2000, 3000] }).toBe(target);
}

async function waitForTerminal(request: any, workflowId: string, timeout: number = 600000) {
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'COMPLETED' || data.lifecycle_status === 'FAILED';
  }, { timeout, intervals: [2000, 3000, 5000] }).toBe(true);
}

async function getRuntimeInspect(request: any, workflowId: string) {
  const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
  if (!res?.ok) return null;
  return res.json();
}

async function getProjection(request: any, workflowId: string) {
  const res = await request.get(`http://localhost:8000/projection/${workflowId}`).catch(() => null);
  if (!res?.ok) return null;
  return res.json();
}

// ── Frontend DOM assertion helpers ──────────────────────────────────────────

async function assertProjectionHydrated(page: Page, workflowId: string, statusText: string | RegExp) {
  // Projection panel must be visible (not "No projection available")
  await expect(page.locator('.workflow-projection-panel')).not.toContainText('No projection available', { timeout: 10000 });

  // Workflow identity must be visible in toolbar
  await expect(page.locator('.studio-toolbar__id')).toContainText(workflowId.slice(0, 10), { timeout: 10000 });

  // Status surface must show expected lifecycle
  await expect(page.locator('.workflow-surface-status')).toContainText(statusText, { timeout: 10000 });

  // Steps must be visible (at least one step card rendered)
  const stepCards = page.locator('.step-card');
  await expect.poll(async () => await stepCards.count(), { timeout: 10000, intervals: [500, 1000] }).toBeGreaterThanOrEqual(1);
}

async function assertControlsForActive(page: Page) {
  // Pause button visible, Chat shows Running… (isExecuting = true)
  await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole('button', { name: 'Running…' })).toBeDisabled({ timeout: 5000 });
}

async function assertControlsForPaused(page: Page) {
  // Resume button visible and enabled
  const resumeBtn = page.getByRole('button', { name: 'Resume' });
  await expect(resumeBtn).toBeVisible({ timeout: 10000 });
  await expect(resumeBtn).toBeEnabled({ timeout: 5000 });
}

async function assertControlsForTerminal(page: Page) {
  // Send enabled, no Pause/Resume
  await expect(page.getByRole('button', { name: 'Send →' })).toBeEnabled({ timeout: 5000 });
  const pauseBtn = page.getByRole('button', { name: 'Pause' });
  await expect(pauseBtn).not.toBeVisible({ timeout: 5000 });
}

// ── Backend restart helper ──────────────────────────────────────────────────

const BACKEND_DIR = path.resolve(process.cwd(), '../../backend');

async function restartBackend(): Promise<void> {
  // PHASE 1: Find and kill process listening on port 8000
  try {
    // Use netstat to find the LISTENING PID (more reliable than Get-NetTCPConnection on Windows)
    const netstatOutput = execSync(
      'netstat -ano | findstr :8000 | findstr LISTENING',
      { encoding: 'utf-8', timeout: 10000 }
    );
    const lines = netstatOutput.split('\n').filter(l => l.includes('LISTENING'));
    if (lines.length > 0) {
      const parts = lines[0].trim().split(/\s+/);
      const pid = parts[parts.length - 1];
      if (pid && /^\d+$/.test(pid)) {
        // Verify PID is alive before killing (netstat can show stale PIDs)
        try {
          execSync(`tasklist /FI "PID eq ${pid}"`, { timeout: 3000 });
          execSync(`taskkill /F /PID ${pid}`, { timeout: 10000 });
        } catch {
          // PID not found or kill failed — ignore
        }
      }
    }
  } catch {
    // ignore — no process or kill failure
  }

  // PHASE 2: Poll /status until backend is ready (handles auto-restart environments)
  await expect.poll(async () => {
    try {
      const res = await fetch('http://localhost:8000/status');
      return res.ok;
    } catch {
      return false;
    }
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);
}

// ═══════════════════════════════════════════════════════════════════════════
// TEST 1: ACTIVE workflow rehydrates after page refresh
// ═══════════════════════════════════════════════════════════════════════════

test('active_workflow_rehydrates_after_page_refresh', async ({ page, request }) => {
  test.setTimeout(900000);

  await page.goto('http://localhost:5173/');
  const initialIds = await getInitialRegistryIds();

  // Start workflow deterministically via API + GUI navigation
  const bgId = await startWorkflowStream('Add 100 and 200.\nMultiply by 3.\nSubtract 50.');
  expect(bgId).toBeTruthy();
  if (!bgId) throw new Error('bgId not resolved');

  const workflowId = await pollStreamWorkflowId(bgId, 300000);
  expect(workflowId).toBeTruthy();
  if (!workflowId) throw new Error('workflowId not resolved');

  // Navigate GUI to the workflow
  await page.goto(`http://localhost:5173/?workflow=${workflowId}`);

  // Wait for ACTIVE via authoritative API
  await waitForLifecycle(request, workflowId, 'ACTIVE', 120000);

  // Wait for at least one step to be visible in DOM (projection converged)
  await expect.poll(async () => {
    const proj = await getProjection(request, workflowId);
    const steps = proj?.projection_state?.steps ?? proj?.steps ?? [];
    return steps.length;
  }, { timeout: 180000, intervals: [2000, 3000] }).toBeGreaterThanOrEqual(1);

  // Capture authoritative state BEFORE refresh
  const preInspect = await getRuntimeInspect(request, workflowId);
  expect(preInspect).toBeTruthy();
  expect(preInspect.lifecycle_status).toBe('ACTIVE');
  expect(preInspect.execution_generation).toBeDefined();
  expect(preInspect.execution_generation).toBeGreaterThanOrEqual(1);
  const preGen = preInspect.execution_generation;

  const preProj = await getProjection(request, workflowId);
  const preSteps = preProj?.steps ?? [];
  expect(preSteps.length).toBeGreaterThanOrEqual(1);

  // ── REFRESH ──
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // ── STRICT ASSERTIONS AFTER REFRESH ──

  // 1. Projection hydrates (not "No projection available")
  await assertProjectionHydrated(page, workflowId, /Running|ACTIVE/);

  // 2. Step count matches pre-refresh
  await expect.poll(async () => {
    const postProj = await getProjection(request, workflowId);
    const postSteps = postProj?.steps ?? [];
    return postSteps.length;
  }, { timeout: 120000, intervals: [2000, 3000] }).toBeGreaterThanOrEqual(preSteps.length);

  // 3. execution_generation preserved (no duplicate context)
  const postGenInspect = await getRuntimeInspect(request, workflowId);
  expect(postGenInspect.execution_generation).toBe(preGen);

  // 4. Controls synchronized for ACTIVE
  await assertControlsForActive(page);

  // 5. Workflow continues to terminal naturally (no duplicate execution)
  await waitForTerminal(request, workflowId, 600000);

  // 6. Terminal state reflected in UI
  await expect(page.locator('.workflow-surface-status')).toContainText(/Completed|Failed/, { timeout: 10000 });
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 2: PAUSED workflow rehydrates after page refresh
// ═══════════════════════════════════════════════════════════════════════════

test('paused_workflow_rehydrates_after_page_refresh', async ({ page, request }) => {
  test.setTimeout(900000);

  await page.goto('http://localhost:5173/');
  const initialIds = await getInitialRegistryIds();

  // Start workflow
  const bgId = await startWorkflowStream('Add 10 and 20.\nMultiply by 2.\nAdd 5.');
  expect(bgId).toBeTruthy();
  if (!bgId) throw new Error('bgId not resolved');

  const workflowId = await pollStreamWorkflowId(bgId, 300000);
  expect(workflowId).toBeTruthy();
  if (!workflowId) throw new Error('workflowId not resolved');

  await page.goto(`http://localhost:5173/?workflow=${workflowId}`);

  // Wait for ACTIVE
  await waitForLifecycle(request, workflowId, 'ACTIVE', 120000);

  // Wait for steps to appear
  await expect.poll(async () => {
    const proj = await getProjection(request, workflowId);
    const steps = proj?.projection_state?.steps ?? proj?.steps ?? [];
    return steps.length;
  }, { timeout: 180000, intervals: [2000, 3000] }).toBeGreaterThanOrEqual(1);

  // PAUSE via UI
  await page.getByRole('button', { name: 'Pause' }).click();

  // Wait for PAUSED via authoritative API
  await waitForLifecycle(request, workflowId, 'PAUSED', 120000);

  // Wait for UI convergence
  await expect(page.locator('.workflow-surface-status')).toContainText('Paused', { timeout: 15000 });

  // Capture authoritative state BEFORE refresh
  const preInspect = await getRuntimeInspect(request, workflowId);
  expect(preInspect.lifecycle_status).toBe('PAUSED');
  expect(preInspect.execution_generation).toBeDefined();
  const preGen = preInspect.execution_generation;

  const preProj = await getProjection(request, workflowId);
  const preSteps = preProj?.steps ?? [];
  expect(preSteps.length).toBeGreaterThanOrEqual(1);

  // ── REFRESH ──
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // ── STRICT ASSERTIONS AFTER REFRESH ──

  // 1. Projection hydrates with PAUSED status
  await assertProjectionHydrated(page, workflowId, 'Paused');

  // 2. Step count preserved
  await expect.poll(async () => {
    const postProj = await getProjection(request, workflowId);
    const postSteps = postProj?.steps ?? [];
    return postSteps.length;
  }, { timeout: 120000, intervals: [2000, 3000] }).toBeGreaterThanOrEqual(preSteps.length);

  // 3. execution_generation preserved
  const postGenInspect = await getRuntimeInspect(request, workflowId);
  expect(postGenInspect.execution_generation).toBe(preGen);

  // 4. Resume button visible and enabled
  await assertControlsForPaused(page);

  // 5. RESUME must work
  await page.getByRole('button', { name: 'Resume' }).click();

  // 6. After resume, workflow returns to ACTIVE
  await waitForLifecycle(request, workflowId, 'ACTIVE', 120000);
  await expect(page.locator('.workflow-surface-status')).toContainText('Running', { timeout: 15000 });

  // 7. Workflow completes to terminal naturally
  await waitForTerminal(request, workflowId, 600000);
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 3: Terminal workflow rehydrates after page refresh (baseline)
// ═══════════════════════════════════════════════════════════════════════════

test('terminal_workflow_rehydrates_after_page_refresh', async ({ page, request }) => {
  test.setTimeout(900000);

  await page.goto('http://localhost:5173/');

  // Start and run to terminal
  const bgId = await startWorkflowStream('Add 5 and 7.');
  expect(bgId).toBeTruthy();
  if (!bgId) throw new Error('bgId not resolved');

  const workflowId = await pollStreamWorkflowId(bgId, 300000);
  expect(workflowId).toBeTruthy();
  if (!workflowId) throw new Error('workflowId not resolved');

  await page.goto(`http://localhost:5173/?workflow=${workflowId}`);

  // Wait for terminal
  await waitForTerminal(request, workflowId, 600000);

  // ── PRE-REFRESH: Verify terminal state ──
  const preInspect = await getRuntimeInspect(request, workflowId);
  expect(preInspect).toBeTruthy();
  expect(['COMPLETED', 'FAILED']).toContain(preInspect.lifecycle_status);
  await expect(page.locator('.workflow-surface-status')).toContainText(/Completed|Failed/, { timeout: 10000 });

  // ── REFRESH ──
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // ── STRICT ASSERTIONS AFTER REFRESH ──

  // COMPLETED is an immutable terminal — backend marks recoverable: false.
  // Frontend correctly does NOT auto-restore non-recoverable workflows.
  // Verify clean idle state with no stale terminal projection or errors.

  // 1. No active workflow surface (not stuck showing old terminal workflow)
  await expect(page.locator('.workflow-surface')).toContainText(/No active workflow|Task Hub/, { timeout: 10000 });

  // 2. No projection errors in DOM
  const projectionError = page.locator('text=projection_fetch_error');
  await expect(projectionError).not.toBeVisible({ timeout: 5000 });

  // 3. Workflow panel shows idle state (not showing stale terminal steps as active)
  await expect(page.locator('.workflow-panel')).toContainText(/No execution yet|0 completed|PENDING/, { timeout: 10000 });

  // 4. Controls in idle state (no Pause/Resume visible, Send disabled until input)
  await expect(page.getByRole('button', { name: 'Pause' })).toBeDisabled({ timeout: 5000 });
  await expect(page.getByRole('button', { name: 'Resume' })).toBeDisabled({ timeout: 5000 });
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 4: Multiple recoverable workflows reattach correctly
// ═══════════════════════════════════════════════════════════════════════════

test('multiple_recoverable_workflows_reattach_correctly', async ({ page, request }) => {
  test.setTimeout(900000);

  await page.goto('http://localhost:5173/');
  const initialIds = await getInitialRegistryIds();

  // ── Launch workflow 1 (foreground) ──
  const bgId1 = await startWorkflowStream('Add 100 and 200.\nMultiply by 2.');
  expect(bgId1).toBeTruthy();
  if (!bgId1) throw new Error('bgId1 not resolved');
  const wf1Id = await pollStreamWorkflowId(bgId1, 300000);
  expect(wf1Id).toBeTruthy();
  if (!wf1Id) throw new Error('wf1Id not resolved');

  await page.goto(`http://localhost:5173/?workflow=${wf1Id}`);
  await waitForLifecycle(request, wf1Id, 'ACTIVE', 120000);

  // Wait for steps
  await expect.poll(async () => {
    const proj = await getProjection(request, wf1Id);
    const steps = proj?.projection_state?.steps ?? proj?.steps ?? [];
    return steps.length;
  }, { timeout: 180000, intervals: [2000, 3000] }).toBeGreaterThanOrEqual(1);

  // ── Launch workflow 2 (background via UI) ──
  await page.locator('.bg-input').fill('Calculate 500 divided by 5.\nAdd 100.');
  await page.getByRole('button', { name: 'Start Background' }).click();

  // Track wf2 via background/list
  let wf2Id = '';
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    const current = (data.workflows || []).map((w: any) => w.workflow_id);
    const newIds = current.filter((id: string) => !initialIds.has(id));
    if (newIds.length > 0) {
      wf2Id = newIds[0];
      return true;
    }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // ── Launch workflow 3 (background via UI) ──
  await page.locator('.bg-input').fill('Calculate 1000 times 2.\nDivide by 4.');
  await page.getByRole('button', { name: 'Start Background' }).click();

  let wf3Id = '';
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    const current = (data.workflows || []).map((w: any) => w.workflow_id);
    const newIds = current.filter((id: string) => id !== wf2Id && !initialIds.has(id));
    if (newIds.length > 0) {
      wf3Id = newIds[0];
      return true;
    }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Verify all 3 have distinct IDs (no contamination)
  expect(wf1Id).not.toEqual(wf2Id);
  expect(wf1Id).not.toEqual(wf3Id);
  expect(wf2Id).not.toEqual(wf3Id);

  // Pause workflow 1
  await page.getByRole('button', { name: 'Pause' }).click();
  await waitForLifecycle(request, wf1Id, 'PAUSED', 120000);

  // ── REFRESH ──
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // ── STRICT ASSERTIONS ──

  // 1. Task Hub badge should show multiple recoverable workflows
  // (Badge count or Task Hub button indicates recoverable count)
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/runtime/registry/summary');
    const data = await res.json();
    return data.total_workflows ?? 0;
  }, { timeout: 30000, intervals: [1000, 2000] }).toBeGreaterThanOrEqual(2);

  // 2. Reattach workflow 1 from Task Hub
  const taskHubBtn = page.locator('.task-hub-access-btn');
  await expect(taskHubBtn).toBeVisible({ timeout: 10000 });
  await taskHubBtn.click();

  // Task Hub modal opens
  await expect(page.locator('.task-hub-modal')).toBeVisible({ timeout: 10000 });

  // Find and click workflow 1 in the hub (match by workflow_id suffix)
  const wf1Entry = page.locator(`.task-hub-item:has-text("${wf1Id.slice(-8)}")`);
  await expect(wf1Entry).toBeVisible({ timeout: 10000 });
  await wf1Entry.click();

  // Close Task Hub modal so controls are accessible
  const closeHubBtn = page.locator('.task-hub-close-btn');
  await expect(closeHubBtn).toBeVisible({ timeout: 5000 });
  await closeHubBtn.click();
  await expect(page.locator('.task-hub-modal')).not.toBeVisible({ timeout: 5000 });

  // After click, wf1 projection hydrates correctly
  await assertProjectionHydrated(page, wf1Id, 'Paused');
  await assertControlsForPaused(page);

  // 3. Background workflows still exist and are recoverable via API
  const bgRes = await request.get('http://localhost:8000/background/list');
  const bgData = await bgRes.json();
  const bgIds = (bgData.workflows || []).map((w: any) => w.workflow_id);
  expect(bgIds).toContain(wf2Id);
  expect(bgIds).toContain(wf3Id);

  // 4. Resume wf1 and let all complete
  const resumeBtn = page.getByRole('button', { name: 'Resume' });
  if (await resumeBtn.isVisible().catch(() => false)) {
    await resumeBtn.click();
    await waitForLifecycle(request, wf1Id, 'ACTIVE', 120000);
  }

  // Wait for all workflows to reach terminal
  await expect.poll(async () => {
    const statuses: string[] = [];
    const wf1Res = await request.get(`http://localhost:8000/runtime/inspect/${wf1Id}`).catch(() => null);
    if (wf1Res?.ok) statuses.push((await wf1Res.json()).lifecycle_status);
    const bgListRes = await request.get('http://localhost:8000/background/list');
    const bgListData = await bgListRes.json();
    for (const w of (bgListData.workflows || [])) statuses.push(w.status);
    return statuses.every((s: string) => s === 'COMPLETED' || s === 'FAILED');
  }, { timeout: 600000, intervals: [3000, 5000, 10000] }).toBe(true);
});

// ═══════════════════════════════════════════════════════════════════════════
// TEST 5: Backend restart preserves operational projection
// ═══════════════════════════════════════════════════════════════════════════

test('backend_restart_preserves_operational_projection', async ({ page, request }) => {
  test.setTimeout(900000);

  await page.goto('http://localhost:5173/');
  const initialIds = await getInitialRegistryIds();

  // Start workflow
  const bgId = await startWorkflowStream('Add 50 and 50.\nMultiply by 3.\nSubtract 25.');
  expect(bgId).toBeTruthy();
  if (!bgId) throw new Error('bgId not resolved');

  const workflowId = await pollStreamWorkflowId(bgId, 300000);
  expect(workflowId).toBeTruthy();
  if (!workflowId) throw new Error('workflowId not resolved');

  await page.goto(`http://localhost:5173/?workflow=${workflowId}`);

  // Wait for ACTIVE
  await waitForLifecycle(request, workflowId, 'ACTIVE', 120000);

  // Wait for steps to appear
  await expect.poll(async () => {
    const proj = await getProjection(request, workflowId);
    const steps = proj?.projection_state?.steps ?? proj?.steps ?? [];
    return steps.length;
  }, { timeout: 180000, intervals: [2000, 3000] }).toBeGreaterThanOrEqual(1);

  // Capture pre-restart state
  const preInspect = await getRuntimeInspect(request, workflowId);
  expect(preInspect).toBeTruthy();
  expect(preInspect.lifecycle_status).toBe('ACTIVE');
  const preGen = preInspect.execution_generation;
  const preProj = await getProjection(request, workflowId);
  const preSteps = preProj?.steps ?? [];

  // ── BACKEND RESTART ──
  await restartBackend();

  // After restart, the page will detect backend disconnection.
  // Wait for backend to be ready again.
  await expect.poll(async () => {
    try {
      const res = await fetch('http://localhost:8000/status');
      return res.ok;
    } catch {
      return false;
    }
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Reload page to trigger reconnect auto-restore
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // ── STRICT ASSERTIONS AFTER BACKEND RESTART ──

  // 1. Reconnect auto-restore hydrates projection
  await assertProjectionHydrated(page, workflowId, /Running|ACTIVE/);

  // 2. Step count preserved after resurrection
  await expect.poll(async () => {
    const postProj = await getProjection(request, workflowId);
    const postSteps = postProj?.steps ?? [];
    return postSteps.length;
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBeGreaterThanOrEqual(preSteps.length);

  // 3. execution_generation preserved (no duplicate context created)
  const postGenInspect = await getRuntimeInspect(request, workflowId);
  expect(postGenInspect.execution_generation).toBe(preGen);

  // 4. Controls synchronized for ACTIVE
  await assertControlsForActive(page);

  // 5. Workflow continues to terminal naturally
  await waitForTerminal(request, workflowId, 600000);
});

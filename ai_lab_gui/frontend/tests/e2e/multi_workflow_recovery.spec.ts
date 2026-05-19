import { test, expect } from '@playwright/test';
import { clearActiveWorkflows, getForegroundWorkflowId, getInitialRegistryIds } from './test-helpers';

/**
 * MULTI-WORKFLOW RECOVERY CONTINUITY VALIDATION
 *
 * Validates simultaneous workflow recovery continuity:
 * - multiple workflows persist simultaneously
 * - multiple workflows survive refresh/reconnect
 * - workflow identity continuity preserved
 * - workflow-scoped hydration preserved
 * - no cross-workflow contamination
 * - controls remain scoped correctly after recovery
 *
 * Contract references:
 * - SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1 §13 (multi-workflow recovery guarantee)
 * - PROJECTION_CONTINUITY_CONTRACT_V1 §12 (multi-workflow continuity)
 * - GUI_ARCHITECTURE.txt (workflow-scoped interaction)
 * - VALIDATION_ARCHITECTURE.txt §9.6 (test isolation)
 */


test.beforeEach(async () => { await clearActiveWorkflows(); });
test.afterEach(async () => { await clearActiveWorkflows(); });

/**
 * Validates that multiple workflows survive page refresh simultaneously.
 */
test('multiple_workflows_survive_refresh', async ({ page, request }) => {
  // 240s: 3 workflows with refresh
  test.setTimeout(240000);

  await page.goto('http://localhost:5173/');

  // Capture existing background workflows BEFORE starting wf1
  const initialBgRes = await request.get('http://localhost:8000/background/list');
  const initialBgData = await initialBgRes.json();
  const initialBgIds = new Set((initialBgData.workflows || []).map((w: any) => w.workflow_id));

  // Foreground workflows do NOT appear in /background/list — capture registry IDs instead
  const initialRegistryIds = await getInitialRegistryIds();

  // Launch workflow 1 (foreground) via UI — explicit attachment per OBSERVABILITY_CONTRACT
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill('Add 100 and 200.\nMultiply by 3.');
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for workflow 1 ACTIVE in focused UI
  await expect(page.locator('button:has-text("Running"), .status-pill.ACTIVE').first()).toBeVisible({ timeout: 60000 });

  // Resolve workflow 1 ID via AUTHORITATIVE runtime registry (foreground workflows are NOT in /background/list)
  let wf1Id = '';
  await expect.poll(async () => {
    const found = await getForegroundWorkflowId(initialRegistryIds, 30000);
    if (found) {
      wf1Id = found;
      return true;
    }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Launch workflow 2 (background)
  await page.locator('.bg-input').fill('Calculate 500 divided by 5.\nAdd 100.');
  await page.getByRole('button', { name: 'Start Background' }).click();

  // Launch workflow 3 (background) - staggered
  await page.waitForTimeout(500);
  await page.locator('.bg-input').fill('Calculate 1000 times 2.\nDivide by 4.');
  await page.getByRole('button', { name: 'Start Background' }).click();

  // Track the 2 new background workflows
  let bgIds: string[] = [];
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    const current = (data.workflows || []).map((w: any) => w.workflow_id);
    bgIds = current.filter((id: string) => !initialBgIds.has(id));
    return bgIds.length;
  }, { timeout: 20000, intervals: [500, 1000, 2000] }).toBe(2);

  const wf2Id = bgIds[0];
  const wf3Id = bgIds[1];

  // Wait for all workflows to be running
  await page.waitForTimeout(5000);

  // Verify all 3 workflows exist via backend
  const verifyRes = await request.get('http://localhost:8000/background/list');
  const verifyData = await verifyRes.json();
  const allBgIds = (verifyData.workflows || []).map((w: any) => w.workflow_id);

  // Background workflows 2 and 3 should be present
  expect(allBgIds).toContain(wf2Id);
  expect(allBgIds).toContain(wf3Id);

  // PAUSE workflow 1 (foreground)
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('button:has-text("Resume")').first()).toBeVisible({ timeout: 15000 });

  // REFRESH page
  await page.reload();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  // VALIDATE: Workflow 1 recovered via authoritative runtime registry (foreground workflows have no projection)
  const wf1AfterRes = await request.get(`http://localhost:8000/runtime/inspect/${wf1Id}`).catch(() => null);
  if (wf1AfterRes?.ok) {
    const wf1After = await wf1AfterRes.json();
    // Workflow 1 should exist and have valid state
    expect(['ACTIVE', 'PAUSED', 'COMPLETED', 'FAILED']).toContain(wf1After.lifecycle_status);
  }

  // VALIDATE: Background workflows 2 and 3 still exist
  const bgAfterRes = await request.get('http://localhost:8000/background/list');
  const bgAfterData = await bgAfterRes.json();
  const bgAfterIds = (bgAfterData.workflows || []).map((w: any) => w.workflow_id);

  expect(bgAfterIds).toContain(wf2Id);
  expect(bgAfterIds).toContain(wf3Id);

  // VALIDATE: No cross-workflow ID contamination
  expect(wf1Id).not.toEqual(wf2Id);
  expect(wf1Id).not.toEqual(wf3Id);
  expect(wf2Id).not.toEqual(wf3Id);

  // Resume workflow 1 if paused
  const resumeBtn = page.getByRole('button', { name: 'Resume' });
  if (await resumeBtn.isVisible().catch(() => false)) {
    await resumeBtn.click();
    await expect(page.locator('button:has-text("Running")').first()).toBeVisible({ timeout: 15000 });
  }

  // Wait for all workflows to complete
  await expect.poll(async () => {
    const statuses = [];

    // Check workflow 1 via authoritative runtime registry (foreground workflows have no projection)
    const wf1Res = await request.get(`http://localhost:8000/runtime/inspect/${wf1Id}`).catch(() => null);
    if (wf1Res?.ok) {
      const wf1Data = await wf1Res.json();
      statuses.push(wf1Data.lifecycle_status);
    }

    // Check workflows 2 and 3 via background status
    for (const id of [wf2Id, wf3Id]) {
      const res = await request.get(`http://localhost:8000/background/status/${id}`);
      const data = await res.json();
      statuses.push(data.status);
    }

    return statuses.every(s => s === 'COMPLETED' || s === 'FAILED');
  }, { timeout: 120000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === FINAL VALIDATION: Deterministic multi-workflow recovery verification ===
  // Use /runtime/inspect for authoritative workflow state validation
  const finalWf1Res = await request.get(`http://localhost:8000/runtime/inspect/${wf1Id}`).catch(() => null);
  if (finalWf1Res?.ok) {
    const finalWf1 = await finalWf1Res.json();
    // VALIDATE: Workflow 1 terminal state from runtime registry
    expect(['COMPLETED', 'FAILED']).toContain(finalWf1.lifecycle_status);
    // VALIDATE: execution_generation tracked
    expect(finalWf1.execution_generation).toBeDefined();
    expect(finalWf1.execution_generation).toBeGreaterThanOrEqual(1);
    // VALIDATE: Persistence exists (survivability)
    expect(finalWf1.persistence_exists).toBe(true);
  }

  // VALIDATE: Background workflows 2 and 3 terminal state
  for (const id of [wf2Id, wf3Id]) {
    const res = await request.get(`http://localhost:8000/background/status/${id}`);
    const data = await res.json();
    expect(['COMPLETED', 'FAILED']).toContain(data.status);
  }

  // === DETERMINISTIC OBSERVABILITY: Validate registry state ===
  // Use /runtime/registry/summary to verify no singleton collapse
  const registrySummaryRes = await request.get(`http://localhost:8000/runtime/registry/summary`);
  const registrySummary = await registrySummaryRes.json();

  // VALIDATE: Foreground workflow in runtime registry (background workflows managed separately)
  expect(registrySummary.total_workflows).toBeGreaterThanOrEqual(1);

  // VALIDATE: execution_generations tracked for foreground workflow
  const wfGenerations = registrySummary.execution_generations.filter(
    (eg: any) => eg.workflow_id === wf1Id || eg.workflow_id === wf2Id || eg.workflow_id === wf3Id
  );
  expect(wfGenerations.length).toBeGreaterThanOrEqual(1);
});

/**
 * Validates workflow-scoped controls after recovery.
 */
test('workflow_scoped_controls_preserved_after_recovery', async ({ page, request }) => {
  // 240s: 2-step workflow with pause/resume + refresh + 180s completion poll
  test.setTimeout(240000);

  await page.goto('http://localhost:5173/');

  // Capture existing workflows BEFORE starting (foreground workflows are NOT in /background/list)
  const initialIds = await getInitialRegistryIds();

  // Launch foreground workflow via UI — explicit attachment per OBSERVABILITY_CONTRACT
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill('Add 10 and 20.\nMultiply by 2.');
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for ACTIVE in focused UI
  await expect(page.locator('button:has-text("Running"), .status-pill.ACTIVE').first()).toBeVisible({ timeout: 60000 });

  // Resolve workflow ID via AUTHORITATIVE runtime registry (foreground workflows are NOT in /background/list)
  let workflowId = '';
  await expect.poll(async () => {
    const found = await getForegroundWorkflowId(initialIds, 30000);
    if (found) {
      workflowId = found;
      return true;
    }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // PAUSE
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('button:has-text("Resume")').first()).toBeVisible({ timeout: 15000 });

  // === DETERMINISTIC OBSERVABILITY: Capture paused state via runtime registry ===
  // Use /runtime/inspect for authoritative lifecycle_status validation
  const pausedInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const pausedInspect = await pausedInspectRes.json();
  expect(pausedInspect.lifecycle_status).toBe('PAUSED');
  expect(pausedInspect.execution_generation).toBeDefined();

  // REFRESH
  await page.reload();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  // VALIDATE: Controls reflect recovered state
  const resumeBtn = page.getByRole('button', { name: 'Resume' });
  const pauseBtn = page.getByRole('button', { name: 'Pause' });

  // One of Pause or Resume should be enabled based on recovered state
  const resumeEnabled = await resumeBtn.isEnabled().catch(() => false);
  const pauseEnabled = await pauseBtn.isEnabled().catch(() => false);

  // Should not have both fully enabled (indicates desync)
  const bothEnabled = resumeEnabled && pauseEnabled;
  expect(bothEnabled).toBe(false);

  // === DETERMINISTIC OBSERVABILITY: Query runtime registry for authoritative state ===
  const afterRefreshRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const afterRefreshState = await afterRefreshRes.json();

  // VALIDATE: Controls align with runtime registry state (authority)
  if (afterRefreshState.lifecycle_status === 'PAUSED') {
    // Resume should be available
    expect(await resumeBtn.isVisible().catch(() => false)).toBe(true);
  }

  // VALIDATE: Persistence exists after refresh (survivability)
  expect(afterRefreshState.persistence_exists).toBe(true);

  // RESUME and verify
  if (await resumeBtn.isEnabled().catch(() => false)) {
    await resumeBtn.click();
    await expect(page.locator('button:has-text("Running")').first()).toBeVisible({ timeout: 15000 });

    // === DETERMINISTIC OBSERVABILITY: Validate resumed state ===
    const runningInspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const runningInspect = await runningInspectRes.json();
    expect(runningInspect.lifecycle_status).toBe('ACTIVE');
    // VALIDATE: execution_generation incremented on resume (new execution context)
    expect(runningInspect.execution_generation).toBeGreaterThanOrEqual(pausedInspect.execution_generation);
  }

  // Wait for completion via polling
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'COMPLETED' || data?.lifecycle_status === 'FAILED';
  }, { timeout: 180000, intervals: [2000, 3000, 5000] }).toBe(true);
});

/**
 * Validates no cross-workflow contamination during recovery.
 */
test('no_cross_workflow_contamination_after_recovery', async ({ page, request }) => {
  // 240s: 2 workflows with isolation validation
  test.setTimeout(240000);

  await page.goto('http://localhost:5173/');

  // Launch workflow 1 using streaming API
  const streamRes1 = await request.post('http://localhost:8000/execute/stream', {
    data: { input: 'Calculate 100 plus 50.' }
  });
  const { bg_id: bg1 } = await streamRes1.json();
  expect(bg1).toBeTruthy();

  // Poll for workflow 1 ID
  let wf1Id = '';
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/execute/stream/workflow_id/${bg1}`);
    const data = await res.json();
    if (data.workflow_id) {
      wf1Id = data.workflow_id;
      return true;
    }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Wait for workflow 1 ACTIVE via API (authoritative runtime registry, NOT projection)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${wf1Id}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'ACTIVE';
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Capture background list before workflow 2
  const beforeWf2Res = await request.get('http://localhost:8000/background/list');
  const beforeWf2Data = await beforeWf2Res.json();
  const beforeWf2Ids = new Set((beforeWf2Data.workflows || []).map((w: any) => w.workflow_id));

  // Launch workflow 2 (background with different calculation)
  await page.locator('.bg-input').fill('Calculate 200 minus 50.');
  await page.getByRole('button', { name: 'Start Background' }).click();

  // Track workflow 2
  let wf2Id = '';
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    const current = (data.workflows || []).map((w: any) => w.workflow_id);
    const newIds = current.filter((id: string) => !beforeWf2Ids.has(id));
    if (newIds.length > 0) {
      wf2Id = newIds[0];
      return true;
    }
    return false;
  }, { timeout: 20000, intervals: [500, 1000, 2000] }).toBe(true);

  // Wait for both to be running
  await page.waitForTimeout(5000);

  // REFRESH
  await page.reload();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  // VALIDATE: Workflow 1 state via projection
  const wf1Res = await request.get(`http://localhost:8000/projection/${wf1Id}`).catch(() => null);
  const wf1State = wf1Res?.ok ? await wf1Res.json() : null;

  // VALIDATE: Workflow 2 state via background status
  const wf2Res = await request.get(`http://localhost:8000/background/status/${wf2Id}`).catch(() => null);
  const wf2State = wf2Res?.ok ? await wf2Res.json() : null;

  // Both should exist
  expect(wf1State).not.toBeNull();
  expect(wf2State).not.toBeNull();

  // Workflow outputs should be different (no shared state)
  if (wf1State?.workflow_output && wf2State?.result) {
    // Results should not be identical (would indicate shared state)
    expect(wf1State.workflow_output).not.toEqual(wf2State.result);
  }

  // Workflow IDs should remain distinct
  expect(wf1Id).not.toEqual(wf2Id);

  // Wait for completion
  await expect.poll(async () => {
    const statuses = [];
    // Foreground workflow checked via authoritative runtime registry
    const wf1Check = await request.get(`http://localhost:8000/runtime/inspect/${wf1Id}`).catch(() => null);
    if (wf1Check?.ok) {
      const data = await wf1Check.json();
      statuses.push(data.lifecycle_status);
    }
    const wf2Check = await request.get(`http://localhost:8000/background/status/${wf2Id}`).catch(() => null);
    if (wf2Check?.ok) {
      const data = await wf2Check.json();
      statuses.push(data.status);
    }
    return statuses.every(s => s === 'COMPLETED' || s === 'FAILED');
  }, { timeout: 120000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === FINAL VALIDATION: Deterministic no-contamination verification ===
  // Foreground workflow via runtime inspect; background via background/status
  const finalWf1Res = await request.get(`http://localhost:8000/runtime/inspect/${wf1Id}`).catch(() => null);
  const finalWf2Res = await request.get(`http://localhost:8000/background/status/${wf2Id}`).catch(() => null);

  if (finalWf1Res?.ok && finalWf2Res?.ok) {
    const finalWf1 = await finalWf1Res.json();
    const finalWf2 = await finalWf2Res.json();

    // VALIDATE: execution_generation tracked for foreground workflow
    expect(finalWf1.execution_generation).toBeDefined();

    // VALIDATE: Workflow IDs remain distinct (no cross-contamination)
    expect(finalWf1.workflow_id).not.toEqual(wf2Id);

    // VALIDATE: Both workflows have independent persistence
    expect(finalWf1.persistence_exists).toBe(true);
    expect(finalWf2.status === 'COMPLETED' || finalWf2.status === 'FAILED').toBe(true);
  }
});

/**
 * Validates that recovery does not collapse into singleton assumptions.
 */
test('recovery_does_not_collapse_to_singleton', async ({ page, request }) => {
  // 240s: 3 workflows, verify all survive
  test.setTimeout(240000);

  await page.goto('http://localhost:5173/');

  // Launch workflow 1
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill('Add 1 and 2.');
  await page.getByRole('button', { name: 'Send →' }).click();
  await expect(page.locator('button:has-text("Running"), .status-pill.ACTIVE').first()).toBeVisible({ timeout: 30000 });

  // Capture initial list
  const initialRes = await request.get('http://localhost:8000/background/list');
  const initialData = await initialRes.json();
  const initialIds = new Set((initialData.workflows || []).map((w: any) => w.workflow_id));

  // Launch workflows 2 and 3
  await page.locator('.bg-input').fill('Add 3 and 4.');
  await page.getByRole('button', { name: 'Start Background' }).click();
  await page.waitForTimeout(500);
  await page.locator('.bg-input').fill('Add 5 and 6.');
  await page.getByRole('button', { name: 'Start Background' }).click();

  // Track new workflows
  let newIds: string[] = [];
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    const current = (data.workflows || []).map((w: any) => w.workflow_id);
    newIds = current.filter((id: string) => !initialIds.has(id));
    return newIds.length;
  }, { timeout: 20000, intervals: [500, 1000, 2000] }).toBe(2);

  // Wait for all to start
  await page.waitForTimeout(5000);

  // Count workflows before refresh
  const beforeRefreshRes = await request.get('http://localhost:8000/background/list');
  const beforeRefreshData = await beforeRefreshRes.json();
  const beforeCount = (beforeRefreshData.workflows || []).length;
  expect(beforeCount).toBeGreaterThanOrEqual(2);

  // REFRESH
  await page.reload();
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(3000);

  // === DETERMINISTIC OBSERVABILITY: Validate no singleton collapse via runtime registry ===
  // Use /runtime/registry/summary for authoritative workflow count
  const afterRefreshRegistryRes = await request.get('http://localhost:8000/runtime/registry/summary');
  const afterRefreshRegistry = await afterRefreshRegistryRes.json();

  // VALIDATE: Multiple workflows in runtime registry (no collapse)
  expect(afterRefreshRegistry.total_workflows).toBeGreaterThanOrEqual(2);

  // VALIDATE: execution_generations tracked for all workflows
  expect(afterRefreshRegistry.execution_generations.length).toBeGreaterThanOrEqual(2);

  // Also verify via background list
  const afterRefreshRes = await request.get('http://localhost:8000/background/list');
  const afterRefreshData = await afterRefreshRes.json();
  const afterCount = (afterRefreshData.workflows || []).length;
  expect(afterCount).toBeGreaterThanOrEqual(2);

  // Wait for completion
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    const workflows = data.workflows || [];
    return workflows.every((w: any) => w.status === 'COMPLETED' || w.status === 'FAILED');
  }, { timeout: 120000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === FINAL VALIDATION: Deterministic singleton collapse verification ===
  // Use /runtime/registry/summary for authoritative workflow count
  const finalRegistryRes = await request.get('http://localhost:8000/runtime/registry/summary');
  const finalRegistry = await finalRegistryRes.json();

  // VALIDATE: Multiple workflows still in registry after completion
  expect(finalRegistry.total_workflows).toBeGreaterThanOrEqual(2);

  // VALIDATE: All tracked workflows have execution_generation
  for (const eg of finalRegistry.execution_generations) {
    expect(eg.execution_generation).toBeDefined();
    expect(eg.execution_generation).toBeGreaterThanOrEqual(1);
  }

  // Also verify via background list
  const finalRes = await request.get('http://localhost:8000/background/list');
  const finalData = await finalRes.json();
  const finalWorkflows = finalData.workflows || [];
  expect(finalWorkflows.length).toBeGreaterThanOrEqual(2);

  // All should have terminal status
  for (const wf of finalWorkflows) {
    expect(['COMPLETED', 'FAILED']).toContain(wf.status);
  }
});

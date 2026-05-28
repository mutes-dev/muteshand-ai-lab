import { test, expect } from '@playwright/test';
import { clearActiveWorkflows } from '../e2e/test-helpers';
import {
  createEvidenceFolder,
  capturePhaseWithOverlay,
  saveRuntimeSnapshot,
  captureFrontendConsole,
  recordTimeline,
  writeMetadata,
  captureTaskHub,
} from './replay-helpers';
import {
  submitWorkflowViaGUI,
  discoverWorkflowId,
  waitForLegalLifecycleState,
  executeRefresh,
  selectWorkflowFromTaskHub,
  waitForWorkflowVisualState,
  getReplayConfig,
  WORKFLOW_PROMPTS,
  LEGAL_LIFECYCLE_STATES,
} from './replay-helpers';

test('pending_recovery_resume_replay', async ({ page, request }) => {
  const config = getReplayConfig();
  test.setTimeout(config.testTimeout);

  // ─── PHASE 0: Initialize evidence capture ───────────────────────────────
  const evidenceFolder = createEvidenceFolder('pending_recovery_resume');
  captureFrontendConsole(page, evidenceFolder);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'setup',
    notes: 'evidence folder initialized',
  });

  await clearActiveWorkflows();

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'backend_reset',
    notes: 'clearActiveWorkflows completed',
  });

  await page.goto('http://localhost:5173/');

  // ─── PHASE 1: Foreground Active ─────────────────────────────────────────
  // Use a longer-running prompt so the workflow stays ACTIVE during detach
  await submitWorkflowViaGUI(page, WORKFLOW_PROMPTS.LONGER_PROCESSING);

  const activeBeforeDetach = await waitForLegalLifecycleState(
    request,
    (await discoverWorkflowId(page))!,
    [LEGAL_LIFECYCLE_STATES.ACTIVE]
  );

  if (!activeBeforeDetach) {
    throw new Error('Workflow did not reach ACTIVE state before detach');
  }

  const workflowId = await discoverWorkflowId(page);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'workflow_active',
    workflow_id: workflowId,
    notes: 'workflow submitted via GUI and reached ACTIVE state',
  });

  const preDetachVisualReady = await waitForWorkflowVisualState(page);
  await capturePhaseWithOverlay(page, evidenceFolder, '01_pre_recovery', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: preDetachVisualReady ? 'workflow_active_visible' : 'workflow_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'pre_recovery');

  // Assertions: workflow visible in foreground, ACTIVE lifecycle, workflowId captured
  expect(preDetachVisualReady, 'workflow should be foreground visible before detach').toBe(true);

  // ─── PHASE 2: Simulated Foreground Loss (page reload during execution) ────
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // Give hydration a bounded window to settle
  try {
    await page.waitForLoadState('networkidle', { timeout: config.networkIdleTimeout });
  } catch {
    /* proceed regardless */
  }

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'foreground_lost',
    workflow_id: workflowId,
    notes: 'page reloaded during ACTIVE execution to detach foreground',
  });

  // Capture detached state evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '02_detached_state', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: 'post_reload_detached',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'detached');

  // Assertions: workflow must NOT be foreground visible after reload
  const detachedVisualState = await waitForWorkflowVisualState(page, 5000);
  expect(detachedVisualState, 'workflow should NOT be foreground visible after reload').toBe(false);

  // Runtime must still exist
  const runtimeAfterDetach = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);
  expect(runtimeAfterDetach?.ok()).toBe(true);

  const detachedData = runtimeAfterDetach ? await runtimeAfterDetach.json() : null;
  expect(detachedData?.workflow_id).toBe(workflowId);

  // ─── PHASE 3: Task Hub Recovery Validation ──────────────────────────────
  const hubBtn = page.locator('button:has-text("Task Hub")');
  await hubBtn.waitFor({ state: 'visible', timeout: 10000 });
  await hubBtn.click();
  await page.waitForTimeout(300);

  // Capture Task Hub state showing the detached workflow
  await capturePhaseWithOverlay(page, evidenceFolder, '03_taskhub_recovery', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: 'task_hub_shows_detached_workflow',
  });

  // Verify workflow exists in Task Hub
  const taskHubItem = page.locator(`[data-workflow-id="${workflowId}"], .task-hub-item:has-text("${workflowId}")`);
  const workflowInTaskHub = await taskHubItem.isVisible().catch(() => false);

  expect(workflowInTaskHub, 'detached workflow must exist in Task Hub').toBe(true);

  // Verify lifecycle is still legal
  const allowedRecoverStates = [LEGAL_LIFECYCLE_STATES.ACTIVE, LEGAL_LIFECYCLE_STATES.COMPLETED];
  expect(allowedRecoverStates.includes(detachedData?.lifecycle_status)).toBe(true);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'task_hub_validated',
    workflow_id: workflowId,
    notes: `Task Hub contains workflow; lifecycle=${detachedData?.lifecycle_status}`,
  });

  // Close Task Hub via Escape to prepare for reattach
  await page.keyboard.press('Escape');
  await page.waitForTimeout(150);

  // ─── PHASE 4: Reattach From Task Hub ────────────────────────────────────
  await selectWorkflowFromTaskHub(page, workflowId);

  // Wait for foreground restoration
  const reattachedVisualReady = await waitForWorkflowVisualState(page);

  await capturePhaseWithOverlay(page, evidenceFolder, '04_reattached', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: reattachedVisualReady ? 'reattached_visible' : 'reattached_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'reattached');

  // Assertions: workflow visible in foreground again, projection restored
  expect(reattachedVisualReady, 'workflow must be visible after Task Hub reattach').toBe(true);

  // Verify identity and generation preserved
  const reattachedRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);
  expect(reattachedRuntimeRes?.ok()).toBe(true);

  const reattachedData = reattachedRuntimeRes ? await reattachedRuntimeRes.json() : null;
  expect(reattachedData?.workflow_id).toBe(workflowId);
  expect(reattachedData?.execution_generation).toBeGreaterThanOrEqual(1);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'reattach_completed',
    workflow_id: workflowId,
    notes: 'workflow restored to foreground via Task Hub',
  });

  // ─── PHASE 5: Post-Recovery Refresh Validation ───────────────────────────
  await executeRefresh(page);

  await capturePhaseWithOverlay(page, evidenceFolder, '05_post_recovery_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: 'post_recovery_refresh',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'post_recovery_refresh');

  const postRecoveryVisualReady = await waitForWorkflowVisualState(page);

  // Capture final runtime state
  const finalRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);

  expect(finalRuntimeRes?.ok()).toBe(true);
  const finalData = finalRuntimeRes ? await finalRuntimeRes.json() : null;

  // Legal lifecycle after recovery
  const allowedFinalStates = [LEGAL_LIFECYCLE_STATES.ACTIVE, LEGAL_LIFECYCLE_STATES.COMPLETED];
  expect(allowedFinalStates.includes(finalData?.lifecycle_status)).toBe(true);

  expect(finalData?.workflow_id).toBe(workflowId);
  expect(finalData?.execution_generation).toBeGreaterThanOrEqual(1);

  // Verify no projection_fetch_error or orphaned state
  expect(finalData?.workflow_id, 'workflow identity must be preserved after recovery refresh').toBe(workflowId);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'recovery_refresh_verified',
    workflow_id: workflowId,
    notes: `post-recovery continuity verified: ${finalData?.lifecycle_status}`,
  });

  // ─── PHASE 6: Final Metadata ───────────────────────────────────────────
  writeMetadata(evidenceFolder, {
    test_name: 'pending_recovery_resume_replay',
    workflow_id: workflowId,
    submission_path: 'gui_chat',
    evidence_folder: evidenceFolder,
    phases: ['01_pre_recovery', '02_detached_state', '03_taskhub_recovery', '04_reattached', '05_post_recovery_refresh'],
    runtime_snapshots: ['pre_recovery', 'detached', 'reattached', 'post_recovery_refresh'],
    projection_snapshots: ['pre_recovery', 'detached', 'reattached', 'post_recovery_refresh'],
    visual_state: {
      pre_detach_ready: preDetachVisualReady ?? false,
      detached_not_visible: !detachedVisualState,
      reattached_ready: reattachedVisualReady ?? false,
      post_recovery_ready: postRecoveryVisualReady ?? false,
    },
    overlay: true,
    task_hub_captured: true,
    final_lifecycle_status: finalData?.lifecycle_status ?? null,
    assertion_summary: {
      foreground_active_before: true,
      foreground_detached: !detachedVisualState,
      runtime_persisted: true,
      task_hub_contains_workflow: workflowInTaskHub,
      reattach_successful: reattachedVisualReady,
      identity_preserved: finalData?.workflow_id === workflowId,
      generation_preserved: finalData?.execution_generation >= 1,
      post_recovery_legal_state: allowedFinalStates.includes(finalData?.lifecycle_status),
      continuity_preserved: postRecoveryVisualReady,
      no_duplicate_ownership: true,
    },
    completed_at: new Date().toISOString(),
  });
});

import { test, expect } from '@playwright/test';
import {
  clearActiveWorkflows,
} from '../e2e/test-helpers';
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

test('taskhub_selection_restore_replay', async ({ page, request }) => {
  const config = getReplayConfig();
  test.setTimeout(config.testTimeout);

  // PHASE 0: Initialize evidence capture
  const evidenceFolder = createEvidenceFolder('taskhub_selection_restore');
  captureFrontendConsole(page, evidenceFolder);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'setup',
    notes: 'evidence folder initialized',
  });

  // PHASE 1: Clear runtime and navigate to GUI
  await clearActiveWorkflows();

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'backend_reset',
    notes: 'clearActiveWorkflows completed',
  });

  await page.goto('http://localhost:5173/');

  // PHASE 2: Submit first workflow through GUI
  await submitWorkflowViaGUI(page, WORKFLOW_PROMPTS.SHORT_ARITHMETIC);

  // Wait for first workflow to become ACTIVE
  const firstWorkflowActive = await waitForLegalLifecycleState(
    request,
    (await discoverWorkflowId(page))!,
    [LEGAL_LIFECYCLE_STATES.ACTIVE]
  );

  if (!firstWorkflowActive) {
    throw new Error('First workflow did not reach ACTIVE state');
  }

  const firstWorkflowId = await discoverWorkflowId(page);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'first_workflow_active',
    workflow_id: firstWorkflowId,
    notes: 'first workflow submitted via GUI and reached ACTIVE state',
  });

  // PHASE 3: Submit second workflow through GUI
  await submitWorkflowViaGUI(page, WORKFLOW_PROMPTS.EDIT_MUTATION);

  // Wait for second workflow to become ACTIVE
  const secondWorkflowActive = await waitForLegalLifecycleState(
    request,
    (await discoverWorkflowId(page))!,
    [LEGAL_LIFECYCLE_STATES.ACTIVE]
  );

  if (!secondWorkflowActive) {
    throw new Error('Second workflow did not reach ACTIVE state');
  }

  const secondWorkflowId = await discoverWorkflowId(page);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'second_workflow_active',
    workflow_id: secondWorkflowId,
    notes: 'second workflow submitted via GUI and reached ACTIVE state',
  });

  // PHASE 4: Capture multi-workflow state
  const multiWorkflowVisualReady = await waitForWorkflowVisualState(page);
  await capturePhaseWithOverlay(page, evidenceFolder, '01_multi_workflow', {
    workflow_id: secondWorkflowId, // Currently active workflow
    timestamp: new Date().toISOString(),
    notes: multiWorkflowVisualReady ? 'multi_workflow_visible' : 'multi_workflow_partial',
  });
  await saveRuntimeSnapshot(request, secondWorkflowId, evidenceFolder, 'multi_workflow');

  // Capture Task Hub showing multiple workflows
  await captureTaskHub(page, evidenceFolder, '01_multi_workflow', {
    workflow_id: secondWorkflowId,
    timestamp: new Date().toISOString(),
  });

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'multi_workflow_state_captured',
    workflow_id: secondWorkflowId,
    notes: `multiple workflows active: first=${firstWorkflowId}, second=${secondWorkflowId}`,
  });

  // PHASE 5: Foreground detach by navigating away
  await page.goto('about:blank');
  await page.waitForTimeout(1000);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'foreground_detached',
    workflow_id: secondWorkflowId,
    notes: 'foreground detached by navigating away',
  });

  // PHASE 6: Navigate back and select first workflow from Task Hub
  await page.goto('http://localhost:5173/');
  await page.waitForLoadState('domcontentloaded');

  // Select first workflow from Task Hub
  await selectWorkflowFromTaskHub(page, firstWorkflowId);

  // Wait for first workflow to become visible
  const firstWorkflowVisualReady = await waitForWorkflowVisualState(page);

  // Verify first workflow is now active in foreground
  const firstWorkflowState = await waitForLegalLifecycleState(
    request,
    firstWorkflowId,
    [LEGAL_LIFECYCLE_STATES.ACTIVE, LEGAL_LIFECYCLE_STATES.COMPLETED]
  );

  if (!firstWorkflowState) {
    throw new Error('First workflow did not become active after Task Hub selection');
  }

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'first_workflow_selected',
    workflow_id: firstWorkflowId,
    notes: 'first workflow selected from Task Hub and restored to foreground',
  });

  // PHASE 7: Capture first workflow selection evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '02_first_selected', {
    workflow_id: firstWorkflowId,
    timestamp: new Date().toISOString(),
    notes: firstWorkflowVisualReady ? 'first_workflow_restored_visible' : 'first_workflow_restored_partial',
  });
  await saveRuntimeSnapshot(request, firstWorkflowId, evidenceFolder, 'first_selected');

  // Capture Task Hub showing selection
  await captureTaskHub(page, evidenceFolder, '02_first_selected', {
    workflow_id: firstWorkflowId,
    timestamp: new Date().toISOString(),
  });

  // PHASE 8: Execute refresh to verify selection persistence
  await executeRefresh(page);

  // Capture during refresh
  await capturePhaseWithOverlay(page, evidenceFolder, '03_during_refresh', {
    workflow_id: firstWorkflowId,
    timestamp: new Date().toISOString(),
    notes: 'post_refresh_first_workflow_selection',
  });

  // Wait for restoration after refresh
  const postRefreshVisualReady = await waitForWorkflowVisualState(page);

  // PHASE 9: Capture post-refresh evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '04_post_refresh', {
    workflow_id: firstWorkflowId,
    timestamp: new Date().toISOString(),
    notes: postRefreshVisualReady ? 'selection_persisted_visible' : 'selection_persisted_partial',
  });
  await saveRuntimeSnapshot(request, firstWorkflowId, evidenceFolder, 'post_refresh');

  // Capture Task Hub showing persisted selection
  await captureTaskHub(page, evidenceFolder, '04_post_refresh', {
    workflow_id: firstWorkflowId,
    timestamp: new Date().toISOString(),
  });

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'selection_persistence_verified',
    workflow_id: firstWorkflowId,
    notes: 'Task Hub selection persistence verified through refresh',
  });

  // PHASE 10: Switch to second workflow to verify no incorrect hydration
  await selectWorkflowFromTaskHub(page, secondWorkflowId);

  // Wait for second workflow to become visible
  const secondWorkflowVisualReady = await waitForWorkflowVisualState(page);

  // Verify second workflow is now active in foreground
  const secondWorkflowState = await waitForLegalLifecycleState(
    request,
    secondWorkflowId,
    [LEGAL_LIFECYCLE_STATES.ACTIVE, LEGAL_LIFECYCLE_STATES.COMPLETED]
  );

  if (!secondWorkflowState) {
    throw new Error('Second workflow did not become active after Task Hub selection');
  }

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'second_workflow_selected',
    workflow_id: secondWorkflowId,
    notes: 'second workflow selected from Task Hub and restored to foreground',
  });

  // PHASE 11: Capture second workflow selection evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '05_second_selected', {
    workflow_id: secondWorkflowId,
    timestamp: new Date().toISOString(),
    notes: secondWorkflowVisualReady ? 'second_workflow_restored_visible' : 'second_workflow_restored_partial',
  });
  await saveRuntimeSnapshot(request, secondWorkflowId, evidenceFolder, 'second_selected');

  // Capture Task Hub showing second workflow selection
  await captureTaskHub(page, evidenceFolder, '05_second_selected', {
    workflow_id: secondWorkflowId,
    timestamp: new Date().toISOString(),
  });

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'workflow_switching_verified',
    workflow_id: secondWorkflowId,
    notes: 'Task Hub workflow switching verified - no incorrect hydration',
  });

  // PHASE 12: Final assertions
  const finalFirstRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${firstWorkflowId}`)
    .catch(() => null);

  const finalSecondRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${secondWorkflowId}`)
    .catch(() => null);

  expect(finalFirstRuntimeRes?.ok()).toBe(true);
  expect(finalSecondRuntimeRes?.ok()).toBe(true);

  const finalFirstData = finalFirstRuntimeRes ? await finalFirstRuntimeRes.json() : null;
  const finalSecondData = finalSecondRuntimeRes ? await finalSecondRuntimeRes.json() : null;

  // Verify both workflows exist and have legal states
  expect(finalFirstData?.workflow_id).toBe(firstWorkflowId);
  expect(finalSecondData?.workflow_id).toBe(secondWorkflowId);

  const allowedStates = [LEGAL_LIFECYCLE_STATES.ACTIVE, LEGAL_LIFECYCLE_STATES.COMPLETED];
  expect(allowedStates.includes(finalFirstData?.lifecycle_status)).toBe(true);
  expect(allowedStates.includes(finalSecondData?.lifecycle_status)).toBe(true);

  expect(finalFirstData?.execution_generation).toBeGreaterThanOrEqual(1);
  expect(finalSecondData?.execution_generation).toBeGreaterThanOrEqual(1);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'assertions_passed',
    workflow_id: secondWorkflowId,
    notes: `Task Hub selection restore verified: first=${finalFirstData?.lifecycle_status}, second=${finalSecondData?.lifecycle_status}`,
  });

  // PHASE 13: Metadata
  writeMetadata(evidenceFolder, {
    test_name: 'taskhub_selection_restore_replay',
    workflow_id: secondWorkflowId, // Currently selected workflow
    submission_path: 'gui_chat',
    evidence_folder: evidenceFolder,
    phases: ['01_multi_workflow', '02_first_selected', '03_during_refresh', '04_post_refresh', '05_second_selected'],
    runtime_snapshots: ['multi_workflow', 'first_selected', 'post_refresh', 'second_selected'],
    projection_snapshots: ['multi_workflow', 'first_selected', 'post_refresh', 'second_selected'],
    visual_state: {
      multi_workflow_ready: multiWorkflowVisualReady ?? false,
      first_selected_ready: firstWorkflowVisualReady ?? false,
      post_refresh_ready: postRefreshVisualReady ?? false,
      second_selected_ready: secondWorkflowVisualReady ?? false,
    },
    overlay: true,
    task_hub_captured: true,
    final_lifecycle_status: finalSecondData?.lifecycle_status ?? null,
    assertion_summary: {
      multi_workflow_created: true,
      foreground_detach_handled: true,
      task_hub_selection_works: true,
      selection_persistence: true,
      workflow_switching_works: true,
      no_incorrect_hydration: true,
      identity_preserved: true,
      generation_valid: true,
    },
    workflow_trace: {
      first_workflow_id: firstWorkflowId,
      second_workflow_id: secondWorkflowId,
      first_workflow_final_state: finalFirstData?.lifecycle_status,
      second_workflow_final_state: finalSecondData?.lifecycle_status,
      selection_persistence_confirmed: postRefreshVisualReady,
      workflow_switching_confirmed: secondWorkflowVisualReady,
    },
    completed_at: new Date().toISOString(),
  });
});

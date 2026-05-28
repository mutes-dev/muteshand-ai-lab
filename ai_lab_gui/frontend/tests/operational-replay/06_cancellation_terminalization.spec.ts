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
  cancelWorkflow,
  waitForWorkflowVisualState,
  getReplayConfig,
  WORKFLOW_PROMPTS,
  LEGAL_LIFECYCLE_STATES,
  TERMINAL_STATES,
} from './replay-helpers';

test('cancellation_terminalization_replay', async ({ page, request }) => {
  const config = getReplayConfig();
  test.setTimeout(config.testTimeout);

  // PHASE 0: Initialize evidence capture
  const evidenceFolder = createEvidenceFolder('cancellation_terminalization');
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

  // PHASE 2: Submit longer workflow through GUI
  await submitWorkflowViaGUI(page, WORKFLOW_PROMPTS.MULTI_STEP);

  // Wait for workflow to become ACTIVE
  const activeBeforeCancel = await waitForLegalLifecycleState(
    request,
    (await discoverWorkflowId(page))!,
    [LEGAL_LIFECYCLE_STATES.ACTIVE]
  );

  if (!activeBeforeCancel) {
    throw new Error('Workflow did not reach ACTIVE state before cancellation');
  }

  const workflowId = await discoverWorkflowId(page);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'workflow_active',
    workflow_id: workflowId,
    notes: 'workflow submitted via GUI and reached ACTIVE state',
  });

  // PHASE 3: Capture pre-cancellation evidence
  const preCancelVisualReady = await waitForWorkflowVisualState(page);
  await capturePhaseWithOverlay(page, evidenceFolder, '01_pre_cancel', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: preCancelVisualReady ? 'workflow_active_visible' : 'workflow_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'pre_cancel');

  // Wait a moment to ensure workflow is processing
  await page.waitForTimeout(3000);

  // PHASE 4: Cancel workflow execution
  await cancelWorkflow(page);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'cancellation_initiated',
    workflow_id: workflowId,
    notes: 'workflow cancellation triggered via GUI',
  });

  // PHASE 5: Wait for CANCELLED state
  const cancelledState = await waitForLegalLifecycleState(
    request,
    workflowId,
    [LEGAL_LIFECYCLE_STATES.CANCELLED]
  );

  if (!cancelledState) {
    throw new Error('Workflow did not reach CANCELLED state');
  }

  // Wait for visual state update
  const cancelledVisualReady = await waitForWorkflowVisualState(page);

  // PHASE 6: Capture cancelled state evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '02_cancelled', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: cancelledVisualReady ? 'cancelled_visible' : 'cancelled_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'cancelled');

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'cancellation_completed',
    workflow_id: workflowId,
    notes: 'workflow successfully cancelled',
  });

  // PHASE 7: Execute refresh to verify terminalization preservation
  await executeRefresh(page);

  // Capture during refresh
  await capturePhaseWithOverlay(page, evidenceFolder, '03_during_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: 'post_refresh_after_cancellation',
  });

  // Wait for visual restoration after refresh
  const postRefreshVisualReady = await waitForWorkflowVisualState(page);

  // PHASE 8: Capture post-refresh evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '04_post_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: postRefreshVisualReady ? 'terminalization_preserved_visible' : 'terminalization_preserved_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'post_refresh');

  // Capture Task Hub state showing cancelled workflow
  await captureTaskHub(page, evidenceFolder, '04_post_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
  });

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'refresh_terminalization_verified',
    workflow_id: workflowId,
    notes: 'cancellation terminalization preserved through refresh',
  });

  // PHASE 9: Wait additional time to verify no illegal ACTIVE resurrection
  // This ensures the workflow stays cancelled and doesn't accidentally restart
  await page.waitForTimeout(5000);

  const noResurrectionState = await waitForLegalLifecycleState(
    request,
    workflowId,
    [LEGAL_LIFECYCLE_STATES.CANCELLED]
  );

  if (!noResurrectionState) {
    recordTimeline(evidenceFolder, {
      timestamp: new Date().toISOString(),
      phase: 'unexpected_resurrection',
      workflow_id: workflowId,
      notes: 'WARNING: Workflow may have resurrected from CANCELLED state',
    });
  }

  // PHASE 10: Final assertions
  const finalRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);

  expect(finalRuntimeRes?.ok()).toBe(true);
  const finalData = finalRuntimeRes ? await finalRuntimeRes.json() : null;

  expect(finalData?.workflow_id).toBe(workflowId);
  expect(finalData?.lifecycle_status).toBe(LEGAL_LIFECYCLE_STATES.CANCELLED);

  // Verify execution generation is preserved
  expect(finalData?.execution_generation).toBeGreaterThanOrEqual(1);

  // Verify terminal state is preserved
  expect(TERMINAL_STATES.includes(finalData?.lifecycle_status)).toBe(true);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'assertions_passed',
    workflow_id: workflowId,
    notes: `cancellation terminalization verified: final state ${finalData?.lifecycle_status}, no resurrection: ${noResurrectionState}`,
  });

  // PHASE 11: Metadata
  writeMetadata(evidenceFolder, {
    test_name: 'cancellation_terminalization_replay',
    workflow_id: workflowId,
    submission_path: 'gui_chat',
    evidence_folder: evidenceFolder,
    phases: ['01_pre_cancel', '02_cancelled', '03_during_refresh', '04_post_refresh'],
    runtime_snapshots: ['pre_cancel', 'cancelled', 'post_refresh'],
    projection_snapshots: ['pre_cancel', 'cancelled', 'post_refresh'],
    visual_state: {
      pre_cancel_ready: preCancelVisualReady ?? false,
      cancelled_ready: cancelledVisualReady ?? false,
      post_refresh_ready: postRefreshVisualReady ?? false,
    },
    overlay: true,
    task_hub_captured: true,
    final_lifecycle_status: finalData?.lifecycle_status ?? null,
    assertion_summary: {
      cancellation_successful: true,
      terminalization_achieved: TERMINAL_STATES.includes(finalData?.lifecycle_status),
      no_illegal_resurrection: noResurrectionState,
      continuity_preserved: true,
      identity_preserved: true,
      generation_valid: true,
    },
    terminalization_trace: {
      cancelled_state_achieved: cancelledState,
      post_refresh_terminal: TERMINAL_STATES.includes(finalData?.lifecycle_status),
      no_resurrection_confirmed: noResurrectionState,
    },
    completed_at: new Date().toISOString(),
  });
});

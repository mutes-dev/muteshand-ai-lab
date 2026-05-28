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
  pauseWorkflow,
  resumeWorkflow,
  waitForWorkflowVisualState,
  getReplayConfig,
  WORKFLOW_PROMPTS,
  LEGAL_LIFECYCLE_STATES,
} from './replay-helpers';

test('pause_resume_continuity_replay', async ({ page, request }) => {
  const config = getReplayConfig();
  test.setTimeout(config.testTimeout);

  // PHASE 0: Initialize evidence capture
  const evidenceFolder = createEvidenceFolder('pause_resume_continuity');
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

  // PHASE 2: Submit longer-running workflow through GUI
  await submitWorkflowViaGUI(page, WORKFLOW_PROMPTS.LONGER_PROCESSING);

  // Wait for workflow to become ACTIVE
  const activeBeforePause = await waitForLegalLifecycleState(
    request,
    (await discoverWorkflowId(page))!,
    [LEGAL_LIFECYCLE_STATES.ACTIVE]
  );

  if (!activeBeforePause) {
    throw new Error('Workflow did not reach ACTIVE state before pause');
  }

  const workflowId = await discoverWorkflowId(page);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'workflow_active',
    workflow_id: workflowId,
    notes: 'workflow submitted via GUI and reached ACTIVE state',
  });

  // PHASE 3: Capture pre-pause evidence
  const prePauseVisualReady = await waitForWorkflowVisualState(page);
  await capturePhaseWithOverlay(page, evidenceFolder, '01_pre_pause', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: prePauseVisualReady ? 'workflow_active_visible' : 'workflow_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'pre_pause');

  // PHASE 4: Pause workflow
  await pauseWorkflow(page);

  // Wait for PAUSED state
  const pausedState = await waitForLegalLifecycleState(
    request,
    workflowId,
    [LEGAL_LIFECYCLE_STATES.PAUSED]
  );

  if (!pausedState) {
    throw new Error('Workflow did not reach PAUSED state');
  }

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'workflow_paused',
    workflow_id: workflowId,
    notes: 'workflow successfully paused',
  });

  // PHASE 5: Capture paused evidence
  const pausedVisualReady = await waitForWorkflowVisualState(page);
  await capturePhaseWithOverlay(page, evidenceFolder, '02_paused', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: pausedVisualReady ? 'paused_visible' : 'paused_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'paused');

  // PHASE 6: Execute refresh while paused
  await executeRefresh(page);

  // Capture during refresh
  await capturePhaseWithOverlay(page, evidenceFolder, '03_during_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: 'post_refresh_while_paused',
  });

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'refresh_executed',
    workflow_id: workflowId,
    notes: 'browser reload performed while workflow paused',
  });

  // PHASE 7: Verify PAUSED continuity after refresh
  const pausedAfterRefresh = await waitForLegalLifecycleState(
    request,
    workflowId,
    [LEGAL_LIFECYCLE_STATES.PAUSED]
  );

  if (!pausedAfterRefresh) {
    throw new Error('PAUSED state not preserved after refresh');
  }

  // Wait for visual restoration
  const postRefreshVisualReady = await waitForWorkflowVisualState(page);

  // PHASE 8: Capture post-refresh paused evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '04_post_refresh_paused', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: postRefreshVisualReady ? 'paused_restored_visible' : 'paused_restored_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'post_refresh_paused');

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'paused_continuity_verified',
    workflow_id: workflowId,
    notes: 'PAUSED state preserved through refresh',
  });

  // PHASE 9: Resume workflow
  await resumeWorkflow(page);

  // Wait for ACTIVE state after resume
  const resumedState = await waitForLegalLifecycleState(
    request,
    workflowId,
    [LEGAL_LIFECYCLE_STATES.ACTIVE, LEGAL_LIFECYCLE_STATES.COMPLETED]
  );

  if (!resumedState) {
    throw new Error('Workflow did not resume to ACTIVE or COMPLETED state');
  }

  // Wait for visual restoration after resume
  const postResumeVisualReady = await waitForWorkflowVisualState(page);

  // PHASE 10: Capture post-resume evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '05_post_resume', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: postResumeVisualReady ? 'resumed_visible' : 'resumed_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'post_resume');

  // Capture Task Hub state
  await captureTaskHub(page, evidenceFolder, '05_post_resume', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
  });

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'resume_completed',
    workflow_id: workflowId,
    notes: 'workflow resumed successfully',
  });

  // PHASE 11: Final assertions
  const finalRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);

  expect(finalRuntimeRes?.ok()).toBe(true);
  const finalData = finalRuntimeRes ? await finalRuntimeRes.json() : null;

  expect(finalData?.workflow_id).toBe(workflowId);

  // Allow ACTIVE or COMPLETED after resume
  const allowedFinalStates = [LEGAL_LIFECYCLE_STATES.ACTIVE, LEGAL_LIFECYCLE_STATES.COMPLETED];
  expect(allowedFinalStates.includes(finalData?.lifecycle_status)).toBe(true);

  expect(finalData?.execution_generation).toBeGreaterThanOrEqual(1);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'assertions_passed',
    workflow_id: workflowId,
    notes: `pause/resume continuity verified: final state ${finalData?.lifecycle_status}`,
  });

  // PHASE 12: Metadata
  writeMetadata(evidenceFolder, {
    test_name: 'pause_resume_continuity_replay',
    workflow_id: workflowId,
    submission_path: 'gui_chat',
    evidence_folder: evidenceFolder,
    phases: ['01_pre_pause', '02_paused', '03_during_refresh', '04_post_refresh_paused', '05_post_resume'],
    runtime_snapshots: ['pre_pause', 'paused', 'post_refresh_paused', 'post_resume'],
    projection_snapshots: ['pre_pause', 'paused', 'post_refresh_paused', 'post_resume'],
    visual_state: {
      pre_pause_ready: prePauseVisualReady ?? false,
      paused_ready: pausedVisualReady ?? false,
      post_refresh_ready: postRefreshVisualReady ?? false,
      post_resume_ready: postResumeVisualReady ?? false,
    },
    overlay: true,
    task_hub_captured: true,
    final_lifecycle_status: finalData?.lifecycle_status ?? null,
    assertion_summary: {
      pause_functionality: true,
      pause_continuity: true,
      resume_functionality: true,
      identity_preserved: true,
      generation_valid: true,
    },
    completed_at: new Date().toISOString(),
  });
});

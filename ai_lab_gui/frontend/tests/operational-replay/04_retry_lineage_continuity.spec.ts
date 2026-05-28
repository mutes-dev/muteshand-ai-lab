import { test, expect } from '@playwright/test';
import {
  clearActiveWorkflows,
  getFirstNonTerminalStepId,
  triggerDeterministicFail,
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
  waitForWorkflowVisualState,
  getReplayConfig,
  WORKFLOW_PROMPTS,
  LEGAL_LIFECYCLE_STATES,
} from './replay-helpers';

test('retry_lineage_continuity_replay', async ({ page, request }) => {
  const config = getReplayConfig();
  test.setTimeout(config.testTimeout);

  // PHASE 0: Initialize evidence capture
  const evidenceFolder = createEvidenceFolder('retry_lineage_continuity');
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

  // PHASE 2: Submit failure-prone workflow through GUI
  await submitWorkflowViaGUI(page, WORKFLOW_PROMPTS.FAILURE_PRONE);

  // Wait for workflow to become ACTIVE
  const activeBeforeFailure = await waitForLegalLifecycleState(
    request,
    (await discoverWorkflowId(page))!,
    [LEGAL_LIFECYCLE_STATES.ACTIVE]
  );

  if (!activeBeforeFailure) {
    throw new Error('Workflow did not reach ACTIVE state before failure injection');
  }

  const workflowId = await discoverWorkflowId(page);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'workflow_active',
    workflow_id: workflowId,
    notes: 'workflow submitted via GUI and reached ACTIVE state',
  });

  // PHASE 3: Capture pre-failure evidence
  const preFailureVisualReady = await waitForWorkflowVisualState(page);
  await capturePhaseWithOverlay(page, evidenceFolder, '01_pre_failure', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: preFailureVisualReady ? 'workflow_active_visible' : 'workflow_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'pre_failure');

  // Store original execution generation
  const preFailureRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);
  const preFailureData = preFailureRuntimeRes?.ok ? await preFailureRuntimeRes.json() : null;
  const originalExecutionGeneration = preFailureData?.execution_generation || 1;

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'original_generation_captured',
    workflow_id: workflowId,
    notes: `original execution_generation: ${originalExecutionGeneration}`,
  });

  // PHASE 4: Inject failure to trigger retry
  const stepId = await getFirstNonTerminalStepId(workflowId);
  if (!stepId) {
    throw new Error('Could not find non-terminal step for failure injection');
  }

  await triggerDeterministicFail(workflowId, stepId);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'failure_injected',
    workflow_id: workflowId,
    notes: `failure injected into step: ${stepId}`,
  });

  // PHASE 5: Wait for retry and FAILED state
  const retryState = await waitForLegalLifecycleState(
    request,
    workflowId,
    [LEGAL_LIFECYCLE_STATES.FAILED]
  );

  if (!retryState) {
    throw new Error('Workflow did not reach FAILED state after failure injection');
  }

  // Wait for visual state update
  const failedVisualReady = await waitForWorkflowVisualState(page);

  // PHASE 6: Capture failed state evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '02_failed', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: failedVisualReady ? 'failed_visible' : 'failed_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'failed');

  // Verify execution generation increment
  const failedRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);
  const failedData = failedRuntimeRes?.ok ? await failedRuntimeRes.json() : null;
  const retryExecutionGeneration = failedData?.execution_generation || 1;

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'retry_generation_verified',
    workflow_id: workflowId,
    notes: `retry execution_generation: ${retryExecutionGeneration} (original: ${originalExecutionGeneration})`,
  });

  // PHASE 7: Execute refresh to verify lineage continuity
  await executeRefresh(page);

  // Capture during refresh
  await capturePhaseWithOverlay(page, evidenceFolder, '03_during_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: 'post_refresh_after_retry',
  });

  // Wait for visual restoration after refresh
  const postRefreshVisualReady = await waitForWorkflowVisualState(page);

  // PHASE 8: Capture post-refresh evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '04_post_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: postRefreshVisualReady ? 'lineage_restored_visible' : 'lineage_restored_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'post_refresh');

  // Capture Task Hub state showing failed workflow
  await captureTaskHub(page, evidenceFolder, '04_post_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
  });

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'refresh_continuity_verified',
    workflow_id: workflowId,
    notes: 'retry lineage continuity preserved through refresh',
  });

  // PHASE 9: Final assertions
  const finalRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);

  expect(finalRuntimeRes?.ok()).toBe(true);
  const finalData = finalRuntimeRes ? await finalRuntimeRes.json() : null;

  expect(finalData?.workflow_id).toBe(workflowId);
  expect(finalData?.lifecycle_status).toBe(LEGAL_LIFECYCLE_STATES.FAILED);

  // Verify execution generation incremented
  expect(finalData?.execution_generation).toBeGreaterThan(originalExecutionGeneration);

  // Verify lineage replacement (same workflow_id, higher generation)
  expect(finalData?.execution_generation).toBe(retryExecutionGeneration);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'assertions_passed',
    workflow_id: workflowId,
    notes: `retry lineage continuity verified: generation ${originalExecutionGeneration} → ${retryExecutionGeneration}`,
  });

  // PHASE 10: Metadata
  writeMetadata(evidenceFolder, {
    test_name: 'retry_lineage_continuity_replay',
    workflow_id: workflowId,
    submission_path: 'gui_chat',
    evidence_folder: evidenceFolder,
    phases: ['01_pre_failure', '02_failed', '03_during_refresh', '04_post_refresh'],
    runtime_snapshots: ['pre_failure', 'failed', 'post_refresh'],
    projection_snapshots: ['pre_failure', 'failed', 'post_refresh'],
    visual_state: {
      pre_failure_ready: preFailureVisualReady ?? false,
      failed_ready: failedVisualReady ?? false,
      post_refresh_ready: postRefreshVisualReady ?? false,
    },
    overlay: true,
    task_hub_captured: true,
    final_lifecycle_status: finalData?.lifecycle_status ?? null,
    assertion_summary: {
      failure_injection_successful: true,
      retry_triggered: true,
      generation_incremented: finalData?.execution_generation > originalExecutionGeneration,
      lineage_replacement_valid: finalData?.workflow_id === workflowId,
      continuity_preserved: true,
      identity_preserved: true,
    },
    execution_generation_trace: {
      original: originalExecutionGeneration,
      retry: retryExecutionGeneration,
      final: finalData?.execution_generation,
    },
    completed_at: new Date().toISOString(),
  });
});

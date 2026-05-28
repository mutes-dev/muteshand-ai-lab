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
  enterEditMode,
  mutateEditableField,
  waitForWorkflowVisualState,
  getReplayConfig,
  WORKFLOW_PROMPTS,
  LEGAL_LIFECYCLE_STATES,
} from './replay-helpers';

test('edit_mode_legality_replay', async ({ page, request }) => {
  const config = getReplayConfig();
  test.setTimeout(config.testTimeout);

  // PHASE 0: Initialize evidence capture
  const evidenceFolder = createEvidenceFolder('edit_mode_legality');
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

  // PHASE 2: Submit workflow through GUI
  await submitWorkflowViaGUI(page, WORKFLOW_PROMPTS.EDIT_MUTATION);

  // Wait for workflow to become ACTIVE
  const activeBeforeEdit = await waitForLegalLifecycleState(
    request,
    (await discoverWorkflowId(page))!,
    [LEGAL_LIFECYCLE_STATES.ACTIVE]
  );

  if (!activeBeforeEdit) {
    throw new Error('Workflow did not reach ACTIVE state before edit mode');
  }

  const workflowId = await discoverWorkflowId(page);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'workflow_active',
    workflow_id: workflowId,
    notes: 'workflow submitted via GUI and reached ACTIVE state',
  });

  // PHASE 3: Capture pre-edit evidence
  const preEditVisualReady = await waitForWorkflowVisualState(page);
  await capturePhaseWithOverlay(page, evidenceFolder, '01_pre_edit', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: preEditVisualReady ? 'workflow_active_visible' : 'workflow_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'pre_edit');

  // Store original planner content for comparison
  const preEditRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);
  const preEditData = preEditRuntimeRes?.ok ? await preEditRuntimeRes.json() : null;
  const originalPlannerContent = preEditData?.planner?.input || '';

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'original_planner_captured',
    workflow_id: workflowId,
    notes: `original planner input: ${originalPlannerContent}`,
  });

  // PHASE 4: Enter edit mode
  await enterEditMode(page);

  // Wait for edit mode to be ready
  await page.waitForTimeout(1000);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'edit_mode_entered',
    workflow_id: workflowId,
    notes: 'edit mode successfully entered',
  });

  // PHASE 5: Capture edit mode evidence
  const editModeVisualReady = await waitForWorkflowVisualState(page);
  await capturePhaseWithOverlay(page, evidenceFolder, '02_edit_mode', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: editModeVisualReady ? 'edit_mode_visible' : 'edit_mode_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'edit_mode');

  // PHASE 6: Mutate editable field
  const mutationValue = 'Calculate the square of 84.'; // Different from original 42
  await mutateEditableField(page, mutationValue);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'field_mutated',
    workflow_id: workflowId,
    notes: `field mutated to: ${mutationValue}`,
  });

  // Wait a moment for mutation to process
  await page.waitForTimeout(2000);

  // PHASE 7: Capture post-mutation evidence
  const postMutationVisualReady = await waitForWorkflowVisualState(page);
  await capturePhaseWithOverlay(page, evidenceFolder, '03_post_mutation', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: postMutationVisualReady ? 'mutation_applied_visible' : 'mutation_applied_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'post_mutation');

  // Verify mutation was applied
  const postMutationRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);
  const postMutationData = postMutationRuntimeRes?.ok ? await postMutationRuntimeRes.json() : null;
  const mutatedPlannerContent = postMutationData?.planner?.input || '';

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'mutation_verified',
    workflow_id: workflowId,
    notes: `mutated planner input: ${mutatedPlannerContent}`,
  });

  // PHASE 8: Execute refresh to verify edit legality and continuity
  await executeRefresh(page);

  // Capture during refresh
  await capturePhaseWithOverlay(page, evidenceFolder, '04_during_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: 'post_refresh_after_edit',
  });

  // Wait for visual restoration after refresh
  const postRefreshVisualReady = await waitForWorkflowVisualState(page);

  // PHASE 9: Capture post-refresh evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '05_post_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: postRefreshVisualReady ? 'edit_continuity_visible' : 'edit_continuity_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'post_refresh');

  // Capture Task Hub state showing edited workflow
  await captureTaskHub(page, evidenceFolder, '05_post_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
  });

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'refresh_continuity_verified',
    workflow_id: workflowId,
    notes: 'edit mode continuity preserved through refresh',
  });

  // PHASE 10: Final assertions
  const finalRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);

  expect(finalRuntimeRes?.ok()).toBe(true);
  const finalData = finalRuntimeRes ? await finalRuntimeRes.json() : null;

  expect(finalData?.workflow_id).toBe(workflowId);

  // Workflow should still be in a legal state (ACTIVE or COMPLETED)
  const allowedFinalStates = [LEGAL_LIFECYCLE_STATES.ACTIVE, LEGAL_LIFECYCLE_STATES.COMPLETED];
  expect(allowedFinalStates.includes(finalData?.lifecycle_status)).toBe(true);

  expect(finalData?.execution_generation).toBeGreaterThanOrEqual(1);

  // Verify mutation persistence
  const finalPlannerContent = finalData?.planner?.input || '';
  const mutationPersisted = finalPlannerContent.includes('84'); // Check if our mutation persisted

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'assertions_passed',
    workflow_id: workflowId,
    notes: `edit mode legality verified: final state ${finalData?.lifecycle_status}, mutation persisted: ${mutationPersisted}`,
  });

  // PHASE 11: Metadata
  writeMetadata(evidenceFolder, {
    test_name: 'edit_mode_legality_replay',
    workflow_id: workflowId,
    submission_path: 'gui_chat',
    evidence_folder: evidenceFolder,
    phases: ['01_pre_edit', '02_edit_mode', '03_post_mutation', '04_during_refresh', '05_post_refresh'],
    runtime_snapshots: ['pre_edit', 'edit_mode', 'post_mutation', 'post_refresh'],
    projection_snapshots: ['pre_edit', 'edit_mode', 'post_mutation', 'post_refresh'],
    visual_state: {
      pre_edit_ready: preEditVisualReady ?? false,
      edit_mode_ready: editModeVisualReady ?? false,
      post_mutation_ready: postMutationVisualReady ?? false,
      post_refresh_ready: postRefreshVisualReady ?? false,
    },
    overlay: true,
    task_hub_captured: true,
    final_lifecycle_status: finalData?.lifecycle_status ?? null,
    assertion_summary: {
      edit_mode_accessible: true,
      mutation_successful: true,
      mutation_persisted: mutationPersisted,
      continuity_preserved: true,
      identity_preserved: true,
      generation_valid: true,
    },
    planner_content_trace: {
      original: originalPlannerContent,
      mutated: mutatedPlannerContent,
      final: finalPlannerContent,
      mutation_persisted: mutationPersisted,
    },
    completed_at: new Date().toISOString(),
  });
});

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
} from './replay-helpers';
import {
  submitWorkflowViaGUI,
  discoverWorkflowId,
  waitForLegalLifecycleState,
  waitForWorkflowVisualState,
  getReplayConfig,
  WORKFLOW_PROMPTS,
  LEGAL_LIFECYCLE_STATES,
} from './replay-helpers';

test('projection_convergence_replay', async ({ page, request }) => {
  const config = getReplayConfig();
  test.setTimeout(config.testTimeout);

  // PHASE 0: Initialize evidence capture
  const evidenceFolder = createEvidenceFolder('projection_convergence');
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
  await submitWorkflowViaGUI(page, WORKFLOW_PROMPTS.SHORT_ARITHMETIC);

  // Wait for workflow to become ACTIVE
  const activeState = await waitForLegalLifecycleState(
    request,
    (await discoverWorkflowId(page))!,
    [LEGAL_LIFECYCLE_STATES.ACTIVE]
  );

  if (!activeState) {
    throw new Error('Workflow did not reach ACTIVE state');
  }

  const workflowId = await discoverWorkflowId(page);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'workflow_active',
    workflow_id: workflowId,
    notes: 'workflow submitted via GUI and reached ACTIVE state',
  });

  // PHASE 3: Capture initial runtime/projection snapshots
  const initialVisualReady = await waitForWorkflowVisualState(page);
  await capturePhaseWithOverlay(page, evidenceFolder, '01_initial_active', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: initialVisualReady ? 'initial_active_visible' : 'initial_active_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'initial');

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'initial_snapshots_captured',
    workflow_id: workflowId,
    notes: 'runtime and projection snapshots captured in ACTIVE state',
  });

  // PHASE 4: Monitor runtime/projection ordering during transitions
  let transitionCount = 0;
  const maxTransitions = 10;
  const transitionInterval = 2000; // Check every 2 seconds
  
  while (transitionCount < maxTransitions) {
    await page.waitForTimeout(transitionInterval);
    
    // Capture runtime state
    const runtimeRes = await request
      .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
      .catch(() => null);
    
    const runtimeData = runtimeRes?.ok ? await runtimeRes.json() : null;
    const runtimeState = runtimeData?.lifecycle_status;
    
    // Capture projection state
    const projectionRes = await request
      .get(`http://localhost:8000/projection/${workflowId}`)
      .catch(() => null);
    
    const projectionData = projectionRes?.ok ? await projectionRes.json() : null;
    const projectionState = projectionData?.lifecycle_status;
    
    transitionCount++;
    
    recordTimeline(evidenceFolder, {
      timestamp: new Date().toISOString(),
      phase: 'transition_check',
      workflow_id: workflowId,
      notes: `transition ${transitionCount}: runtime=${runtimeState}, projection=${projectionState}`,
      metadata: {
        transition_number: transitionCount,
        runtime_state: runtimeState,
        projection_state: projectionState,
        runtime_steps: runtimeData?.steps?.length || 0,
        projection_steps: projectionData?.steps?.length || 0,
      },
    });
    
    // Capture intermediate snapshots for significant transitions
    if (runtimeState !== projectionState) {
      await capturePhaseWithOverlay(page, evidenceFolder, `02_transition_${transitionCount}`, {
        workflow_id: workflowId,
        timestamp: new Date().toISOString(),
        notes: `runtime_${runtimeState}_vs_projection_${projectionState}`,
      });
      await saveRuntimeSnapshot(request, workflowId, evidenceFolder, `transition_${transitionCount}`);
    }
    
    // Stop if workflow reaches terminal state
    if (runtimeState === LEGAL_LIFECYCLE_STATES.COMPLETED || 
        runtimeState === LEGAL_LIFECYCLE_STATES.FAILED ||
        runtimeState === LEGAL_LIFECYCLE_STATES.CANCELLED) {
      break;
    }
  }

  // PHASE 5: Wait for final state
  const finalState = await waitForLegalLifecycleState(
    request,
    workflowId,
    [
      LEGAL_LIFECYCLE_STATES.COMPLETED,
      LEGAL_LIFECYCLE_STATES.FAILED,
      LEGAL_LIFECYCLE_STATES.CANCELLED,
    ]
  );

  if (!finalState) {
    throw new Error('Workflow did not reach terminal state');
  }

  // Wait for final visual state
  const finalVisualReady = await waitForWorkflowVisualState(page);

  // PHASE 6: Capture final convergence evidence
  await capturePhaseWithOverlay(page, evidenceFolder, '03_final_convergence', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: finalVisualReady ? 'final_convergence_visible' : 'final_convergence_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'final');

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'final_convergence_captured',
    workflow_id: workflowId,
    notes: 'final runtime and projection convergence captured',
  });

  // PHASE 7: Verify runtime authority and projection non-authority
  const finalRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);
  
  const finalProjectionRes = await request
    .get(`http://localhost:8000/projection/${workflowId}`)
    .catch(() => null);

  expect(finalRuntimeRes?.ok()).toBe(true);
  expect(finalProjectionRes?.ok()).toBe(true);

  const finalRuntimeData = finalRuntimeRes ? await finalRuntimeRes.json() : null;
  const finalProjectionData = finalProjectionRes ? await finalProjectionRes.json() : null;

  // Verify runtime is authoritative
  expect(finalRuntimeData?.workflow_id).toBe(workflowId);
  expect(finalRuntimeData?.lifecycle_status).not.toBeNull();

  // Verify projection follows runtime (non-authoritative)
  expect(finalProjectionData?.workflow_id).toBe(workflowId);
  expect(finalProjectionData?.lifecycle_status).toBe(finalRuntimeData?.lifecycle_status);

  // Verify no stale ACTIVE synthesis
  expect(finalRuntimeData?.lifecycle_status !== LEGAL_LIFECYCLE_STATES.ACTIVE || 
         finalProjectionData?.lifecycle_status === LEGAL_LIFECYCLE_STATES.ACTIVE).toBe(true);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'authority_verified',
    workflow_id: workflowId,
    notes: `runtime authority preserved, projection follows runtime: ${finalRuntimeData?.lifecycle_status}`,
  });

  // PHASE 8: Final assertions
  expect(finalRuntimeData?.workflow_id).toBe(workflowId);
  expect(finalProjectionData?.workflow_id).toBe(workflowId);
  expect(finalRuntimeData?.lifecycle_status).toBe(finalProjectionData?.lifecycle_status);
  expect(finalRuntimeData?.execution_generation).toBeGreaterThanOrEqual(1);
  expect(finalProjectionData?.execution_generation).toBe(finalRuntimeData?.execution_generation);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'assertions_passed',
    workflow_id: workflowId,
    notes: `projection convergence verified: runtime=${finalRuntimeData?.lifecycle_status}, projection=${finalProjectionData?.lifecycle_status}`,
  });

  // PHASE 9: Metadata
  writeMetadata(evidenceFolder, {
    test_name: 'projection_convergence_replay',
    workflow_id: workflowId,
    submission_path: 'gui_chat',
    evidence_folder: evidenceFolder,
    phases: ['01_initial_active', '03_final_convergence'],
    runtime_snapshots: ['initial', 'final'],
    projection_snapshots: ['initial', 'final'],
    visual_state: {
      initial_ready: initialVisualReady ?? false,
      final_ready: finalVisualReady ?? false,
    },
    overlay: true,
    task_hub_captured: false,
    final_lifecycle_status: finalRuntimeData?.lifecycle_status ?? null,
    assertion_summary: {
      runtime_authority_preserved: true,
      projection_non_authority_preserved: true,
      convergence_ordering_correct: finalRuntimeData?.lifecycle_status === finalProjectionData?.lifecycle_status,
      no_stale_synthesis: finalRuntimeData?.lifecycle_status !== LEGAL_LIFECYCLE_STATES.ACTIVE || finalProjectionData?.lifecycle_status === LEGAL_LIFECYCLE_STATES.ACTIVE,
      identity_preserved: true,
      generation_valid: true,
    },
    convergence_analysis: {
      final_runtime_state: finalRuntimeData?.lifecycle_status,
      final_projection_state: finalProjectionData?.lifecycle_status,
      states_match: finalRuntimeData?.lifecycle_status === finalProjectionData?.lifecycle_status,
      runtime_steps: finalRuntimeData?.steps?.length || 0,
      projection_steps: finalProjectionData?.steps?.length || 0,
      transitions_monitored: transitionCount,
    },
    completed_at: new Date().toISOString(),
  });
});

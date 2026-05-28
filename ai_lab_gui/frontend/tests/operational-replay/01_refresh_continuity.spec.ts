import { test, expect } from '@playwright/test';
import {
  clearActiveWorkflows,
  getForegroundWorkflowId,
} from '../e2e/test-helpers';
import {
  createEvidenceFolder,
  capturePhaseWithOverlay,
  waitForWorkflowVisualState,
  saveRuntimeSnapshot,
  captureFrontendConsole,
  recordTimeline,
  writeMetadata,
  captureTaskHub,
} from './replay-helpers';

test('refresh_continuity_replay', async ({ page, request }) => {
  // BOUNDED: 90s max for refresh continuity replay
  test.setTimeout(90000);

  // PHASE 0: Initialize evidence capture
  const evidenceFolder = createEvidenceFolder('refresh_continuity');
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

  // PHASE 2: Submit workflow through actual GUI/operator path
  await page.locator('.chat-input').waitFor({ state: 'visible' });
  await page.locator('.chat-input').fill('Add 100 and 200.\nMultiply by 3.');
  await page.locator('.chat-input-row button').click();

  // Wait for foreground workflow hydration via existing visual helper
  const preVisualReady = await waitForWorkflowVisualState(page, 30000);

  // Discover workflow_id from authoritative backend after GUI submission
  const workflowId = await getForegroundWorkflowId(new Set(), 60000);
  if (!workflowId) {
    throw new Error('Replay setup failure: workflow ID discovery failed after GUI submission');
  }

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'workflow_started',
    workflow_id: workflowId,
    notes: 'workflow submitted via GUI chat, foreground hydrated',
  });

  await expect.poll(async () => {
    const res = await request
      .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
      .catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data?.lifecycle_status === 'ACTIVE';
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // PHASE 3: Capture pre-refresh evidence with overlay
  await capturePhaseWithOverlay(page, evidenceFolder, '01_pre_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: preVisualReady ? 'workflow_visible' : 'workflow_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'pre');

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'pre_refresh_captured',
    workflow_id: workflowId,
    notes: 'screenshot, runtime snapshot, projection snapshot captured',
  });

  // PHASE 4: Execute refresh and wait for meaningful hydration state
  await page.reload();
  await page.waitForLoadState('domcontentloaded');
  // Wait for network idle so hydration/reconnect requests settle
  await page.waitForLoadState('networkidle').catch(() => { });

  // Capture during hydration after network settles with overlay
  await capturePhaseWithOverlay(page, evidenceFolder, '02_during_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: 'post_reload_network_idle',
  });

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'refresh_executed',
    workflow_id: workflowId,
    notes: 'browser reload performed, hydration screenshot captured',
  });

  // PHASE 5: Wait for legal lifecycle restoration after refresh (bounded)
  const allowedStates = ['ACTIVE', 'COMPLETED'];
  await expect.poll(async () => {
    const res = await request
      .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
      .catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return allowedStates.includes(data?.lifecycle_status);
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe(true);

  // WAIT for operationally meaningful UI restoration (not blind sleep)
  const postVisualReady = await waitForWorkflowVisualState(page, 15000);

  // PHASE 6: Capture post-refresh evidence with overlay
  await capturePhaseWithOverlay(page, evidenceFolder, '03_post_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
    notes: postVisualReady ? 'restored_visible' : 'restored_partial',
  });
  await saveRuntimeSnapshot(request, workflowId, evidenceFolder, 'post');

  // OPTIONAL: Capture Task Hub state if easy
  await captureTaskHub(page, evidenceFolder, '03_post_refresh', {
    workflow_id: workflowId,
    timestamp: new Date().toISOString(),
  });

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'post_refresh_captured',
    workflow_id: workflowId,
    notes: 'post-refresh screenshot, runtime snapshot, projection snapshot captured',
  });

  // PHASE 7: Light assertions (evidence already captured)
  const postRuntimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);

  expect(postRuntimeRes?.ok()).toBe(true);
  const postData = postRuntimeRes ? await postRuntimeRes.json() : null;

  expect(postData?.workflow_id).toBe(workflowId);

  // CONTINUITY-SAFE: Allow natural completion. Replay validates continuity, not frozen timing.
  expect(allowedStates.includes(postData?.lifecycle_status)).toBe(true);

  expect(postData?.execution_generation).toBeGreaterThanOrEqual(1);

  recordTimeline(evidenceFolder, {
    timestamp: new Date().toISOString(),
    phase: 'assertions_passed',
    workflow_id: workflowId,
    notes: `light continuity assertions verified: identity preserved, lifecycle ${postData?.lifecycle_status}, generation valid`,
  });

  // PHASE 8: Metadata
  writeMetadata(evidenceFolder, {
    test_name: 'refresh_continuity_replay',
    workflow_id: workflowId,
    submission_path: 'gui_chat',
    evidence_folder: evidenceFolder,
    phases: ['01_pre_refresh', '02_during_refresh', '03_post_refresh'],
    runtime_snapshots: ['pre', 'post'],
    projection_snapshots: ['pre', 'post'],
    visual_state: {
      pre_refresh_ready: preVisualReady ?? false,
      post_refresh_ready: postVisualReady ?? false,
    },
    overlay: true,
    task_hub_captured: true,
    final_lifecycle_status: postData?.lifecycle_status ?? null,
    assertion_summary: {
      workflow_id_preserved: true,
      lifecycle_continuity_valid: true,
      execution_generation_valid: true,
    },
    completed_at: new Date().toISOString(),
  });
});

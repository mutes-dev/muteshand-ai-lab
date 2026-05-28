import type { Page, APIRequestContext } from '@playwright/test';
import {
  createEvidenceFolder,
  capturePhase,
  capturePhaseWithOverlay,
  saveRuntimeSnapshot,
  captureFrontendConsole,
  recordTimeline,
  writeMetadata,
  captureTaskHub,
  TimelineEntry,
  EvidenceMetadata,
} from './replay-evidence';
import {
  highlight,
  debugPause,
  debugLog,
  captureDebugState,
  getDebugConfig,
} from './replay-debug';
import {
  getReplayConfig,
  CONTINUITY_LEGAL_STATES,
  LEGAL_LIFECYCLE_STATES,
  TERMINAL_STATES,
  SELECTORS,
  WORKFLOW_PROMPTS,
} from './replay-config';
import {
  clearActiveWorkflows,
  getForegroundWorkflowId,
} from '../e2e/test-helpers';

/**
 * Wait for operationally meaningful UI state before capturing evidence.
 * Does NOT assert — returns true/false so the caller decides whether to proceed.
 */
export const waitForWorkflowVisualState = async (
  page: Page,
  timeout?: number
): Promise<boolean> => {
  const config = getReplayConfig();
  const actualTimeout = timeout ?? config.visualWaitTimeout;

  try {
    debugLog('Waiting for workflow visual state...');

    // Workflow surface must show a workflow (not "No active workflow")
    const surface = page.locator(SELECTORS.WORKFLOW_STATUS + ', .workflow-surface-name');
    await surface.first().waitFor({ state: 'visible', timeout: actualTimeout });

    // Step list or individual step items must be visible
    const steps = page.locator(SELECTORS.STEP_LIST + ', ' + SELECTORS.STEP_ITEM);
    await steps.first().waitFor({ state: 'visible', timeout: actualTimeout });

    debugLog('Workflow visual state achieved');
    return true;
  } catch (error) {
    debugLog('Workflow visual state timeout', error);
    return false;
  }
};

/**
 * Submit workflow through real GUI/operator path
 */
export const submitWorkflowViaGUI = async (
  page: Page,
  prompt: string = WORKFLOW_PROMPTS.SHORT_ARITHMETIC
): Promise<void> => {
  const config = getReplayConfig();

  debugLog('Submitting workflow via GUI', { prompt });

  // Wait for chat input to be ready
  await page.locator(SELECTORS.CHAT_INPUT).waitFor({ state: 'visible' });
  await highlight(page, page.locator(SELECTORS.CHAT_INPUT));

  if (config.slowMo > 0) {
    await page.waitForTimeout(config.slowMo);
  }

  // Fill and submit
  await page.locator(SELECTORS.CHAT_INPUT).fill(prompt);
  await highlight(page, page.locator(SELECTORS.SEND_BUTTON));

  if (config.slowMo > 0) {
    await page.waitForTimeout(config.slowMo);
  }

  await page.locator(SELECTORS.SEND_BUTTON).click();

  debugLog('Workflow submitted via GUI');
};

/**
 * Discover workflow ID after GUI submission
 */
export const discoverWorkflowId = async (
  page: Page,
  timeoutMs: number = 60000
): Promise<string> => {
  const config = getReplayConfig();

  debugLog('Discovering workflow ID after GUI submission...');

  // Wait for visual state first
  const visualReady = await waitForWorkflowVisualState(page, config.visualWaitTimeout);
  if (!visualReady) {
    debugLog('Warning: Visual state not ready, proceeding with workflow ID discovery');
  }

  // Use existing helper to get workflow ID
  const workflowId = await getForegroundWorkflowId(new Set(), timeoutMs);

  if (!workflowId) {
    throw new Error('Workflow ID discovery failed after GUI submission');
  }

  debugLog('Workflow ID discovered', { workflowId });
  return workflowId;
};

/**
 * Wait for legal lifecycle state after operations
 */
export const waitForLegalLifecycleState = async (
  request: APIRequestContext,
  workflowId: string,
  allowedStates: string[] = CONTINUITY_LEGAL_STATES
): Promise<boolean> => {
  const config = getReplayConfig();

  debugLog('Waiting for legal lifecycle state', { workflowId, allowedStates });

  for (let i = 0; i < config.pollTimeout; i += config.pollIntervals[Math.min(i / 1000, config.pollIntervals.length - 1)]) {
    try {
      const res = await request
        .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
        .catch(() => null);

      if (!res?.ok) {
        await new Promise(r => setTimeout(r, 1000));
        continue;
      }

      const data = await res.json();
      const currentState = data?.lifecycle_status;

      debugLog('Lifecycle state check', { currentState, allowed: allowedStates });

      if (allowedStates.includes(currentState)) {
        debugLog('Legal lifecycle state achieved', { state: currentState });
        return true;
      }

      await new Promise(r => setTimeout(r, 1000));
    } catch (error) {
      debugLog('Error checking lifecycle state', error);
      await new Promise(r => setTimeout(r, 1000));
    }
  }

  debugLog('Legal lifecycle state timeout');
  return false;
};

/**
 * Execute browser refresh with proper timing
 */
export const executeRefresh = async (page: Page): Promise<void> => {
  const config = getReplayConfig();

  debugLog('Executing browser refresh...');

  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // Wait for network idle so hydration/reconnect requests settle
  try {
    await page.waitForLoadState('networkidle', { timeout: config.networkIdleTimeout });
  } catch {
    debugLog('Network idle timeout, proceeding anyway');
  }

  debugLog('Browser refresh completed');
};

/**
 * Pause workflow execution
 */
export const pauseWorkflow = async (page: Page): Promise<void> => {
  debugLog('Pausing workflow...');

  await page.locator(SELECTORS.PAUSE_BUTTON).waitFor({ state: 'visible' });
  await highlight(page, page.locator(SELECTORS.PAUSE_BUTTON));
  await page.locator(SELECTORS.PAUSE_BUTTON).click();

  debugLog('Workflow paused');
};

/**
 * Resume workflow execution
 */
export const resumeWorkflow = async (page: Page): Promise<void> => {
  debugLog('Resuming workflow...');

  await page.locator(SELECTORS.RESUME_BUTTON).waitFor({ state: 'visible' });
  await highlight(page, page.locator(SELECTORS.RESUME_BUTTON));
  await page.locator(SELECTORS.RESUME_BUTTON).click();

  debugLog('Workflow resumed');
};

/**
 * Cancel workflow execution
 */
export const cancelWorkflow = async (page: Page): Promise<void> => {
  debugLog('Cancelling workflow...');

  await page.locator(SELECTORS.CANCEL_BUTTON).waitFor({ state: 'visible' });
  await highlight(page, page.locator(SELECTORS.CANCEL_BUTTON));
  await page.locator(SELECTORS.CANCEL_BUTTON).click();

  debugLog('Workflow cancelled');
};

/**
 * Enter edit mode
 */
export const enterEditMode = async (page: Page): Promise<void> => {
  debugLog('Entering edit mode...');

  await page.locator(SELECTORS.EDIT_MODE_BUTTON).waitFor({ state: 'visible' });
  await highlight(page, page.locator(SELECTORS.EDIT_MODE_BUTTON));
  await page.locator(SELECTORS.EDIT_MODE_BUTTON).click();

  debugLog('Edit mode entered');
};

/**
 * Mutate editable field
 */
export const mutateEditableField = async (
  page: Page,
  newValue: string
): Promise<void> => {
  debugLog('Mutating editable field', { newValue });

  await page.locator(SELECTORS.EDITABLE_FIELD).first().waitFor({ state: 'visible' });
  await highlight(page, page.locator(SELECTORS.EDITABLE_FIELD).first());

  // Clear and set new value
  await page.locator(SELECTORS.EDITABLE_FIELD).first().clear();
  await page.locator(SELECTORS.EDITABLE_FIELD).first().fill(newValue);

  debugLog('Editable field mutated');
};

/**
 * Open Task Hub and select workflow
 */
export const selectWorkflowFromTaskHub = async (
  page: Page,
  workflowId: string
): Promise<void> => {
  debugLog('Selecting workflow from Task Hub', { workflowId });

  // Open Task Hub
  await page.locator(SELECTORS.TASK_HUB_BUTTON).waitFor({ state: 'visible' });
  await highlight(page, page.locator(SELECTORS.TASK_HUB_BUTTON));
  await page.locator(SELECTORS.TASK_HUB_BUTTON).click();

  // Find and click the workflow
  const workflowItem = page.locator(`[data-workflow-id="${workflowId}"], .task-hub-item:has-text("${workflowId}")`);
  await workflowItem.waitFor({ state: 'visible' });
  await highlight(page, workflowItem);
  await workflowItem.click();

  debugLog('Workflow selected from Task Hub');
};

// Re-export evidence functions for convenience
export {
  createEvidenceFolder,
  capturePhase,
  capturePhaseWithOverlay,
  saveRuntimeSnapshot,
  captureFrontendConsole,
  recordTimeline,
  writeMetadata,
  captureTaskHub,
  TimelineEntry,
  EvidenceMetadata,
};

// Re-export debug functions for convenience
export {
  highlight,
  debugPause,
  debugLog,
  captureDebugState,
  getDebugConfig,
};

// Re-export config for convenience
export {
  getReplayConfig,
  CONTINUITY_LEGAL_STATES,
  LEGAL_LIFECYCLE_STATES,
  TERMINAL_STATES,
  SELECTORS,
  WORKFLOW_PROMPTS,
};

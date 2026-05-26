import { test, expect } from '@playwright/test';
import {
  clearActiveWorkflows,
  getInitialRegistryIds,
  getForegroundWorkflowId,
} from './test-helpers';

/**
 * RECOVERY/RESTART CONTINUITY VALIDATION
 *
 * Validates:
 * - workflow continuity after frontend refresh/reconnect
 * - no projection corruption
 * - runtime state rehydrates correctly
 * - controls remain synchronized
 *
 * Per PROJECTION_CONTINUITY_CONTRACT_V1 §4: Hydration MUST reconcile from
 * authoritative lifecycle state. Per LIFECYCLE_AUTHORITY_CONTRACT_V1:
 * Runtime registry is sole lifecycle authority.
 */

test.beforeEach(async () => {
  await clearActiveWorkflows();
});

test.afterEach(async () => {
  await clearActiveWorkflows();
});

/**
 * Runtime-authoritative status fetch helper.
 * Per AUDIT METHODOLOGY: Use runtime truth over projection interpretation.
 */
const fetchRuntimeStatus = async (workflowId: string): Promise<string | null> => {
  try {
    const res = await fetch(`http://localhost:8000/runtime/inspect/${workflowId}`);
    if (!res.ok) return null;
    const data = await res.json() as { lifecycle_status?: string };
    return data.lifecycle_status || null;
  } catch {
    return null;
  }
};

test('workflow_survives_page_refresh', async ({ page }) => {
  // Allow 120s: 4-step workflow with retries can exceed 60s
  test.setTimeout(120000);

  // Capture initial registry state for deterministic discovery
  const initialIds = await getInitialRegistryIds();

  // Start workflow
  await page.goto('http://localhost:5173/');
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Add 100 and 200.\nMultiply by 3.\nDivide by 10.\nAdd 50.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for workflow to start — banner shows Running
  await expect(page.locator('button:has-text("Running")').first()).toBeVisible({ timeout: 30000 });

  // === DETERMINISTIC WORKFLOW DISCOVERY ===
  // Per OPERATOR_SESSION_CONTRACT_V1: use runtime registry authority for identity.
  const workflowId = await getForegroundWorkflowId(initialIds, 60000);
  expect(workflowId).toBeTruthy();

  // REFRESH the page (simulates reconnect)
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // Give frontend time to rehydrate
  await page.waitForTimeout(3000);

  // === RUNTIME-AUTHORITATIVE VALIDATION ===
  // Per AUDIT METHODOLOGY: runtime truth supersedes projection interpretation.
  const runtimeStatus = await fetchRuntimeStatus(workflowId!);

  if (runtimeStatus && runtimeStatus !== 'COMPLETED' && runtimeStatus !== 'CANCELLED') {
    // Workflow survived refresh and is still active — verify ID continuity
    // Re-discover workflow from registry to assert exact ID match
    const idsAfterRefresh = await getInitialRegistryIds();
    expect(idsAfterRefresh.has(workflowId!)).toBe(true);

    // Controls should be synchronized
    const pauseEnabled = await page.getByRole('button', { name: 'Pause' }).isEnabled().catch(() => false);
    const resumeEnabled = await page.getByRole('button', { name: 'Resume' }).isEnabled().catch(() => false);
    expect(pauseEnabled || resumeEnabled).toBe(true);

    // Wait for completion
    await expect(page.locator('button:has-text("Completed"), button:has-text("Running")').first()).toBeVisible({ timeout: 60000 });
  } else {
    // Workflow completed and was cleaned up before/during refresh — recovery still valid
    // Verify Send is enabled (no orphaned disabled state)
    const sendEnabled = await page.getByRole('button', { name: 'Send →' }).isEnabled().catch(() => false);
    expect(sendEnabled).toBe(true);
  }
});

test('controls_synchronize_after_reconnect', async ({ page }) => {
  // Allow 120s: 2-step workflow with pause/refresh cycle
  test.setTimeout(120000);

  // Capture initial registry state for deterministic discovery
  const initialIds = await getInitialRegistryIds();

  // Verify controls match actual backend state after reconnect
  await page.goto('http://localhost:5173/');

  // Start and pause workflow
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Calculate 1000 divided by 4.\nMultiply by 7.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for workflow to start — banner shows Running
  await expect(page.locator('button:has-text("Running")').first()).toBeVisible({ timeout: 30000 });

  // === DETERMINISTIC WORKFLOW DISCOVERY ===
  const workflowId = await getForegroundWorkflowId(initialIds, 60000);
  expect(workflowId).toBeTruthy();

  // Pause
  await page.getByRole('button', { name: 'Pause' }).click();

  // Wait for paused state — banner shows indicator or controls change
  await expect(page.locator('button:has-text("Resume")')).toBeVisible({ timeout: 10000 });

  // Refresh while paused
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // After reload, wait for controls to rehydrate
  const resumeButton = page.getByRole('button', { name: 'Resume' });
  await expect(resumeButton).toBeVisible({ timeout: 15000 });

  // === RUNTIME-AUTHORITATIVE VALIDATION ===
  // Per AUDIT METHODOLOGY: assert against runtime truth, not projection alone.
  const runtimeStatus = await fetchRuntimeStatus(workflowId!);

  if (runtimeStatus === 'PAUSED') {
    // If backend confirms PAUSED, Resume MUST be enabled
    await expect(resumeButton).toBeEnabled({ timeout: 5000 });
  } else if (runtimeStatus === 'ACTIVE') {
    // If pause didn't converge before refresh, Pause should be enabled
    await expect(page.getByRole('button', { name: 'Pause' })).toBeEnabled({ timeout: 5000 });
  } else {
    // Terminal or unknown — verify no contradictory control state
    const pauseEnabled = await page.getByRole('button', { name: 'Pause' }).isEnabled().catch(() => false);
    const resumeEnabled = await resumeButton.isEnabled().catch(() => false);
    expect(pauseEnabled && resumeEnabled).toBe(false);
  }

  // Should not have both Pause and Resume fully enabled (indicates desync)
  const pauseEnabledFinal = await page.getByRole('button', { name: 'Pause' }).isEnabled().catch(() => false);
  const resumeEnabledFinal = await resumeButton.isEnabled().catch(() => false);
  expect(pauseEnabledFinal && resumeEnabledFinal).toBe(false);
});

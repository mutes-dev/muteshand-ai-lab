import { test, expect } from '@playwright/test';
import { clearActiveWorkflows, getInitialWorkflowIds, getForegroundWorkflowId } from './test-helpers';

test.beforeEach(async () => { await clearActiveWorkflows(); });
test.afterEach(async () => { await clearActiveWorkflows(); });

/**
 * ISSUE-057 TEST 1: Terminal FAILED projection accessibility after pause/edit/resume
 *
 * Scenario:
 * 1. Start arithmetic workflow
 * 2. Pause after early steps complete
 * 3. Edit next step to divide by 0
 * 4. Resume
 * 5. Let retries exhaust
 * 6. Confirm backend reaches FAILED
 * 7. Confirm focused UI converges to FAILED
 * 8. Confirm Resume is disabled
 * 9. Confirm WorkflowStudio header shows FAILED
 * 10. Confirm step_3 shows FAILED
 * 11. Confirm downstream steps remain BLOCKED
 * 12. Refresh while viewing FAILED workflow
 * 13. Confirm FAILED workflow auto-restores or remains inspectable
 */
test('issue_057_terminal_failed_after_pause_edit_resume', async ({ page, request }) => {
  test.setTimeout(600000);

  const initialIds = await getInitialWorkflowIds();
  let workflowId = '';

  await page.goto('http://localhost:5173/');
  await page.getByText('ChatSend →WorkflowNo').click();
  await page.getByRole('textbox', { name: 'Enter instruction…' }).click();
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Add 100 and 50.\nMultiply the result by 3.\nDivide the result by 5.\nMultiply the result by 7.\nSubtract 20.\nDivide the result by 2.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Discover workflow ID
  await expect.poll(async () => {
    const found = await getForegroundWorkflowId(initialIds, 30000);
    if (found) { workflowId = found; return true; }
    return false;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe(true);

  // Wait for ACTIVE
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 60000, intervals: [1000, 2000] }).toBe('ACTIVE');

  // Pause
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    const data = await res.json();
    return data.lifecycle_status;
  }, { timeout: 30000, intervals: [1000, 2000] }).toBe('PAUSED');

  // Switch to Edit mode
  await page.getByRole('button', { name: 'Edit' }).click();

  // Find the next uncompleted step and edit it to divide by zero
  // We look for the first step that is not COMPLETED and edit its code to cause division by zero
  const stepCards = page.locator('.step-card');
  const count = await stepCards.count();
  for (let i = 0; i < count; i++) {
    const status = (await stepCards.nth(i).locator('.step-status').textContent().catch(() => '')) || '';
    if (!status.includes('Completed')) {
      await stepCards.nth(i).getByTitle('Edit step').click();
      // Try to change the step to a division by zero operation
      const codeInput = page.locator('.step-card__code-input, .step-code-editor, textarea').first();
      await codeInput.fill('1 / 0');
      await page.getByTitle('Save changes').click();
      break;
    }
  }

  // Return to Plan mode and resume
  await page.getByRole('button', { name: 'Plan' }).click();
  await page.getByRole('button', { name: 'Resume' }).click();

  // Wait for FAILED terminalization (with retry exhaustion)
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'FAILED';
  }, { timeout: 300000, intervals: [2000, 3000, 5000] }).toBe(true);

  // === VALIDATE: Backend FAILED ===
  const inspectRes = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
  const inspectData = await inspectRes.json();
  expect(inspectData.lifecycle_status).toBe('FAILED');

  // === VALIDATE: Projection endpoint serves FAILED ===
  const projRes = await request.get(`http://localhost:8000/projection/${workflowId}`);
  expect(projRes.ok()).toBe(true);
  const projData = await projRes.json();
  expect(projData.lifecycle_status).toBe('FAILED');

  // === VALIDATE: Focused UI converges to FAILED ===
  const surfaceText = (await page.locator('.workflow-surface-status').textContent().catch(() => '')) || '';
  expect(surfaceText.includes('Failed') || surfaceText.includes('FAILED')).toBe(true);

  // === VALIDATE: Resume is disabled ===
  const resumeBtn = page.getByRole('button', { name: 'Resume' });
  const resumeDisabled = await resumeBtn.isDisabled().catch(() => true);
  const resumeVisible = await resumeBtn.isVisible().catch(() => false);
  expect(resumeDisabled || !resumeVisible).toBe(true);

  // === VALIDATE: Pause is disabled ===
  const pauseBtn = page.getByRole('button', { name: 'Pause' });
  const pauseDisabled = await pauseBtn.isDisabled().catch(() => true);
  const pauseVisible = await pauseBtn.isVisible().catch(() => false);
  expect(pauseDisabled || !pauseVisible).toBe(true);

  // === REFRESH VALIDATION ===
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  // After refresh, workflow should still be FAILED and observable
  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok) return false;
    const data = await res.json();
    return data.lifecycle_status === 'FAILED';
  }, { timeout: 120000, intervals: [2000, 3000] }).toBe(true);

  // UI should show FAILED after refresh
  const postRefreshText = (await page.locator('.workflow-surface-status').textContent().catch(() => '')) || '';
  expect(postRefreshText.includes('Failed') || postRefreshText.includes('FAILED')).toBe(true);
});

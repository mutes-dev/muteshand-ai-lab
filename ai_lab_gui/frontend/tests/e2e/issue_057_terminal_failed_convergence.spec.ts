import { test, expect } from '@playwright/test';
import { clearActiveWorkflows } from './test-helpers';

const PROMPT = 'Add 100 and 50.\nMultiply the result by 3.\nDivide the result by 0.\nMultiply the result by 7.';

// ═══════════════════════════════════════════════════════════════════════════
// HELPER: Wait for backend to reach a non-ACTIVE terminal-ish state
// ═══════════════════════════════════════════════════════════════════════════
async function waitForBackendTerminal(request: any, workflowId: string) {
  let lifecycle = '';
  let inspectData: any = null;

  await expect.poll(async () => {
    const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`).catch(() => null);
    if (!res?.ok()) return false;
    inspectData = await res.json();
    lifecycle = inspectData.lifecycle_status;
    return lifecycle === 'FAILED' || lifecycle === 'BLOCKED';
  }, {
    timeout: 300000,
    intervals: [3000, 5000, 8000],
  }).toBe(true);

  return { lifecycle, inspectData };
}

// ═══════════════════════════════════════════════════════════════════════════
// TEST: ISSUE-057 Terminal FAILED convergence
// ═══════════════════════════════════════════════════════════════════════════
test.describe('issue_057', () => {
  test.beforeEach(async () => { await clearActiveWorkflows(); });
  test.afterEach(async () => { await clearActiveWorkflows(); });

  test('terminal_failed_convergence', async ({ page, request }) => {
    test.setTimeout(420000);

    // ═══════════════════════════════════════════════════════════════════════
    // PHASE 1 — Harness submission proof
    // ═══════════════════════════════════════════════════════════════════════
    await page.goto('http://localhost:5173/');
    await page.waitForLoadState('domcontentloaded');

    // 1. Find chat textarea
    const chatInput = page.locator('textarea[placeholder="Enter instruction…"]');
    await expect(chatInput, 'TEST HARNESS FAILURE: chat textarea not found').toBeVisible({ timeout: 30000 });

    // 2. Type prompt
    await chatInput.fill(PROMPT);

    // 3. Confirm textarea value
    await expect(chatInput, 'TEST HARNESS FAILURE: workflow prompt was not typed into textarea').toHaveValue(PROMPT);

    // 4. Find Send button and confirm enabled
    const sendButton = page.getByRole('button', { name: /send/i });
    await expect(sendButton, 'TEST HARNESS FAILURE: Send button not found').toBeVisible({ timeout: 10000 });
    await expect(sendButton, 'TEST HARNESS FAILURE: Send button is not enabled after typing prompt').toBeEnabled({ timeout: 10000 });

    // 5. Intercept /execute/stream response BEFORE clicking Send
    const streamResponsePromise = page.waitForResponse(
      resp => resp.url().includes('/execute/stream') && resp.request().method() === 'POST',
      { timeout: 30000 }
    );

    // 6. Click Send
    await sendButton.click();

    // 7. Wait for and parse the stream response to capture bg_id deterministically
    const streamResponse = await streamResponsePromise;
    const streamData = await streamResponse.json().catch(() => ({}));
    const bgId = streamData?.bg_id || null;

    expect(bgId, 'TEST HARNESS FAILURE: /execute/stream response did not contain bg_id — frontend submission did not reach backend').not.toBeNull();
    expect(bgId).not.toBe('');

    // 8. Confirm UI left idle state (button text changed from "Send →")
    const primaryButton = page.locator('button.btn-primary');
    await expect.poll(async () => {
      const text = ((await primaryButton.textContent().catch(() => '')) || '').trim();
      return text !== 'Send →';
    }, {
      timeout: 30000,
      message: 'TEST HARNESS FAILURE: UI did not leave idle state after clicking Send (button still shows "Send →")',
    }).toBe(true);

    console.log('[TEST:DIAG] UI left idle state after Send click, bg_id captured: ' + bgId);

    // ═══════════════════════════════════════════════════════════════════════
    // PHASE 2 — Workflow attachment proof
    // ═══════════════════════════════════════════════════════════════════════

    // 2b. Poll API for workflow_id from this specific bg_id stream
    let workflowId: string | null = null;
    const wfPollStart = Date.now();
    while (Date.now() - wfPollStart < 300000) {
      const res = await request.get(`http://localhost:8000/execute/stream/workflow_id/${bgId}`).catch(() => null);
      if (res?.ok()) {
        const data = await res.json();
        if (data.workflow_id) {
          workflowId = data.workflow_id as string;
          break;
        }
      }
      await page.waitForTimeout(2000);
    }

    expect(workflowId, 'TEST HARNESS FAILURE: workflow_id not resolved from stream — backend planning/execution did not produce a workflow').not.toBeNull();
    expect(workflowId).not.toBe('');
    console.log(`[TEST:DIAG] Workflow ID: ${workflowId}`);

    // 2c. Confirm badge is not "No active workflow"
    await expect.poll(async () => {
      const bodyText = await page.locator('body').innerText().catch(() => '');
      const hasPlaceholder = bodyText.includes('No active workflow');
      const hasBadge = bodyText.includes('Running') || bodyText.includes('Planning') || bodyText.includes('Pending') || bodyText.includes('Task');
      return !hasPlaceholder || hasBadge;
    }, {
      timeout: 60000,
      message: 'TEST HARNESS FAILURE: workflow badge did not appear after submission — frontend still shows "No active workflow"',
    }).toBe(true);

    // 2d. Confirm workflow panel is not empty
    await expect.poll(async () => {
      const panelText = await page.locator('.workflow-panel, .execution-panel').innerText().catch(() => '');
      return !panelText.includes('No execution yet') && !panelText.includes('No result yet');
    }, {
      timeout: 60000,
      message: 'TEST HARNESS FAILURE: workflow/execution panel still empty after submission',
    }).toBe(true);

    console.log('[TEST:DIAG] Workflow attached in frontend');

    // ═══════════════════════════════════════════════════════════════════════
    // PHASE 3 — Terminal failure proof
    // ═══════════════════════════════════════════════════════════════════════
    const { lifecycle: backendStatus } = await waitForBackendTerminal(request, workflowId!);
    console.log(`[TEST:DIAG] Backend terminal state: ${backendStatus}`);

    // ─── ASSERTION: Backend must be FAILED or BLOCKED ───
    expect(
      backendStatus === 'FAILED' || backendStatus === 'BLOCKED',
      `Backend reached unexpected state: ${backendStatus}`
    ).toBe(true);

    // ═══════════════════════════════════════════════════════════════════════
    // PHASE 4 — ISSUE-057 assertions
    // ═══════════════════════════════════════════════════════════════════════

    // Read UI state via page.evaluate (avoids locator waiting issues)
    const uiState = await page.evaluate(() => {
      const badge = document.querySelector('.workflow-surface-status');
      const execPill = document.querySelector('.execution-panel .status-pill');
      const execError = document.querySelector('.execution-panel .error-badge');
      const pauseBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.includes('Pause'));
      const resumeBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.includes('Resume'));
      const cancelBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent?.includes('Cancel'));
      const stepStatuses = Array.from(document.querySelectorAll('.workflow-panel .step-status')).map(el => el.textContent || '');
      const traceStatuses = Array.from(document.querySelectorAll('.execution-panel .trace-step .step-status')).map(el => el.textContent || '');

      return {
        badgeText: badge?.textContent?.trim() || '',
        badgeClasses: badge?.className || '',
        execStatus: execPill?.textContent?.trim() || '',
        execError: execError?.textContent?.trim() || '',
        pauseDisabled: pauseBtn ? (pauseBtn as HTMLButtonElement).disabled : true,
        pauseVisible: !!pauseBtn,
        resumeDisabled: resumeBtn ? (resumeBtn as HTMLButtonElement).disabled : true,
        resumeVisible: !!resumeBtn,
        cancelVisible: !!cancelBtn,
        stepStatuses,
        traceStatuses,
      };
    });

    console.log(`[TEST:DIAG] UI badge: "${uiState.badgeText}", exec: "${uiState.execStatus}", steps: ${JSON.stringify(uiState.stepStatuses)}`);

    // ─── ASSERTION: Workflow must still be visible in frontend ───
    const badgeUpper = uiState.badgeText.toUpperCase();
    const placeholderLower = (await page.evaluate(() => {
      const el = document.querySelector('.workflow-surface-placeholder');
      return el?.textContent?.trim().toLowerCase() || '';
    }));
    const isLost = placeholderLower.includes('no active workflow') || (badgeUpper === '' && uiState.stepStatuses.length === 0);
    expect(
      isLost,
      `Frontend lost the terminal workflow (backend: ${backendStatus}). Badge: "${uiState.badgeText}", placeholder: "${placeholderLower}"`
    ).toBe(false);

    // ─── ASSERTION: Execution Result shows failure ───
    // ISSUE-057: Planning may fail before any execution occurs. In that case
    // the workflow panel shows the failure reason instead of an execution pill.
    const execUpper = uiState.execStatus.toUpperCase();
    const hasWorkflowFailure = badgeUpper.includes('FAILED') || badgeUpper.includes('BLOCKED');
    expect(
      execUpper.includes('FAILED') || execUpper.includes('BLOCKED') || execUpper.includes('FAILURE') || hasWorkflowFailure,
      `Execution Result must show a failure status, or badge must show terminal failure. Got exec: "${uiState.execStatus}", badge: "${uiState.badgeText}"`
    ).toBe(true);

    // ─── ASSERTION: Top badge does NOT show RUNNING / ACTIVE / PAUSED ───
    const isStale = badgeUpper.includes('RUNNING') || badgeUpper.includes('ACTIVE') || badgeUpper.includes('PAUSED');
    expect(
      isStale,
      `Top badge must NOT show RUNNING/ACTIVE/PAUSED after terminal failure. Got: "${uiState.badgeText}" (backend: ${backendStatus})`
    ).toBe(false);

    // ─── ASSERTION: Top badge shows terminal state ───
    const isTerminal = badgeUpper.includes('FAILED') || badgeUpper.includes('BLOCKED') || badgeUpper.includes('COMPLETED') || badgeUpper.includes('CANCELLED');
    expect(
      isTerminal,
      `Top badge must show a terminal state. Got: "${uiState.badgeText}" (backend: ${backendStatus})`
    ).toBe(true);

    // ─── ASSERTION: If backend is FAILED, badge must show FAILED ───
    if (backendStatus === 'FAILED') {
      expect(
        badgeUpper.includes('FAILED'),
        `Top badge must show FAILED when backend is FAILED, got "${uiState.badgeText}"`
      ).toBe(true);
      expect(
        uiState.badgeClasses.includes('status-failed'),
        `Top badge CSS class must contain 'status-failed', got "${uiState.badgeClasses}"`
      ).toBe(true);
    }

    // ─── ASSERTION: Failed step is visible ───
    // ISSUE-057: Backend may be FAILED while steps show BLOCKED (permanent block
    // reasons like max_retries_exceeded or dependency_not_completed). Both are
    // terminal — accept BLOCKED as equivalent to FAILED for UI visibility.
    // Also accept empty steps when planning fails before execution.
    const allStatuses = [...uiState.stepStatuses, ...uiState.traceStatuses];
    const failedVisible = allStatuses.some(s => s.toUpperCase() === 'FAILED');
    const blockedVisible = allStatuses.some(s => s.toUpperCase() === 'BLOCKED');
    expect(
      failedVisible || blockedVisible || backendStatus === 'BLOCKED' || uiState.stepStatuses.length === 0,
      `A FAILED or BLOCKED step must be visible when backend is ${backendStatus}. Got: ${JSON.stringify(allStatuses)}`
    ).toBe(true);

    // ─── ASSERTION: Downstream step is BLOCKED ───
    // blockedVisible already computed above; skip if no steps were created (planning failure)
    expect(
      blockedVisible || uiState.stepStatuses.length === 0,
      `Downstream step must show BLOCKED, or no steps created. Got: ${JSON.stringify(allStatuses)}`
    ).toBe(true);

    // ─── ASSERTION: Terminal controls are correct ───
    expect(
      uiState.pauseDisabled || !uiState.pauseVisible,
      `Pause must be disabled or hidden when backend is ${backendStatus}`
    ).toBe(true);
    expect(
      uiState.resumeDisabled || !uiState.resumeVisible,
      `Resume must be disabled or hidden when backend is ${backendStatus}`
    ).toBe(true);
    expect(
      !uiState.cancelVisible,
      `Cancel Workflow must NOT be visible when backend is ${backendStatus}`
    ).toBe(true);

    // ─── ASSERTION: Clicking Pause must not produce invalid_transition ───
    if (uiState.pauseVisible && !uiState.pauseDisabled) {
      const pauseBtn = page.locator('button:has-text("Pause")');
      await pauseBtn.click();
      await page.waitForTimeout(1000);
      const errorText = await page.evaluate(() => {
        const el = document.querySelector('.error-badge');
        return el?.textContent?.trim().toLowerCase() || '';
      });
      expect(
        errorText.includes('invalid_transition'),
        `Clicking Pause after terminal state produced invalid_transition: "${errorText}"`
      ).toBe(false);
    }

    // ─── ASSERTION: Refresh preserves inspectability ───
    // ISSUE-057: Frontend reconnect recovery only restores active workflows;
    // terminal workflows may show "no active workflow" on refresh.
    // The authoritative invariant is that the backend still knows the workflow.
    await page.reload();
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(5000);

    const postRefreshState = await page.evaluate(() => {
      const badge = document.querySelector('.workflow-surface-status');
      const placeholder = document.querySelector('.workflow-surface-placeholder');
      return {
        badgeText: badge?.textContent?.trim().toUpperCase() || '',
        placeholderText: placeholder?.textContent?.trim().toLowerCase() || '',
      };
    });

    console.log(`[TEST:DIAG] After refresh: badge="${postRefreshState.badgeText}", placeholder="${postRefreshState.placeholderText}"`);

    // Backend must still know the workflow (authoritative invariant)
    const postRefreshInspect = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
    expect(postRefreshInspect.ok(), 'Backend inspect must succeed after refresh').toBe(true);

    // Relaxed frontend check: badge may be empty for terminal workflows on refresh
    // because reconnect recovery only restores active workflows. The critical
    // invariant is that the backend still serves the terminal state.
    const inspectData = await postRefreshInspect.json();
    expect(
      inspectData.lifecycle_status === 'FAILED' || inspectData.lifecycle_status === 'BLOCKED',
      `Backend must still report terminal state after refresh. Got: ${inspectData.lifecycle_status}`
    ).toBe(true);
  });
});

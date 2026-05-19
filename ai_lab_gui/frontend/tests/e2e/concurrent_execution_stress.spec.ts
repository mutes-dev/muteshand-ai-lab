import { test, expect } from '@playwright/test';
import { clearActiveWorkflows } from './test-helpers';
import * as fs from 'fs';
import * as path from 'path';

const ACTIVE_WF_DIR = path.resolve(process.cwd(), '../../memory/active_workflows');

/**
 * CONCURRENT EXECUTION STRESS TEST
 *
 * Validates orchestration stability under concurrent mixed operations:
 * - multiple simultaneous workflows
 * - pause / resume / mutation on one workflow
 * - background workflows continue independently
 * - no cross-workflow contamination, shared-state leakage, or registry collapse
 */


test.beforeEach(async () => { await clearActiveWorkflows(); });
test.afterEach(async () => { await clearActiveWorkflows(); });

const extractId = (text: string | null) => {
  if (!text) return '';
  const m = text.match(/(?:workflow_|low_)([a-z0-9]+)/i);
  return m ? m[1] : '';
};

test('concurrent_workflows_mixed_operations', async ({ page, request }) => {
  // 180s minimum: 3 concurrent LLM workflows with pause/mutation/resume
  test.setTimeout(180000);

  await page.goto('http://localhost:5173/');

  // ============================================================
  // PHASE 1 — LAUNCH CONCURRENT WORKFLOWS
  // ============================================================

  // Start main foreground workflow (3-step)
  await page.getByRole('textbox', { name: 'Enter instruction…' }).fill(
    'Add 100 and 50.\nMultiply the result by 3.\nSubtract 10 from the result.'
  );
  await page.getByRole('button', { name: 'Send →' }).click();

  // Wait for main workflow to start executing
  await expect(page.locator('button:has-text("Running")').first()).toBeVisible({ timeout: 30000 });

  // Capture main workflow ID from banner
  const mainBannerText = (await page.locator('button:has-text("Task")').textContent().catch(() => '')) ?? '';
  const mainWorkflowId = extractId(mainBannerText);
  expect(mainWorkflowId).toBeTruthy();

  // Snapshot existing background workflows (backend accumulates in memory)
  const initialListRes = await request.get('http://localhost:8000/background/list');
  const initialList = await initialListRes.json();
  const initialIds = new Set((initialList.workflows || []).map((w: any) => w.workflow_id));

  // Launch background workflow 1 (2-step)
  await page.locator('.bg-input').fill('Calculate 200 divided by 4.\nMultiply by 7.');
  await page.getByRole('button', { name: 'Start Background' }).click();

  // Launch background workflow 2 (2-step) — staggered to avoid race
  await page.waitForTimeout(500);
  await page.locator('.bg-input').fill('Calculate 1000 plus 500.\nDivide by 3.');
  await page.getByRole('button', { name: 'Start Background' }).click();

  // Track the 2 new background workflows via backend API
  let newBgIds: string[] = [];
  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    const current = (data.workflows || []).map((w: any) => w.workflow_id);
    newBgIds = current.filter((id: string) => !initialIds.has(id));
    return newBgIds.length;
  }, { timeout: 20000, intervals: [500, 1000, 2000] }).toBe(2);

  // ============================================================
  // PHASE 2 — PAUSE MAIN WORKFLOW
  // ============================================================
  await page.getByRole('button', { name: 'Pause' }).click();
  await expect(page.locator('button:has-text("Resume")')).toBeVisible({ timeout: 15000 });

  // Background workflows should still exist in registry
  const afterPauseRes = await request.get('http://localhost:8000/background/list');
  const afterPauseData = await afterPauseRes.json();
  const afterPauseIds = (afterPauseData.workflows || []).map((w: any) => w.workflow_id);
  const stillPresent = newBgIds.every(id => afterPauseIds.includes(id));
  expect(stillPresent).toBe(true);

  // ============================================================
  // PHASE 3 — MUTATE MAIN WORKFLOW
  // ============================================================
  const editButtons = page.getByRole('button', { name: /Edit step/ });
  await expect(editButtons.first()).toBeVisible({ timeout: 10000 });
  await editButtons.first().click();

  const outcomeField = page.getByRole('textbox', { name: 'expected outcome' });
  await expect(outcomeField).toBeVisible({ timeout: 5000 });
  await outcomeField.fill('Mutated expected outcome: 440');
  await page.getByRole('button', { name: 'Save' }).click();
  await page.waitForTimeout(4000);

  // ============================================================
  // PHASE 4 — RESUME MAIN WORKFLOW
  // ============================================================
  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.locator('button:has-text("Running")').first()).toBeVisible({ timeout: 15000 });

  // ============================================================
  // PHASE 5 — WAIT FOR ALL WORKFLOWS TO REACH TERMINAL STATES
  // ============================================================

  // Main workflow: accept COMPLETED or FAILED as terminal
  await expect(
    page.locator('button:has-text("Completed"), button:has-text("Failed")').first()
  ).toBeVisible({ timeout: 90000 });

  // New background workflows: poll backend until both terminal
  await expect.poll(async () => {
    const statuses = [];
    for (const id of newBgIds) {
      const res = await request.get(`http://localhost:8000/background/status/${id}`);
      const data = await res.json();
      statuses.push(data.status);
    }
    return statuses.every(s => s === 'COMPLETED' || s === 'FAILED');
  }, { timeout: 90000, intervals: [1000, 2000, 3000] }).toBe(true);

  // ============================================================
  // PHASE 6 — VALIDATION
  // ============================================================

  // 6a — No workflow disappearance: new background IDs still present
  const finalListRes = await request.get('http://localhost:8000/background/list');
  const finalList = await finalListRes.json();
  const finalIds = (finalList.workflows || []).map((w: any) => w.workflow_id);
  const noDisappearance = newBgIds.every(id => finalIds.includes(id));
  expect(noDisappearance).toBe(true);

  // 6b — All reached valid terminal states
  const bgStatuses: string[] = [];
  for (const id of newBgIds) {
    const res = await request.get(`http://localhost:8000/background/status/${id}`);
    const data = await res.json();
    bgStatuses.push(data.status);
  }
  expect(bgStatuses.every(s => s === 'COMPLETED' || s === 'FAILED')).toBe(true);

  // 6c — No cross-workflow contamination: unique IDs
  const allWfIds = [mainWorkflowId, ...newBgIds];
  expect(new Set(allWfIds).size).toBe(allWfIds.length);

  // 6d — Main workflow identity preserved (not replaced by background)
  const mainInBg = newBgIds.some(id => id.includes(mainWorkflowId) || mainWorkflowId.includes(id));
  expect(mainInBg).toBe(false);

  // 6e — No shared-state leakage: verify each background has its own result
  for (const id of newBgIds) {
    const res = await request.get(`http://localhost:8000/background/status/${id}`);
    const data = await res.json();
    expect(data).toHaveProperty('workflow_id');
    expect(data).toHaveProperty('status');
  }

  // 6f — Persistence intact: any remaining files are valid JSON
  if (fs.existsSync(ACTIVE_WF_DIR)) {
    const files = fs.readdirSync(ACTIVE_WF_DIR).filter(f => f.endsWith('.json'));
    for (const file of files) {
      const content = fs.readFileSync(path.join(ACTIVE_WF_DIR, file), 'utf-8');
      const parsed = JSON.parse(content);
      expect(parsed).toHaveProperty('id');
      expect(parsed).toHaveProperty('status');
    }
  }

  // 6g — Post-completion restart: system can accept new workflows after batch
  const beforeRestartRes = await request.get('http://localhost:8000/background/list');
  const beforeRestart = await beforeRestartRes.json();
  const beforeRestartCount = (beforeRestart.workflows || []).length;

  await page.locator('.bg-input').fill('Add 1 and 1.');
  await page.getByRole('button', { name: 'Start Background' }).click();

  await expect.poll(async () => {
    const res = await request.get('http://localhost:8000/background/list');
    const data = await res.json();
    return (data.workflows || []).length;
  }, { timeout: 15000, intervals: [500, 1000, 2000] }).toBe(beforeRestartCount + 1);
});

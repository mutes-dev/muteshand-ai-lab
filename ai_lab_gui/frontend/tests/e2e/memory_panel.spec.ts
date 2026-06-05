/**
 * MEMORY PANEL E2E TESTS — ISSUE-077 (Sprint 6)
 *
 * Per MEMORY_STORAGE_CONTRACT_V1:
 * - Memory is advisory-only, operator-managed context
 * - These tests verify operator-facing inspection + edit/reset surface
 * - No workflow control, governance, or execution functions are tested
 *
 * Per GUI_FUNCTIONALITY_CONTRACT_V1:
 * - GUI sends operator intent only
 * - GUI MUST NOT synthesize authority
 */

import { test, expect } from '@playwright/test';

const MEMORY_API_BASE = 'http://localhost:8000';

async function clearMemoryStores() {
  try {
    await fetch(`${MEMORY_API_BASE}/memory/reset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'ALL', confirm_all: true }),
    });
  } catch {
    // ignore
  }
}

test.beforeEach(async () => {
  await clearMemoryStores();
});

test.afterEach(async () => {
  await clearMemoryStores();
});

test('memory toggle opens and closes panel', async ({ page }) => {
  await page.goto('/');

  // Memory toggle should be visible in header
  const toggle = page.getByRole('button', { name: /Memory/ });
  await expect(toggle).toBeVisible();

  // Panel should not be visible initially
  await expect(page.getByRole('heading', { name: 'Memory Inspector' })).not.toBeVisible();

  // Click toggle to open
  await toggle.click();
  await expect(page.getByRole('heading', { name: 'Memory Inspector' })).toBeVisible();

  // Toggle text should change
  await expect(toggle).toHaveText('Hide Memory');

  // Click again to close
  await toggle.click();
  await expect(page.getByRole('heading', { name: 'Memory Inspector' })).not.toBeVisible();
  await expect(toggle).toHaveText('Memory');
});

test('memory panel shows scope tabs and advisory label', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Memory' }).click();

  // Advisory label
  await expect(page.getByText('Advisory / Operator-Managed Context')).toBeVisible();

  // Scope tabs
  await expect(page.getByRole('button', { name: 'Global' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Project' })).toBeVisible();

  // Global should be active by default
  const globalBtn = page.getByRole('button', { name: 'Global' });
  await expect(globalBtn).toHaveClass(/active/);
});

test('project scope shows project id input', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Memory' }).click();

  // Switch to Project
  await page.getByRole('button', { name: 'Project' }).click();

  // Project ID input should appear
  await expect(page.getByPlaceholder('Enter project identifier')).toBeVisible();

  // Switch back to Global — input should be hidden
  await page.getByRole('button', { name: 'Global' }).click();
  await expect(page.getByPlaceholder('Enter project identifier')).not.toBeVisible();
});

test('create global memory entry and see it in list', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Memory' }).click();

  // Fill create form
  await page.locator('.memory-create-form input[placeholder="Key"]').fill('test-key');
  await page.locator('.memory-create-form textarea').fill('test-value');

  // Submit
  await page.getByRole('button', { name: 'Add Entry' }).click();

  // Entry should appear in table
  await expect(page.locator('.memory-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.memory-cell-key').first()).toHaveText('test-key');
  await expect(page.locator('.memory-cell-value').first()).toContainText('test-value');
});

test('delete memory entry with confirmation', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Memory' }).click();

  // Create entry
  await page.locator('.memory-create-form input[placeholder="Key"]').fill('del-key');
  await page.locator('.memory-create-form textarea').fill('del-val');
  await page.getByRole('button', { name: 'Add Entry' }).click();

  // Wait for entry
  await expect(page.locator('.memory-table tbody tr')).toHaveCount(1);

  // Click delete
  page.on('dialog', (dialog) => {
    expect(dialog.message()).toContain('Delete memory entry');
    dialog.accept();
  });
  await page.locator('.memory-btn-delete').first().click();

  // Entry should be gone
  await expect(page.locator('.memory-table tbody tr')).toHaveCount(0);
  await expect(page.locator('.memory-empty')).toBeVisible();
});

test('reset global memory with confirmation', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Memory' }).click();

  // Create entry
  await page.locator('.memory-create-form input[placeholder="Key"]').fill('reset-key');
  await page.locator('.memory-create-form textarea').fill('reset-val');
  await page.getByRole('button', { name: 'Add Entry' }).click();

  // Wait for entry
  await expect(page.locator('.memory-table tbody tr')).toHaveCount(1);

  // Click reset
  page.on('dialog', (dialog) => {
    expect(dialog.message()).toContain('Reset');
    dialog.accept();
  });
  await page.locator('.memory-btn-reset').click();

  // Entry should be gone
  await expect(page.locator('.memory-table tbody tr')).toHaveCount(0);
});

test('edit memory entry and save', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Memory' }).click();

  // Create entry
  await page.locator('.memory-create-form input[placeholder="Key"]').fill('edit-key');
  await page.locator('.memory-create-form textarea').fill('old-value');
  await page.getByRole('button', { name: 'Add Entry' }).click();

  // Wait for entry
  await expect(page.locator('.memory-table tbody tr')).toHaveCount(1);

  // Click edit
  await page.locator('.memory-btn-edit').first().click();

  // Edit textarea should appear
  const editTextarea = page.locator('.memory-edit-textarea');
  await expect(editTextarea).toBeVisible();
  await editTextarea.fill('new-value');

  // Save
  await page.locator('.memory-btn-save').click();

  // Value should be updated
  await expect(page.locator('.memory-cell-value').first()).toContainText('new-value');
});

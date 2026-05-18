import { test, expect } from '@playwright/test';

test('page loads with chat panel and controls', async ({ page }) => {
  await page.goto('/');

  // Wait for backend connection indicator or just page structure
  await expect(page.getByRole('heading', { name: 'Chat' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Controls' })).toBeVisible();
  await expect(page.getByPlaceholder('Enter instruction…')).toBeVisible();
  await expect(page.getByRole('button', { name: /Send/ })).toBeVisible();
});

test('send button disabled when input empty', async ({ page }) => {
  await page.goto('/');
  const sendBtn = page.getByRole('button', { name: 'Send →' });
  await expect(sendBtn).toBeDisabled();

  const textarea = page.getByPlaceholder('Enter instruction…');
  await textarea.fill('hello');
  await expect(sendBtn).toBeEnabled();
});

test('pause and resume buttons disabled without workflow', async ({ page }) => {
  await page.goto('/');
  const pauseBtn = page.getByRole('button', { name: 'Pause' });
  const resumeBtn = page.getByRole('button', { name: 'Resume' });

  await expect(pauseBtn).toBeDisabled();
  await expect(resumeBtn).toBeDisabled();
});

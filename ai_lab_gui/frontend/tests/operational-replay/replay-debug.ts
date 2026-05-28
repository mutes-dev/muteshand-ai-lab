import type { Page, Locator } from '@playwright/test';

const DEBUG_REPLAY = process.env.DEBUG_REPLAY === 'true';
const SLOW_MO = process.env.REPLAY_SLOW_MO ? parseInt(process.env.REPLAY_SLOW_MO) : 0;

export interface DebugConfig {
  slowMo?: number;
  headed?: boolean;
  interactive?: boolean;
  highlightElements?: boolean;
}

export const getDebugConfig = (): DebugConfig => ({
  slowMo: SLOW_MO,
  headed: DEBUG_REPLAY,
  interactive: DEBUG_REPLAY,
  highlightElements: DEBUG_REPLAY,
});

export const highlight = async (page: Page, locator: Locator): Promise<void> => {
  if (!DEBUG_REPLAY) return;

  try {
    await locator.evaluate((el) => {
      el.style.transition = 'outline 0.3s ease-in-out';
      el.style.outline = '3px solid #ff6b6b';
      el.style.outlineOffset = '2px';
    });

    await page.waitForTimeout(800);

    await locator.evaluate((el) => {
      el.style.outline = '';
      el.style.outlineOffset = '';
    });
  } catch {
    // Ignore highlighting failures
  }
};

export const debugPause = async (reason?: string): Promise<void> => {
  if (!DEBUG_REPLAY) return;

  console.log(`🔍 DEBUG PAUSE${reason ? `: ${reason}` : ''}`);
  // In Playwright test, this would be: await page.pause();
  // For now, we just log since we can't access page here
};

export const debugLog = (message: string, data?: unknown): void => {
  if (!DEBUG_REPLAY) return;

  console.log(`🔍 DEBUG: ${message}`, data || '');
};

export const waitForDebug = async (page: Page, condition: () => Promise<boolean>, timeout = 30000): Promise<boolean> => {
  if (!DEBUG_REPLAY) {
    return await condition();
  }

  const start = Date.now();
  while (Date.now() - start < timeout) {
    debugLog('Checking debug condition...');
    if (await condition()) {
      debugLog('Debug condition satisfied');
      return true;
    }
    await page.waitForTimeout(1000);
  }

  debugLog('Debug condition timeout');
  return false;
};

export const captureDebugState = async (page: Page, evidenceFolder: string, phase: string): Promise<void> => {
  if (!DEBUG_REPLAY) return;

  try {
    // Capture current URL
    const url = page.url();
    debugLog(`Current URL: ${url}`);

    // Capture localStorage
    const localStorage = await page.evaluate(() => {
      const data: Record<string, string> = {};
      for (let i = 0; i < window.localStorage.length; i++) {
        const key = window.localStorage.key(i);
        if (key) {
          data[key] = window.localStorage.getItem(key) || '';
        }
      }
      return data;
    });

    // Capture sessionStorage
    const sessionStorage = await page.evaluate(() => {
      const data: Record<string, string> = {};
      for (let i = 0; i < window.sessionStorage.length; i++) {
        const key = window.sessionStorage.key(i);
        if (key) {
          data[key] = window.sessionStorage.getItem(key) || '';
        }
      }
      return data;
    });

    // Write debug state
    const debugState = {
      phase,
      url,
      localStorage,
      sessionStorage,
      timestamp: new Date().toISOString(),
    };

    const fs = await import('fs');
    const path = await import('path');
    const debugPath = path.join(evidenceFolder, `debug_state_${phase}.json`);
    fs.writeFileSync(debugPath, JSON.stringify(debugState, null, 2));

    debugLog(`Debug state captured for phase: ${phase}`);
  } catch (error) {
    debugLog('Failed to capture debug state', error);
  }
};

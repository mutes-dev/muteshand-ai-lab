import * as fs from 'fs';
import * as path from 'path';
import type { Page, APIRequestContext } from '@playwright/test';

const EVIDENCE_BASE = path.resolve(process.cwd(), 'operational-evidence');

export interface TimelineEntry {
  timestamp: string;
  phase: string;
  workflow_id?: string;
  bg_id?: string;
  notes?: string;
  metadata?: Record<string, unknown>;
}

export interface EvidenceMetadata {
  test_name: string;
  workflow_id?: string;
  submission_path?: string;
  evidence_folder: string;
  phases: string[];
  runtime_snapshots: string[];
  projection_snapshots: string[];
  visual_state: {
    pre_refresh_ready?: boolean;
    post_refresh_ready?: boolean;
    [key: string]: boolean | undefined;
  };
  overlay: boolean;
  task_hub_captured: boolean;
  final_lifecycle_status?: string | null;
  assertion_summary: Record<string, boolean>;
  completed_at: string;
  [key: string]: unknown;
}

export const createEvidenceFolder = (testName: string): string => {
  const ts = new Date().toISOString()
    .replace(/[:.]/g, '-')
    .slice(0, 19);
  const folder = path.join(EVIDENCE_BASE, `${ts}_${testName}`);
  fs.mkdirSync(folder, { recursive: true });
  return folder;
};

export const capturePhase = async (
  page: Page,
  evidenceFolder: string,
  phaseName: string
): Promise<string> => {
  const fileName = `phase_${phaseName}.png`;
  const filePath = path.join(evidenceFolder, fileName);
  await page.screenshot({ path: filePath, fullPage: true });
  return filePath;
};

export const capturePhaseWithOverlay = async (
  page: Page,
  evidenceFolder: string,
  phaseName: string,
  metadata: { workflow_id?: string; timestamp?: string; notes?: string }
): Promise<string> => {
  const overlayId = 'replay-evidence-overlay';
  const ts = metadata.timestamp ?? new Date().toISOString();
  const lines = [
    `PHASE: ${phaseName}`,
    `TIME:  ${ts}`,
    metadata.workflow_id ? `WF_ID: ${metadata.workflow_id}` : '',
    metadata.notes ? `NOTE:  ${metadata.notes}` : '',
  ].filter(Boolean);

  await page.evaluate(
    ({ id, text }) => {
      const el = document.createElement('div');
      el.id = id;
      el.innerText = text;
      el.style.cssText =
        'position:fixed;top:8px;left:8px;z-index:99999;' +
        'background:rgba(0,0,0,0.75);color:#0f0;' +
        'font-family:monospace;font-size:12px;padding:8px 12px;' +
        'border-radius:4px;white-space:pre;line-height:1.4;' +
        'pointer-events:none;box-shadow:0 2px 8px rgba(0,0,0,0.4);';
      document.body.appendChild(el);
    },
    { id: overlayId, text: lines.join('\n') }
  );

  await page.waitForTimeout(150);

  const filePath = await capturePhase(page, evidenceFolder, phaseName);

  await page.evaluate(
    (id) => {
      const el = document.getElementById(id);
      if (el) el.remove();
    },
    overlayId
  );

  return filePath;
};

export const saveRuntimeSnapshot = async (
  request: APIRequestContext,
  workflowId: string,
  evidenceFolder: string,
  phaseName: string
): Promise<void> => {
  const runtimeRes = await request
    .get(`http://localhost:8000/runtime/inspect/${workflowId}`)
    .catch(() => null);
  const projectionRes = await request
    .get(`http://localhost:8000/projection/${workflowId}`)
    .catch(() => null);

  const runtimeData = runtimeRes?.ok ? await runtimeRes.json() : null;
  const projectionData = projectionRes?.ok ? await projectionRes.json() : null;

  fs.writeFileSync(
    path.join(evidenceFolder, `runtime_snapshot_${phaseName}.json`),
    JSON.stringify(runtimeData, null, 2)
  );
  fs.writeFileSync(
    path.join(evidenceFolder, `projection_snapshot_${phaseName}.json`),
    JSON.stringify(projectionData, null, 2)
  );
};

export const captureFrontendConsole = (
  page: Page,
  evidenceFolder: string
): void => {
  const logPath = path.join(evidenceFolder, 'frontend-console.log');
  const stream = fs.createWriteStream(logPath, { flags: 'a' });

  page.on('console', (msg) => {
    const line = `[${msg.type()}] ${msg.text()}\n`;
    stream.write(line);
  });

  page.on('pageerror', (error) => {
    const line = `[pageerror] ${error.message}\n`;
    stream.write(line);
  });
};

export const recordTimeline = (
  evidenceFolder: string,
  entry: TimelineEntry
): void => {
  const timelinePath = path.join(evidenceFolder, 'replay_timeline.json');
  let timeline: TimelineEntry[] = [];
  if (fs.existsSync(timelinePath)) {
    try {
      timeline = JSON.parse(fs.readFileSync(timelinePath, 'utf-8'));
    } catch {
      timeline = [];
    }
  }
  timeline.push(entry);
  fs.writeFileSync(timelinePath, JSON.stringify(timeline, null, 2));
};

export const writeMetadata = (
  evidenceFolder: string,
  metadata: EvidenceMetadata
): void => {
  const metaPath = path.join(evidenceFolder, 'metadata.json');
  fs.writeFileSync(metaPath, JSON.stringify(metadata, null, 2));
};

export const captureTaskHub = async (
  page: Page,
  evidenceFolder: string,
  phaseName: string,
  metadata: { workflow_id?: string; timestamp?: string }
): Promise<string | null> => {
  try {
    const hubBtn = page.getByRole('button', { name: /Task Hub/i });
    if (!(await hubBtn.isVisible().catch(() => false))) return null;
    await hubBtn.click();
    await page.waitForTimeout(300);
    const filePath = await capturePhaseWithOverlay(page, evidenceFolder, `taskhub_${phaseName}`, metadata);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(150);
    return filePath;
  } catch {
    return null;
  }
};

/**
 * RECONNECT OWNERSHIP FORENSIC DEBUGGER
 *
 * FORENSIC CAPTURE ONLY — NO FIXES.
 * Captures exact runtime divergence between:
 *   FLOW_A: Normal Chat-initiated workflow (controls expected ENABLED)
 *   FLOW_B: Reload + Task Hub reattach (controls reportedly DISABLED)
 *
 * Output: comparison table + DOM inspection + full audit dumps.
 */

import { test, type Page } from '@playwright/test';
import {
  clearActiveWorkflows,
  getInitialRegistryIds,
  getForegroundWorkflowId,
} from './test-helpers';

// ── Backend lifecycle poll ─────────────────────────────────────────────────

async function waitForLifecycle(
  request: any,
  workflowId: string,
  target: string,
  timeoutMs = 120000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await request.get(`http://localhost:8000/runtime/inspect/${workflowId}`);
      if (res.ok()) {
        const data = await res.json();
        if (data.lifecycle_status === target) return;
      }
    } catch { /* retry */ }
    await new Promise(r => setTimeout(r, 1000));
  }
  throw new Error(`Timeout: lifecycle did not reach ${target} for ${workflowId}`);
}

// ── Console capture via addInitScript + exposeFunction ────────────────────

async function setupForensicCapture(page: Page) {
  const logs: Array<{ tag: string; data: any; ts: number }> = [];

  await page.exposeFunction('__forensicLog', (tag: string, data: any) => {
    logs.push({ tag, data, ts: Date.now() });
  });

  await page.addInitScript(() => {
    // ── Console log capture ──
    const orig = console.log.bind(console);
    console.log = (...args: any[]) => {
      orig(...args);
      const tag = typeof args[0] === 'string' ? args[0] : '';
      if (
        tag === '[CONTROL_RUNTIME_AUDIT]' ||
        tag === '[CONTROL_SOURCE_AUDIT]' ||
        tag === '[GUI:PROJECTION_HYDRATION_COMMIT]' ||
        tag === '[GUI:HYDRATION_TRACE_SELECTION]' ||
        tag === '[GUI:TASK_HUB_SELECT]' ||
        tag === '[GUI:OVERLAY_SCAN]' ||
        tag === '[GUI:PAUSE_HITBOX]' ||
        tag === '[GUI:CLICK_INTERCEPT]'
      ) {
        (window as any).__forensicLog(tag, args[1] ?? null);
      }
    };

    // ── Global click interceptor (capture phase) ──
    // Runs BEFORE any click handler — captures what element is physically at
    // the click point regardless of React's synthetic event handling.
    document.addEventListener('mousedown', (e: MouseEvent) => {
      const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
      const s = el ? window.getComputedStyle(el) : null;
      (window as any).__forensicLog('[CLICK_HIT]', {
        x: e.clientX,
        y: e.clientY,
        targetTag: (e.target as HTMLElement)?.tagName,
        targetClass: (e.target as HTMLElement)?.className?.toString().slice(0, 120),
        hitTag: el?.tagName ?? null,
        hitClass: el?.className?.toString().slice(0, 120) ?? null,
        hitText: el?.textContent?.trim().slice(0, 60) ?? null,
        hitPos: s?.position ?? null,
        hitZ: s?.zIndex ?? null,
        hitPE: s?.pointerEvents ?? null,
        ts: Date.now(),
      });
    }, { capture: true });
  });

  return logs;
}

// ── DOM button state capture ───────────────────────────────────────────────

async function captureDom(page: Page) {
  return page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button'));

    // Per-button state + elementFromPoint hit-test
    const find = (text: string) => {
      const b = btns.find(x => (x.textContent ?? '').trim().includes(text));
      if (!b) return { exists: false, disabled: null, classes: '', cursor: '', hitTest: null };
      const s = window.getComputedStyle(b);
      const rect = b.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const top = document.elementFromPoint(cx, cy) as HTMLElement | null;
      return {
        exists: true,
        disabled: b.disabled,
        classes: b.className,
        cursor: s.cursor,
        opacity: s.opacity,
        pointerEvents: s.pointerEvents,
        rect: { left: Math.round(rect.left), top: Math.round(rect.top), w: Math.round(rect.width), h: Math.round(rect.height) },
        hitTest: {
          isButton: top === b,
          topTag: top?.tagName ?? null,
          topClass: top?.className?.toString().slice(0, 120) ?? null,
          topText: top?.textContent?.trim().slice(0, 60) ?? null,
          topPosition: top ? window.getComputedStyle(top).position : null,
          topZIndex: top ? window.getComputedStyle(top).zIndex : null,
          topPointerEvents: top ? window.getComputedStyle(top).pointerEvents : null,
        },
      };
    };

    // Full overlay scan: every visible fixed/absolute element
    const overlayEls = Array.from(document.querySelectorAll('*'))
      .filter(el => {
        const s = window.getComputedStyle(el as HTMLElement);
        if (s.display === 'none' || s.visibility === 'hidden') return false;
        if (parseFloat(s.opacity) <= 0) return false;
        return s.position === 'fixed' || s.position === 'absolute';
      })
      .map(el => {
        const s = window.getComputedStyle(el as HTMLElement);
        const r = (el as HTMLElement).getBoundingClientRect();
        return {
          tag: el.tagName,
          cls: (el as HTMLElement).className?.toString().slice(0, 100),
          pos: s.position,
          z: s.zIndex,
          pe: s.pointerEvents,
          op: s.opacity,
          rect: { l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right), b: Math.round(r.bottom) },
          fullscreen: r.left <= 2 && r.top <= 2 && r.right >= window.innerWidth - 2 && r.bottom >= window.innerHeight - 2,
        };
      });

    // Stacking context ancestors of .control-panel
    const controlPanel = document.querySelector('.control-panel');
    const stackingCtx: any[] = [];
    let node: Element | null = controlPanel?.parentElement ?? null;
    while (node && node !== document.documentElement) {
      const s = window.getComputedStyle(node as HTMLElement);
      const creates =
        s.transform !== 'none' ||
        s.filter !== 'none' ||
        s.perspective !== 'none' ||
        (s.position !== 'static' && s.zIndex !== 'auto') ||
        parseFloat(s.opacity) < 1 ||
        (s as any).willChange !== 'auto';
      if (creates) {
        stackingCtx.push({
          tag: node.tagName,
          cls: (node as HTMLElement).className?.toString().slice(0, 60),
          pos: s.position,
          z: s.zIndex,
          transform: s.transform !== 'none' ? s.transform.slice(0, 40) : null,
          filter: s.filter !== 'none' ? s.filter : null,
          op: s.opacity,
        });
      }
      node = node.parentElement;
    }

    return {
      pause: find('Pause'),
      resume: find('Resume'),
      cancel: find('Cancel Workflow'),
      controlPanelVisible: !!document.querySelector('.control-panel'),
      studioVisible: !!document.querySelector('.workflow-projection-panel'),
      taskHubModalOpen: !!document.querySelector('.task-hub-modal-backdrop'),
      isSwitchingOverlay: !!document.querySelector('.task-hub-switching-overlay'),
      overlayEls,
      stackingCtx,
    };
  });
}

// ── Two-click Task Hub attach ──────────────────────────────────────────────

async function attachViaTaskHub(page: Page, workflowId: string): Promise<void> {
  // Open hub
  const hubBtn = page.locator('.task-hub-access-btn');
  await hubBtn.waitFor({ state: 'visible', timeout: 15000 });
  await hubBtn.click();

  // Modal appears
  await page.locator('.task-hub-modal').waitFor({ state: 'visible', timeout: 10000 });

  // Click workflow item (first click = select → shows "Attach Workflow" button)
  const idSuffix = workflowId.slice(-8);
  const item = page.locator(`.task-hub-item`).filter({ hasText: idSuffix });
  await item.waitFor({ state: 'visible', timeout: 10000 });
  await item.click();

  // Second click = actual attach (calls handleWorkflowSelect)
  const attachBtn = page.locator('.task-hub-attach-btn');
  await attachBtn.waitFor({ state: 'visible', timeout: 5000 });
  await attachBtn.click();

  // Wait for WorkflowManager 800ms close timeout + React render
  await page.waitForTimeout(2000);
}

// ═══════════════════════════════════════════════════════════════════════════
// FORENSIC TEST
// ═══════════════════════════════════════════════════════════════════════════

test.describe('FORENSIC: Reconnect Control Ownership Divergence', () => {
  test.beforeEach(async () => { await clearActiveWorkflows(); });
  test.afterEach(async () => { await clearActiveWorkflows(); });

  test('FLOW_A_vs_FLOW_B: capture runtime divergence', async ({ page, request }) => {
    test.setTimeout(600000);

    // Setup capture BEFORE any goto (addInitScript must precede navigation)
    const logs = await setupForensicCapture(page);

    // ── Helper: get last log entry by tag ──────────────────────────────
    const last = (tag: string) => {
      const entries = logs.filter(e => e.tag === tag);
      return entries.at(-1)?.data ?? {};
    };
    const snap = () => ({
      controlRuntime: last('[CONTROL_RUNTIME_AUDIT]'),
      controlSource: last('[CONTROL_SOURCE_AUDIT]'),
      hydrationCommit: last('[GUI:PROJECTION_HYDRATION_COMMIT]'),
      traceSelection: last('[GUI:HYDRATION_TRACE_SELECTION]'),
      taskHubSelect: last('[GUI:TASK_HUB_SELECT]'),
    });

    // ══════════════════════════════════════════════════════════════════
    // FLOW_A: Normal Chat-initiated workflow
    // ══════════════════════════════════════════════════════════════════

    await page.goto('http://localhost:5173/');
    await page.waitForLoadState('domcontentloaded');

    // Wait for Chat panel to be ready
    const textarea = page.getByPlaceholder('Enter instruction…');
    await textarea.waitFor({ state: 'visible', timeout: 15000 });

    // Capture registry snapshot before submit
    const preIds = await getInitialRegistryIds();

    // Submit via Chat UI (normal execution path)
    await textarea.fill('Add 100 and 200.\nMultiply by 3.\nSubtract 50.');
    await page.getByRole('button', { name: 'Send →' }).click();

    // Discover workflow ID from runtime registry
    const workflowId = await getForegroundWorkflowId(preIds, 300000);
    if (!workflowId) throw new Error('FLOW_A: workflowId not resolved');

    // Wait for backend ACTIVE
    await waitForLifecycle(request, workflowId, 'ACTIVE', 120000);

    // Wait for Pause to become enabled (normal path should work)
    // Use soft wait — capture regardless of outcome
    await page.getByRole('button', { name: 'Pause' })
      .waitFor({ state: 'visible', timeout: 10000 })
      .catch(() => { });
    await page.waitForTimeout(1500);

    const snapA = snap();
    const domA = await captureDom(page);
    const allLogsA = [...logs];

    // ══════════════════════════════════════════════════════════════════
    // FLOW_B: Reload + Task Hub reattach
    // ══════════════════════════════════════════════════════════════════

    // Clear captured logs for Flow B
    logs.length = 0;

    await page.reload();
    await page.waitForLoadState('domcontentloaded');

    // Confirm backend still ACTIVE
    await waitForLifecycle(request, workflowId, 'ACTIVE', 30000);

    // Attach via Task Hub (TWO-CLICK sequence)
    await attachViaTaskHub(page, workflowId);

    // Extra settle time for stream poll + React render
    await page.waitForTimeout(2000);

    const snapB = snap();
    const domB = await captureDom(page);
    const allLogsB = [...logs];

    // ══════════════════════════════════════════════════════════════════
    // OUTPUT: FORENSIC COMPARISON REPORT
    // ══════════════════════════════════════════════════════════════════

    const sep = '═'.repeat(80);
    const row = (name: string, a: any, b: any) => {
      const as = JSON.stringify(a) ?? 'undefined';
      const bs = JSON.stringify(b) ?? 'undefined';
      const flag = as !== bs ? '  ← DIVERGED' : '';
      console.log(`  ${name.padEnd(42)} │ ${String(as).padEnd(18)} │ ${String(bs).padEnd(18)} │${flag}`);
    };

    console.log(`\n${sep}`);
    console.log('  FORENSIC CAPTURE: RECONNECT OWNERSHIP DIVERGENCE REPORT');
    console.log(`  workflowId: ${workflowId}`);
    console.log(sep);

    console.log('\n  ── CONTROL LEGALITY TABLE ──');
    console.log(`  ${'Variable'.padEnd(42)} │ ${'FLOW_A (Chat)'.padEnd(18)} │ ${'FLOW_B (Reattach)'.padEnd(18)} │`);
    console.log(`  ${'-'.repeat(42)}-+-${'-'.repeat(18)}-+-${'-'.repeat(18)}-+`);

    const rA = snapA.controlRuntime;
    const rB = snapB.controlRuntime;
    const sA = snapA.controlSource;
    const sB = snapB.controlSource;
    const hA = snapA.hydrationCommit;
    const hB = snapB.hydrationCommit;

    row('workflowId (ControlPanel)', rA.workflowId, rB.workflowId);
    row('status (prop value)', rA.status, rB.status);
    row('statusValue (JSON.stringify)', rA.statusValue, rB.statusValue);
    row('statusType', rA.statusType, rB.statusType);
    row('statusIsNull', rA.statusIsNull, rB.statusIsNull);
    row('statusIsUndefined', rA.statusIsUndefined, rB.statusIsUndefined);
    row('canPause', rA.canPause, rB.canPause);
    row('canResume', rA.canResume, rB.canResume);
    row('showCancel', rA.showCancel, rB.showCancel);
    row('activeWorkflowId (source)', sA.activeWorkflowId, sB.activeWorkflowId);
    row('focusedProjection.lifecycle_status', sA.focusedProjectionLifecycle, sB.focusedProjectionLifecycle);
    row('lastResult.status', sA.lastResultStatus, sB.lastResultStatus);
    row('resolvedStatus (expression result)', sA.resolvedStatus, sB.resolvedStatus);
    row('hydration.lifecycleStatus', hA.lifecycleStatus, hB.lifecycleStatus);
    row('hydration.projectedStatus', hA.projectedStatus, hB.projectedStatus);
    row('selection.bgId', snapA.traceSelection?.bgId, snapB.traceSelection?.bgId);
    row('selection.hasBgId', snapA.traceSelection?.hasBgId, snapB.traceSelection?.hasBgId);

    console.log('\n  ── DOM BUTTON STATE ──');
    console.log(`  ${'Button'.padEnd(10)} │ ${'exists_A'.padEnd(8)} │ ${'dis_A'.padEnd(6)} │ ${'exists_B'.padEnd(8)} │ ${'dis_B'.padEnd(6)} │ flag`);
    console.log(`  ${'-'.repeat(10)}-+-${'-'.repeat(8)}-+-${'-'.repeat(6)}-+-${'-'.repeat(8)}-+-${'-'.repeat(6)}-+-----`);
    for (const btn of ['pause', 'resume', 'cancel'] as const) {
      const a = (domA as any)[btn];
      const b = (domB as any)[btn];
      const flag = JSON.stringify(a?.disabled) !== JSON.stringify(b?.disabled) ? '← DIVERGED' : '';
      console.log(`  ${btn.padEnd(10)} │ ${String(a?.exists).padEnd(8)} │ ${String(a?.disabled).padEnd(6)} │ ${String(b?.exists).padEnd(8)} │ ${String(b?.disabled).padEnd(6)} │ ${flag}`);
    }

    console.log('\n  ── HIT-TEST (elementFromPoint at button center) — FLOW_B ──');
    console.log(`  ${'Button'.padEnd(10)} │ ${'isButton?'.padEnd(9)} │ ${'topTag'.padEnd(8)} │ ${'topClass'.padEnd(40)} │ ${'topZ'.padEnd(6)} │ topPE`);
    console.log(`  ${'-'.repeat(10)}-+-${'-'.repeat(9)}-+-${'-'.repeat(8)}-+-${'-'.repeat(40)}-+-${'-'.repeat(6)}-+-------`);
    for (const btn of ['pause', 'resume', 'cancel'] as const) {
      const b = (domB as any)[btn];
      const ht = b?.hitTest ?? {};
      const intercepted = ht.isButton === false ? ' ← INTERCEPTED' : '';
      console.log(`  ${btn.padEnd(10)} │ ${String(ht.isButton).padEnd(9)} │ ${String(ht.topTag ?? 'N/A').padEnd(8)} │ ${String(ht.topClass ?? '').padEnd(40)} │ ${String(ht.topZIndex ?? '').padEnd(6)} │ ${ht.topPointerEvents ?? ''}${intercepted}`);
    }

    console.log('\n  ── ACTIVE OVERLAYS (fixed/absolute, visible) — FLOW_B ──');
    const overlaysB = (domB as any).overlayEls ?? [];
    if (overlaysB.length === 0) {
      console.log('  (none)');
    } else {
      overlaysB.forEach((o: any) => {
        const fullscreenFlag = o.fullscreen ? ' ← FULLSCREEN' : '';
        console.log(`  ${o.pos} z:${o.z.padEnd(6)} pe:${o.pe.padEnd(6)} op:${o.op} [${o.rect.l},${o.rect.t}→${o.rect.r},${o.rect.b}] ${o.cls}${fullscreenFlag}`);
      });
    }

    console.log('\n  ── STACKING CTX ANCESTORS of .control-panel — FLOW_B ──');
    const ctxB = (domB as any).stackingCtx ?? [];
    if (ctxB.length === 0) {
      console.log('  (none — clean stacking context)');
    } else {
      ctxB.forEach((c: any) => {
        console.log(`  ${c.tag}.${c.cls} pos:${c.pos} z:${c.z} transform:${c.transform ?? '-'} filter:${c.filter ?? '-'}`);
      });
    }

    console.log(`\n  taskHubModalOpen (B): ${(domB as any).taskHubModalOpen}`);
    console.log(`  isSwitchingOverlay (B): ${(domB as any).isSwitchingOverlay}`);

    console.log('\n  ── [GUI:OVERLAY_SCAN] from App.jsx instrumentation (FLOW_A) ──');
    const overlayScanA = allLogsA.filter(e => e.tag === '[GUI:OVERLAY_SCAN]').at(-1)?.data;
    if (overlayScanA) {
      console.log(`  totalFixed: ${overlayScanA.totalFixed}, fullscreenBlockers: ${overlayScanA.fullscreenBlockers}`);
    } else {
      console.log('  (not captured)');
    }
    const hitboxA = allLogsA.filter(e => e.tag === '[GUI:PAUSE_HITBOX]').at(-1)?.data;
    console.log(`  [GUI:PAUSE_HITBOX] FLOW_A: hitIsButton=${hitboxA?.hitIsButton ?? 'N/A'} topTag=${hitboxA?.topTag ?? 'N/A'}`);

    console.log('\n  ── [GUI:OVERLAY_SCAN] from App.jsx instrumentation (FLOW_B) ──');
    const overlayScanB = allLogsB.filter(e => e.tag === '[GUI:OVERLAY_SCAN]').at(-1)?.data;
    if (overlayScanB) {
      console.log(`  totalFixed: ${overlayScanB.totalFixed}, fullscreenBlockers: ${overlayScanB.fullscreenBlockers}`);
      (overlayScanB.blockers ?? []).forEach((b: any) => console.log(`  BLOCKER: ${JSON.stringify(b)}`));
      console.log(`  allFixed: ${JSON.stringify(overlayScanB.allFixed)}`);
    } else {
      console.log('  (not captured — activeWorkflowId may not have been set in FLOW_B)');
    }

    console.log('\n  ── [GUI:PAUSE_HITBOX] from App.jsx instrumentation (FLOW_B) ──');
    const hitboxB = allLogsB.filter(e => e.tag === '[GUI:PAUSE_HITBOX]').at(-1)?.data;
    if (hitboxB) {
      console.log(`  hitIsButton: ${hitboxB.hitIsButton}  topTag: ${hitboxB.topTag}  topClass: ${hitboxB.topClass}`);
      console.log(`  topZ: ${hitboxB.topZ}  topPE: ${hitboxB.topPE}`);
      if (hitboxB.hitIsButton === false) console.log('  *** INTERCEPTION CONFIRMED — something is blocking the Pause button ***');
    } else {
      console.log('  (not captured)');
    }

    console.log('\n  ── CLICK INTERCEPT LOG (FLOW_B) — both sources ──');
    const clicksB = allLogsB.filter(e => e.tag === '[CLICK_HIT]' || e.tag === '[GUI:CLICK_INTERCEPT]');
    if (clicksB.length === 0) {
      console.log('  (no clicks during settle window — captures only Playwright click() interactions)');
    } else {
      clicksB.forEach((e, i) => console.log(`  [${e.tag} #${i}] hit:${e.data?.hitTag}.${String(e.data?.hitClass ?? '').slice(0, 60)} z:${e.data?.hitZ} pe:${e.data?.hitPE}`));
    }

    console.log('\n  ── FULL AUDIT DUMPS ──');
    console.log('  FLOW_A CONTROL_RUNTIME_AUDIT:', JSON.stringify(rA));
    console.log('  FLOW_A CONTROL_SOURCE_AUDIT:', JSON.stringify(sA));
    console.log('  FLOW_A HYDRATION_COMMIT:', JSON.stringify(hA));
    console.log('  FLOW_A DOM (buttons+overlays):', JSON.stringify({ pause: (domA as any).pause, resume: (domA as any).resume, cancel: (domA as any).cancel, taskHubModalOpen: (domA as any).taskHubModalOpen, overlayCount: ((domA as any).overlayEls ?? []).length }));
    console.log('');
    console.log('  FLOW_B CONTROL_RUNTIME_AUDIT:', JSON.stringify(rB));
    console.log('  FLOW_B CONTROL_SOURCE_AUDIT:', JSON.stringify(sB));
    console.log('  FLOW_B HYDRATION_COMMIT:', JSON.stringify(hB));
    console.log('  FLOW_B DOM (buttons+overlays):', JSON.stringify({ pause: (domB as any).pause, resume: (domB as any).resume, cancel: (domB as any).cancel, taskHubModalOpen: (domB as any).taskHubModalOpen, overlayCount: ((domB as any).overlayEls ?? []).length }));

    console.log('\n  ── ALL CAPTURED LOGS (FLOW_A) ──');
    allLogsA.forEach((e, i) => console.log(`  [A${i}] ${e.tag}: ${JSON.stringify(e.data)}`));

    console.log('\n  ── ALL CAPTURED LOGS (FLOW_B) ──');
    allLogsB.forEach((e, i) => console.log(`  [B${i}] ${e.tag}: ${JSON.stringify(e.data)}`));

    // ── Auto-classification ──────────────────────────────────────────
    console.log('\n  ── CLASSIFICATION ──');
    const divergences: string[] = [];
    if (JSON.stringify(rA.canPause) !== JSON.stringify(rB.canPause)) divergences.push('canPause');
    if (JSON.stringify(rA.showCancel) !== JSON.stringify(rB.showCancel)) divergences.push('showCancel');
    if (JSON.stringify(sA.resolvedStatus) !== JSON.stringify(sB.resolvedStatus)) divergences.push('resolvedStatus');
    if (JSON.stringify(sA.lastResultStatus) !== JSON.stringify(sB.lastResultStatus)) divergences.push('lastResultStatus');
    if (JSON.stringify(sA.focusedProjectionLifecycle) !== JSON.stringify(sB.focusedProjectionLifecycle)) divergences.push('focusedProjection.lifecycle_status');

    console.log(`  DIVERGENCES DETECTED: ${divergences.join(', ') || 'NONE'}`);

    // ── Physical interception signals ──
    const pauseHitB = (domB as any).pause?.hitTest;
    const hitIntercepted = pauseHitB?.isButton === false;
    const fullscreenBlocker = ((domB as any).overlayEls ?? []).some((o: any) => o.fullscreen && o.pe !== 'none');
    const modalStuck = (domB as any).taskHubModalOpen === true;
    const switchingStuck = (domB as any).isSwitchingOverlay === true;
    const hasStackingCtxIssue = ((domB as any).stackingCtx ?? []).some((c: any) => c.filter || c.transform);
    const appScanIntercepted = hitboxB?.hitIsButton === false;

    if (modalStuck) {
      console.log('  CLASSIFICATION: E1 — task-hub-modal-backdrop STILL MOUNTED after reattach (800ms close timer may not have fired)');
      console.log(`    interceptor: .task-hub-modal-backdrop (position:fixed, z-index:1000, fullscreen)`);
    } else if (switchingStuck) {
      console.log('  CLASSIFICATION: E2 — task-hub-switching-overlay still visible inside modal body');
    } else if (hitIntercepted || appScanIntercepted) {
      const interceptor = pauseHitB ?? {};
      console.log(`  CLASSIFICATION: E3 — PHYSICAL INTERCEPTION CONFIRMED at Pause button coordinates`);
      console.log(`    interceptor: ${interceptor.topTag} .${interceptor.topClass} z:${interceptor.topZIndex} pe:${interceptor.topPointerEvents}`);
    } else if (fullscreenBlocker) {
      const blocker = ((domB as any).overlayEls ?? []).find((o: any) => o.fullscreen && o.pe !== 'none');
      console.log(`  CLASSIFICATION: E4 — fullscreen fixed overlay present with pointer-events:${blocker?.pe}`);
      console.log(`    element: ${JSON.stringify(blocker)}`);
    } else if (hasStackingCtxIssue) {
      console.log('  CLASSIFICATION: E5 — stacking context ancestor has transform/filter (may trap fixed backdrop in wrong z-index layer)');
    } else if (!rB.workflowId) {
      console.log('  CLASSIFICATION: B — activeWorkflowId lost (workflowId null in ControlPanel)');
    } else if (rB.statusIsNull || rB.statusIsUndefined) {
      console.log('  CLASSIFICATION: C — operational state missing (status null/undefined after reattach)');
    } else if (!sB.focusedProjectionLifecycle && sB.lastResultStatus === 'ACTIVE') {
      console.log('  CLASSIFICATION: A — projection ownership only (focusedProjection null, lastResult OK)');
    } else if (divergences.length === 0) {
      console.log('  CLASSIFICATION: E0 — state identical, overlay scan clean — may be Tauri WebView2-specific rendering issue');
      console.log('  ACTION: Open Tauri DevTools (right-click → Inspect) and reproduce the bug; check [GUI:OVERLAY_SCAN] and [GUI:CLICK_INTERCEPT] logs live');
    } else {
      console.log('  CLASSIFICATION: F — multiple state divergences:', divergences.join(', '));
    }

    console.log(`\n${sep}\n`);
  });
});

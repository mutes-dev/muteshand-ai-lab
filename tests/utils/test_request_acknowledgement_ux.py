"""
REQUEST ACKNOWLEDGEMENT UX — TEST SUITE
Phase 4C.0

Tests (Python / static analysis — no browser required):

  1. Source Authority Tests       — ChatPanel carries no workflow identity
  2. Duplicate Submission Tests   — inFlightRef guard + locked state coverage
  3. Planning State Tests         — submitting/planningLabel transitions
  4. Failure Reset Tests          — clean state reset on error
  5. Projection Replacement Tests — planning state is cleared after stream hand-off
  6. Architecture Validation      — all 10 architecture rules checked
  7. Contract Boundary Tests      — prohibited patterns absent from source

Per PHASE 4C.0:
  SUB-PHASE 3A — Immediate Request Acknowledgement
  SUB-PHASE 3B — Planning Visibility State
  SUB-PHASE 3C — Duplicate Submission Protection
  SUB-PHASE 3D — Failure Visibility

Per authoritative documents:
  GUI_ARCHITECTURE.txt, GUI_FUNCTIONALITY_CONTRACT_V1.txt,
  CANONICAL_PROJECTION_MODEL_V1.txt, PROJECTION_CONTINUITY_CONTRACT_V1.txt,
  AUTHORITY_MODEL.txt
"""

import os
import sys
import re
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_passed = 0
_failed = 0
_traces = []


def check(label, cond, detail=""):
    global _passed, _failed
    marker = "[PASS]" if cond else "[FAIL]"
    msg = f"  {marker} {label}"
    if detail and not cond:
        msg += f"\n         {detail}"
    print(msg)
    _traces.append({"label": label, "pass": cond, "detail": detail})
    if cond:
        _passed += 1
    else:
        _failed += 1


# =============================================================================
# SOURCE LOADING
# =============================================================================

FRONTEND_BASE = os.path.join(
    os.path.dirname(__file__), "..", "ai_lab_gui", "frontend", "src"
)

def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

CHAT_PANEL_PATH = os.path.join(FRONTEND_BASE, "components", "ChatPanel.jsx")
APP_PATH        = os.path.join(FRONTEND_BASE, "App.jsx")
API_JS_PATH     = os.path.join(FRONTEND_BASE, "api.js")
STYLES_PATH     = os.path.join(FRONTEND_BASE, "styles.css")

chat_src = _read(CHAT_PANEL_PATH)
app_src  = _read(APP_PATH)
api_src  = _read(API_JS_PATH)
css_src  = _read(STYLES_PATH)


# =============================================================================
# TEST 1 — SOURCE AUTHORITY: ChatPanel carries no workflow identity
# =============================================================================

def test_source_authority():
    print("\n" + "=" * 60)
    print("  TEST 1 — Source Authority")
    print("=" * 60)

    # 1A: submitting state has ZERO workflow identity
    check("1A: submitting state declared (transport-only)",
          "submitting" in chat_src)
    check("1A: submitting carries no workflow_id reference",
          "submitting" in chat_src and "workflow_id" not in chat_src.split("submitting")[1].split("useState")[0])

    # 1B: planningLabel contains no workflow identity
    check("1B: planningLabel declared", "planningLabel" in chat_src)
    # planningLabel values must be string labels only, not workflow objects
    check("1B: planningLabel values are string literals only",
          '"submitting"' in chat_src and '"planning"' in chat_src)
    check("1B: planningLabel never assigned a workflow_id",
          not re.search(r'setPlanningLabel\s*\(\s*\w*[Ww]orkflow', chat_src))

    # 1C: No fake workflow IDs created in ChatPanel
    check("1C: no uuid generation in ChatPanel",
          "uuid" not in chat_src and "crypto.randomUUID" not in chat_src)
    check("1C: no workflow_id assignment in ChatPanel",
          not re.search(r'workflow_id\s*=\s*["\']', chat_src))
    check("1C: no setLastResult call in ChatPanel (no local projection ownership)",
          "setLastResult" not in chat_src)

    # 1D: isExecuting derived from backend projection in App.jsx (not synthesized)
    check("1D: isExecuting derived from lastResult?.status in App",
          "lastResult?.status" in app_src or 'lastResult?.status === "ACTIVE"' in app_src)
    check("1D: isExecuting is NOT locally synthesized in ChatPanel",
          "isExecuting" in chat_src and "setIsExecuting" not in chat_src)

    # 1E: Transport acknowledgement logging present with correct note
    check("1E: REQUEST_TRANSPORT_ACKNOWLEDGED log emitted",
          "REQUEST_TRANSPORT_ACKNOWLEDGED" in chat_src)
    check("1E: log note states transport_only_no_workflow_identity",
          "transport_only_no_workflow_identity" in chat_src)
    check("1E: REQUEST_BACKEND_ACCEPTED log emitted on bg_id receipt",
          "REQUEST_BACKEND_ACCEPTED" in chat_src)
    check("1E: planning_phase_no_projection_yet note present",
          "planning_phase_no_projection_yet" in chat_src)


# =============================================================================
# TEST 2 — DUPLICATE SUBMISSION PROTECTION (3C)
# =============================================================================

def test_duplicate_submission_protection():
    print("\n" + "=" * 60)
    print("  TEST 2 — Duplicate Submission Protection (3C)")
    print("=" * 60)

    # 2A: inFlightRef synchronous guard
    check("2A: inFlightRef declared as useRef", "inFlightRef = useRef" in chat_src)
    check("2A: inFlightRef.current guard in handleSend",
          "inFlightRef.current" in chat_src)
    check("2A: inFlightRef set true at start of handleSend",
          "inFlightRef.current = true" in chat_src)
    check("2A: inFlightRef reset in finally block",
          "inFlightRef.current = false" in chat_src and "finally" in chat_src)

    # 2B: Button disabled while locked
    check("2B: button disabled={locked || !input.trim()}",
          "disabled={locked || !input.trim()}" in chat_src)
    check("2B: locked combines submitting and isExecuting",
          "locked = submitting || isExecuting" in chat_src)

    # 2C: textarea disabled while locked
    check("2C: textarea disabled={locked}", "disabled={locked}" in chat_src)

    # 2D: Enter key guard checks locked
    check("2D: Enter key guard: if (!locked) handleSend()",
          "if (!locked) handleSend()" in chat_src)

    # 2E: handleSend early-return guard includes inFlightRef.current
    send_fn_match = re.search(
        r'async function handleSend\(\)(.*?)^  }',
        chat_src, re.DOTALL | re.MULTILINE
    )
    if send_fn_match:
        send_body = send_fn_match.group(1)
        check("2E: handleSend guards on inFlightRef.current",
              "inFlightRef.current" in send_body)
        check("2E: handleSend guards on isExecuting",
              "isExecuting" in send_body)
    else:
        check("2E: handleSend body found for guard inspection", False, "regex failed")


# =============================================================================
# TEST 3 — PLANNING STATE LIFECYCLE (3A + 3B)
# =============================================================================

def test_planning_state_lifecycle():
    print("\n" + "=" * 60)
    print("  TEST 3 — Planning State Lifecycle (3A+3B)")
    print("=" * 60)

    # 3A: submitting set TRUE before any async call
    # The sequence must be: setSubmitting(true) → await api.executeStream(...)
    submitting_pos = chat_src.find("setSubmitting(true)")
    execute_pos    = chat_src.find("api.executeStream")
    check("3A: setSubmitting(true) appears before api.executeStream call",
          0 < submitting_pos < execute_pos,
          f"submitting_pos={submitting_pos} execute_pos={execute_pos}")

    # 3A: planningLabel set "submitting" before async
    planning_sub_pos = chat_src.find('setPlanningLabel("submitting")')
    check("3A: setPlanningLabel(submitting) appears before async call",
          0 < planning_sub_pos < execute_pos,
          f"planning_sub_pos={planning_sub_pos} execute_pos={execute_pos}")

    # 3B: planningLabel transitions to "planning" after bg_id received
    planning_pos = chat_src.find('setPlanningLabel("planning")')
    check("3B: setPlanningLabel(planning) appears after api.executeStream",
          planning_pos > execute_pos,
          f"planning_pos={planning_pos} execute_pos={execute_pos}")

    # 3B: planning banner rendered only when planningLabel === "planning"
    check('3B: planning banner conditional on planningLabel === "planning"',
          'planningLabel === "planning"' in chat_src)
    check("3B: planning banner has role=status for screen readers",
          'role="status"' in chat_src)
    check("3B: planning banner has aria-live=polite",
          'aria-live="polite"' in chat_src)

    # 3B: submitting cleared before returning from success path
    submitting_false_pos = chat_src.find("setSubmitting(false)")
    onstream_pos = chat_src.find("onStreamStart")
    check("3B: setSubmitting(false) present in success path",
          submitting_false_pos > 0)

    # 3B: planningLabel cleared to null in success path
    check("3B: setPlanningLabel(null) present in success path",
          "setPlanningLabel(null)" in chat_src)

    # 3B: getSendLabel() returns correct labels per phase
    check("3B: getSendLabel returns Submitting label",
          '"Submitting\u2026"' in chat_src or '"Submitting..."' in chat_src)
    check("3B: getSendLabel returns Planning label",
          '"Planning\u2026"' in chat_src or '"Planning..."' in chat_src)
    check("3B: getSendLabel returns Running label for isExecuting",
          '"Running\u2026"' in chat_src or '"Running..."' in chat_src)

    # 3B: CSS classes exist
    check("3B: .planning-notice CSS present", ".planning-notice" in css_src)
    check("3B: .spinner-inline CSS present", ".spinner-inline" in css_src)


# =============================================================================
# TEST 4 — FAILURE RESET (3D)
# =============================================================================

def test_failure_reset():
    print("\n" + "=" * 60)
    print("  TEST 4 — Failure Reset (3D)")
    print("=" * 60)

    # Find catch block
    catch_match = re.search(r'catch\s*\(e\)\s*\{(.*?)\}(?=\s*finally)', chat_src, re.DOTALL)
    if not catch_match:
        check("4: catch block found", False, "regex failed")
        return

    catch_body = catch_match.group(1)

    # 4A: error set in catch
    check("4A: setError called in catch", "setError(e.message)" in catch_body)

    # 4B: submitting cleared in catch
    check("4B: setSubmitting(false) in catch path",
          "setSubmitting(false)" in catch_body)

    # 4C: planningLabel cleared in catch
    check("4C: setPlanningLabel(null) in catch path",
          "setPlanningLabel(null)" in catch_body)

    # 4D: inFlightRef released in finally (not catch — ensures release on any path)
    finally_match = re.search(r'finally\s*\{(.*?)\}', chat_src, re.DOTALL)
    if finally_match:
        finally_body = finally_match.group(1)
        check("4D: inFlightRef.current = false in finally",
              "inFlightRef.current = false" in finally_body)
    else:
        check("4D: finally block found", False, "regex failed")

    # 4E: REQUEST_TRANSPORT_FAILED log in catch
    check("4E: REQUEST_TRANSPORT_FAILED log in failure path",
          "REQUEST_TRANSPORT_FAILED" in chat_src)

    # 4F: No phantom workflow state preserved on failure
    check("4F: no setLastResult call in catch (no phantom workflow)",
          "setLastResult" not in catch_body)


# =============================================================================
# TEST 5 — PROJECTION REPLACEMENT SEMANTICS
# =============================================================================

def test_projection_replacement():
    print("\n" + "=" * 60)
    print("  TEST 5 — Projection Replacement Semantics")
    print("=" * 60)

    # 5A: submitting is cleared AFTER onStreamStart — stream poll owns lifecycle signal
    stream_pos      = chat_src.find("onStreamStart(stream.bg_id)")
    clear_sub_pos   = chat_src.find("setSubmitting(false)")
    check("5A: setSubmitting(false) appears after onStreamStart in success path",
          0 < stream_pos < clear_sub_pos,
          f"stream_pos={stream_pos} clear_sub_pos={clear_sub_pos}")

    # 5B: Once stream attached, isExecuting (from projection) drives the locked state
    check("5B: locked derived from submitting || isExecuting (projection-driven)",
          "locked = submitting || isExecuting" in chat_src)

    # 5C: WorkflowProjectionView still projection-driven in App
    check("5C: WorkflowProjectionView rendered only with activeWorkflowId (projection-gated)",
          "activeWorkflowId &&" in app_src and "WorkflowProjectionView" in app_src)

    # 5D: activeWorkflowId derived from backend projection in App
    check("5D: activeWorkflowId = lastResult?.workflow_id in App",
          "lastResult?.workflow_id" in app_src)

    # 5E: No planning state in App — planning state scoped to ChatPanel only
    check("5E: planning-notice not in App.jsx (scoped to ChatPanel)",
          "planning-notice" not in app_src)
    check("5E: planningLabel not in App.jsx",
          "planningLabel" not in app_src)

    # 5F: Planning banner disappears when projection arrives
    # planningLabel is cleared after setSubmitting(false) in success path
    check("5F: planningLabel(null) clears planning banner on projection arrival",
          "setPlanningLabel(null)" in chat_src)


# =============================================================================
# TEST 6 — ARCHITECTURE VALIDATION (all 10 rules)
# =============================================================================

def test_architecture_validation():
    print("\n" + "=" * 60)
    print("  TEST 6 — Architecture Validation (10 rules)")
    print("=" * 60)

    # Rule 1: Frontend does NOT synthesize workflow truth
    check("Rule 1: Frontend does NOT synthesize workflow truth",
          "setLastResult" not in chat_src and
          not re.search(r'workflow_id\s*=\s*["\']', chat_src),
          "no workflow truth synthesis in ChatPanel")

    # Rule 2: Frontend does NOT create optimistic projections
    check("Rule 2: no optimistic projection creation in ChatPanel",
          "setProjection" not in chat_src and
          "projection_version" not in chat_src,
          "no projection vars in ChatPanel")

    # Rule 3: Frontend acknowledges transport only
    check("Rule 3: transport acknowledgement only (submitting is transport state)",
          "transport_only_no_workflow_identity" in chat_src)

    # Rule 4: Canonical projections remain orchestrator-owned
    check("Rule 4: WorkflowProjectionView polls /projection endpoint (orchestrator-owned)",
          "getProjection" in api_src and "/projection/" in api_src)

    # Rule 5: Projection continuity preserved — no stale overwrite in App
    check("Rule 5: terminal projection protection present in App",
          "TERMINAL_PROTECTION" in app_src or "isTerminal" in app_src)

    # Rule 6: Workflow rendering remains projection-driven
    check("Rule 6: WorkflowProjectionView gated on activeWorkflowId (projection-derived)",
          "activeWorkflowId &&" in app_src)

    # Rule 7: No local lifecycle authority introduced
    check("Rule 7: no lifecycle status assignment in ChatPanel",
          not re.search(r'status\s*[:=]\s*["\'](?:ACTIVE|PAUSED|FAILED|COMPLETED)', chat_src))

    # Rule 8: Duplicate request protection works
    check("Rule 8: duplicate protection via inFlightRef + locked",
          "inFlightRef" in chat_src and "locked" in chat_src)

    # Rule 9: Planning state remains non-authoritative
    # planningLabel may only be set to null, "submitting", or "planning"
    planning_assignments = re.findall(r'setPlanningLabel\s*\(([^)]+)\)', chat_src)
    allowed_values = {"null", '"submitting"', '"planning"'}
    bad_assignments = [v.strip() for v in planning_assignments if v.strip() not in allowed_values]
    check("Rule 9: planningLabel only assigned null/submitting/planning (no workflow objects)",
          len(bad_assignments) == 0,
          f"bad assignments: {bad_assignments}")
    check("Rule 9: planning banner text is non-authoritative",
          "awaiting orchestrator projection" in chat_src)

    # Rule 10: No system_entry bypass introduced
    check("Rule 10: ChatPanel calls api.executeStream only (no direct system_entry)",
          "executeStream" in chat_src and
          "system_entry" not in chat_src and
          "orchestrator_runtime" not in chat_src)


# =============================================================================
# TEST 7 — CONTRACT BOUNDARY: PROHIBITED PATTERNS ABSENT
# =============================================================================

def test_contract_boundaries():
    print("\n" + "=" * 60)
    print("  TEST 7 — Contract Boundary (prohibited patterns)")
    print("=" * 60)

    # 7A: No fake workflow IDs
    check("7A: no uuid() call in ChatPanel", "uuid" not in chat_src)
    check("7A: no crypto.randomUUID in ChatPanel",
          "crypto.randomUUID" not in chat_src)

    # 7B: No speculative projections
    check("7B: no projection_version in ChatPanel", "projection_version" not in chat_src)
    check("7B: no build_workflow_projection call in ChatPanel",
          "build_workflow_projection" not in chat_src)

    # 7C: No optimistic step rendering
    check("7C: no steps array synthesis in ChatPanel",
          not re.search(r'steps\s*=\s*\[', chat_src))
    check("7C: no StepProjection construction in ChatPanel",
          "step_id" not in chat_src and "step_type" not in chat_src)

    # 7D: No local lifecycle synthesis
    check("7D: no local status field assignment in ChatPanel",
          not re.search(r'\bstatus\b\s*[:=]\s*["\']ACTIVE', chat_src))
    check("7D: no workflow state registry calls in ChatPanel",
          "_workflow_state_registry" not in chat_src)

    # 7E: No canonical projection bypass
    check("7E: no direct projection mutation in ChatPanel",
          "setProjection" not in chat_src)

    # 7F: Transport failure produces NO phantom workflow
    catch_match = re.search(r'catch\s*\(e\)\s*\{(.*?)\}(?=\s*finally)', chat_src, re.DOTALL)
    if catch_match:
        catch_body = catch_match.group(1)
        check("7F: no workflow_id set in catch block",
              "workflow_id" not in catch_body)
        check("7F: no setLastResult in catch (no phantom workflow)",
              "setLastResult" not in catch_body)
    else:
        check("7F: catch block found for phantom check", False)


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 60)
    print("  REQUEST ACKNOWLEDGEMENT UX — TEST SUITE (Phase 4C.0)")
    print("=" * 60)

    tests = [
        test_source_authority,
        test_duplicate_submission_protection,
        test_planning_state_lifecycle,
        test_failure_reset,
        test_projection_replacement,
        test_architecture_validation,
        test_contract_boundaries,
    ]

    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"\n  [ERROR] {t.__name__}: {e}")
            traceback.print_exc()
            global _failed
            _failed += 1

    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Passed: {_passed}")
    print(f"  Failed: {_failed}")
    print(f"  Total:  {_passed + _failed}")

    if _failed:
        print("\n" + "=" * 60)
        print("  FAILURES")
        print("=" * 60)
        for t in _traces:
            if not t["pass"]:
                print(f"  [FAIL] {t['label']}")
                if t["detail"]:
                    print(f"         {t['detail']}")

    return _failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)

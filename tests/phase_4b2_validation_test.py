"""
Phase 4B.2 — Active Workflow Foundation Validation Tests

Validates:
1. Single active workflow context (activeWorkflowId in App.jsx)
2. Workflow context propagation to all panels
3. Background workflows are selectable
4. API includes workflow_id where required
5. HEADERS bug is fixed
"""

import re
import os
import sys

def read_file(path):
    """Read file content."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"  Error reading {path}: {e}")
        return None

def test_app_has_active_workflow_state():
    """Test that App.jsx has single source of truth for active workflow"""
    print("\n[TEST] App.jsx has activeWorkflowId state")

    content = read_file("e:/MutesHand/ai_lab_gui/frontend/src/App.jsx")
    if not content:
        return False

    # Check for activeWorkflowId state declaration
    has_state = "const [activeWorkflowId, setActiveWorkflowId] = useState" in content
    # Check for ref for sync access
    has_ref = "const activeWorkflowIdRef = useRef" in content

    print(f"  State: {has_state}, Ref: {has_ref}")

    if has_state and has_ref:
        print("  ✓ PASS: Single source of truth established")
        return True

    print("  ✗ FAIL: Missing activeWorkflowId state or ref")
    return False

def test_chat_receives_workflow_context():
    """Test that ChatPanel receives activeWorkflowId"""
    print("\n[TEST] ChatPanel receives activeWorkflowId prop")

    app_content = read_file("e:/MutesHand/ai_lab_gui/frontend/src/App.jsx")
    chat_content = read_file("e:/MutesHand/ai_lab_gui/frontend/src/components/ChatPanel.jsx")

    if not app_content or not chat_content:
        return False

    # Check App.jsx passes the prop
    app_passes = "activeWorkflowId={activeWorkflowId}" in app_content and "<ChatPanel" in app_content

    # Check ChatPanel accepts the prop
    chat_accepts = "activeWorkflowId" in chat_content and "export default function ChatPanel(" in chat_content

    print(f"  App passes: {app_passes}, Chat accepts: {chat_accepts}")

    if app_passes and chat_accepts:
        print("  ✓ PASS: Chat panel receives workflow context")
        return True

    print("  ✗ FAIL: Chat panel missing workflow context")
    return False

def test_background_has_select_handler():
    """Test that BackgroundPanel can select workflows"""
    print("\n[TEST] BackgroundPanel has workflow selection")

    content = read_file("e:/MutesHand/ai_lab_gui/frontend/src/components/BackgroundPanel.jsx")
    if not content:
        return False

    # Check for onSelectWorkflow prop
    has_prop = "onSelectWorkflow" in content
    # Check for handleSelectWorkflow function
    has_handler = "handleSelectWorkflow" in content
    # Check that click calls handler
    click_calls = "onClick={() => handleSelectWorkflow" in content

    print(f"  Prop: {has_prop}, Handler: {has_handler}, Click binding: {click_calls}")

    if has_prop and has_handler and click_calls:
        print("  ✓ PASS: Background workflows are selectable")
        return True

    print("  ✗ FAIL: Missing selection mechanism")
    return False

def test_api_has_headers():
    """Test that HEADERS constant is defined in api.js"""
    print("\n[TEST] api.js has HEADERS constant")

    content = read_file("e:/MutesHand/ai_lab_gui/frontend/src/api.js")
    if not content:
        return False

    # Check for HEADERS definition
    has_headers = "const HEADERS" in content and '"Content-Type": "application/json"' in content
    # Check it's used in post
    used_in_post = "headers: HEADERS" in content

    print(f"  Defined: {has_headers}, Used: {used_in_post}")

    if has_headers and used_in_post:
        print("  ✓ PASS: HEADERS bug fixed")
        return True

    print("  ✗ FAIL: HEADERS issue not resolved")
    return False

def test_api_includes_workflow_id():
    """Test that API calls include workflow_id"""
    print("\n[TEST] API includes workflow_id in calls")

    content = read_file("e:/MutesHand/ai_lab_gui/frontend/src/api.js")
    if not content:
        return False

    # Check pause/resume/approve include workflow_id
    has_pause = "pause: async (workflow_id)" in content
    has_resume = "resume: async (workflow_id)" in content
    has_approve = "approve: (workflow_id, step_id)" in content
    has_stream = "executeStream: (input, workflow_id" in content

    print(f"  Pause: {has_pause}, Resume: {has_resume}, Approve: {has_approve}, Stream: {has_stream}")

    if has_pause and has_resume and has_approve and has_stream:
        print("  ✓ PASS: API includes workflow_id where required")
        return True

    print("  ✗ FAIL: Some API calls missing workflow_id")
    return False

def test_workflow_panel_filters_by_id():
    """Test that WorkflowPanel filters events by workflow_id"""
    print("\n[TEST] WorkflowPanel filters by activeWorkflowId")

    content = read_file("e:/MutesHand/ai_lab_gui/frontend/src/components/WorkflowPanel.jsx")
    if not content:
        return False

    # Check it receives the prop
    receives = "activeWorkflowId" in content
    # Check it uses it for filtering (in getEvents call)
    uses = "api.getEvents(workflowId" in content or "api.getEvents(id" in content

    print(f"  Receives: {receives}, Uses: {uses}")

    if receives and uses:
        print("  ✓ PASS: WorkflowPanel filters by workflow")
        return True

    print("  ✗ FAIL: WorkflowPanel not properly filtering")
    return False

def test_control_panel_uses_workflow_id():
    """Test that ControlPanel uses workflowId for actions"""
    print("\n[TEST] ControlPanel uses workflowId for actions")

    content = read_file("e:/MutesHand/ai_lab_gui/frontend/src/components/ControlPanel.jsx")
    if not content:
        return False

    # Check it receives workflowId
    receives = "workflowId" in content
    # Check it's used in pause/resume
    uses_pause = "api.pause(workflowId)" in content
    uses_resume = "api.resume(workflowId)" in content

    print(f"  Receives: {receives}, Pause: {uses_pause}, Resume: {uses_resume}")

    if receives and uses_pause and uses_resume:
        print("  ✓ PASS: ControlPanel uses workflowId correctly")
        return True

    print("  ✗ FAIL: ControlPanel missing workflow context")
    return False

def test_default_workflow_handling():
    """Test that App.jsx has default workflow fallback logic"""
    print("\n[TEST] Default workflow handling exists")

    content = read_file("e:/MutesHand/ai_lab_gui/frontend/src/App.jsx")
    if not content:
        return False

    # Check for fallback logic
    has_fallback = "WORKFLOW_FALLBACK" in content or "fallback" in content.lower()
    has_default = "WORKFLOW_DEFAULT_SET" in content or "default" in content.lower()
    checks_missing = "!workflowIds.includes" in content

    print(f"  Fallback: {has_fallback}, Default: {has_default}, Missing check: {checks_missing}")

    if checks_missing:
        print("  ✓ PASS: Default workflow handling implemented")
        return True

    print("  ✗ FAIL: Missing default workflow handling")
    return False

def run_all_tests():
    print("=" * 70)
    print("PHASE 4B.2 — ACTIVE WORKFLOW FOUNDATION VALIDATION")
    print("=" * 70)

    tests = [
        test_app_has_active_workflow_state,
        test_chat_receives_workflow_context,
        test_background_has_select_handler,
        test_api_has_headers,
        test_api_includes_workflow_id,
        test_workflow_panel_filters_by_id,
        test_control_panel_uses_workflow_id,
        test_default_workflow_handling,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ✗ EXCEPTION in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

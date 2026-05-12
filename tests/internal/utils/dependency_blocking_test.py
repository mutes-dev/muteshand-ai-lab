"""
CATEGORY: INTERNAL_RUNTIME
AUTHORITY_LAYER: Runtime Behavioral Truth
VALIDATES:
  - Dependency model contract
  - FAILED dependencies block dependent steps
  - Dependency satisfaction checking
ENTRYPOINT: run_workflow
DIRECT_INTERNAL_CALLS:
  - execution_scheduler internals
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: BEHAVIORAL_VALIDATION
ARCHITECTURAL_SCOPE: Dependency model

---

Dependency Model Contract Test — FAILED dependencies MUST block dependent steps
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.execution_scheduler import _check_dependencies_satisfied


def test_no_dependencies():
    """Step with no dependencies should be satisfied"""
    print("\n[TEST] No Dependencies")

    step = {"id": "step_1", "depends_on": []}
    step_states = {}
    steps_map = {}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if satisfied and reason == "no_dependencies":
        print("  ✓ PASS")
        return True
    print("  ✗ FAIL")
    return False


def test_all_dependencies_completed():
    """Step with all COMPLETED dependencies should be satisfied"""
    print("\n[TEST] All Dependencies Completed")

    step = {"id": "step_2", "depends_on": ["step_1"]}
    step_states = {"step_1": "COMPLETED"}
    steps_map = {"step_1": {"id": "step_1"}}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if satisfied and reason == "all_dependencies_completed":
        print("  ✓ PASS")
        return True
    print("  ✗ FAIL")
    return False


def test_dependency_failed():
    """Step with FAILED dependency should be blocked — per DEPENDENCY_MODEL_CONTRACT_V1"""
    print("\n[TEST] Dependency Failed — MUST BLOCK")

    step = {"id": "step_2", "depends_on": ["step_1"]}
    step_states = {"step_1": "FAILED"}
    steps_map = {"step_1": {"id": "step_1"}}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if not satisfied and "dependency_failed" in reason:
        print("  ✓ PASS: FAILED dependency correctly blocks step")
        return True
    print("  ✗ FAIL: FAILED dependency did not block step")
    return False


def test_dependency_pending():
    """Step with PENDING dependency should be blocked"""
    print("\n[TEST] Dependency Pending — MUST BLOCK")

    step = {"id": "step_2", "depends_on": ["step_1"]}
    step_states = {"step_1": "PENDING"}
    steps_map = {"step_1": {"id": "step_1"}}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if not satisfied and "dependency_not_completed" in reason:
        print("  ✓ PASS: PENDING dependency correctly blocks step")
        return True
    print("  ✗ FAIL: PENDING dependency did not block step")
    return False


def test_dependency_blocked():
    """Step with BLOCKED dependency should be blocked"""
    print("\n[TEST] Dependency Blocked — MUST BLOCK")

    step = {"id": "step_2", "depends_on": ["step_1"]}
    step_states = {"step_1": "BLOCKED"}
    steps_map = {"step_1": {"id": "step_1"}}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if not satisfied and "dependency_not_completed" in reason:
        print("  ✓ PASS: BLOCKED dependency correctly blocks step")
        return True
    print("  ✗ FAIL: BLOCKED dependency did not block step")
    return False


def test_multiple_dependencies_one_failed():
    """Step with multiple dependencies where one FAILED should be blocked"""
    print("\n[TEST] Multiple Dependencies — One Failed")

    step = {"id": "step_3", "depends_on": ["step_1", "step_2"]}
    step_states = {"step_1": "COMPLETED", "step_2": "FAILED"}
    steps_map = {"step_1": {"id": "step_1"}, "step_2": {"id": "step_2"}}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if not satisfied and "dependency_failed" in reason:
        print("  ✓ PASS: One FAILED dependency correctly blocks step")
        return True
    print("  ✗ FAIL: FAILED dependency did not block step")
    return False


def test_live_status_beats_stale_snapshot_completed():
    """
    FIX REGRESSION TEST — live object COMPLETED must win over stale snapshot BLOCKED.

    Scenario: pre-flight mutation wrote BLOCKED to step_1 in a previous iteration.
    step_states snapshot captured that BLOCKED. But step_1 live object is now COMPLETED.
    step_2 depends on step_1. Must be satisfied.
    """
    print("\n[TEST] Live COMPLETED beats stale snapshot BLOCKED")

    step_1_live = {"id": "step_1", "status": "COMPLETED"}
    step_2 = {"id": "step_2", "depends_on": ["step_1"]}

    step_states = {"step_1": "BLOCKED"}           # stale snapshot
    steps_map = {"step_1": step_1_live}            # live objects

    satisfied, reason = _check_dependencies_satisfied(step_2, step_states, steps_map)
    print(f"  step_states['step_1'] = BLOCKED (stale)")
    print(f"  steps_map['step_1']['status'] = COMPLETED (live)")
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if satisfied and reason == "all_dependencies_completed":
        print("  ✓ PASS: live COMPLETED correctly overrides stale BLOCKED snapshot")
        return True
    print("  ✗ FAIL: stale BLOCKED snapshot incorrectly blocked a satisfied dependency")
    return False


def test_live_status_beats_stale_snapshot_pending():
    """
    FIX REGRESSION TEST — live object COMPLETED must win over stale snapshot PENDING.

    Scenario: step_states was built before executor wrote COMPLETED.
    snapshot has PENDING; live object has COMPLETED.
    """
    print("\n[TEST] Live COMPLETED beats stale snapshot PENDING")

    step_1_live = {"id": "step_1", "status": "COMPLETED"}
    step_2 = {"id": "step_2", "depends_on": ["step_1"]}

    step_states = {"step_1": "PENDING"}            # stale snapshot
    steps_map = {"step_1": step_1_live}             # live objects

    satisfied, reason = _check_dependencies_satisfied(step_2, step_states, steps_map)
    print(f"  step_states['step_1'] = PENDING (stale)")
    print(f"  steps_map['step_1']['status'] = COMPLETED (live)")
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if satisfied and reason == "all_dependencies_completed":
        print("  ✓ PASS: live COMPLETED correctly overrides stale PENDING snapshot")
        return True
    print("  ✗ FAIL: stale PENDING snapshot incorrectly blocked a satisfied dependency")
    return False


def test_live_failed_blocks_even_if_snapshot_says_completed():
    """
    FIX REGRESSION TEST — live object FAILED must block even if snapshot says COMPLETED.

    Guarantees the fix does not allow a genuinely FAILED dependency to slip through
    because a stale snapshot still shows COMPLETED.
    """
    print("\n[TEST] Live FAILED blocks even when snapshot says COMPLETED")

    step_1_live = {"id": "step_1", "status": "FAILED"}
    step_2 = {"id": "step_2", "depends_on": ["step_1"]}

    step_states = {"step_1": "COMPLETED"}          # stale snapshot (outdated)
    steps_map = {"step_1": step_1_live}             # live objects

    satisfied, reason = _check_dependencies_satisfied(step_2, step_states, steps_map)
    print(f"  step_states['step_1'] = COMPLETED (stale/outdated)")
    print(f"  steps_map['step_1']['status'] = FAILED (live)")
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if not satisfied and "dependency_failed" in reason:
        print("  ✓ PASS: live FAILED correctly blocked dependent step")
        return True
    print("  ✗ FAIL: stale COMPLETED snapshot incorrectly allowed a failed dependency through")
    return False


def test_three_step_chain_no_false_blocked():
    """
    FIX REGRESSION TEST — Case A from audit.
    step_1 COMPLETED, step_2 COMPLETED (live), step_3 depends on step_2.
    step_states may have stale BLOCKED for step_2 from a pre-flight mutation.
    step_3 must be satisfied.
    """
    print("\n[TEST] Three-step chain — step_3 not falsely BLOCKED (Case A)")

    step_1_live = {"id": "step_1", "status": "COMPLETED"}
    step_2_live = {"id": "step_2", "status": "COMPLETED", "depends_on": ["step_1"]}
    step_3 = {"id": "step_3", "depends_on": ["step_2"]}

    # Simulate stale snapshot: step_2 was BLOCKED in a previous pre-flight cycle
    step_states = {"step_1": "COMPLETED", "step_2": "BLOCKED", "step_3": "PENDING"}
    steps_map = {"step_1": step_1_live, "step_2": step_2_live, "step_3": step_3}

    satisfied, reason = _check_dependencies_satisfied(step_3, step_states, steps_map)
    print(f"  step_states['step_2'] = BLOCKED (stale pre-flight mutation)")
    print(f"  steps_map['step_2']['status'] = COMPLETED (live)")
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if satisfied and reason == "all_dependencies_completed":
        print("  ✓ PASS: step_3 correctly sees step_2 as COMPLETED via live object")
        return True
    print(f"  ✗ FAIL: step_3 falsely BLOCKED — saw stale '{step_states['step_2']}' instead of live COMPLETED")
    return False


def test_create_execution_group_sequential_chain():
    """
    Integration test — create_execution_group must schedule step_3 after step_1 and step_2
    have completed. No false BLOCKED should appear.
    Uses Case A: step_1→step_2→step_3 full dependency chain.
    """
    print("\n[TEST] create_execution_group — full sequential chain (Case A)")
    from system.orchestrator.execution_scheduler import create_execution_group
    from system.orchestrator.conflict_detector import ConflictDetector

    step_1 = {"id": "step_1", "status": "COMPLETED", "depends_on": [],
               "type": "EXECUTE_API", "risk": "LOW", "resource_targets": []}
    step_2 = {"id": "step_2", "status": "COMPLETED", "depends_on": ["step_1"],
               "type": "EXECUTE_API", "risk": "LOW", "resource_targets": []}
    step_3 = {"id": "step_3", "status": "PENDING", "depends_on": ["step_2"],
               "type": "EXECUTE_API", "risk": "LOW", "resource_targets": []}

    workflow = {"id": "wf_test", "status": "ACTIVE", "steps": [step_1, step_2, step_3]}
    # Simulate stale snapshot: step_2 had BLOCKED written by a previous pre-flight cycle
    step_states = {"step_1": "COMPLETED", "step_2": "BLOCKED", "step_3": "PENDING"}
    detector = ConflictDetector()

    group = create_execution_group(workflow, step_states, detector, "wf_test")
    print(f"  step_states['step_2'] = BLOCKED (stale)")
    print(f"  step_2 live status = COMPLETED")
    print(f"  Resulting group: {group}")

    if group is not None and "step_3" in group.get("steps", []):
        print("  ✓ PASS: step_3 correctly scheduled after live-COMPLETED step_2")
        return True
    if group is None:
        print("  ✗ FAIL: No group formed — step_3 falsely blocked by stale step_2 snapshot")
    else:
        print(f"  ✗ FAIL: Wrong steps in group: {group.get('steps')}")
    return False


def test_fallback_to_snapshot_when_no_live_object():
    """
    FIX SAFETY TEST — when dep_id has no entry in steps_map (unknown step),
    must fall back to step_states snapshot, not crash or return True.
    """
    print("\n[TEST] Fallback to snapshot when dep_id absent from steps_map")

    step_2 = {"id": "step_2", "depends_on": ["step_unknown"]}
    step_states = {"step_unknown": "PENDING"}
    steps_map = {}                                  # dep_id not in steps_map

    satisfied, reason = _check_dependencies_satisfied(step_2, step_states, steps_map)
    print(f"  steps_map is empty, step_states['step_unknown'] = PENDING")
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if not satisfied and "dependency_not_completed" in reason:
        print("  ✓ PASS: correctly fell back to snapshot for unknown dep_id")
        return True
    print("  ✗ FAIL: fallback to snapshot did not work")
    return False


def run_all_tests():
    print("=" * 60)
    print("DEPENDENCY MODEL CONTRACT — BLOCKING TESTS")
    print("=" * 60)

    tests = [
        test_no_dependencies,
        test_all_dependencies_completed,
        test_dependency_failed,
        test_dependency_pending,
        test_dependency_blocked,
        test_multiple_dependencies_one_failed,
        test_live_status_beats_stale_snapshot_completed,
        test_live_status_beats_stale_snapshot_pending,
        test_live_failed_blocks_even_if_snapshot_says_completed,
        test_three_step_chain_no_false_blocked,
        test_create_execution_group_sequential_chain,
        test_fallback_to_snapshot_when_no_live_object,
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
            print(f"  ✗ EXCEPTION: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

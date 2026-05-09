"""
Phase 4B.2.3 — Resolution Order Fix Validation Tests

Validates:
1. PLAN STEP (without tool_call) passes structural validation
2. PLAN STEP fails STEP_SCHEMA validation (post-resolution)
3. EXECUTION STEP (with tool_call) passes both validations
4. Resolution order: PLAN → RESOLUTION → VALIDATION → EXECUTION
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.workflow_validator import validate_workflow, validate_step_schema


def test_plan_step_passes_structural_validation():
    """PLAN STEP (no tool_call) should pass structural validation"""
    print("\n[TEST] PLAN STEP passes structural validation")
    
    workflow = {
        "id": "wf_001",
        "name": "Test Workflow",
        "status": "QUEUED",
        "steps": [
            {
                "id": "step_001",
                "type": "EXECUTE_FILE",
                "purpose": "Test purpose",
                "expected_outcome": "Test outcome",
                "risk": "LOW",
                "importance": "MEDIUM"
                # NOTE: No tool_call - this is a PLAN STEP
            }
        ]
    }
    
    # Structural validation (pre-resolution) should pass
    result = validate_workflow(workflow, require_step_schema=False)
    
    if result["status"] == "success":
        print("  ✓ PASS: PLAN STEP passes structural validation")
        return True
    else:
        print(f"  ✗ FAIL: PLAN STEP failed structural validation: {result.get('reason')}")
        return False


def test_plan_step_fails_step_schema_validation():
    """PLAN STEP (no tool_call) should fail STEP_SCHEMA validation"""
    print("\n[TEST] PLAN STEP fails STEP_SCHEMA validation")
    
    plan_step = {
        "id": "step_001",
        "type": "EXECUTE_FILE",
        "purpose": "Test purpose",
        "expected_outcome": "Test outcome",
        "risk": "LOW",
        "importance": "MEDIUM",
        "resource_targets": []
        # NOTE: No tool_call - this is a PLAN STEP
    }
    
    # STEP_SCHEMA validation (post-resolution) should fail
    result = validate_step_schema(plan_step)
    
    if result["status"] == "failure" and "tool_call" in result.get("reason", ""):
        print("  ✓ PASS: PLAN STEP correctly fails STEP_SCHEMA validation")
        return True
    else:
        print(f"  ✗ FAIL: Expected failure due to missing tool_call, got: {result}")
        return False


def test_execution_step_passes_both_validations():
    """EXECUTION STEP (with tool_call) should pass both validations"""
    print("\n[TEST] EXECUTION STEP passes both validations")
    
    workflow = {
        "id": "wf_001",
        "name": "Test Workflow",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "step_001",
                "type": "EXECUTE_FILE",
                "purpose": "Test purpose",
                "tool_call": "test_tool arg1 arg2",
                "expected_outcome": "Test outcome",
                "risk": "LOW",
                "importance": "MEDIUM",
                "resource_targets": ["file1.txt"]
            }
        ]
    }
    
    # Both validations should pass
    structural_result = validate_workflow(workflow, require_step_schema=False)
    schema_result = validate_step_schema(workflow["steps"][0])
    
    if structural_result["status"] == "success" and schema_result["status"] == "success":
        print("  ✓ PASS: EXECUTION STEP passes both validations")
        return True
    else:
        print(f"  ✗ FAIL: structural={structural_result}, schema={schema_result}")
        return False


def test_workflow_with_mixed_steps():
    """Workflow with PLAN and EXECUTION steps"""
    print("\n[TEST] Workflow with mixed PLAN and EXECUTION steps")
    
    workflow = {
        "id": "wf_001",
        "name": "Test Workflow",
        "status": "QUEUED",
        "steps": [
            {
                "id": "step_001",
                "type": "PLAN",
                "purpose": "Plan the task",
                "expected_outcome": "Plan created",
                "risk": "LOW",
                "importance": "HIGH"
                # PLAN STEP - no tool_call
            },
            {
                "id": "step_002",
                "type": "EXECUTE_FILE",
                "purpose": "Execute the plan",
                "tool_call": "execute_tool arg1",
                "expected_outcome": "Execution complete",
                "risk": "MEDIUM",
                "importance": "HIGH",
                "resource_targets": ["file.txt"]
                # EXECUTION STEP - has tool_call
            }
        ]
    }
    
    # Structural validation should pass for both
    structural_result = validate_workflow(workflow, require_step_schema=False)
    
    if structural_result["status"] != "success":
        print(f"  ✗ FAIL: Structural validation failed: {structural_result.get('reason')}")
        return False
    
    # STEP_SCHEMA validation: step_001 should fail, step_002 should pass
    plan_step_result = validate_step_schema(workflow["steps"][0])
    exec_step_result = validate_step_schema(workflow["steps"][1])
    
    if (plan_step_result["status"] == "failure" and 
        exec_step_result["status"] == "success"):
        print("  ✓ PASS: PLAN step fails, EXECUTION step passes STEP_SCHEMA")
        return True
    else:
        print(f"  ✗ FAIL: plan={plan_step_result}, exec={exec_step_result}")
        return False


def test_step_executor_rejects_unresolved_step():
    """step_executor should reject step without tool_call"""
    print("\n[TEST] step_executor rejects unresolved PLAN STEP")
    
    from system.orchestrator.step_executor import execute_step
    
    workflow = {"id": "wf_001", "name": "Test"}
    plan_step = {
        "id": "step_001",
        "type": "EXECUTE_FILE",
        "purpose": "Test purpose",
        "expected_outcome": "Test outcome",
        "risk": "LOW",
        "importance": "MEDIUM",
        "resource_targets": []
        # No tool_call - unresolved PLAN STEP
    }
    
    result = execute_step(plan_step, workflow)
    
    if (result.get("execution_result", {}).get("status") == "failure" and
        "step_schema_validation_failed" in result.get("execution_result", {}).get("reason", "")):
        print("  ✓ PASS: step_executor correctly rejects unresolved PLAN STEP")
        return True
    else:
        print(f"  ✗ FAIL: Expected rejection, got: {result}")
        return False


def test_step_executor_accepts_resolved_step():
    """step_executor should accept step with tool_call"""
    print("\n[TEST] step_executor accepts resolved EXECUTION STEP")
    
    from system.orchestrator.step_executor import execute_step
    
    workflow = {"id": "wf_001", "name": "Test"}
    exec_step = {
        "id": "step_001",
        "type": "EXECUTE_FILE",
        "purpose": "Test purpose",
        "tool_call": "finalize_output 'test result'",
        "expected_outcome": "Test outcome",
        "risk": "LOW",
        "importance": "MEDIUM",
        "resource_targets": []
    }
    
    result = execute_step(exec_step, workflow)
    
    # Should not fail due to validation
    if "step_schema_validation_failed" not in str(result):
        print("  ✓ PASS: step_executor accepts resolved EXECUTION STEP")
        return True
    else:
        print(f"  ✗ FAIL: step_executor rejected resolved step: {result}")
        return False


def test_pre_resolution_does_not_require_tool_call():
    """Pre-resolution validation should not require tool_call"""
    print("\n[TEST] Pre-resolution validation doesn't require tool_call")
    
    workflow = {
        "id": "wf_001",
        "name": "Test",
        "status": "QUEUED",
        "steps": [
            {
                "id": "step_001",
                "type": "ANALYZE",
                "purpose": "Analyze data",
                "expected_outcome": "Analysis complete",
                "risk": "LOW",
                "importance": "MEDIUM"
            }
        ]
    }
    
    # Default validate_workflow (pre-resolution) should pass
    result = validate_workflow(workflow)
    
    if result["status"] == "success":
        print("  ✓ PASS: Pre-resolution validation accepts PLAN STEP")
        return True
    else:
        print(f"  ✗ FAIL: Pre-resolution rejected PLAN STEP: {result.get('reason')}")
        return False


def run_all_tests():
    print("=" * 70)
    print("PHASE 4B.2.3 — RESOLUTION ORDER FIX VALIDATION")
    print("=" * 70)
    
    tests = [
        test_plan_step_passes_structural_validation,
        test_plan_step_fails_step_schema_validation,
        test_execution_step_passes_both_validations,
        test_workflow_with_mixed_steps,
        test_step_executor_rejects_unresolved_step,
        test_step_executor_accepts_resolved_step,
        test_pre_resolution_does_not_require_tool_call,
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

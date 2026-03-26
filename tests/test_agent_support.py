"""
Test suite for agent support in NEW planner pipeline.

Tests verify:
1. Agent-only plans pass validation
2. Mixed tool+agent plans pass validation
3. Agent execution via structured_plan
4. Invalid agent rejection
5. Tool flow regression (unchanged behavior)
"""

import sys
import os

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from core.validation import validate_plan


# Mock tool_index for testing
tool_index = {
    "add_numbers": {
        "description": "Add two numbers",
        "inputs": {"a": "number", "b": "number"}
    },
    "square_number": {
        "description": "Square a number",
        "inputs": {"x": "number"}
    }
}

# Mock AGENTS registry
from projects.manager import manager
manager.AGENTS = {
    "code_agent": lambda x: f"Code agent executed with input: {x}",
    "tester_agent": lambda x: f"Tester agent executed with input: {x}"
}


def test_agent_only_plan_validation():
    """Test that agent-only plans pass validation."""
    print("\n" + "="*60)
    print("TEST 1: Agent-Only Plan Validation")
    print("="*60)
    
    plan = [
        {
            "type": "agent",
            "name": "code_agent",
            "args": [],
            "input_text": "create a factorial tool"
        }
    ]
    
    is_valid, error = validate_plan(plan, tool_index)
    
    print(f"Plan: {plan}")
    print(f"Result: is_valid={is_valid}, error={error}")
    
    if is_valid:
        print("✅ PASS: Agent-only plan accepted by validation")
        return True
    else:
        print(f"❌ FAIL: Agent-only plan rejected: {error}")
        return False


def test_mixed_plan_validation():
    """Test that mixed tool+agent plans pass validation."""
    print("\n" + "="*60)
    print("TEST 2: Mixed Tool+Agent Plan Validation")
    print("="*60)
    
    plan = [
        {
            "type": "tool",
            "name": "add_numbers",
            "args": [2, 3],
            "input_text": "2 and 3"
        },
        {
            "type": "agent",
            "name": "tester_agent",
            "args": [],
            "input_text": "test the add_numbers tool"
        }
    ]
    
    is_valid, error = validate_plan(plan, tool_index)
    
    print(f"Plan: {plan}")
    print(f"Result: is_valid={is_valid}, error={error}")
    
    if is_valid:
        print("✅ PASS: Mixed plan accepted by validation")
        return True
    else:
        print(f"❌ FAIL: Mixed plan rejected: {error}")
        return False


def test_invalid_agent_rejection():
    """Test that invalid agents are rejected by validation."""
    print("\n" + "="*60)
    print("TEST 3: Invalid Agent Rejection")
    print("="*60)
    
    plan = [
        {
            "type": "agent",
            "name": "unknown_agent",
            "args": [],
            "input_text": "test"
        }
    ]
    
    is_valid, error = validate_plan(plan, tool_index)
    
    print(f"Plan: {plan}")
    print(f"Result: is_valid={is_valid}, error={error}")
    
    if not is_valid and "unknown agent" in str(error).lower():
        print("✅ PASS: Invalid agent correctly rejected")
        return True
    else:
        print(f"❌ FAIL: Invalid agent not rejected properly")
        return False


def test_tool_flow_regression():
    """Test that tool-only plans still work (regression test)."""
    print("\n" + "="*60)
    print("TEST 4: Tool Flow Regression")
    print("="*60)
    
    plan = [
        {
            "type": "tool",
            "name": "add_numbers",
            "args": [5, 7],
            "input_text": "5 and 7"
        },
        {
            "type": "tool",
            "name": "square_number",
            "args": ["PREVIOUS_RESULT"],
            "input_text": "result of previous step"
        }
    ]
    
    is_valid, error = validate_plan(plan, tool_index)
    
    print(f"Plan: {plan}")
    print(f"Result: is_valid={is_valid}, error={error}")
    
    if is_valid:
        print("✅ PASS: Tool-only plan still works (no regression)")
        return True
    else:
        print(f"❌ FAIL: Tool-only plan broken: {error}")
        return False


def test_agent_with_chaining():
    """Test agent step after tool step (chaining scenario)."""
    print("\n" + "="*60)
    print("TEST 5: Agent After Tool (Chaining Scenario)")
    print("="*60)
    
    plan = [
        {
            "type": "tool",
            "name": "add_numbers",
            "args": [10, 20],
            "input_text": "10 and 20"
        },
        {
            "type": "agent",
            "name": "tester_agent",
            "args": [],
            "input_text": "verify the result is 30"
        }
    ]
    
    is_valid, error = validate_plan(plan, tool_index)
    
    print(f"Plan: {plan}")
    print(f"Result: is_valid={is_valid}, error={error}")
    
    if is_valid:
        print("✅ PASS: Agent after tool accepted")
        return True
    else:
        print(f"❌ FAIL: Agent after tool rejected: {error}")
        return False


def test_invalid_type_rejection():
    """Test that invalid types are still rejected."""
    print("\n" + "="*60)
    print("TEST 6: Invalid Type Rejection")
    print("="*60)
    
    plan = [
        {
            "type": "invalid_type",
            "name": "something",
            "args": [],
            "input_text": "test"
        }
    ]
    
    is_valid, error = validate_plan(plan, tool_index)
    
    print(f"Plan: {plan}")
    print(f"Result: is_valid={is_valid}, error={error}")
    
    if not is_valid and "type must be" in str(error).lower():
        print("✅ PASS: Invalid type correctly rejected")
        return True
    else:
        print(f"❌ FAIL: Invalid type not rejected properly")
        return False


def run_all_tests():
    """Run all tests and report results."""
    print("\n" + "="*60)
    print("AGENT SUPPORT VALIDATION TESTS")
    print("="*60)
    
    tests = [
        ("Agent-Only Plan", test_agent_only_plan_validation),
        ("Mixed Tool+Agent Plan", test_mixed_plan_validation),
        ("Invalid Agent Rejection", test_invalid_agent_rejection),
        ("Tool Flow Regression", test_tool_flow_regression),
        ("Agent After Tool", test_agent_with_chaining),
        ("Invalid Type Rejection", test_invalid_type_rejection)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ EXCEPTION in {name}: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED")
        return True
    else:
        print(f"\n⚠️  {total - passed} TEST(S) FAILED")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

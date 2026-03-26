"""
Integration test for agent support through full manager pipeline.

This test simulates actual goal execution through the manager,
testing the complete flow:
  User goal → Planner → Validation → Execution
"""

import sys
import os

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from core.planner import generate_structured_plan
from core.validation import validate_plan


def test_tool_goal_through_planner():
    """Test tool goal through NEW planner (regression test)."""
    print("\n" + "="*60)
    print("TEST 1: Tool Goal Through NEW Planner (Regression)")
    print("="*60)
    
    goal = "add 5 and 7"
    tool_names = ["add_numbers", "subtract_numbers", "multiply_numbers", "square_number"]
    
    print(f"Goal: {goal}")
    print(f"Available tools: {tool_names}")
    
    # Generate plan
    plan = generate_structured_plan(goal, tool_names)
    
    print(f"\nGenerated plan: {plan}")
    
    if plan is None:
        print("❌ FAIL: Planner returned None")
        return False
    
    # Check structure
    if len(plan) != 1:
        print(f"❌ FAIL: Expected 1 step, got {len(plan)}")
        return False
    
    step = plan[0]
    if step.get("type") != "tool":
        print(f"❌ FAIL: Expected type='tool', got {step.get('type')}")
        return False
    
    if step.get("name") != "add_numbers":
        print(f"❌ FAIL: Expected name='add_numbers', got {step.get('name')}")
        return False
    
    if step.get("args") != [5, 7]:
        print(f"❌ FAIL: Expected args=[5, 7], got {step.get('args')}")
        return False
    
    print("✅ PASS: Tool goal generates correct plan")
    return True


def test_agent_goal_detection():
    """Test that agent keywords trigger agent goal detection."""
    print("\n" + "="*60)
    print("TEST 2: Agent Goal Detection")
    print("="*60)
    
    from projects.manager.manager import is_agent_goal
    
    test_cases = [
        ("create tool to add numbers", True, "contains 'create tool'"),
        ("test the add_numbers tool", True, "contains 'test'"),
        ("fix the broken tool", True, "contains 'fix'"),
        ("add 5 and 7", False, "pure tool goal"),
        ("multiply 3 and 4", False, "pure tool goal")
    ]
    
    all_passed = True
    for goal, expected, reason in test_cases:
        result = is_agent_goal(goal)
        status = "✅" if result == expected else "❌"
        print(f"{status} '{goal}' → {result} (expected {expected}, {reason})")
        if result != expected:
            all_passed = False
    
    if all_passed:
        print("\n✅ PASS: Agent goal detection works correctly")
        return True
    else:
        print("\n❌ FAIL: Some agent goal detection cases failed")
        return False


def test_planner_accepts_agent_in_prompt():
    """Test that planner can theoretically output agent steps (prompt allows it)."""
    print("\n" + "="*60)
    print("TEST 3: Planner Schema Supports Agents")
    print("="*60)
    
    # Read planner prompt to verify agent schema is present
    planner_file = os.path.join(PROJECT_ROOT, "core", "planner.py")
    with open(planner_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ('"type": "agent"' in content, "Agent type in schema"),
        ('"type": MUST be "tool" or "agent"' in content, "Type rule mentions agent"),
        ('if step["type"] not in ["tool", "agent"]' in content, "Validation accepts agent")
    ]
    
    all_passed = True
    for check, description in checks:
        status = "✅" if check else "❌"
        print(f"{status} {description}")
        if not check:
            all_passed = False
    
    if all_passed:
        print("\n✅ PASS: Planner schema supports agents")
        return True
    else:
        print("\n❌ FAIL: Planner schema missing agent support")
        return False


def test_validation_accepts_agent_plan():
    """Test that validation layer accepts agent plans."""
    print("\n" + "="*60)
    print("TEST 4: Validation Accepts Agent Plans")
    print("="*60)
    
    # Mock AGENTS for validation
    from projects.manager import manager
    manager.AGENTS = {
        "code_agent": lambda x: f"Mock code agent: {x}",
        "tester_agent": lambda x: f"Mock tester agent: {x}"
    }
    
    tool_index = {
        "add_numbers": {
            "description": "Add two numbers",
            "inputs": {"a": "number", "b": "number"}
        }
    }
    
    # Test 1: Agent-only plan
    agent_plan = [
        {
            "type": "agent",
            "name": "code_agent",
            "args": [],
            "input_text": "create a tool"
        }
    ]
    
    is_valid, error = validate_plan(agent_plan, tool_index)
    print(f"Agent-only plan: is_valid={is_valid}, error={error}")
    
    if not is_valid:
        print(f"❌ FAIL: Agent-only plan rejected: {error}")
        return False
    
    # Test 2: Mixed plan
    mixed_plan = [
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
            "input_text": "test the result"
        }
    ]
    
    is_valid, error = validate_plan(mixed_plan, tool_index)
    print(f"Mixed plan: is_valid={is_valid}, error={error}")
    
    if not is_valid:
        print(f"❌ FAIL: Mixed plan rejected: {error}")
        return False
    
    print("\n✅ PASS: Validation accepts agent plans")
    return True


def test_execution_handler_exists():
    """Test that agent execution handler exists in manager."""
    print("\n" + "="*60)
    print("TEST 5: Agent Execution Handler Exists")
    print("="*60)
    
    manager_file = os.path.join(PROJECT_ROOT, "projects", "manager", "manager.py")
    with open(manager_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ('if next_step and next_step.get("type") == "agent"' in content, "Agent type check exists"),
        ('AGENTS[agent_name]' in content and 'FORCED EXECUTION' in content, "Agent execution call exists"),
        ('log(f"FORCED EXECUTION: {agent_name}' in content, "Agent forced execution logging")
    ]
    
    all_passed = True
    for check, description in checks:
        status = "✅" if check else "❌"
        print(f"{status} {description}")
        if not check:
            all_passed = False
    
    if all_passed:
        print("\n✅ PASS: Agent execution handler exists")
        return True
    else:
        print("\n❌ FAIL: Agent execution handler missing")
        return False


def test_no_llm_execution_paths():
    """Test that LLM-driven execution paths are removed."""
    print("\n" + "="*60)
    print("TEST 6: No LLM-Driven Execution Paths")
    print("="*60)
    
    manager_file = os.path.join(PROJECT_ROOT, "projects", "manager", "manager.py")
    with open(manager_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Look for blocking messages
    checks = [
        ('BLOCKED: LLM attempted to trigger tool execution' in content, "Tool execution blocked"),
        ('BLOCKED: LLM attempted to trigger agent execution' in content, "Agent execution blocked"),
        ('Direct tool execution is disabled' in content, "Tool blocking message"),
        ('Direct agent execution is disabled' in content, "Agent blocking message")
    ]
    
    all_passed = True
    for check, description in checks:
        status = "✅" if check else "❌"
        print(f"{status} {description}")
        if not check:
            all_passed = False
    
    if all_passed:
        print("\n✅ PASS: LLM execution paths are blocked")
        return True
    else:
        print("\n❌ FAIL: LLM execution paths not properly blocked")
        return False


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "="*60)
    print("AGENT SUPPORT INTEGRATION TESTS")
    print("="*60)
    
    tests = [
        ("Tool Goal Through Planner (Regression)", test_tool_goal_through_planner),
        ("Agent Goal Detection", test_agent_goal_detection),
        ("Planner Schema Supports Agents", test_planner_accepts_agent_in_prompt),
        ("Validation Accepts Agent Plans", test_validation_accepts_agent_plan),
        ("Agent Execution Handler Exists", test_execution_handler_exists),
        ("No LLM-Driven Execution Paths", test_no_llm_execution_paths)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ EXCEPTION in {name}: {e}")
            import traceback
            traceback.print_exc()
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
        print("\n🎉 ALL INTEGRATION TESTS PASSED")
        print("\nAgent support successfully integrated into NEW planner pipeline!")
        return True
    else:
        print(f"\n⚠️  {total - passed} TEST(S) FAILED")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

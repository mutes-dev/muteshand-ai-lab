"""Test purified system_entry (core execution only)"""
from system.entry.system_entry import system_entry

print("=" * 60)
print("PHASE 4 — TESTING PURIFIED CORE")
print("=" * 60)
print()

# VALID CASES
print("=== VALID CASES ===")
print()

tests = [
    ("add_numbers 2 3", 5),
    ("subtract_numbers 10 3", 7),
    ("multiply_numbers 4 5", 20),
    ("square_number 5", 25),
]

for tool_call, expected in tests:
    result = system_entry(tool_call)
    status = result.get("status")
    value = result.get("result")
    passed = status == "success" and value == expected
    print(f"{'PASS' if passed else 'FAIL'}: {tool_call}")
    print(f"  Result: {result}")
    print(f"  Expected: status=success, result={expected}")
    print()

# INVALID CASES
print("=== INVALID CASES ===")
print()

invalid_tests = [
    ("add 2 3", "unknown_tool"),
    ("add_numbers 2", "validation_failed"),  # wrong arg count
    ("random text", "invalid_tool_name"),
    ("", "invalid_tool_call_format"),
    ("123invalid", "invalid_tool_name"),
]

for tool_call, expected_reason in invalid_tests:
    result = system_entry(tool_call)
    status = result.get("status")
    reason = result.get("reason")
    passed = status == "failure"
    print(f"{'PASS' if passed else 'FAIL'}: {repr(tool_call)}")
    print(f"  Result: {result}")
    print(f"  Expected: status=failure")
    print()

# ORCHESTRATOR PATH TEST
print("=== ORCHESTRATOR PATH TEST ===")
print()

from system.orchestrator.agent_executor import execute_agent

agent = {
    "name": "test_agent",
    "role": "tool_executor",
    "scope": ["tools"]
}

result = execute_agent(agent, "square 5")
exec_result = result.get("result", {}).get("execution_result")
print(f"Agent input: 'square 5'")
print(f"Execution result: {exec_result}")
print(f"PASS" if exec_result.get("status") == "success" and exec_result.get("result") == 25 else "FAIL")
print()

print("=" * 60)
print("TESTING COMPLETE")
print("=" * 60)

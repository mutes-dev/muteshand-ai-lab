import sys
sys.path.insert(0, 'E:/MutesHand')

from core.planner import _validate_plan
import json

print("=" * 70)
print("DETAILED VALIDATION FEEDBACK TESTS")
print("=" * 70)

# Test cases with expected error messages
test_cases = [
    {
        "name": "Plan not a list",
        "plan": {"type": "tool"},
        "tools": ["add_numbers"],
        "expected_error": "Plan must be a non-empty list"
    },
    {
        "name": "Empty plan",
        "plan": [],
        "tools": ["add_numbers"],
        "expected_error": "Plan must be a non-empty list"
    },
    {
        "name": "Step not a dict",
        "plan": ["invalid"],
        "tools": ["add_numbers"],
        "expected_error": "Step 1 must be a dict"
    },
    {
        "name": "Missing field",
        "plan": [{"type": "tool", "name": "add_numbers", "args": [1, 2]}],
        "tools": ["add_numbers"],
        "expected_error": "Step 1 must contain exactly 4 fields: type, name, args, input_text"
    },
    {
        "name": "Extra field",
        "plan": [{"type": "tool", "name": "add_numbers", "args": [1, 2], "input_text": "1 and 2", "extra": "field"}],
        "tools": ["add_numbers"],
        "expected_error": "Step 1 must contain exactly 4 fields: type, name, args, input_text"
    },
    {
        "name": "Invalid type",
        "plan": [{"type": "agent", "name": "add_numbers", "args": [1, 2], "input_text": "1 and 2"}],
        "tools": ["add_numbers"],
        "expected_error": "Step 1: Invalid type 'agent', must be 'tool'"
    },
    {
        "name": "Unknown tool",
        "plan": [{"type": "tool", "name": "unknown_tool", "args": [1, 2], "input_text": "1 and 2"}],
        "tools": ["add_numbers"],
        "expected_error": "Step 1: Unknown tool name 'unknown_tool'"
    },
    {
        "name": "Args not a list",
        "plan": [{"type": "tool", "name": "add_numbers", "args": "not a list", "input_text": "1 and 2"}],
        "tools": ["add_numbers"],
        "expected_error": "Step 1: Args must be a list"
    },
    {
        "name": "Invalid arg type",
        "plan": [{"type": "tool", "name": "add_numbers", "args": [1, {"invalid": "dict"}], "input_text": "1 and 2"}],
        "tools": ["add_numbers"],
        "expected_error": "Step 1: Invalid arg type at position 2, must be int, float, or string"
    },
    {
        "name": "PREVIOUS_RESULT in first step",
        "plan": [{"type": "tool", "name": "add_numbers", "args": ["PREVIOUS_RESULT", 2], "input_text": "result and 2"}],
        "tools": ["add_numbers"],
        "expected_error": "Step 1: PREVIOUS_RESULT cannot be used in first step"
    },
    {
        "name": "Multiple PREVIOUS_RESULT",
        "plan": [
            {"type": "tool", "name": "add_numbers", "args": [1, 2], "input_text": "1 and 2"},
            {"type": "tool", "name": "multiply_numbers", "args": ["PREVIOUS_RESULT", "PREVIOUS_RESULT"], "input_text": "result and result"}
        ],
        "tools": ["add_numbers", "multiply_numbers"],
        "expected_error": "Step 2: PREVIOUS_RESULT used more than once in step"
    },
    {
        "name": "Empty input_text",
        "plan": [{"type": "tool", "name": "add_numbers", "args": [1, 2], "input_text": ""}],
        "tools": ["add_numbers"],
        "expected_error": "Step 1: input_text must be a non-empty string"
    },
    {
        "name": "input_text not string",
        "plan": [{"type": "tool", "name": "add_numbers", "args": [1, 2], "input_text": 123}],
        "tools": ["add_numbers"],
        "expected_error": "Step 1: input_text must be a non-empty string"
    },
]

print("\nINVALID CASES - Testing Specific Error Messages:")
print("-" * 70)

passed = 0
failed = 0

for test in test_cases:
    is_valid, error_msg = _validate_plan(test["plan"], test["tools"])
    
    if not is_valid:
        # Check if error message matches expected
        if error_msg == test["expected_error"]:
            print(f"✅ {test['name']}")
            print(f"   Error: {error_msg}")
            passed += 1
        else:
            print(f"❌ {test['name']}")
            print(f"   Expected: {test['expected_error']}")
            print(f"   Got:      {error_msg}")
            failed += 1
    else:
        print(f"❌ {test['name']} - Expected invalid, got valid")
        failed += 1
    print()

# Test valid cases
print("\nVALID CASES - Should Return (True, None):")
print("-" * 70)

valid_cases = [
    {
        "name": "Simple single step",
        "plan": [{"type": "tool", "name": "add_numbers", "args": [2, 3], "input_text": "2 and 3"}],
        "tools": ["add_numbers"]
    },
    {
        "name": "Chained steps",
        "plan": [
            {"type": "tool", "name": "add_numbers", "args": [2, 3], "input_text": "2 and 3"},
            {"type": "tool", "name": "square_number", "args": ["PREVIOUS_RESULT"], "input_text": "result of previous step"}
        ],
        "tools": ["add_numbers", "square_number"]
    },
]

for test in valid_cases:
    is_valid, error_msg = _validate_plan(test["plan"], test["tools"])
    
    if is_valid and error_msg is None:
        print(f"✅ {test['name']}")
        passed += 1
    else:
        print(f"❌ {test['name']} - Expected valid, got error: {error_msg}")
        failed += 1
    print()

print("=" * 70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 70)

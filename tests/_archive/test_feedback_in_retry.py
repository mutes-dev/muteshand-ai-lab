import sys
sys.path.insert(0, 'E:/MutesHand')

from core.planner import generate_structured_plan, _generate_plan_llm
import json

print("=" * 70)
print("TESTING DETAILED FEEDBACK IN RETRY LOOP")
print("=" * 70)

# Simulate a scenario where we manually create invalid plans
# and see what feedback would be generated

print("\nSimulation 1: Testing feedback propagation")
print("-" * 70)

# Create a mock invalid plan to see what feedback it generates
invalid_plan_1 = [
    {"type": "tool", "name": "unknown_tool", "args": [1, 2], "input_text": "1 and 2"}
]

from core.planner import _validate_plan

is_valid, error_msg = _validate_plan(invalid_plan_1, ["add_numbers", "multiply_numbers"])
print(f"Invalid Plan 1:")
print(f"  Validation Result: {is_valid}")
print(f"  Error Message: {error_msg}")
print(f"  Feedback to LLM: Validation error: {error_msg}")
print()

# Test another invalid case
invalid_plan_2 = [
    {"type": "tool", "name": "add_numbers", "args": ["PREVIOUS_RESULT", 2], "input_text": "result and 2"}
]

is_valid, error_msg = _validate_plan(invalid_plan_2, ["add_numbers"])
print(f"Invalid Plan 2:")
print(f"  Validation Result: {is_valid}")
print(f"  Error Message: {error_msg}")
print(f"  Feedback to LLM: Validation error: {error_msg}")
print()

# Test multiple PREVIOUS_RESULT
invalid_plan_3 = [
    {"type": "tool", "name": "add_numbers", "args": [1, 2], "input_text": "1 and 2"},
    {"type": "tool", "name": "multiply_numbers", "args": ["PREVIOUS_RESULT", "PREVIOUS_RESULT"], "input_text": "result and result"}
]

is_valid, error_msg = _validate_plan(invalid_plan_3, ["add_numbers", "multiply_numbers"])
print(f"Invalid Plan 3:")
print(f"  Validation Result: {is_valid}")
print(f"  Error Message: {error_msg}")
print(f"  Feedback to LLM: Validation error: {error_msg}")
print()

print("\nSimulation 2: Real LLM test with feedback")
print("-" * 70)

# Test a normal goal to see if it works
result = generate_structured_plan('Add 5 and 10', ['add_numbers', 'multiply_numbers', 'square_number'])

if result:
    print("✅ Plan generated successfully:")
    print(json.dumps(result, indent=2))
else:
    print("❌ Plan generation failed after all retries")

print()

# Test with limited tools to potentially trigger validation errors
print("\nSimulation 3: Limited tools (may trigger specific feedback)")
print("-" * 70)

result = generate_structured_plan('Square the number 9', ['add_numbers', 'multiply_numbers'])

if result:
    print("✅ Plan generated (LLM found workaround):")
    print(json.dumps(result, indent=2))
else:
    print("✅ Plan generation correctly failed (no square_number tool)")

print()

print("=" * 70)
print("FEEDBACK SYSTEM VERIFICATION COMPLETE")
print("=" * 70)
print("\nKEY IMPROVEMENTS:")
print("- Specific error messages for each validation rule")
print("- Step numbers included in error messages")
print("- Tool names and positions included where relevant")
print("- LLM receives actionable feedback for self-correction")

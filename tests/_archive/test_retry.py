import sys
sys.path.insert(0, 'E:/MutesHand')

from core.planner import generate_structured_plan, _generate_plan_llm, _validate_plan
import json

print("=" * 60)
print("RETRY LOGIC TESTS")
print("=" * 60)

# Test 1: Normal valid plan (should succeed on first attempt)
print("\nTest 1: Valid plan generation")
print("-" * 60)
result = generate_structured_plan('Add 2 and 3', ['add_numbers', 'square_number', 'multiply_numbers'])
if result is not None:
    print("✅ PASS - Valid plan generated:")
    print(json.dumps(result, indent=2))
else:
    print("❌ FAIL - Expected valid plan, got None")

# Test 2: Chained plan (should succeed)
print("\nTest 2: Chained plan generation")
print("-" * 60)
result = generate_structured_plan('Add 2 and 3, then square the result', ['add_numbers', 'square_number', 'multiply_numbers'])
if result is not None:
    print("✅ PASS - Valid chained plan generated:")
    print(json.dumps(result, indent=2))
else:
    print("❌ FAIL - Expected valid plan, got None")

# Test 3: Simulate retry with manual feedback
print("\nTest 3: Manual retry simulation with error feedback")
print("-" * 60)

# First attempt - simulate invalid JSON
print("Attempt 1: Testing with error feedback for invalid JSON")
raw1 = _generate_plan_llm('Add 5 and 7', ['add_numbers'], error_feedback="Invalid JSON format. Return valid JSON only.")
print(f"Raw response length: {len(raw1)} chars")

try:
    parsed1 = json.loads(raw1)
    is_valid1 = _validate_plan(parsed1, ['add_numbers'])
    if is_valid1:
        print("✅ LLM corrected output after feedback")
        print(json.dumps(parsed1, indent=2))
    else:
        print("⚠️ LLM output is valid JSON but failed validation")
except:
    print("❌ LLM still producing invalid JSON after feedback")

# Test 4: Simulate retry with validation error feedback
print("\nTest 4: Manual retry simulation with validation error feedback")
print("-" * 60)

print("Attempt with validation error feedback")
raw2 = _generate_plan_llm('Multiply 3 and 4', ['multiply_numbers'], error_feedback="Plan failed validation. Fix structure, tool names, args, or chaining.")
print(f"Raw response length: {len(raw2)} chars")

try:
    parsed2 = json.loads(raw2)
    is_valid2 = _validate_plan(parsed2, ['multiply_numbers'])
    if is_valid2:
        print("✅ LLM corrected validation issues after feedback")
        print(json.dumps(parsed2, indent=2))
    else:
        print("⚠️ LLM output is valid JSON but still failed validation")
        print("Plan:", parsed2)
except:
    print("❌ LLM producing invalid JSON")

# Test 5: Test with limited tool set (potential for failure)
print("\nTest 5: Limited tool set (may trigger retries)")
print("-" * 60)
result = generate_structured_plan('Calculate square root of 16', ['add_numbers', 'multiply_numbers'])
if result is None:
    print("✅ PASS - Correctly returned None when no valid plan possible")
else:
    print("⚠️ Generated plan despite missing square_root tool:")
    print(json.dumps(result, indent=2))

print("\n" + "=" * 60)
print("RETRY TESTS COMPLETE")
print("=" * 60)

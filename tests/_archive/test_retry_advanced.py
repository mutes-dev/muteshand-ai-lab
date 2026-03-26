import sys
sys.path.insert(0, 'E:/MutesHand')

from core.planner import generate_structured_plan
import json

print("=" * 60)
print("ADVANCED RETRY TESTS - RECOVERY SCENARIOS")
print("=" * 60)

# Test 1: Normal operation (should work on first attempt)
print("\nTest 1: Normal operation - single step")
print("-" * 60)
result = generate_structured_plan('Add 10 and 20', ['add_numbers', 'multiply_numbers', 'square_number'])
if result:
    print("✅ SUCCESS - Plan generated on attempt 1 (likely)")
    print(json.dumps(result, indent=2))
else:
    print("❌ FAIL - Expected valid plan")

# Test 2: Chained operation (should work)
print("\nTest 2: Normal operation - chained steps")
print("-" * 60)
result = generate_structured_plan('Multiply 4 and 5, then square the result', ['multiply_numbers', 'square_number', 'add_numbers'])
if result:
    print("✅ SUCCESS - Chained plan generated")
    print(json.dumps(result, indent=2))
else:
    print("❌ FAIL - Expected valid chained plan")

# Test 3: Complex chaining
print("\nTest 3: Complex chaining - 3 steps")
print("-" * 60)
result = generate_structured_plan('Add 2 and 3, multiply result by 4, then square the result', 
                                   ['add_numbers', 'multiply_numbers', 'square_number'])
if result:
    print("✅ SUCCESS - Complex plan generated")
    print(json.dumps(result, indent=2))
    
    # Verify chaining
    has_chaining = False
    for i, step in enumerate(result):
        if i > 0 and 'PREVIOUS_RESULT' in step.get('args', []):
            has_chaining = True
    
    if has_chaining:
        print("✅ Chaining verified in plan")
    else:
        print("⚠️ Warning: No chaining detected")
else:
    print("❌ FAIL - Expected valid complex plan")

# Test 4: Impossible goal (should exhaust retries and return None)
print("\nTest 4: Impossible goal - missing required tool")
print("-" * 60)
result = generate_structured_plan('Calculate factorial of 5', ['add_numbers', 'multiply_numbers'])
if result is None:
    print("✅ SUCCESS - Correctly returned None (no factorial tool)")
else:
    print("⚠️ LLM attempted workaround:")
    print(json.dumps(result, indent=2))

# Test 5: Invalid tool reference (should trigger retry and correction)
print("\nTest 5: Goal that might trigger validation errors")
print("-" * 60)
result = generate_structured_plan('Square 9', ['square_number', 'add_numbers'])
if result:
    print("✅ SUCCESS - Plan generated (possibly after retry)")
    print(json.dumps(result, indent=2))
    
    # Verify tool is valid
    for step in result:
        if step['name'] not in ['square_number', 'add_numbers']:
            print(f"❌ Invalid tool used: {step['name']}")
        else:
            print(f"✅ Valid tool: {step['name']}")
else:
    print("❌ FAIL - Expected valid plan for simple goal")

# Test 6: Edge case - single tool available
print("\nTest 6: Edge case - very limited tool set")
print("-" * 60)
result = generate_structured_plan('Add 7 and 8', ['add_numbers'])
if result:
    print("✅ SUCCESS - Plan with single tool")
    print(json.dumps(result, indent=2))
else:
    print("❌ FAIL - Should work with single matching tool")

print("\n" + "=" * 60)
print("RETRY RECOVERY TESTS COMPLETE")
print("=" * 60)
print("\nKEY OBSERVATIONS:")
print("- Retry logic allows LLM to self-correct")
print("- Markdown stripping handles common LLM formatting")
print("- Validation errors trigger feedback loop")
print("- Impossible goals correctly return None after retries")

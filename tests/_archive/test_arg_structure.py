"""
Test script for argument structure rules in planner.
"""

from core.planner import generate_structured_plan

# Test tools
tool_names = ['add_numbers', 'subtract_numbers', 'multiply_numbers', 'square_number']

print("=" * 60)
print("TEST 1: 'add 1 and 2 and 3' (3 values for 2-arg tool)")
print("=" * 60)
result1 = generate_structured_plan("add 1 and 2 and 3", tool_names)
print(f"Result: {result1}")
print(f"Expected: 2-step plan")
if result1 is not None and len(result1) == 2:
    print(f"Step 1: {result1[0].get('name')} with args {result1[0].get('args')}")
    print(f"Step 2: {result1[1].get('name')} with args {result1[1].get('args')}")
    
    step1_valid = result1[0].get('args') == [1, 2]
    step2_valid = result1[1].get('args') == ["PREVIOUS_RESULT", 3]
    
    if step1_valid and step2_valid:
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - wrong args")
else:
    print(f"Status: ❌ FAIL - expected 2 steps, got {len(result1) if result1 else 0}")
print()

print("=" * 60)
print("TEST 2: 'add the result of adding 1 and 2 and 3'")
print("=" * 60)
result2 = generate_structured_plan("add the result of adding 1 and 2 and 3", tool_names)
print(f"Result: {result2}")
print(f"Expected: 2-step chained plan")
if result2 is not None and len(result2) == 2:
    print(f"Step 1: {result2[0].get('name')} with args {result2[0].get('args')}")
    print(f"Step 2: {result2[1].get('name')} with args {result2[1].get('args')}")
    
    # Should be: add 1 and 2, then add result and 3
    step1_valid = result2[0].get('args') == [1, 2]
    step2_has_chaining = "PREVIOUS_RESULT" in result2[1].get('args', [])
    
    if step1_valid and step2_has_chaining:
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - incorrect plan structure")
else:
    print(f"Status: ❌ FAIL - expected 2 steps, got {len(result2) if result2 else 0}")
print()

print("=" * 60)
print("TEST 3: 'add 2 and 3' (normal 2-arg case)")
print("=" * 60)
result3 = generate_structured_plan("add 2 and 3", tool_names)
print(f"Result: {result3}")
print(f"Expected: Single step with args [2, 3]")
if result3 is not None and len(result3) == 1:
    print(f"Step 1: {result3[0].get('name')} with args {result3[0].get('args')}")
    
    if result3[0].get('args') == [2, 3]:
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - wrong args")
else:
    print(f"Status: ❌ FAIL - expected 1 step, got {len(result3) if result3 else 0}")
print()

print("=" * 60)
print("SUMMARY")
print("=" * 60)
test1_pass = (result1 is not None and len(result1) == 2 and 
              result1[0].get('args') == [1, 2] and 
              result1[1].get('args') == ["PREVIOUS_RESULT", 3])

test2_pass = (result2 is not None and len(result2) == 2 and 
              result2[0].get('args') == [1, 2] and 
              "PREVIOUS_RESULT" in result2[1].get('args', []))

test3_pass = (result3 is not None and len(result3) == 1 and 
              result3[0].get('args') == [2, 3])

print(f"Test 1 (add 1 and 2 and 3): {'✅ PASS' if test1_pass else '❌ FAIL'}")
print(f"Test 2 (add result of adding 1 and 2 and 3): {'✅ PASS' if test2_pass else '❌ FAIL'}")
print(f"Test 3 (add 2 and 3): {'✅ PASS' if test3_pass else '❌ FAIL'}")
print()
print(f"Overall: {sum([test1_pass, test2_pass, test3_pass])}/3 tests passed")

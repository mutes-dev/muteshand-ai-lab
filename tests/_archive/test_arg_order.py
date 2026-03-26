"""
Test script for argument order preservation rules in planner.
"""

from core.planner import generate_structured_plan

# Test tools
tool_names = ['add_numbers', 'subtract_numbers', 'multiply_numbers', 'divide_numbers', 'square_number']

print("=" * 60)
print("TEST 1: 'subtract 10 from 20'")
print("=" * 60)
result1 = generate_structured_plan("subtract 10 from 20", tool_names)
print(f"Result: {result1}")
print(f"Expected: [20, 10] (20 - 10 = 10)")
if result1 is not None and len(result1) == 1:
    print(f"Step 1: {result1[0].get('name')} with args {result1[0].get('args')}")
    
    if result1[0].get('args') == [20, 10]:
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - wrong order (got {result1[0].get('args')})")
else:
    print(f"Status: ❌ FAIL - expected 1 step, got {len(result1) if result1 else 0}")
print()

print("=" * 60)
print("TEST 2: 'subtract 10 from the result of adding 7 and 8'")
print("=" * 60)
result2 = generate_structured_plan("subtract 10 from the result of adding 7 and 8", tool_names)
print(f"Result: {result2}")
print(f"Expected: Step 1: add(7, 8), Step 2: subtract(PREV, 10)")
if result2 is not None and len(result2) == 2:
    print(f"Step 1: {result2[0].get('name')} with args {result2[0].get('args')}")
    print(f"Step 2: {result2[1].get('name')} with args {result2[1].get('args')}")
    
    step1_valid = result2[0].get('name') == 'add_numbers' and result2[0].get('args') == [7, 8]
    step2_valid = (result2[1].get('name') == 'subtract_numbers' and 
                   result2[1].get('args') == ["PREVIOUS_RESULT", 10])
    
    if step1_valid and step2_valid:
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - incorrect plan structure")
else:
    print(f"Status: ❌ FAIL - expected 2 steps, got {len(result2) if result2 else 0}")
print()

print("=" * 60)
print("TEST 3: 'divide 20 by 5'")
print("=" * 60)
result3 = generate_structured_plan("divide 20 by 5", tool_names)
print(f"Result: {result3}")
print(f"Expected: [20, 5] (20 / 5 = 4)")
if result3 is not None and len(result3) == 1:
    print(f"Step 1: {result3[0].get('name')} with args {result3[0].get('args')}")
    
    if result3[0].get('args') == [20, 5]:
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - wrong order (got {result3[0].get('args')})")
else:
    print(f"Status: ❌ FAIL - expected 1 step, got {len(result3) if result3 else 0}")
print()

print("=" * 60)
print("SUMMARY")
print("=" * 60)
test1_pass = (result1 is not None and len(result1) == 1 and 
              result1[0].get('args') == [20, 10])

test2_pass = (result2 is not None and len(result2) == 2 and 
              result2[0].get('args') == [7, 8] and 
              result2[1].get('args') == ["PREVIOUS_RESULT", 10])

test3_pass = (result3 is not None and len(result3) == 1 and 
              result3[0].get('args') == [20, 5])

print(f"Test 1 (subtract 10 from 20): {'✅ PASS' if test1_pass else '❌ FAIL'}")
print(f"Test 2 (subtract 10 from result of adding 7 and 8): {'✅ PASS' if test2_pass else '❌ FAIL'}")
print(f"Test 3 (divide 20 by 5): {'✅ PASS' if test3_pass else '❌ FAIL'}")
print()
print(f"Overall: {sum([test1_pass, test2_pass, test3_pass])}/3 tests passed")

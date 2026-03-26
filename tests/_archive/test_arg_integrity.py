"""
Test script for argument integrity rules in planner.
"""

from core.planner import generate_structured_plan

# Test tools
tool_names = ['add_numbers', 'subtract_numbers', 'multiply_numbers', 'square_number']

print("=" * 60)
print("TEST 1: 'use add_numbers' (no values)")
print("=" * 60)
result1 = generate_structured_plan("use add_numbers", tool_names)
print(f"Result: {result1}")
print(f"Expected: None")
print(f"Status: {'✅ PASS' if result1 is None else '❌ FAIL'}")
print()

print("=" * 60)
print("TEST 2: 'add numbers' (no values)")
print("=" * 60)
result2 = generate_structured_plan("add numbers", tool_names)
print(f"Result: {result2}")
print(f"Expected: None")
print(f"Status: {'✅ PASS' if result2 is None else '❌ FAIL'}")
print()

print("=" * 60)
print("TEST 3: 'add 2 and 3' (valid with values)")
print("=" * 60)
result3 = generate_structured_plan("add 2 and 3", tool_names)
print(f"Result: {result3}")
print(f"Expected: Valid plan with args [2, 3]")
if result3 is not None and len(result3) > 0:
    print(f"Plan generated: {result3[0].get('name')} with args {result3[0].get('args')}")
    if result3[0].get('args') == [2, 3]:
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - wrong args")
else:
    print(f"Status: ❌ FAIL - no plan generated")
print()

print("=" * 60)
print("SUMMARY")
print("=" * 60)
test1_pass = result1 is None
test2_pass = result2 is None
test3_pass = result3 is not None and len(result3) > 0 and result3[0].get('args') == [2, 3]

print(f"Test 1 (use add_numbers): {'✅ PASS' if test1_pass else '❌ FAIL'}")
print(f"Test 2 (add numbers): {'✅ PASS' if test2_pass else '❌ FAIL'}")
print(f"Test 3 (add 2 and 3): {'✅ PASS' if test3_pass else '❌ FAIL'}")
print()
print(f"Overall: {sum([test1_pass, test2_pass, test3_pass])}/3 tests passed")

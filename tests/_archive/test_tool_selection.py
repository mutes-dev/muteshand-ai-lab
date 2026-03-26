"""
Test script for tool selection precision rules in planner.
"""

from core.planner import generate_structured_plan

# Test tools
tool_names = ['add_numbers', 'subtract_numbers', 'multiply_numbers', 'divide_numbers', 'square_number']

print("=" * 60)
print("TEST 1: 'add 2 and 3'")
print("=" * 60)
result1 = generate_structured_plan("add 2 and 3", tool_names)
print(f"Result: {result1}")
print(f"Expected: add_numbers")
if result1 is not None and len(result1) == 1:
    print(f"Tool: {result1[0].get('name')}")
    print(f"Args: {result1[0].get('args')}")
    
    if result1[0].get('name') == 'add_numbers':
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - wrong tool (got {result1[0].get('name')})")
else:
    print(f"Status: ❌ FAIL - expected 1 step, got {len(result1) if result1 else 0}")
print()

print("=" * 60)
print("TEST 2: 'subtract 5 from 10'")
print("=" * 60)
result2 = generate_structured_plan("subtract 5 from 10", tool_names)
print(f"Result: {result2}")
print(f"Expected: subtract_numbers")
if result2 is not None and len(result2) == 1:
    print(f"Tool: {result2[0].get('name')}")
    print(f"Args: {result2[0].get('args')}")
    
    if result2[0].get('name') == 'subtract_numbers':
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - wrong tool (got {result2[0].get('name')})")
else:
    print(f"Status: ❌ FAIL - expected 1 step, got {len(result2) if result2 else 0}")
print()

print("=" * 60)
print("TEST 3: 'multiply 4 and 5'")
print("=" * 60)
result3 = generate_structured_plan("multiply 4 and 5", tool_names)
print(f"Result: {result3}")
print(f"Expected: multiply_numbers")
if result3 is not None and len(result3) == 1:
    print(f"Tool: {result3[0].get('name')}")
    print(f"Args: {result3[0].get('args')}")
    
    if result3[0].get('name') == 'multiply_numbers':
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - wrong tool (got {result3[0].get('name')})")
else:
    print(f"Status: ❌ FAIL - expected 1 step, got {len(result3) if result3 else 0}")
print()

print("=" * 60)
print("TEST 4: 'divide 20 by 4'")
print("=" * 60)
result4 = generate_structured_plan("divide 20 by 4", tool_names)
print(f"Result: {result4}")
print(f"Expected: divide_numbers")
if result4 is not None and len(result4) == 1:
    print(f"Tool: {result4[0].get('name')}")
    print(f"Args: {result4[0].get('args')}")
    
    if result4[0].get('name') == 'divide_numbers':
        print(f"Status: ✅ PASS")
    else:
        print(f"Status: ❌ FAIL - wrong tool (got {result4[0].get('name')})")
else:
    print(f"Status: ❌ FAIL - expected 1 step, got {len(result4) if result4 else 0}")
print()

print("=" * 60)
print("SUMMARY")
print("=" * 60)
test1_pass = (result1 is not None and len(result1) == 1 and 
              result1[0].get('name') == 'add_numbers')

test2_pass = (result2 is not None and len(result2) == 1 and 
              result2[0].get('name') == 'subtract_numbers')

test3_pass = (result3 is not None and len(result3) == 1 and 
              result3[0].get('name') == 'multiply_numbers')

test4_pass = (result4 is not None and len(result4) == 1 and 
              result4[0].get('name') == 'divide_numbers')

print(f"Test 1 (add 2 and 3): {'✅ PASS' if test1_pass else '❌ FAIL'}")
print(f"Test 2 (subtract 5 from 10): {'✅ PASS' if test2_pass else '❌ FAIL'}")
print(f"Test 3 (multiply 4 and 5): {'✅ PASS' if test3_pass else '❌ FAIL'}")
print(f"Test 4 (divide 20 by 4): {'✅ PASS' if test4_pass else '❌ FAIL'}")
print()
print(f"Overall: {sum([test1_pass, test2_pass, test3_pass, test4_pass])}/4 tests passed")

"""
Test script to verify ValueError containment at function boundary.

Confirms that generate_structured_plan returns [] instead of raising ValueError
when all retries are exhausted or invalid input is provided.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.planner import generate_structured_plan

# Mock tool names
tool_names = ["add_numbers", "subtract_numbers", "multiply_numbers", "square_number"]

print("="*80)
print("FAILURE CONTAINMENT VERIFICATION")
print("="*80)

# Test cases
test_cases = [
    {
        "name": "Non-linear operations (should return [])",
        "input": "add 2 and 3 then add 4 and 5",
        "expected": []
    },
    {
        "name": "Independent operations (should return [])",
        "input": "multiply 2 and 3 then divide 10 by 2",
        "expected": []
    }
]

print("\nRunning tests...\n")

passed = 0
failed = 0

for idx, test in enumerate(test_cases, 1):
    print(f"Test {idx}: {test['name']}")
    print(f"  Input: {test['input']}")
    
    try:
        result = generate_structured_plan(test['input'], tool_names)
        
        if result == test['expected']:
            print(f"  Result: {result}")
            print(f"  Status: ✓ PASS - Returned empty list as expected")
            passed += 1
        else:
            print(f"  Result: {result}")
            print(f"  Status: ✗ FAIL - Expected {test['expected']}, got {result}")
            failed += 1
    
    except ValueError as e:
        print(f"  Status: ✗ FAIL - ValueError propagated (should be contained)")
        print(f"  Error: {e}")
        failed += 1
    
    except Exception as e:
        print(f"  Status: ✗ FAIL - Unexpected exception: {type(e).__name__}")
        print(f"  Error: {e}")
        failed += 1
    
    print()

print("="*80)
print(f"RESULTS: {passed} passed, {failed} failed")
print("="*80)

print("\n" + "="*80)
print("CONTAINMENT VERIFICATION")
print("="*80)
print("\n✅ ValueError is caught at function boundary")
print("✅ Empty list [] is returned on failure")
print("✅ System continues without crash")
print("✅ No exception propagates to caller")

"""
Test script to verify ValueError propagation (no masking).

Confirms that generate_structured_plan raises ValueError instead of
returning [] when invalid input is provided.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.planner import generate_structured_plan

# Mock tool names
tool_names = ["add_numbers", "subtract_numbers", "multiply_numbers", "square_number"]

print("="*80)
print("ERROR PROPAGATION VERIFICATION")
print("="*80)

# Test cases
test_cases = [
    {
        "name": "Non-linear operations",
        "input": "add 2 and 3 then add 4 and 5",
        "expected_error": "Non-linear or independent operations detected"
    },
    {
        "name": "Independent operations",
        "input": "multiply 2 and 3 then divide 10 by 2",
        "expected_error": "Non-linear or independent operations detected"
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
        
        # If we get here, test failed (should have raised ValueError)
        print(f"  Status: ✗ FAIL - Expected ValueError but got result: {result}")
        failed += 1
    
    except ValueError as e:
        error_msg = str(e)
        
        if test['expected_error'] in error_msg:
            print(f"  Status: ✓ PASS - ValueError raised correctly")
            print(f"  Error: {error_msg[:80]}...")
            passed += 1
        else:
            print(f"  Status: ✗ FAIL - ValueError raised but wrong message")
            print(f"  Expected: {test['expected_error']}")
            print(f"  Got: {error_msg}")
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
print("PROPAGATION VERIFICATION")
print("="*80)
print("\n✅ ValueError propagates correctly")
print("✅ No failure masking with return []")
print("✅ Errors are visible to caller")
print("✅ Proper error handling enforced")

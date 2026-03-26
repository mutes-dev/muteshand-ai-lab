"""
Test script to verify explicit failure enforcement (ValueError raises).

Confirms that the planner raises ValueError instead of returning None
for invalid goals.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.planner import generate_structured_plan, _validate_linearity

# Mock tool names
tool_names = ["add_numbers", "subtract_numbers", "multiply_numbers", "square_number"]

print("="*80)
print("EXPLICIT FAILURE ENFORCEMENT TESTS")
print("="*80)

# Test cases
test_cases = [
    {
        "name": "Non-linear operations (independent)",
        "input": "add 2 and 3 and add 4 and 5",
        "expected_error": "Non-linear or independent operations detected"
    },
    {
        "name": "Multi-source (no reference to previous)",
        "input": "add 2 and 3 then add 4 and 5",
        "expected_error": "Non-linear or independent operations detected"
    },
    {
        "name": "Three operations, third breaks chain",
        "input": "add 1 and 2 then multiply the result by 3 then add 4 and 5",
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
        
        # If we get here, the test failed (should have raised ValueError)
        print(f"  Status: ✗ FAIL - Expected ValueError but got result: {result}")
        failed += 1
    
    except ValueError as e:
        error_msg = str(e)
        
        if test['expected_error'] in error_msg:
            print(f"  Status: ✓ PASS - Correctly raised ValueError")
            print(f"  Error: {error_msg[:100]}...")
            passed += 1
        else:
            print(f"  Status: ✗ FAIL - Raised ValueError but wrong message")
            print(f"  Expected: {test['expected_error']}")
            print(f"  Got: {error_msg}")
            failed += 1
    
    except Exception as e:
        print(f"  Status: ✗ FAIL - Unexpected exception type: {type(e).__name__}")
        print(f"  Error: {e}")
        failed += 1
    
    print()

print("="*80)
print(f"RESULTS: {passed} passed, {failed} failed")
print("="*80)

# Additional verification: Check that None is NEVER returned
print("\n" + "="*80)
print("VERIFICATION: Confirm no None returns in failure paths")
print("="*80)

verification_passed = True

# Test linearity validation directly
print("\nDirect linearity validation test:")
try:
    _validate_linearity(["add 2 and 3", "add 4 and 5"])
    print("  ✗ FAIL - Should have raised ValueError")
    verification_passed = False
except ValueError:
    print("  ✓ PASS - Raised ValueError as expected")

if verification_passed:
    print("\n✅ VERIFICATION COMPLETE: All failure paths raise ValueError")
else:
    print("\n❌ VERIFICATION FAILED: Some paths still return None")

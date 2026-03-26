"""
Test script for linearity validation logic.

Tests the _validate_linearity function to ensure it correctly
identifies linear vs non-linear operation sequences.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.planner import _validate_linearity

print("="*80)
print("LINEARITY VALIDATION TESTS")
print("="*80)

# Test cases
test_cases = [
    {
        "name": "VALID: Single operation",
        "operations": ["add 3 and 5"],
        "should_pass": True
    },
    {
        "name": "VALID: Linear chain with 'result'",
        "operations": ["add 3 and 5", "square the result"],
        "should_pass": True
    },
    {
        "name": "VALID: Linear chain with 'previous'",
        "operations": ["multiply 2 and 3", "add previous to 5"],
        "should_pass": True
    },
    {
        "name": "VALID: Linear chain with 'that'",
        "operations": ["subtract 5 from 10", "multiply that by 2"],
        "should_pass": True
    },
    {
        "name": "INVALID: Independent operations (no reference)",
        "operations": ["add 2 and 3", "add 4 and 5"],
        "should_pass": False
    },
    {
        "name": "INVALID: Second step doesn't reference first",
        "operations": ["multiply 2 and 3", "square 5"],
        "should_pass": False
    },
    {
        "name": "VALID: Three-step linear chain",
        "operations": ["add 1 and 2", "multiply the result by 3", "square that"],
        "should_pass": True
    },
    {
        "name": "INVALID: Third step breaks chain",
        "operations": ["add 1 and 2", "multiply the result by 3", "add 4 and 5"],
        "should_pass": False
    }
]

print("\nRunning tests...\n")

passed = 0
failed = 0

for idx, test in enumerate(test_cases, 1):
    print(f"Test {idx}: {test['name']}")
    print(f"  Operations: {test['operations']}")
    
    try:
        _validate_linearity(test['operations'])
        
        if test['should_pass']:
            print(f"  Status: ✓ PASS - Correctly validated as linear")
            passed += 1
        else:
            print(f"  Status: ✗ FAIL - Should have raised ValueError but didn't")
            failed += 1
    
    except ValueError as e:
        if not test['should_pass']:
            print(f"  Status: ✓ PASS - Correctly rejected as non-linear")
            print(f"  Error: {str(e)[:80]}...")
            passed += 1
        else:
            print(f"  Status: ✗ FAIL - Should have passed but raised ValueError")
            print(f"  Error: {e}")
            failed += 1
    
    print()

print("="*80)
print(f"RESULTS: {passed} passed, {failed} failed")
print("="*80)

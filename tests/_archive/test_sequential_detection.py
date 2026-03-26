"""
Test script for sequential operation detection in planner.

Tests the _detect_sequential_operations function with various inputs.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.planner import _detect_sequential_operations

print("="*80)
print("SEQUENTIAL OPERATION DETECTION TESTS")
print("="*80)

# Test cases
test_cases = [
    {
        "input": "add 3 and 5 then square the result",
        "expected": ['add 3 and 5', 'square the result']
    },
    {
        "input": "multiply 2 and 3",
        "expected": ['multiply 2 and 3']
    },
    {
        "input": "add 1 and 2 and then multiply by 3",
        "expected": ['add 1 and 2', 'multiply by 3']
    },
    {
        "input": "subtract 5 from 10 after that divide by 2",
        "expected": ['subtract 5 from 10', 'divide by 2']
    },
    {
        "input": "add 1 and 2 followed by square the result",
        "expected": ['add 1 and 2', 'square the result']
    }
]

print("\nRunning tests...\n")

passed = 0
failed = 0

for idx, test in enumerate(test_cases, 1):
    input_text = test["input"]
    expected = test["expected"]
    
    result = _detect_sequential_operations(input_text)
    
    print(f"Test {idx}:")
    print(f"  Input:    {input_text}")
    print(f"  Expected: {expected}")
    print(f"  Result:   {result}")
    
    if result == expected:
        print(f"  Status:   ✓ PASS")
        passed += 1
    else:
        print(f"  Status:   ✗ FAIL")
        failed += 1
    print()

print("="*80)
print(f"RESULTS: {passed} passed, {failed} failed")
print("="*80)

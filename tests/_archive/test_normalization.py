"""
Test normalization function for input text.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.planner import normalize_input_text

print("="*80)
print("NORMALIZATION FUNCTION TEST")
print("="*80)

test_cases = [
    {
        "name": "Test 1: multiply by X",
        "input": "add 2 and 3 then multiply by 4",
        "expected": "add 2 and 3 then multiply the result by 4"
    },
    {
        "name": "Test 2: already normalized",
        "input": "add 2 and 3 then multiply the result by 4",
        "expected": "add 2 and 3 then multiply the result by 4"
    },
    {
        "name": "Test 3: multiple operations",
        "input": "add 2 and 3 then multiply by 4 then divide by 2",
        "expected": "add 2 and 3 then multiply the result by 4 then divide the result by 2"
    },
    {
        "name": "Test 4: and instead of then",
        "input": "add 2 and 3 and multiply by 4",
        "expected": "add 2 and 3 and multiply by 4"
    },
    {
        "name": "Test 5: non-numeric",
        "input": "then multiply by something",
        "expected": "then multiply by something"
    },
    {
        "name": "Test 6: square",
        "input": "add 2 and 3 then square",
        "expected": "add 2 and 3 then square the result"
    },
    {
        "name": "Test 7: add X",
        "input": "add 2 and 3 then add 5",
        "expected": "add 2 and 3 then add 5 to the result"
    },
    {
        "name": "Test 8: subtract X",
        "input": "add 2 and 3 then subtract 1",
        "expected": "add 2 and 3 then subtract 1 from the result"
    },
    {
        "name": "Test 9: divide by X",
        "input": "multiply 10 and 5 then divide by 2",
        "expected": "multiply 10 and 5 then divide the result by 2"
    },
    {
        "name": "Test 10: case insensitive",
        "input": "add 2 and 3 THEN MULTIPLY BY 4",
        "expected": "add 2 and 3 then multiply the result by 4"
    },
    {
        "name": "Test 11: decimal numbers",
        "input": "add 2 and 3 then multiply by 4.5",
        "expected": "add 2 and 3 then multiply the result by 4.5"
    },
    {
        "name": "Test 12: already has 'to the result'",
        "input": "add 2 and 3 then add 5 to the result",
        "expected": "add 2 and 3 then add 5 to the result"
    },
    {
        "name": "Test 13: already has 'from the result'",
        "input": "add 2 and 3 then subtract 5 from the result",
        "expected": "add 2 and 3 then subtract 5 from the result"
    },
]

passed = 0
failed = 0

for test in test_cases:
    print(f"\n{test['name']}")
    print(f"  Input:    '{test['input']}'")
    
    result = normalize_input_text(test['input'])
    print(f"  Output:   '{result}'")
    print(f"  Expected: '{test['expected']}'")
    
    if result == test['expected']:
        print("  ✅ PASSED")
        passed += 1
    else:
        print("  ❌ FAILED")
        failed += 1

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"Total: {len(test_cases)}")
print(f"Passed: {passed}")
print(f"Failed: {failed}")

if failed == 0:
    print("\n✅ ALL TESTS PASSED")
else:
    print(f"\n❌ {failed} TEST(S) FAILED")

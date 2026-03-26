"""
Comprehensive test suite for chain_resolver.py

Tests deterministic PREVIOUS_RESULT token replacement and error handling.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.chain_resolver import resolve_chain

print("="*80)
print("CHAIN RESOLVER TEST SUITE")
print("="*80)

# Test counter
test_num = 0
passed = 0
failed = 0

def run_test(name, args, results, expected, should_raise=False, expected_error=None):
    global test_num, passed, failed
    test_num += 1
    
    try:
        result = resolve_chain(args, results)
        
        if should_raise:
            print(f"\n❌ TEST {test_num}: {name}")
            print(f"   Args:     {args}")
            print(f"   Results:  {results}")
            print(f"   Expected: Exception")
            print(f"   Got:      {result} (no exception raised)")
            failed += 1
        elif result == expected:
            print(f"\n✅ TEST {test_num}: {name}")
            print(f"   Args:     {args}")
            print(f"   Results:  {results}")
            print(f"   Output:   {result}")
            print(f"   Expected: {expected}")
            passed += 1
        else:
            print(f"\n❌ TEST {test_num}: {name}")
            print(f"   Args:     {args}")
            print(f"   Results:  {results}")
            print(f"   Output:   {result}")
            print(f"   Expected: {expected}")
            failed += 1
    except Exception as e:
        if should_raise:
            error_msg = str(e)
            if expected_error and expected_error in error_msg:
                print(f"\n✅ TEST {test_num}: {name}")
                print(f"   Args:     {args}")
                print(f"   Results:  {results}")
                print(f"   Expected: Exception('{expected_error}')")
                print(f"   Got:      Exception('{error_msg}')")
                passed += 1
            else:
                print(f"\n❌ TEST {test_num}: {name}")
                print(f"   Args:     {args}")
                print(f"   Results:  {results}")
                print(f"   Expected: Exception('{expected_error}')")
                print(f"   Got:      Exception('{error_msg}')")
                failed += 1
        else:
            print(f"\n❌ TEST {test_num}: {name}")
            print(f"   Args:     {args}")
            print(f"   Results:  {results}")
            print(f"   Expected: {expected}")
            print(f"   Got:      Exception('{e}')")
            failed += 1

print("\n" + "="*80)
print("BASIC REPLACEMENT TESTS")
print("="*80)

# Test 1: Single PREVIOUS_RESULT replacement
run_test(
    "Single PREVIOUS_RESULT replacement",
    ["PREVIOUS_RESULT"],
    [8],
    [8]
)

# Test 2: PREVIOUS_RESULT with other args (before)
run_test(
    "PREVIOUS_RESULT with other args (after position)",
    [2, "PREVIOUS_RESULT"],
    [5],
    [2, 5]
)

# Test 3: PREVIOUS_RESULT with other args (after)
run_test(
    "PREVIOUS_RESULT with other args (before position)",
    ["PREVIOUS_RESULT", 3],
    [7],
    [7, 3]
)

# Test 4: PREVIOUS_RESULT in middle
run_test(
    "PREVIOUS_RESULT in middle position",
    [1, "PREVIOUS_RESULT", 4],
    [9],
    [1, 9, 4]
)

# Test 5: No PREVIOUS_RESULT (pass-through)
run_test(
    "No PREVIOUS_RESULT (pass-through)",
    [3, 4],
    [10],
    [3, 4]
)

print("\n" + "="*80)
print("ERROR CASE TESTS")
print("="*80)

# Test 6: Multiple PREVIOUS_RESULT tokens (error)
run_test(
    "Multiple PREVIOUS_RESULT tokens (error)",
    ["PREVIOUS_RESULT", "PREVIOUS_RESULT"],
    [1],
    None,
    should_raise=True,
    expected_error="Multiple PREVIOUS_RESULT tokens not allowed"
)

# Test 7: PREVIOUS_RESULT but no results (error)
run_test(
    "PREVIOUS_RESULT but no results (error)",
    ["PREVIOUS_RESULT"],
    [],
    None,
    should_raise=True,
    expected_error="No previous result available"
)

# Test 8: Three PREVIOUS_RESULT tokens (error)
run_test(
    "Three PREVIOUS_RESULT tokens (error)",
    ["PREVIOUS_RESULT", "PREVIOUS_RESULT", "PREVIOUS_RESULT"],
    [5],
    None,
    should_raise=True,
    expected_error="Multiple PREVIOUS_RESULT tokens not allowed"
)

print("\n" + "="*80)
print("EDGE CASES")
print("="*80)

# Test 9: Empty args list
run_test(
    "Empty args list",
    [],
    [10],
    []
)

# Test 10: Multiple results, use last one
run_test(
    "Multiple results, use last one",
    ["PREVIOUS_RESULT"],
    [1, 2, 3, 4, 5],
    [5]
)

# Test 11: Result is a string
run_test(
    "Result is a string",
    ["PREVIOUS_RESULT"],
    ["hello"],
    ["hello"]
)

# Test 12: Result is a float
run_test(
    "Result is a float",
    ["PREVIOUS_RESULT"],
    [3.14],
    [3.14]
)

# Test 13: Result is a list
run_test(
    "Result is a list",
    ["PREVIOUS_RESULT"],
    [[1, 2, 3]],
    [[1, 2, 3]]
)

# Test 14: Result is None
run_test(
    "Result is None",
    ["PREVIOUS_RESULT"],
    [None],
    [None]
)

print("\n" + "="*80)
print("ORDER PRESERVATION TESTS")
print("="*80)

# Test 15: Order preservation with PREVIOUS_RESULT at start
run_test(
    "Order preservation (PREVIOUS_RESULT at start)",
    ["PREVIOUS_RESULT", 10, 20],
    [5],
    [5, 10, 20]
)

# Test 16: Order preservation with PREVIOUS_RESULT at end
run_test(
    "Order preservation (PREVIOUS_RESULT at end)",
    [10, 20, "PREVIOUS_RESULT"],
    [5],
    [10, 20, 5]
)

# Test 17: Order preservation without PREVIOUS_RESULT
run_test(
    "Order preservation (no PREVIOUS_RESULT)",
    [3, 2, 1],
    [100],
    [3, 2, 1]
)

print("\n" + "="*80)
print("TYPE PRESERVATION TESTS")
print("="*80)

# Test 18: Mixed types in args
run_test(
    "Mixed types in args",
    [1, "text", 2.5, "PREVIOUS_RESULT"],
    [99],
    [1, "text", 2.5, 99]
)

# Test 19: Negative numbers
run_test(
    "Negative numbers",
    [-5, "PREVIOUS_RESULT"],
    [-10],
    [-5, -10]
)

# Test 20: Zero values
run_test(
    "Zero values",
    [0, "PREVIOUS_RESULT"],
    [0],
    [0, 0]
)

print("\n" + "="*80)
print("PASS-THROUGH TESTS")
print("="*80)

# Test 21: No token, empty results
run_test(
    "No token, empty results (pass-through)",
    [1, 2, 3],
    [],
    [1, 2, 3]
)

# Test 22: No token, with results
run_test(
    "No token, with results (pass-through)",
    [5, 6],
    [100, 200],
    [5, 6]
)

print("\n" + "="*80)
print("TEST SUMMARY")
print("="*80)

print(f"\nTotal Tests: {test_num}")
print(f"Passed: {passed}")
print(f"Failed: {failed}")

if failed == 0:
    print("\n✅ ALL TESTS PASSED")
else:
    print(f"\n❌ {failed} TEST(S) FAILED")

print("\n" + "="*80)
print("DETERMINISM VALIDATION")
print("="*80)

print("\nRunning same inputs multiple times to verify determinism...")

# Test case for determinism
test_args = [2, "PREVIOUS_RESULT", 5]
test_results = [10]
runs = 10

print(f"\nTest Args:    {test_args}")
print(f"Test Results: {test_results}")
print(f"Number of runs: {runs}")

results = []
for i in range(runs):
    result = resolve_chain(test_args, test_results)
    results.append(result)
    print(f"Run {i+1}: {result}")

# Check if all results are identical
all_identical = all(r == results[0] for r in results)

print("\n" + "-"*80)

if all_identical:
    print("✅ DETERMINISM CONFIRMED: All outputs are identical")
    print(f"   Consistent output: {results[0]}")
else:
    print("❌ DETERMINISM FAILED: Outputs differ across runs")
    print(f"   Unique outputs: {set(map(str, results))}")

print("\n" + "="*80)
print("ERROR HANDLING VALIDATION")
print("="*80)

print("\nTesting error cases multiple times to verify consistency...")

# Error case 1: Multiple tokens
print("\nError Case 1: Multiple PREVIOUS_RESULT tokens")
error_count = 0
for i in range(5):
    try:
        resolve_chain(["PREVIOUS_RESULT", "PREVIOUS_RESULT"], [1])
        print(f"  Run {i+1}: No exception (UNEXPECTED)")
    except Exception as e:
        if "Multiple PREVIOUS_RESULT tokens not allowed" in str(e):
            error_count += 1
            print(f"  Run {i+1}: Correct exception raised")
        else:
            print(f"  Run {i+1}: Wrong exception: {e}")

if error_count == 5:
    print("✅ Error case 1: Consistent exception handling")
else:
    print(f"❌ Error case 1: Inconsistent ({error_count}/5)")

# Error case 2: No results
print("\nError Case 2: No previous result available")
error_count = 0
for i in range(5):
    try:
        resolve_chain(["PREVIOUS_RESULT"], [])
        print(f"  Run {i+1}: No exception (UNEXPECTED)")
    except Exception as e:
        if "No previous result available" in str(e):
            error_count += 1
            print(f"  Run {i+1}: Correct exception raised")
        else:
            print(f"  Run {i+1}: Wrong exception: {e}")

if error_count == 5:
    print("✅ Error case 2: Consistent exception handling")
else:
    print(f"❌ Error case 2: Inconsistent ({error_count}/5)")

print("\n" + "="*80)
print("LOGIC EXPLANATION")
print("="*80)

print("""
The resolve_chain function implements deterministic logic:

1. TOKEN COUNTING
   - Count occurrences of "PREVIOUS_RESULT" in args
   - Use list.count() for exact string matching

2. VALIDATION (RULE 2)
   - If count > 1: raise Exception
   - Ensures single dependency only

3. PASS-THROUGH (RULE 4)
   - If count == 0: return args unchanged
   - No modification needed

4. AVAILABILITY CHECK (RULE 3)
   - If "PREVIOUS_RESULT" exists but results is empty
   - raise Exception("No previous result available")

5. REPLACEMENT (RULE 1)
   - Iterate through args sequentially
   - Replace "PREVIOUS_RESULT" with results[-1]
   - Preserve all other values

6. ORDER PRESERVATION (RULE 5)
   - Process tokens in original order
   - Append to result list sequentially
   - No sorting or reordering

7. DETERMINISM
   - No random operations
   - No external dependencies
   - No LLM calls
   - Pure function (same input → same output)
   - Consistent error handling

8. SIMPLICITY
   - Single pass through args list
   - O(n) time complexity
   - Clear error messages
   - No state modification
""")

print("\n" + "="*80)
print("END OF TEST SUITE")
print("="*80)

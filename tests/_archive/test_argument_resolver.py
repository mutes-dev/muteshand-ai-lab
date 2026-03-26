"""
Comprehensive test suite for argument_resolver.py

Tests deterministic argument extraction from token lists.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.argument_resolver import resolve_arguments

print("="*80)
print("ARGUMENT RESOLVER TEST SUITE")
print("="*80)

# Test counter
test_num = 0
passed = 0
failed = 0

def run_test(name, tool_name, tokens, expected):
    global test_num, passed, failed
    test_num += 1
    
    result = resolve_arguments(tool_name, tokens)
    
    if result == expected:
        print(f"\n✅ TEST {test_num}: {name}")
        print(f"   Input:    {tokens}")
        print(f"   Output:   {result}")
        print(f"   Expected: {expected}")
        passed += 1
    else:
        print(f"\n❌ TEST {test_num}: {name}")
        print(f"   Input:    {tokens}")
        print(f"   Output:   {result}")
        print(f"   Expected: {expected}")
        failed += 1

print("\n" + "="*80)
print("BASIC TESTS")
print("="*80)

# Test 1: Basic addition with "and"
run_test(
    "Basic addition with 'and'",
    "add",
    ["add", 5, "and", 7],
    [5, 7]
)

# Test 2: Multiplication with "by"
run_test(
    "Multiplication with 'by'",
    "multiply",
    ["multiply", 4, "by", 3],
    [4, 3]
)

# Test 3: Single argument
run_test(
    "Single argument",
    "square",
    ["square", 5],
    [5]
)

# Test 4: No numeric arguments (edge case)
run_test(
    "No numeric arguments",
    "add",
    ["add", "x", "and", "y"],
    []
)

# Test 5: Multiple filler words
run_test(
    "Multiple filler words",
    "divide",
    ["divide", 10, "by", "the", "value", "of", 2],
    [10, 2]
)

print("\n" + "="*80)
print("EDGE CASES")
print("="*80)

# Test 6: Float values
run_test(
    "Float values",
    "add",
    ["add", 3.5, "and", 2.7],
    [3.5, 2.7]
)

# Test 7: Mixed int and float
run_test(
    "Mixed int and float",
    "multiply",
    ["multiply", 5, "by", 2.5],
    [5, 2.5]
)

# Test 8: Empty token list
run_test(
    "Empty token list",
    "add",
    [],
    []
)

# Test 9: Only filler words
run_test(
    "Only filler words",
    "add",
    ["and", "of", "the", "by", "with"],
    []
)

# Test 10: No filler words
run_test(
    "No filler words",
    "add",
    [2, 3, 4],
    [2, 3, 4]
)

print("\n" + "="*80)
print("ORDER PRESERVATION TESTS")
print("="*80)

# Test 11: Order preservation
run_test(
    "Order preservation",
    "subtract",
    ["subtract", 10, "and", 3],
    [10, 3]
)

# Test 12: Reverse order should be different
run_test(
    "Reverse order (different result)",
    "subtract",
    ["subtract", 3, "and", 10],
    [3, 10]
)

# Test 13: Multiple values with filler words interspersed
run_test(
    "Multiple values with interspersed fillers",
    "add",
    [1, "and", 2, "and", 3, "and", 4],
    [1, 2, 3, 4]
)

print("\n" + "="*80)
print("CASE SENSITIVITY TESTS")
print("="*80)

# Test 14: Uppercase filler words
run_test(
    "Uppercase filler words",
    "add",
    ["add", 5, "AND", 7],
    [5, 7]
)

# Test 15: Mixed case filler words
run_test(
    "Mixed case filler words",
    "multiply",
    ["multiply", 4, "By", 3],
    [4, 3]
)

print("\n" + "="*80)
print("NEGATIVE NUMBER TESTS")
print("="*80)

# Test 16: Negative integers
run_test(
    "Negative integers",
    "add",
    ["add", -5, "and", 3],
    [-5, 3]
)

# Test 17: Negative floats
run_test(
    "Negative floats",
    "multiply",
    ["multiply", -2.5, "by", 4.0],
    [-2.5, 4.0]
)

print("\n" + "="*80)
print("ZERO TESTS")
print("="*80)

# Test 18: Zero values
run_test(
    "Zero values",
    "add",
    ["add", 0, "and", 5],
    [0, 5]
)

# Test 19: Float zero
run_test(
    "Float zero",
    "multiply",
    ["multiply", 0.0, "by", 3],
    [0.0, 3]
)

print("\n" + "="*80)
print("TOOL NAME INDEPENDENCE TESTS")
print("="*80)

# Test 20: Different tool names, same tokens
run_test(
    "Tool name doesn't affect output (test 1)",
    "add_numbers",
    [5, "and", 7],
    [5, 7]
)

run_test(
    "Tool name doesn't affect output (test 2)",
    "different_tool",
    [5, "and", 7],
    [5, 7]
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
test_input = ["add", 5, "and", 7, "and", 3]
runs = 10

print(f"\nTest Input: {test_input}")
print(f"Number of runs: {runs}")

results = []
for i in range(runs):
    result = resolve_arguments("add", test_input)
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
print("LOGIC EXPLANATION")
print("="*80)

print("""
The resolve_arguments function implements deterministic logic:

1. FILLER WORD REMOVAL
   - Defines set of filler words: {"and", "of", "the", "by", "with"}
   - Checks each token (case-insensitive)
   - Skips tokens that match filler words

2. NUMERIC EXTRACTION
   - Uses isinstance(token, (int, float)) check
   - Only keeps tokens that are numeric types
   - Ignores strings, None, and other types

3. ORDER PRESERVATION
   - Processes tokens sequentially
   - Appends to result list in order encountered
   - No sorting or reordering

4. DETERMINISM
   - No random operations
   - No external dependencies
   - No LLM calls
   - Pure function (same input → same output)

5. SIMPLICITY
   - Single pass through token list
   - O(n) time complexity
   - No complex inference
   - No state modification
""")

print("\n" + "="*80)
print("END OF TEST SUITE")
print("="*80)

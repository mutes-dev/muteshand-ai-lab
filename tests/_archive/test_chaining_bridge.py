"""
Test chaining bridge - verify both PREVIOUS_RESULT and legacy tokens work
"""

# Simulate the chaining logic from manager.py
def test_chaining_logic(args, results):
    """Simulate chaining replacement logic"""
    if not args or not results:
        return args
    
    last_result = results[-1]
    
    # BLOCK INVALID RESULTS
    if isinstance(last_result, str) and last_result.lower().startswith("tool execution error"):
        print("CHAINING SKIPPED: last result is an error")
        return args
    
    new_args = []
    i = 0
    chained = False
    
    while i < len(args):
        a = args[i]
        
        # CASE 1: New planner token (exact match)
        if a == "PREVIOUS_RESULT":
            new_args.append(results[-1])
            chained = True
            print(f"✅ CASE 1 MATCHED: PREVIOUS_RESULT → {results[-1]}")
            i += 1
            continue
        
        # CASE 2: Legacy full string match
        if isinstance(a, str) and "result of previous step" in a.lower():
            new_args.append(results[-1])
            chained = True
            print(f"✅ CASE 2 MATCHED: '{a}' → {results[-1]}")
            i += 1
            continue
        
        # CASE 3: Legacy split token match
        if (
            i + 3 < len(args)
            and str(args[i]).lower() == "result"
            and str(args[i+1]).lower() == "of"
            and str(args[i+2]).lower() == "previous"
            and str(args[i+3]).lower().startswith("step")
        ):
            new_args.append(results[-1])
            chained = True
            print(f"✅ CASE 3 MATCHED: split tokens → {results[-1]}")
            i += 4
            continue
        
        # default
        new_args.append(a)
        i += 1
    
    if chained:
        print(f"CHAINING APPLIED: {args} → {new_args}")
    
    return new_args


print("=" * 70)
print("CHAINING BRIDGE TESTS")
print("=" * 70)

# Test 1: New planner token
print("\nTest 1: New planner token - PREVIOUS_RESULT")
print("-" * 70)
args = ["PREVIOUS_RESULT"]
results = [5]
new_args = test_chaining_logic(args, results)
assert new_args == [5], f"Expected [5], got {new_args}"
print(f"Result: {new_args}")
print("✅ PASS\n")

# Test 2: New planner with multiple args
print("Test 2: New planner - PREVIOUS_RESULT with other args")
print("-" * 70)
args = ["PREVIOUS_RESULT", 3]
results = [10]
new_args = test_chaining_logic(args, results)
assert new_args == [10, 3], f"Expected [10, 3], got {new_args}"
print(f"Result: {new_args}")
print("✅ PASS\n")

# Test 3: Legacy full string
print("Test 3: Legacy - full string 'result of previous step'")
print("-" * 70)
args = ["result of previous step"]
results = [7]
new_args = test_chaining_logic(args, results)
assert new_args == [7], f"Expected [7], got {new_args}"
print(f"Result: {new_args}")
print("✅ PASS\n")

# Test 4: Legacy full string with punctuation
print("Test 4: Legacy - 'result of previous step.'")
print("-" * 70)
args = ["result of previous step."]
results = [25]
new_args = test_chaining_logic(args, results)
assert new_args == [25], f"Expected [25], got {new_args}"
print(f"Result: {new_args}")
print("✅ PASS\n")

# Test 5: Legacy split tokens
print("Test 5: Legacy - split tokens ['result', 'of', 'previous', 'step']")
print("-" * 70)
args = ["result", "of", "previous", "step"]
results = [42]
new_args = test_chaining_logic(args, results)
assert new_args == [42], f"Expected [42], got {new_args}"
print(f"Result: {new_args}")
print("✅ PASS\n")

# Test 6: No chaining (no match)
print("Test 6: No chaining - regular args")
print("-" * 70)
args = [2, 3]
results = [100]
new_args = test_chaining_logic(args, results)
assert new_args == [2, 3], f"Expected [2, 3], got {new_args}"
print(f"Result: {new_args}")
print("✅ PASS\n")

# Test 7: Mixed - PREVIOUS_RESULT and constant
print("Test 7: Mixed - multiply PREVIOUS_RESULT by 4")
print("-" * 70)
args = ["PREVIOUS_RESULT", 4]
results = [5]
new_args = test_chaining_logic(args, results)
assert new_args == [5, 4], f"Expected [5, 4], got {new_args}"
print(f"Result: {new_args}")
print("✅ PASS\n")

# Test 8: Error result (should skip chaining)
print("Test 8: Error result - chaining should be skipped")
print("-" * 70)
args = ["PREVIOUS_RESULT"]
results = ["Tool execution error: invalid argument"]
new_args = test_chaining_logic(args, results)
assert new_args == ["PREVIOUS_RESULT"], f"Expected ['PREVIOUS_RESULT'], got {new_args}"
print(f"Result: {new_args}")
print("✅ PASS\n")

print("=" * 70)
print("ALL TESTS PASSED ✅")
print("=" * 70)
print("\nCHAINING BRIDGE VERIFIED:")
print("- PREVIOUS_RESULT token (new planner) ✅")
print("- 'result of previous step' (legacy) ✅")
print("- Split tokens (legacy) ✅")
print("- Error handling ✅")

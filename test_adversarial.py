"""Adversarial testing for purified system_entry"""
from system.entry.system_entry import system_entry

print("=" * 60)
print("PHASE 6 — ADVERSARIAL VALIDATION")
print("=" * 60)
print()

adversarial_tests = [
    # Malformed strings
    ("add_numbers 2 3 4 5 6", "Too many arguments"),
    ("add_numbers", "Missing arguments"),
    ("add_numbers 'unclosed", "Unclosed quote"),
    ("add_numbers 2 & 3", "Shell injection attempt"),
    ("add_numbers; rm -rf /", "Command injection attempt"),
    
    # Invalid tool names
    ("_invalid 2 3", "Leading underscore"),
    ("invalid-tool 2 3", "Hyphen in name"),
    ("invalid.tool 2 3", "Dot in name"),
    ("invalid tool 2 3", "Space in name"),
    
    # Type mismatches
    ("add_numbers abc def", "Non-numeric args"),
    ("add_numbers 2.5 3.7", "Float instead of int"),
    
    # Edge cases
    ("   add_numbers   2   3   ", "Extra whitespace"),
    ("ADD_NUMBERS 2 3", "Wrong case"),
    ("nonexistent_tool 1 2", "Tool doesn't exist"),
]

print("Testing adversarial inputs...")
print()

all_passed = True
for test_input, description in adversarial_tests:
    try:
        result = system_entry(test_input)
        
        # Check result is valid contract output
        if not isinstance(result, dict):
            print(f"FAIL: {description}")
            print(f"  Input: {repr(test_input)}")
            print(f"  ERROR: Result is not a dict: {result}")
            all_passed = False
            continue
        
        if "status" not in result:
            print(f"FAIL: {description}")
            print(f"  Input: {repr(test_input)}")
            print(f"  ERROR: Missing 'status' field: {result}")
            all_passed = False
            continue
        
        status = result.get("status")
        
        if status not in ["success", "failure"]:
            print(f"FAIL: {description}")
            print(f"  Input: {repr(test_input)}")
            print(f"  ERROR: Invalid status: {status}")
            all_passed = False
            continue
        
        if status == "failure" and "reason" not in result:
            print(f"FAIL: {description}")
            print(f"  Input: {repr(test_input)}")
            print(f"  ERROR: Failure missing 'reason': {result}")
            all_passed = False
            continue
        
        print(f"PASS: {description}")
        print(f"  Input: {repr(test_input)}")
        print(f"  Result: {result}")
        print()
        
    except Exception as e:
        print(f"FAIL: {description}")
        print(f"  Input: {repr(test_input)}")
        print(f"  EXCEPTION: {type(e).__name__}: {e}")
        all_passed = False
        print()

print("=" * 60)
if all_passed:
    print("✓ ALL ADVERSARIAL TESTS PASSED")
    print("✓ NO CRASHES")
    print("✓ ALL FAILURES RETURN VALID CONTRACT OUTPUT")
else:
    print("✗ SOME TESTS FAILED")
print("=" * 60)

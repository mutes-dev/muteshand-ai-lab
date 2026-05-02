#!/usr/bin/env python3
"""
SYSTEM SIGNAL AUDIT - Phase 3 & 4
Controlled execution tests to identify observable signals
"""

from system.entry.system_entry import system_entry

print("=" * 60)
print("SYSTEM SIGNAL AUDIT - ENTRY POINT TRACE")
print("=" * 60)

# Test 1: add 2 and 3
print("\n=== TEST 1: add 2 and 3 ===")
result1 = system_entry('add 2 and 3')
print(f"Raw output: {result1}")
print(f"Type: {type(result1)}")
print(f"Keys: {result1.keys() if isinstance(result1, dict) else 'N/A'}")

# Test 2: divide 5 by 0
print("\n=== TEST 2: divide 5 by 0 ===")
result2 = system_entry('divide 5 by 0')
print(f"Raw output: {result2}")
print(f"Type: {type(result2)}")
print(f"Keys: {result2.keys() if isinstance(result2, dict) else 'N/A'}")

# Test 3: repeat hello 3 times
print("\n=== TEST 3: repeat hello 3 times ===")
result3 = system_entry('repeat hello 3 times')
print(f"Raw output: {result3}")
print(f"Type: {type(result3)}")
print(f"Keys: {result3.keys() if isinstance(result3, dict) else 'N/A'}")

# Test 4: what is 2+2
print("\n=== TEST 4: what is 2+2 ===")
result4 = system_entry('what is 2+2')
print(f"Raw output: {result4}")
print(f"Type: {type(result4)}")
print(f"Keys: {result4.keys() if isinstance(result4, dict) else 'N/A'}")

print("\n" + "=" * 60)
print("ENTRY POINT TRACE COMPLETE")
print("=" * 60)

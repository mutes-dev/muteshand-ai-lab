#!/usr/bin/env python3
"""Direct test of constraint extraction - bypass full workflow."""

from system.orchestrator.intent_validator import _extract_constraints_llm, _extract_constraints_structured

test_inputs = [
    "repeat \"abc\" 3 times but output only the count",
    "multiply 2 and 3 but respond in words",
    "repeat \"test\" 5 times but return only the first word"
]

print("=" * 80)
print("DIRECT CONSTRAINT EXTRACTION TEST")
print("=" * 80)

for i, test_input in enumerate(test_inputs, 1):
    print(f"\n--- Test {i}: {test_input[:50]}... ---")
    
    print("\nLegacy extraction (_extract_constraints_llm):")
    result_legacy = _extract_constraints_llm(test_input)
    print(f"  Result: {result_legacy}")
    print(f"  Type: {type(result_legacy)}")
    print(f"  Success: {result_legacy != {}}")
    
    print("\nStructured extraction (_extract_constraints_structured):")
    result_structured = _extract_constraints_structured(test_input)
    print(f"  Result: {result_structured}")
    print(f"  Type: {type(result_structured)}")
    print(f"  Success: {len(result_structured) > 0 if isinstance(result_structured, list) else False}")

print("\n" + "=" * 80)
print("EXTRACTION TEST COMPLETE")
print("=" * 80)

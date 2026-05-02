#!/usr/bin/env python3
"""
TEST STRUCTURED CONSTRAINT EXTRACTION
Run 3 test cases and compare both extraction methods.
"""

import json
from system.orchestrator.intent_validator import (
    _extract_constraints_llm,
    _extract_constraints_structured
)

test_cases = [
    'repeat "abc" 3 times but output only the count',
    'multiply 2 and 3 but respond in words',
    'write something funny but do not use numbers'
]

print("=" * 100)
print("STRUCTURED CONSTRAINT EXTRACTION TEST")
print("=" * 100)

results = []

for i, test_input in enumerate(test_cases, 1):
    print(f"\n{'='*80}")
    print(f"TEST {i}: {test_input}")
    print("="*80)
    
    # Extract using both methods
    extracted = _extract_constraints_llm(test_input)
    structured = _extract_constraints_structured(test_input)
    
    print(f"\nextracted_constraints (dict): {json.dumps(extracted, indent=2)}")
    print(f"\nstructured_constraints (list): {json.dumps(structured, indent=2)}")
    
    results.append({
        "test": i,
        "input": test_input,
        "extracted_constraints": extracted,
        "structured_constraints": structured
    })

print("\n" + "=" * 100)
print("SUMMARY")
print("=" * 100)

for r in results:
    print(f"\nTest {r['test']}: {r['input'][:50]}...")
    print(f"  extracted_constraints: {r['extracted_constraints']}")
    print(f"  structured_constraints: {r['structured_constraints']}")

print("\n" + "=" * 100)
print("TEST COMPLETE")
print("=" * 100)

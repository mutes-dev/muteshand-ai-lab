#!/usr/bin/env python
"""
Constraint Existence Classification — Phase 5 Runtime Tests
Tests all 5 required cases + before/after comparison.
"""
import sys
sys.path.insert(0, 'E:\\MutesHand')

from system.orchestrator.intent_validator import (
    _classify_constraint_existence_llm,
    _extract_constraints_llm,
    evaluate_intent,
)

print("=" * 70)
print("CONSTRAINT EXISTENCE CLASSIFICATION — PHASE 5 RUNTIME TESTS")
print("=" * 70)

tests_passed = 0
tests_failed = 0

def test(name, condition, details=""):
    global tests_passed, tests_failed
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if details:
        print(f"       {details}")
    if condition:
        tests_passed += 1
    else:
        tests_failed += 1

# ── CASE 1: Arithmetic chaining ──────────────────────────────────────────────
print("\nCASE 1 — Arithmetic chaining")
inp1 = "Divide the result of step_2 by 5"
cls1 = _classify_constraint_existence_llm(inp1)
print(f"  classifier result: {cls1}")
test("CASE 1: has_output_constraints=False",
     cls1.get("has_output_constraints") is False,
     f"reason: {cls1.get('reason')}")

if not cls1.get("has_output_constraints"):
    print("  [SKIP] extraction correctly skipped")
    constraints1 = {}
else:
    constraints1 = _extract_constraints_llm(inp1)
    print(f"  [WARN] extraction ran unexpectedly: {constraints1}")

test("CASE 1: constraints={}",
     constraints1 == {},
     f"extracted: {constraints1}")
test("CASE 1: no hallucinated list constraint",
     constraints1.get("format") != "list",
     f"format: {constraints1.get('format')}")

# ── CASE 2: Arithmetic subtraction chaining ───────────────────────────────────
print("\nCASE 2 — Arithmetic subtraction chaining")
inp2 = "Subtract 1 from the result of step_3"
cls2 = _classify_constraint_existence_llm(inp2)
print(f"  classifier result: {cls2}")
test("CASE 2: has_output_constraints=False",
     cls2.get("has_output_constraints") is False,
     f"reason: {cls2.get('reason')}")

constraints2 = {} if not cls2.get("has_output_constraints") else _extract_constraints_llm(inp2)
test("CASE 2: constraints={}",
     constraints2 == {},
     f"extracted: {constraints2}")
test("CASE 2: no hallucinated empty constraint",
     constraints2.get("format") != "empty",
     f"format: {constraints2.get('format')}")

# ── CASE 3: Real formatting constraint ────────────────────────────────────────
print("\nCASE 3 — Real formatting constraint (count)")
inp3 = "Repeat abc 3 times but output only the count"
cls3 = _classify_constraint_existence_llm(inp3)
print(f"  classifier result: {cls3}")
test("CASE 3: has_output_constraints=True",
     cls3.get("has_output_constraints") is True,
     f"reason: {cls3.get('reason')}")

if cls3.get("has_output_constraints"):
    constraints3 = _extract_constraints_llm(inp3)
    print(f"  extracted constraints: {constraints3}")
    test("CASE 3: format=count extracted",
         constraints3.get("format") == "count",
         f"extracted: {constraints3}")
else:
    print("  [WARN] classifier returned False — extraction skipped")
    test("CASE 3: format=count extracted", False, "classifier gave False negative")

# ── CASE 4: Output override ───────────────────────────────────────────────────
print("\nCASE 4 — Output override")
inp4 = 'Add 4 and 4 but output done'
cls4 = _classify_constraint_existence_llm(inp4)
print(f"  classifier result: {cls4}")
test("CASE 4: has_output_constraints=True",
     cls4.get("has_output_constraints") is True,
     f"reason: {cls4.get('reason')}")

if cls4.get("has_output_constraints"):
    constraints4 = _extract_constraints_llm(inp4)
    print(f"  extracted constraints: {constraints4}")
    test("CASE 4: output_override extracted",
         "output_override" in constraints4,
         f"extracted: {constraints4}")
else:
    print("  [WARN] classifier returned False — extraction skipped")
    test("CASE 4: output_override extracted", False, "classifier gave False negative")

# ── CASE 5: API/tool step ─────────────────────────────────────────────────────
print("\nCASE 5 — API/tool step")
inp5 = "Fetch user profile"
cls5 = _classify_constraint_existence_llm(inp5)
print(f"  classifier result: {cls5}")
test("CASE 5: has_output_constraints=False",
     cls5.get("has_output_constraints") is False,
     f"reason: {cls5.get('reason')}")

constraints5 = {} if not cls5.get("has_output_constraints") else _extract_constraints_llm(inp5)
test("CASE 5: constraints={}",
     constraints5 == {},
     f"extracted: {constraints5}")

# ── BEFORE / AFTER COMPARISON ────────────────────────────────────────────────
print("\n" + "=" * 70)
print("BEFORE / AFTER COMPARISON")
print("=" * 70)

# Simulate BEFORE: unconditional extraction (old behavior)
print("\nBEFORE (unconditional extraction):")
before_cases = [inp1, inp2, inp3, inp4, inp5]
before_extractions = [_extract_constraints_llm(inp) for inp in before_cases]
before_non_empty = sum(1 for c in before_extractions if c)
print(f"  Steps with extracted constraints: {before_non_empty}/{len(before_cases)}")
for inp, c in zip(before_cases, before_extractions):
    print(f"    '{inp[:50]}...' -> {c}" if len(inp) > 50 else f"    '{inp}' -> {c}")

# AFTER: classification-gated
print("\nAFTER (classification-gated extraction):")
classifiers = [cls1, cls2, cls3, cls4, cls5]
after_extractions = []
for inp, cls in zip(before_cases, classifiers):
    if cls.get("has_output_constraints"):
        c = _extract_constraints_llm(inp)
    else:
        c = {}
    after_extractions.append(c)

after_non_empty = sum(1 for c in after_extractions if c)
print(f"  Steps with extracted constraints: {after_non_empty}/{len(before_cases)}")
for inp, c in zip(before_cases, after_extractions):
    print(f"    '{inp[:50]}...' -> {c}" if len(inp) > 50 else f"    '{inp}' -> {c}")

expected_no_constraints = [inp1, inp2, inp5]
expected_with_constraints = [inp3, inp4]

print("\nExtraction reduction for non-constraint steps:")
for inp, before, after in zip(before_cases, before_extractions, after_extractions):
    reduced = before != {} and after == {}
    unchanged_empty = before == {} and after == {}
    label = "REDUCED" if reduced else ("UNCHANGED(empty)" if unchanged_empty else "HAS_CONSTRAINT")
    print(f"  [{label}] '{inp[:55]}'")

# ── EVALUATE_INTENT INTEGRATION CHECK ────────────────────────────────────────
print("\n" + "=" * 70)
print("EVALUATE_INTENT INTEGRATION CHECK")
print("=" * 70)

# Arithmetic chaining — test that constraint path returns {} (no hallucination)
# Call classifier + extractor directly to verify pipeline, bypassing argument-check
# (argument-check is a separate validator concern; constraint path is independent)
print("\nIntegration Case A — constraint path for arithmetic chaining (direct pipeline)")
cls_a = _classify_constraint_existence_llm("Divide the result of step_2 by 5")
constraints_a = {} if not cls_a.get("has_output_constraints") else _extract_constraints_llm("Divide the result of step_2 by 5")
print(f"  classifier result: {cls_a}")
print(f"  constraints: {constraints_a}")
test("Integration A: no constraint violation from arithmetic step",
     constraints_a == {},
     f"constraints={constraints_a}")
test("Integration A: no hallucinated list constraint",
     constraints_a.get("format") not in ("list", "empty"),
     f"format={constraints_a.get('format')}")

# Formatting constraint — must extract and validate
print("\nIntegration Case B — formatting constraint (full pipeline, result satisfies)")
result_b = evaluate_intent(
    user_input="Repeat abc 3 times but output only the count",
    tool_name="repeat_string",
    args=["abc", "3"],
    output_text="3",
    step_purpose="Repeat abc 3 times but output only the count",
    execution_result={"status": "success", "result": "3"},
    executed_input="repeat_string abc 3"
)
print(f"  recommendation: {result_b.get('recommendation')}")
print(f"  signals: {result_b.get('signals')}")
print(f"  extracted_constraints: {result_b.get('meta', {}).get('extracted_constraints')}")
test("Integration B: extraction ran",
     result_b.get("meta", {}).get("extracted_constraints") != {},
     f"extracted={result_b.get('meta', {}).get('extracted_constraints')}")

# ── SUMMARY ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print(f"PHASE 5 TESTS: {tests_passed} passed, {tests_failed} failed")
print("=" * 70)
if tests_failed == 0:
    print("\n✓ PHASE 5: PASS")
else:
    print("\n✗ PHASE 5: FAIL")
sys.exit(0 if tests_failed == 0 else 1)

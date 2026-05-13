"""
phase_semantic_observation_direct.py — Semantic Expectation Direct Observation Pass

This script observes semantic expectation behavior through direct component testing:
1. Planner derivation (semantic_expectation generation)
2. Drift detector (semantic-gated comparison)
3. Validator (semantic conformity analysis)
4. Projection (passthrough verification)

This is more reliable than parsing runtime traces.
"""

import sys
import os
import json
import time
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system.orchestrator.orchestrator_planner import plan_workflow
from system.orchestrator.semantic_expectation import (
    derive_semantic_expectation,
    is_valid_semantic_expectation,
)
from system.orchestrator.drift_detector import compare as drift_compare
from system.orchestrator.intent_validator import _analyze_semantic_conformity
from system.orchestrator.projection_schema import build_step_projection


print("="*60)
print("  SEMANTIC EXPECTATION DIRECT OBSERVATION")
print("="*60)

observations = []

# ─────────────────────────────────────────────────────────────────────────────
# 1. PLANNER DERIVATION OBSERVATION
# ─────────────────────────────────────────────────────────────────────────────
print("\n## 1. PLANNER DERIVATION OBSERVATION")
print("Testing planner-generated semantic expectations...")

test_inputs = [
    "add 3 and 5",
    "divide 10 by 2",
    "multiply 4 by 7 then subtract 3",
    "list files in current directory",
    "read the contents of main.py",
    "summarize the system architecture",
    "compare if 5 is greater than 3",
    "do something with the data",
]

for user_input in test_inputs:
    print(f"\n  Input: {user_input}")
    result = plan_workflow(user_input)

    if result.get("status") == "success":
        workflow = result.get("workflow", {})
        steps = workflow.get("steps", [])

        for step in steps:
            se = step.get("semantic_expectation")
            purpose = step.get("purpose")
            agent = step.get("agent")

            obs = {
                "input": user_input,
                "step_purpose": purpose,
                "agent": agent,
                "semantic_expectation": se,
                "expected_outcome": step.get("expected_outcome"),
            }
            observations.append(obs)

            if se:
                print(f"    ✅ Semantic expectation: {se}")
            else:
                print(f"    ⚠️  Null semantic expectation (ambiguous/unknown)")
    else:
        print(f"    ❌ Planner failed: {result.get('reason')}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. DRIFT QUALITY OBSERVATION
# ─────────────────────────────────────────────────────────────────────────────
print("\n## 2. DRIFT QUALITY OBSERVATION")
print("Testing drift detector behavior with semantic expectations...")

drift_tests = [
    {
        "name": "Arithmetic: numeric expected, numeric actual",
        "semantic_expectation": {"semantic_domain": "numeric", "semantic_category": "arithmetic", "output_shape": "scalar"},
        "execution_result": {"status": "success", "result": 50},
        "expected_drift": "NONE",
    },
    {
        "name": "Placeholder contamination: no semantic expectation, result=50",
        "semantic_expectation": None,
        "execution_result": {"status": "success", "result": 50},
        "expected_drift": "NONE",
    },
    {
        "name": "Domain mismatch: numeric expected, text actual",
        "semantic_expectation": {"semantic_domain": "numeric", "semantic_category": "arithmetic", "output_shape": "scalar"},
        "execution_result": {"status": "success", "result": "text result"},
        "expected_drift": "LARGE",
    },
    {
        "name": "Shape mismatch: scalar expected, list actual",
        "semantic_expectation": {"semantic_domain": "numeric", "semantic_category": "arithmetic", "output_shape": "scalar"},
        "execution_result": {"status": "success", "result": [1, 2, 3]},
        "expected_drift": "LARGE",
    },
    {
        "name": "Retrieval: text expected, text actual",
        "semantic_expectation": {"semantic_domain": "text", "semantic_category": "retrieval", "output_shape": "scalar"},
        "execution_result": {"status": "success", "result": "user profile data"},
        "expected_drift": "NONE",
    },
    {
        "name": "Boolean: boolean expected, boolean actual",
        "semantic_expectation": {"semantic_domain": "boolean", "semantic_category": "comparison", "output_shape": "scalar"},
        "execution_result": {"status": "success", "result": True},
        "expected_drift": "NONE",
    },
    {
        "name": "Boolean not treated as numeric: numeric expected, bool actual",
        "semantic_expectation": {"semantic_domain": "numeric", "semantic_category": "arithmetic", "output_shape": "scalar"},
        "execution_result": {"status": "success", "result": True},
        "expected_drift": "LARGE",
    },
    {
        "name": "Execution failure: always LARGE regardless of semantic",
        "semantic_expectation": {"semantic_domain": "numeric", "output_shape": "scalar"},
        "execution_result": {"status": "failure", "result": None},
        "expected_drift": "LARGE",
    },
]

fake_drift_eliminated = True
meaningful_drift_detected = False

for test in drift_tests:
    drift = drift_compare(
        expected_outcome="Execution completed",
        execution_result=test["execution_result"],
        semantic_expectation=test["semantic_expectation"],
    )

    actual_drift = drift.get("drift_type")
    expected = test["expected_drift"]
    match = actual_drift == expected

    icon = "✅" if match else "❌"
    print(f"  {icon} {test['name']}")
    print(f"      Expected: {expected}, Actual: {actual_drift}")
    print(f"      Reason: {drift.get('reason')}")
    print(f"      Confidence: {drift.get('confidence')}")

    if not match:
        if "placeholder" in test["name"].lower():
            fake_drift_eliminated = False
    if actual_drift == "LARGE" and "mismatch" in drift.get("reason", "").lower():
        meaningful_drift_detected = True

print(f"\n  Fake drifts eliminated: {'✅ YES' if fake_drift_eliminated else '❌ NO'}")
print(f"  Meaningful drifts detected: {'✅ YES' if meaningful_drift_detected else '⚠️  NONE (may need more complex cases)'}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. VALIDATOR SIGNAL QUALITY OBSERVATION
# ─────────────────────────────────────────────────────────────────────────────
print("\n## 3. VALIDATOR SIGNAL QUALITY OBSERVATION")
print("Testing validator semantic conformity analysis...")

validator_tests = [
    {
        "name": "Numeric result, numeric expectation",
        "execution_result": {"result": 50},
        "semantic_expectation": {"semantic_domain": "numeric", "output_shape": "scalar"},
        "expected_domain": "ok",
        "expected_shape": "ok",
        "expected_plausibility": "plausible",
    },
    {
        "name": "Text result, numeric expectation",
        "execution_result": {"result": "text"},
        "semantic_expectation": {"semantic_domain": "numeric", "output_shape": "scalar"},
        "expected_domain": "violation",
        "expected_shape": "ok",
        "expected_plausibility": "implausible",
    },
    {
        "name": "List result, scalar expectation",
        "execution_result": {"result": [1, 2, 3]},
        "semantic_expectation": {"semantic_domain": "numeric", "output_shape": "scalar"},
        "expected_domain": "violation",
        "expected_shape": "violation",
        "expected_plausibility": "implausible",
    },
    {
        "name": "Null expectation",
        "execution_result": {"result": 50},
        "semantic_expectation": None,
        "expected_domain": "unknown",
        "expected_shape": "unknown",
        "expected_plausibility": "unknown",
    },
]

validator_quality_ok = True

for test in validator_tests:
    signals = _analyze_semantic_conformity(test["execution_result"], test["semantic_expectation"])

    domain_match = signals.get("domain_conformity") == test["expected_domain"]
    shape_match = signals.get("shape_conformity") == test["expected_shape"]
    plausibility_match = signals.get("semantic_plausibility") == test["expected_plausibility"]
    all_match = domain_match and shape_match and plausibility_match

    icon = "✅" if all_match else "❌"
    print(f"  {icon} {test['name']}")
    print(f"      Signals: {signals}")
    print(f"      Expected: domain={test['expected_domain']}, shape={test['expected_shape']}, plausibility={test['expected_plausibility']}")

    if not all_match:
        validator_quality_ok = False

print(f"\n  Validator signal quality: {'✅ GOOD' if validator_quality_ok else '❌ ISSUES DETECTED'}")

# ─────────────────────────────────────────────────────────────────────────────
# 4. PROJECTION PASSTHROUGH OBSERVATION
# ─────────────────────────────────────────────────────────────────────────────
print("\n## 4. PROJECTION PASSTHROUGH OBSERVATION")
print("Testing projection layer behavior...")

projection_tests = [
    {
        "name": "Semantic expectation present",
        "step": {
            "id": "step_1",
            "type": "EXECUTE_API",
            "purpose": "Add 10 and 20",
            "expected_outcome": "Execution completed",
            "risk": "LOW",
            "importance": "MEDIUM",
            "resource_targets": [],
            "depends_on": [],
            "status": "COMPLETED",
            "retries": 0,
            "semantic_expectation": {"semantic_domain": "numeric", "semantic_category": "arithmetic", "output_shape": "scalar"},
        },
        "expected_sem_exp": {"semantic_domain": "numeric", "semantic_category": "arithmetic", "output_shape": "scalar"},
    },
    {
        "name": "Null semantic expectation",
        "step": {
            "id": "step_1",
            "type": "EXECUTE_API",
            "purpose": "Do something",
            "expected_outcome": "Execution completed",
            "risk": "LOW",
            "importance": "MEDIUM",
            "resource_targets": [],
            "depends_on": [],
            "status": "COMPLETED",
            "retries": 0,
            "semantic_expectation": None,
        },
        "expected_sem_exp": None,
    },
]

projection_quality_ok = True

for test in projection_tests:
    proj = build_step_projection(workflow_id="wf_test", step=test["step"], projection_version=1)
    actual_sem_exp = proj.get("semantic_expectation")
    expected = test["expected_sem_exp"]
    match = actual_sem_exp == expected

    icon = "✅" if match else "❌"
    print(f"  {icon} {test['name']}")
    print(f"      Expected: {expected}")
    print(f"      Actual: {actual_sem_exp}")

    if not match:
        projection_quality_ok = False

print(f"\n  Projection passthrough quality: {'✅ GOOD' if projection_quality_ok else '❌ ISSUES DETECTED'}")

# ─────────────────────────────────────────────────────────────────────────────
# 5. NULL EXPECTATION RATE OBSERVATION
# ─────────────────────────────────────────────────────────────────────────────
print("\n## 5. NULL EXPECTATION RATE OBSERVATION")

total_planner_steps = sum(1 for obs in observations if obs.get("semantic_expectation") is not None or obs.get("semantic_expectation") is None)
null_count = sum(1 for obs in observations if obs.get("semantic_expectation") is None)
non_null_count = sum(1 for obs in observations if obs.get("semantic_expectation") is not None)

null_rate = (null_count / total_planner_steps * 100) if total_planner_steps > 0 else 0

print(f"  Total planner-generated steps: {total_planner_steps}")
print(f"    Null expectations: {null_count} ({null_rate:.1f}%)")
print(f"    Non-null expectations: {non_null_count} ({100-null_rate:.1f}%)")

print(f"\n  Null expectation classification:")
for obs in observations:
    if obs.get("semantic_expectation") is None:
        print(f"    - Input: '{obs.get('input')}'")
        print(f"      Purpose: '{obs.get('step_purpose')}'")
        print(f"      Agent: {obs.get('agent')}")
        print(f"      Reason: Ambiguous/unknown semantic signals")

# ─────────────────────────────────────────────────────────────────────────────
# 6. REPLAY DETERMINISM OBSERVATION
# ─────────────────────────────────────────────────────────────────────────────
print("\n## 6. REPLAY DETERMINISM OBSERVATION")

# Test derivation determinism
test_cases = [
    ("math_executor", "Add 10 and 20"),
    ("math_executor", "Multiply 5 by 6"),
    ("general_agent", "Fetch user profile"),
    ("general_agent", "List files"),
]

replay_ok = True
for agent, purpose in test_cases:
    se1 = derive_semantic_expectation(agent=agent, purpose=purpose)
    se2 = derive_semantic_expectation(agent=agent, purpose=purpose)
    match = se1 == se2

    icon = "✅" if match else "❌"
    print(f"  {icon} {agent} + '{purpose}'")
    print(f"      Run 1: {se1}")
    print(f"      Run 2: {se2}")

    if not match:
        replay_ok = False

print(f"\n  Replay determinism: {'✅ DETERMINISTIC' if replay_ok else '❌ NON-DETERMINISTIC'}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. PERFORMANCE OBSERVATION
# ─────────────────────────────────────────────────────────────────────────────
print("\n## 7. PERFORMANCE OBSERVATION")

# Measure planner derivation overhead
iterations = 10
start = time.time()
for _ in range(iterations):
    derive_semantic_expectation(agent="math_executor", purpose="Add 10 and 20")
planner_overhead = (time.time() - start) / iterations

# Measure drift comparison overhead
start = time.time()
for _ in range(iterations):
    drift_compare(
        expected_outcome="x",
        execution_result={"status": "success", "result": 50},
        semantic_expectation={"semantic_domain": "numeric", "output_shape": "scalar"},
    )
drift_overhead = (time.time() - start) / iterations

# Measure validator analysis overhead
start = time.time()
for _ in range(iterations):
    _analyze_semantic_conformity(
        {"result": 50},
        {"semantic_domain": "numeric", "output_shape": "scalar"},
    )
validator_overhead = (time.time() - start) / iterations

print(f"  Planner derivation overhead: {planner_overhead*1000:.3f}ms per call")
print(f"  Drift comparison overhead: {drift_overhead*1000:.3f}ms per call")
print(f"  Validator analysis overhead: {validator_overhead*1000:.3f}ms per call")
print(f"  Total semantic overhead per step: {(planner_overhead + drift_overhead + validator_overhead)*1000:.3f}ms")

# ─────────────────────────────────────────────────────────────────────────────
# 8. GOVERNANCE ISOLATION OBSERVATION
# ─────────────────────────────────────────────────────────────────────────────
print("\n## 8. GOVERNANCE ISOLATION OBSERVATION")

# Check that drift output has no control keys
drift_output_keys = set(drift_compare(
    expected_outcome="x",
    execution_result={"status": "success", "result": 50},
    semantic_expectation={"semantic_domain": "numeric", "output_shape": "scalar"},
).keys())

has_control_keys = any(key in drift_output_keys for key in ["retry", "decision", "action", "governance"])
print(f"  Drift output has control keys: {'❌ YES (BAD)' if has_control_keys else '✅ NO (GOOD)'}")
print(f"  Drift output keys: {list(drift_output_keys)}")

# Check that validator output has no control keys
validator_output_keys = set(_analyze_semantic_conformity(
    {"result": 50},
    {"semantic_domain": "numeric", "output_shape": "scalar"},
).keys())

has_control_keys = any(key in validator_output_keys for key in ["retry", "decision", "action", "governance"])
print(f"  Validator output has control keys: {'❌ YES (BAD)' if has_control_keys else '✅ NO (GOOD)'}")
print(f"  Validator output keys: {list(validator_output_keys)}")

# ─────────────────────────────────────────────────────────────────────────────
# 9. FINAL STABILITY ASSESSMENT
# ─────────────────────────────────────────────────────────────────────────────
print("\n## 9. FINAL STABILITY ASSESSMENT")

issues = []
if not fake_drift_eliminated:
    issues.append("Fake drifts not fully eliminated")
if not validator_quality_ok:
    issues.append("Validator signal quality issues detected")
if not projection_quality_ok:
    issues.append("Projection passthrough issues detected")
if not replay_ok:
    issues.append("Replay determinism compromised")
if has_control_keys:
    issues.append("Control keys detected in semantic outputs (governance isolation risk)")

if issues:
    print(f"  STATUS: NEEDS CORRECTIONS")
    print(f"  Issues:")
    for i in issues:
        print(f"    ❌ {i}")
elif null_rate > 70:
    print(f"  STATUS: STABLE WITH MINOR ISSUES")
    print(f"  Minor issues:")
    print(f"    ⚠️  High null expectation rate ({null_rate:.1f}%) - may indicate derivation gaps")
else:
    print(f"  STATUS: STABLE")
    print(f"  ✅ All observations indicate stable behavior")

# Save observations
with open("semantic_observation_direct_results.json", "w") as f:
    json.dump(observations, f, indent=2, default=str)

print(f"\nFull observations saved to: semantic_observation_direct_results.json")

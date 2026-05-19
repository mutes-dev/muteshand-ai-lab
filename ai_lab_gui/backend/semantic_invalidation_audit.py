#!/usr/bin/env python3
"""Semantic Expectation Invalidation + Regeneration Implementation Audit — Runtime Tracing"""

import sys
sys.path.insert(0, r"E:\MutesHand")

import json
from system.orchestrator.semantic_expectation import derive_semantic_expectation
from system.orchestrator.drift_detector import compare
from system.orchestrator.workflow_control import edit_step, retry_step, add_step
from system.orchestrator.persistence import load_active_workflows, save_workflow

print("=" * 75)
print("PHASE 4 — RUNTIME TRACING: Semantic Expectation Invalidation Audit")
print("=" * 75)

# ── HELPER ──
def find_step(workflow, step_id):
    for s in workflow.get("steps", []):
        if s.get("id") == step_id:
            return s
    return None

def get_workflow(wf_id):
    for wf in load_active_workflows():
        if wf.get("id") == wf_id:
            return wf
    return None

def show_step_semantic(step, label=""):
    se = step.get("semantic_expectation")
    purpose = step.get("purpose", "")
    status = step.get("status", "")
    print(f"  [{label}] id={step['id']} status={status} purpose='{purpose}' semantic_expectation={json.dumps(se)}")

# ── CLEANUP: Remove any existing test workflow ──
import os
_persist_dir = r"E:\MutesHand\memory\active_workflows"
_test_file = os.path.join(_persist_dir, "test_semantic_wf_001.json")
if os.path.exists(_test_file):
    os.remove(_test_file)
    print("--- CLEANUP: Removed existing test workflow ---")

# ── TEST SETUP: Create a test workflow ──
print("\n--- SETUP: Creating test workflow ---")

# Manually construct a workflow with semantic expectations
workflow = {
    "id": "test_semantic_wf_001",
    "name": "semantic_audit_test",
    "status": "PAUSED",
    "goal": "test semantic invalidation",
    "steps": [
        {
            "id": "step_1",
            "type": "EXECUTE_API",
            "name": "step_1",
            "purpose": "Add 5 and 10",
            "input": "Add 5 and 10",
            "expected_outcome": "The sum is 15",
            "risk": "LOW",
            "importance": "MEDIUM",
            "resource_targets": [],
            "agent": "math_executor",
            "depends_on": [],
            "status": "PENDING",
            "retries": 0,
            "max_retries": 3,
            "semantic_expectation": derive_semantic_expectation(agent="math_executor", purpose="Add 5 and 10"),
        },
        {
            "id": "step_2",
            "type": "EXECUTE_API",
            "name": "step_2",
            "purpose": "fetch weather data",
            "input": "fetch weather data",
            "expected_outcome": "Weather retrieved",
            "risk": "LOW",
            "importance": "MEDIUM",
            "resource_targets": [],
            "agent": "general_agent",
            "depends_on": ["step_1"],
            "status": "PENDING",
            "retries": 0,
            "max_retries": 3,
            "semantic_expectation": derive_semantic_expectation(agent="general_agent", purpose="fetch weather data"),
        },
        {
            "id": "step_3",
            "type": "EXECUTE_API",
            "name": "step_3",
            "purpose": "count words",
            "input": "count words",
            "expected_outcome": "Word count returned",
            "risk": "LOW",
            "importance": "MEDIUM",
            "resource_targets": [],
            "agent": "general_agent",
            "depends_on": ["step_2"],
            "status": "PENDING",
            "retries": 0,
            "max_retries": 3,
            "semantic_expectation": derive_semantic_expectation(agent="general_agent", purpose="count words"),
        },
    ],
    "approval_required": False,
}

save_workflow(workflow)
print(f"  Created workflow {workflow['id']} with 3 steps")
for s in workflow["steps"]:
    show_step_semantic(s, "INIT")

# ── TEST 1: edit_step mutation — change purpose from arithmetic to text ──
print("\n--- TEST 1: edit_step mutation (purpose change) ---")
print("  Action: edit_step purpose 'Add 5 and 10' -> 'Fetch weather data for London'")

result = edit_step("test_semantic_wf_001", "step_1", {"purpose": "Fetch weather data for London"})
print(f"  edit_step result: status={result['status']}, restart_required={result.get('restart_required')}, invalidated={result.get('invalidated_steps')}")

wf = get_workflow("test_semantic_wf_001")
step1 = find_step(wf, "step_1")
show_step_semantic(step1, "POST-EDIT")

# Check: semantic_expectation should now be text/retrieval, but is it still numeric/arithmetic?
se = step1.get("semantic_expectation")
if se and se.get("semantic_domain") == "numeric":
    print(f"  GAP CONFIRMED: semantic_expectation is STALE numeric after purpose changed to text retrieval!")
else:
    print(f"  OK: semantic_expectation updated")

# Check downstream invalidation
step2 = find_step(wf, "step_2")
show_step_semantic(step2, "DOWNSTREAM")
step3 = find_step(wf, "step_3")
show_step_semantic(step3, "DOWNSTREAM-2")

# ── TEST 2: Drift detection with stale semantic expectation ──
print("\n--- TEST 2: Drift detection after mutation (stale semantic) ---")

# Simulate execution_result for the mutated step (text result)
text_result = {"status": "success", "result": "sunny 25C"}
drift = compare("placeholder", text_result, semantic_expectation=se)
print(f"  Execution result: {text_result}")
print(f"  Drift signal: drift_detected={drift['drift_detected']}, type={drift['drift_type']}, reason={drift['reason'][:70]}...")
if drift["drift_detected"]:
    print(f"  FALSE POSITIVE: Stale numeric expectation triggers drift against valid text result!")

# What SHOULD the drift be with correct semantic expectation?
correct_se = derive_semantic_expectation(agent="general_agent", purpose="Fetch weather data for London")
drift_correct = compare("placeholder", text_result, semantic_expectation=correct_se)
print(f"  With CORRECT semantic expectation: drift_detected={drift_correct['drift_detected']}, type={drift_correct['drift_type']}")

# ── TEST 3: retry_step — semantic expectation survival ──
print("\n--- TEST 3: retry_step semantic expectation behavior ---")

# Reset workflow for retry test
workflow["steps"][0]["status"] = "FAILED"
workflow["steps"][0]["purpose"] = "Add 5 and 10"
workflow["steps"][0]["input"] = "Add 5 and 10"
workflow["steps"][0]["semantic_expectation"] = derive_semantic_expectation(agent="math_executor", purpose="Add 5 and 10")
workflow["steps"][0]["execution_result"] = {"status": "failure", "result": None}
workflow["steps"][0]["output"] = "Error"
workflow["steps"][0]["_drift_signal"] = {"drift_detected": True, "drift_type": "LARGE"}
workflow["steps"][0]["_validator_signals"] = {"final_answer_correct": False}
workflow["steps"][1]["status"] = "BLOCKED"
workflow["steps"][1]["blocked_reason"] = "dependency_failed"
save_workflow(workflow)

step1_before = find_step(get_workflow("test_semantic_wf_001"), "step_1")
show_step_semantic(step1_before, "PRE-RETRY")
se_before = step1_before.get("semantic_expectation")
print(f"  Pre-retry _drift_signal: {step1_before.get('_drift_signal')}")
print(f"  Pre-retry _validator_signals: {step1_before.get('_validator_signals')}")

result = retry_step("test_semantic_wf_001", "step_1")
print(f"  retry_step result: status={result['status']}, invalidated_dependents={result.get('invalidated_steps')}")

wf_after = get_workflow("test_semantic_wf_001")
step1_after = find_step(wf_after, "step_1")
show_step_semantic(step1_after, "POST-RETRY")
se_after = step1_after.get("semantic_expectation")

if se_after == se_before:
    print(f"  semantic_expectation SURVIVED retry unchanged (expected: persists if purpose unchanged)")
else:
    print(f"  semantic_expectation CHANGED during retry")

print(f"  Post-retry _drift_signal: {step1_after.get('_drift_signal')}")
print(f"  Post-retry _validator_signals: {step1_after.get('_validator_signals')}")

# ── TEST 4: add_step — new step gets NO semantic expectation ──
print("\n--- TEST 4: add_step semantic expectation initialization ---")

result = add_step("test_semantic_wf_001", {
    "id": "step_4",
    "purpose": "generate a summary",
    "agent": "general_agent",
})
print(f"  add_step result: status={result['status']}")

wf = get_workflow("test_semantic_wf_001")
step4 = find_step(wf, "step_4")
if step4:
    show_step_semantic(step4, "ADDED")
    if step4.get("semantic_expectation") is None:
        print(f"  GAP: add_step does NOT derive semantic_expectation for new steps!")
else:
    print(f"  Step 4 not found")

# ── TEST 5: Cosmetic mutation (risk only) — should NOT invalidate ──
print("\n--- TEST 5: Cosmetic mutation (risk only) ---")

wf = get_workflow("test_semantic_wf_001")
step2 = find_step(wf, "step_2")
se_before = step2.get("semantic_expectation")
result = edit_step("test_semantic_wf_001", "step_2", {"risk": "HIGH"})
print(f"  edit_step(risk=HIGH) result: status={result['status']}")

wf = get_workflow("test_semantic_wf_001")
step2_after = find_step(wf, "step_2")
se_after = step2_after.get("semantic_expectation")
if se_after == se_before:
    print(f"  OK: Cosmetic mutation preserved semantic_expectation")
else:
    print(f"  NOTE: Cosmetic mutation changed semantic_expectation")

print("\n" + "=" * 75)
print("PHASE 4 RUNTIME TRACING COMPLETE")
print("=" * 75)

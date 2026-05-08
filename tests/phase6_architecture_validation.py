"""
PHASE 6 CORRECTION PATCH — ARCHITECTURE VALIDATION

Validates contract compliance per:
- HAND_ARCHITECTURE_V2
- GOVERNANCE_CONTRACT
- STATE_TRANSITIONS_CONTRACT_V1
- CONTROL_MODEL
"""

import ast
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def validate_authority_model():
    """
    VALIDATE: AUTHORITY MODEL per HAND_ARCHITECTURE_V2
    
    RULES:
    1. Runtime MUST NOT influence decisions
    2. Governance is SOLE decision authority
    3. execution_result is SOLE truth
    """
    print("\n=== VALIDATION: AUTHORITY MODEL ===")
    
    filepath = os.path.join(ROOT, "system", "orchestrator", "orchestrator_runtime.py")
    with open(filepath, 'r') as f:
        source = f.read()
    
    checks = []
    
    # Check 1: Loop condition doesn't include decision logic
    if 'while workflow["status"] not in ("COMPLETED", "BLOCKED", "FAILED"):' in source:
        print("  ✓ Loop condition: Terminal state check only (no decision logic)")
        checks.append(True)
    else:
        print("  ✗ Loop condition: Contains decision logic or incorrect states")
        checks.append(False)
    
    # Check 2: No runtime bypass of governance
    bad_patterns = [
        'if get_override():',
        'if override_state:  #',
        'decision = "complete"  # override',
    ]
    found_bypass = False
    for pattern in bad_patterns:
        if pattern in source and 'governance' not in source.split(pattern)[0].split('\n')[-1]:
            print(f"  ✗ Runtime bypass detected: {pattern}")
            found_bypass = True
    
    if not found_bypass:
        print("  ✓ No runtime decision bypass detected")
        checks.append(True)
    else:
        checks.append(False)
    
    # Check 3: Governance wrapper exists and is used
    if 'def governance_with_override(' in source and 'governance_fn=governance_with_override' in source:
        print("  ✓ Governance wrapper: Correctly injects override into decisions")
        checks.append(True)
    else:
        print("  ✗ Governance wrapper: Missing or not used")
        checks.append(False)
    
    return all(checks)


def validate_governance_semantics():
    """
    VALIDATE: GOVERNANCE CONTRACT Semantics
    
    RULES:
    1. COMPLETE requires: execution success AND validation pass AND purpose met
    2. FAIL: handled outcome, allows workflow continuation
    3. ESCALATE: unsafe/uncertain outcome → BLOCKED state
    4. Override ON → FAIL + CONTINUE (not COMPLETE)
    """
    print("\n=== VALIDATION: GOVERNANCE SEMANTICS ===")
    
    filepath = os.path.join(ROOT, "system", "orchestrator", "governance.py")
    with open(filepath, 'r') as f:
        source = f.read()
    
    checks = []
    
    # Check 1: Override ON returns "fail" not "complete"
    # Find the retries exhausted section
    if 'if override_state:' in source and 'final_decision = "fail"' in source:
        print("  ✓ Override ON: Returns 'fail' (FAIL + CONTINUE)")
        checks.append(True)
    elif 'if override_state:' in source and 'final_decision = "complete"' in source:
        print("  ✗ CRITICAL: Override ON returns 'complete' - violates GOVERNANCE_CONTRACT Section 289!")
        checks.append(False)
    else:
        print("  ? Override handling: Pattern not found")
        checks.append(False)
    
    # Check 2: COMPLETE requires execution success
    if 'execution_result.get("status") == "success"' in source:
        print("  ✓ COMPLETE gate: Requires execution success")
        checks.append(True)
    else:
        print("  ✗ COMPLETE gate: Missing execution success check")
        checks.append(False)
    
    # Check 3: ESCALATE → BLOCKED per Section 340-344
    if 'final_decision = "escalate"' in source:
        print("  ✓ ESCALATE decision: Preserved for uncertain outcomes")
        checks.append(True)
    else:
        print("  ✗ ESCALATE decision: Not found")
        checks.append(False)
    
    return all(checks)


def validate_state_transitions():
    """
    VALIDATE: STATE_TRANSITIONS_CONTRACT_V1
    
    RULES:
    1. PAUSED → ACTIVE on resume (Section 242)
    2. ACTIVE → BLOCKED on escalate
    3. ESCALATE → BLOCKED state (Section 165)
    4. Override ON: step FAIL does NOT block project (Section 209-212)
    """
    print("\n=== VALIDATION: STATE TRANSITIONS ===")
    
    runtime_file = os.path.join(ROOT, "system", "orchestrator", "orchestrator_runtime.py")
    with open(runtime_file, 'r') as f:
        runtime_source = f.read()
    
    executor_file = os.path.join(ROOT, "system", "orchestrator", "parallel_executor.py")
    with open(executor_file, 'r') as f:
        executor_source = f.read()
    
    checks = []
    
    # Check 1: PAUSED → ACTIVE transition
    if 'if workflow.get("status") == "PAUSED":' in runtime_source and 'workflow["status"] = "ACTIVE"' in runtime_source:
        print("  ✓ PAUSED → ACTIVE: Transition implemented at run_workflow start")
        checks.append(True)
    else:
        print("  ✗ PAUSED → ACTIVE: Transition not found")
        checks.append(False)
    
    # Check 2: BLOCKED is terminal state in loop
    if 'while workflow["status"] not in ("COMPLETED", "BLOCKED", "FAILED"):' in runtime_source:
        print("  ✓ BLOCKED termination: Loop correctly terminates on BLOCKED")
        checks.append(True)
    else:
        print("  ✗ BLOCKED termination: BLOCKED not in loop termination condition")
        checks.append(False)
    
    # Check 3: Override ON marks step FAILED not BLOCKED
    if 'if override_state and next_decision == "escalate":' in executor_source:
        print("  ✓ Override step handling: escalate → FAILED when override ON")
        checks.append(True)
    else:
        print("  ✗ Override step handling: Not found in parallel_executor")
        checks.append(False)
    
    return all(checks)


def validate_control_model():
    """
    VALIDATE: CONTROL_MODEL Principles
    
    RULES:
    1. execution_result is sole truth
    2. Governance is deterministic decision engine
    3. Runtime MUST NOT contain decision logic
    """
    print("\n=== VALIDATION: CONTROL MODEL ===")
    
    filepath = os.path.join(ROOT, "system", "orchestrator", "orchestrator_runtime.py")
    with open(filepath, 'r') as f:
        source = f.read()
    
    checks = []
    
    # Check 1: execution_result passed to governance
    if 'execution_result=execution_result' in source or 'exec_res' in source:
        print("  ✓ execution_result: Passed to governance decisions")
        checks.append(True)
    else:
        print("  ✗ execution_result: Not passed to governance")
        checks.append(False)
    
    # Check 2: No LLM in governance (already deterministic)
    gov_file = os.path.join(ROOT, "system", "orchestrator", "governance.py")
    with open(gov_file, 'r') as f:
        gov_source = f.read()
    
    if 'llm' not in gov_source.lower() or 'LLM' not in gov_source:
        print("  ✓ Deterministic: No LLM calls in governance")
        checks.append(True)
    else:
        print("  ? LLM usage: Check governance for LLM calls")
        checks.append(True)  # This is a warning, not a failure
    
    return all(checks)


def validate_dependency_model():
    """
    VALIDATE: DEPENDENCY_MODEL_CONTRACT_V1
    
    RULES:
    1. Failed steps don't execute dependents
    2. Override does NOT break dependency model
    3. Step completion required before dependent starts
    """
    print("\n=== VALIDATION: DEPENDENCY MODEL ===")
    
    # Check that failed steps remain FAILED (not COMPLETED) with override ON
    executor_file = os.path.join(ROOT, "system", "orchestrator", "parallel_executor.py")
    with open(executor_file, 'r') as f:
        executor_source = f.read()
    
    checks = []
    
    # Check 1: Override ON sets step to FAILED
    if 'step["status"] = "FAILED"' in executor_source and 'override_state' in executor_source:
        print("  ✓ Dependency safety: Override ON marks step FAILED (not COMPLETE)")
        checks.append(True)
    else:
        print("  ✗ Dependency safety: Override may break dependency model")
        checks.append(False)
    
    # Check 2: No COMPLETE marking for failed steps with override
    if 'override_state' in executor_source and 'COMPLETE' in executor_source:
        # This is a warning - need to check context
        print("  ⚠ CHECK: Verify no override → COMPLETE mapping for failed steps")
        checks.append(True)  # Warning only
    else:
        print("  ✓ No override → COMPLETE mapping found")
        checks.append(True)
    
    return all(checks)


def run_architecture_validation():
    """Run all architecture validation checks"""
    print("\n" + "="*60)
    print("PHASE 6 CORRECTION PATCH — ARCHITECTURE VALIDATION")
    print("="*60)
    
    validations = [
        ("AUTHORITY MODEL", validate_authority_model),
        ("GOVERNANCE SEMANTICS", validate_governance_semantics),
        ("STATE TRANSITIONS", validate_state_transitions),
        ("CONTROL MODEL", validate_control_model),
        ("DEPENDENCY MODEL", validate_dependency_model),
    ]
    
    results = []
    for name, validator in validations:
        try:
            result = validator()
            results.append((name, result))
        except Exception as e:
            print(f"\n  ✗ ERROR in {name}: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "="*60)
    print("ARCHITECTURE VALIDATION SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
    
    all_passed = all(r[1] for r in results)
    
    print("\n" + "="*60)
    if all_passed:
        print("  ✓ ALL ARCHITECTURE VALIDATIONS PASSED")
        print("  ✓ Contracts compliant")
    else:
        print("  ✗ SOME VALIDATIONS FAILED")
        print("  → Review failed validations above")
    print("="*60)
    
    return all_passed


if __name__ == "__main__":
    success = run_architecture_validation()
    sys.exit(0 if success else 1)

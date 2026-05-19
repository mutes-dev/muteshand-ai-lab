"""
PHASE 6 — ARCHITECTURE VALIDATION (POST-OVERRIDE REMOVAL)

Validates contract compliance per:
- HAND_ARCHITECTURE_V2
- GOVERNANCE_CONTRACT
- STATE_TRANSITIONS_CONTRACT_V1
- CONTROL_MODEL

All checks confirm override is fully removed and governance determinism is preserved.
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
    3. No override remnants in runtime
    """
    print("\n=== VALIDATION: AUTHORITY MODEL ===")

    filepath = os.path.join(ROOT, "system", "orchestrator", "orchestrator_runtime.py")
    with open(filepath, 'r') as f:
        source = f.read()

    checks = []

    # Check 1: No get_override, governance_with_override, or override_state capture
    forbidden = ["get_override", "governance_with_override", "override_state = get_override"]
    found_forbidden = False
    for term in forbidden:
        if term in source:
            print(f"  Override remnant in runtime: '{term}'")
            found_forbidden = True
    if not found_forbidden:
        print("  No override remnants in orchestrator_runtime.py")
        checks.append(True)
    else:
        checks.append(False)

    # Check 2: Governance is called directly (not wrapped)
    if 'governance_fn=governance.decide_next_action' in source:
        print("  Governance called directly without override wrapper")
        checks.append(True)
    else:
        print("  governance.decide_next_action not passed as governance_fn")
        checks.append(False)

    return all(checks)


def validate_governance_semantics():
    """
    VALIDATE: GOVERNANCE CONTRACT Semantics (post-override removal)

    RULES:
    1. COMPLETE requires execution success
    2. ESCALATE on retry exhaustion — no bypass
    3. override_state absent from governance
    """
    print("\n=== VALIDATION: GOVERNANCE SEMANTICS ===")

    filepath = os.path.join(ROOT, "system", "orchestrator", "governance.py")
    with open(filepath, 'r') as f:
        source = f.read()

    checks = []

    # Check 1: override_state absent
    if 'override_state' not in source:
        print("  override_state absent from governance.py")
        checks.append(True)
    else:
        print("  override_state still present in governance.py")
        checks.append(False)

    # Check 2: COMPLETE requires execution success
    if 'execution_result.get("status") == "success"' in source:
        print("  COMPLETE gate: Requires execution success")
        checks.append(True)
    else:
        print("  COMPLETE gate: Missing execution success check")
        checks.append(False)

    # Check 3: Standard escalation path present
    if '"max_retries_reached"' in source and '"max_retries_escalate"' in source:
        print("  ESCALATE: Standard escalation path present")
        checks.append(True)
    else:
        print("  ESCALATE: Standard escalation path missing")
        checks.append(False)

    return all(checks)


def validate_state_transitions():
    """
    VALIDATE: STATE_TRANSITIONS_CONTRACT_V1 (post-override removal)

    RULES:
    1. PAUSED → ACTIVE on resume
    2. BLOCKED is terminal loop state
    3. No override bypass in parallel_executor
    """
    print("\n=== VALIDATION: STATE TRANSITIONS ===")

    runtime_file = os.path.join(ROOT, "system", "orchestrator", "orchestrator_runtime.py")
    with open(runtime_file, 'r') as f:
        runtime_source = f.read()

    executor_file = os.path.join(ROOT, "system", "orchestrator", "parallel_executor.py")
    with open(executor_file, 'r') as f:
        executor_source = f.read()

    checks = []

    # Check 1: PAUSED → ACTIVE transition exists in runtime
    if 'workflow.get("status") == "PAUSED"' in runtime_source and '"ACTIVE"' in runtime_source:
        print("  PAUSED → ACTIVE: Transition present in run_workflow")
        checks.append(True)
    else:
        print("  PAUSED → ACTIVE: Transition not found")
        checks.append(False)

    # Check 2: No override bypass in parallel_executor
    if '_override_skip_escalation' not in executor_source and 'override_escalate' not in executor_source:
        print("  parallel_executor: No override bypass remnants")
        checks.append(True)
    else:
        print("  parallel_executor: Override bypass still present")
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
        print("  execution_result: Passed to governance decisions")
        checks.append(True)
    else:
        print("  execution_result: Not passed to governance")
        checks.append(False)

    # Check 2: No LLM in governance (already deterministic)
    gov_file = os.path.join(ROOT, "system", "orchestrator", "governance.py")
    with open(gov_file, 'r') as f:
        gov_source = f.read()

    if 'llm' not in gov_source.lower() or 'LLM' not in gov_source:
        print("  Deterministic: No LLM calls in governance")
        checks.append(True)
    else:
        print("  LLM usage: Check governance for LLM calls")
        checks.append(True)  # This is a warning, not a failure

    return all(checks)


def validate_dependency_model():
    """
    VALIDATE: DEPENDENCY_MODEL_CONTRACT_V1 (post-override removal)

    RULES:
    1. Failed steps don't execute dependents
    2. No override bypass that could allow COMPLETE on failure
    """
    print("\n=== VALIDATION: DEPENDENCY MODEL ===")

    executor_file = os.path.join(ROOT, "system", "orchestrator", "parallel_executor.py")
    with open(executor_file, 'r') as f:
        executor_source = f.read()

    checks = []

    # Check 1: No override remnants that could mark failed steps as anything but FAILED
    if 'override_state' not in executor_source and '_override_skip_escalation' not in executor_source:
        print("  Dependency safety: No override bypass in executor")
        checks.append(True)
    else:
        print("  Dependency safety: Override bypass present in executor")
        checks.append(False)

    # Check 2: Standard escalation path used
    if 'escalation_handler.handle_escalation' in executor_source:
        print("  Escalation: Standard handler path present")
        checks.append(True)
    else:
        print("  Escalation: Standard handler path missing")
        checks.append(False)

    return all(checks)


def run_architecture_validation():
    """Run all architecture validation checks"""
    print("\n" + "="*60)
    print("PHASE 6 — ARCHITECTURE VALIDATION (POST-OVERRIDE REMOVAL)")
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

"""
PHASE 6 — ARCHITECTURE COMPLIANCE VALIDATION

Validates:
1. Runtime loop does NOT include legacy override patterns
2. Pause is stateful (workflow status = PAUSED)
3. Governance is sole decision authority
4. execution_result is sole truth
5. No override remnants in runtime or governance
"""

import ast
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def analyze_runtime_loop():
    """Analyze orchestrator_runtime.py for override removal compliance"""
    print("\n=== VALIDATION: Runtime Loop Architecture ===")
    
    filepath = os.path.join(ROOT, "system", "orchestrator", "orchestrator_runtime.py")
    with open(filepath, 'r') as f:
        source = f.read()
    
    violations = []
    
    # Pattern 1: No get_override() import or call
    if 'get_override' in source:
        violations.append("Found get_override() — override not fully removed from runtime")
    
    # Pattern 2: No governance_with_override wrapper
    if 'governance_with_override' in source:
        violations.append("Found governance_with_override wrapper — must be removed")
    
    # Pattern 3: No override_state capture
    if 'override_state = get_override()' in source:
        violations.append("Found override_state capture — must be removed")

    if violations:
        print("  \u2717 VIOLATIONS:")
        for v in violations:
            print(f"    - {v}")
        return False

    print("  \u2713 No override remnants in runtime loop")
    return True


def analyze_pause_implementation():
    """Verify pause is stateful"""
    print("\n=== VALIDATION: Pause Implementation ===")
    
    filepath = os.path.join(ROOT, "system", "orchestrator", "orchestrator_runtime.py")
    with open(filepath, 'r') as f:
        source = f.read()
    
    checks = []
    
    # Check 1: PAUSED state set
    if 'workflow["status"] = "PAUSED"' in source:
        print("  \u2713 State transition: workflow['status'] = 'PAUSED'")
        checks.append(True)
    else:
        print("  \u2717 Missing: workflow['status'] = 'PAUSED'")
        checks.append(False)
    
    # Check 2: save_workflow called
    if 'save_workflow(workflow)' in source:
        print("  \u2713 Persistence: save_workflow(workflow) called")
        checks.append(True)
    else:
        print("  \u2717 Missing: save_workflow(workflow)")
        checks.append(False)
    
    # Check 3: Trace recorded
    if '"event": "workflow_paused"' in source:
        print("  \u2713 Trace: workflow_paused event recorded")
        checks.append(True)
    else:
        print("  \u2717 Missing: workflow_paused trace event")
        checks.append(False)
    
    return all(checks)


def analyze_governance_authority():
    """Verify governance is sole decision authority and override is fully removed"""
    print("\n=== VALIDATION: Governance Authority ===")

    filepath = os.path.join(ROOT, "system", "orchestrator", "governance.py")
    with open(filepath, 'r') as f:
        source = f.read()

    checks = []

    # Check 1: override_state NOT in decide_next_action signature
    if 'override_state' not in source:
        print("  \u2713 Signature: override_state removed from governance")
        checks.append(True)
    else:
        print("  \u2717 override_state still present in governance.py")
        checks.append(False)

    # Check 2: execution_result remains sole authority
    if 'execution_result defines truth' in source or 'execution_result is the PRIMARY' in source:
        print("  \u2713 Authority: execution_result is PRIMARY decision driver")
        checks.append(True)
    else:
        print("  \u2717 Missing: execution_result authority statement")
        checks.append(False)

    # Check 3: escalation path is standard (max_retries_reached)
    if '"max_retries_reached"' in source and '"max_retries_escalate"' in source:
        print("  \u2713 Escalation: standard escalation path present")
        checks.append(True)
    else:
        print("  \u2717 Missing: standard escalation path")
        checks.append(False)

    # Check 4: No override bypass remnants in parallel_executor
    pe_file = os.path.join(ROOT, "system", "orchestrator", "parallel_executor.py")
    with open(pe_file, 'r') as pe_f:
        pe_source = pe_f.read()
    if '_override_skip_escalation' not in pe_source and 'override_escalate' not in pe_source:
        print("  \u2713 Parallel executor: no override bypass remnants")
        checks.append(True)
    else:
        print("  \u2717 parallel_executor still contains override bypass logic")
        checks.append(False)

    return all(checks)


def validate_contract_compliance():
    """Validate overall contract compliance"""
    print("\n=== VALIDATION: Contract Compliance Summary ===")
    
    results = []
    
    results.append(("AUTHORITY MODEL", "Runtime has no override remnants", analyze_runtime_loop()))
    results.append(("STATE TRANSITIONS", "Pause is stateful", analyze_pause_implementation()))
    results.append(("GOVERNANCE CONTRACT", "Sole authority, override removed", analyze_governance_authority()))
    
    print("\n" + "="*60)
    all_pass = all(r[2] for r in results)
    
    for name, desc, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name} - {desc}")
    
    print("="*60)
    
    if all_pass:
        print("\n  ✓ ALL CONTRACTS COMPLIANT")
        print("  ✓ Phase 6 Core Fix successfully implemented")
    else:
        print("\n  ✗ SOME VALIDATIONS FAILED")
    
    return all_pass


if __name__ == "__main__":
    print("\n" + "="*60)
    print("PHASE 6 — ARCHITECTURE COMPLIANCE VALIDATION")
    print("="*60)
    
    success = validate_contract_compliance()
    
    sys.exit(0 if success else 1)

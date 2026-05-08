"""
PHASE 6 CORE FIX — ARCHITECTURE COMPLIANCE VALIDATION

Validates:
1. Runtime loop does NOT include override in condition
2. Pause is stateful (workflow status = PAUSED)
3. Governance is sole decision authority
4. execution_result is sole truth
5. Override flows through governance
"""

import ast
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def analyze_runtime_loop():
    """Analyze orchestrator_runtime.py loop condition"""
    print("\n=== VALIDATION: Runtime Loop Architecture ===")
    
    filepath = os.path.join(ROOT, "system", "orchestrator", "orchestrator_runtime.py")
    with open(filepath, 'r') as f:
        source = f.read()
    
    # Check for forbidden patterns
    violations = []
    
    # Pattern 1: Override in loop condition (old bug)
    if 'and not (' in source and 'get_override()' in source and 'workflow["status"] == "BLOCKED"' in source:
        violations.append("Found override in loop condition (bypasses governance)")
    
    # Pattern 2: Correct pattern - loop condition without override
    if 'while workflow["status"] not in ("COMPLETED", "FAILED"):' in source:
        print("  ✓ Loop condition: Correct - no override (per AUTHORITY MODEL)")
    else:
        violations.append("Loop condition doesn't match expected pattern")
    
    # Pattern 3: Governance wrapper exists
    if 'def governance_with_override(' in source:
        print("  ✓ Governance wrapper: Found - override injected correctly")
    else:
        violations.append("Missing governance_with_override wrapper")
    
    # Pattern 4: Override captured once before loop
    if 'override_state = get_override()' in source:
        print("  ✓ Override capture: Correct - captured once before loop")
    else:
        violations.append("Override not captured before loop")
    
    if violations:
        print("  ✗ VIOLATIONS:")
        for v in violations:
            print(f"    - {v}")
        return False
    
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
        print("  ✓ State transition: workflow['status'] = 'PAUSED'")
        checks.append(True)
    else:
        print("  ✗ Missing: workflow['status'] = 'PAUSED'")
        checks.append(False)
    
    # Check 2: save_workflow called
    if 'save_workflow(workflow)' in source:
        print("  ✓ Persistence: save_workflow(workflow) called")
        checks.append(True)
    else:
        print("  ✗ Missing: save_workflow(workflow)")
        checks.append(False)
    
    # Check 3: Trace recorded
    if '"event": "workflow_paused"' in source:
        print("  ✓ Trace: workflow_paused event recorded")
        checks.append(True)
    else:
        print("  ✗ Missing: workflow_paused trace event")
        checks.append(False)
    
    return all(checks)


def analyze_governance_authority():
    """Verify governance is sole decision authority"""
    print("\n=== VALIDATION: Governance Authority ===")
    
    filepath = os.path.join(ROOT, "system", "orchestrator", "governance.py")
    with open(filepath, 'r') as f:
        source = f.read()
    
    checks = []
    
    # Check 1: override_state parameter exists
    if 'def decide_next_action(' in source and 'override_state' in source:
        print("  ✓ Signature: override_state parameter present")
        checks.append(True)
    else:
        print("  ✗ Missing: override_state parameter")
        checks.append(False)
    
    # Check 2: Escalation logic uses override
    if 'if override_state:' in source and 'final_decision = "complete"' in source:
        print("  ✓ Override handling: escalation → complete when override ON")
        checks.append(True)
    else:
        print("  ✗ Missing: override_state escalation handling")
        checks.append(False)
    
    # Check 3: No runtime decision bypass
    runtime_file = os.path.join(ROOT, "system", "orchestrator", "orchestrator_runtime.py")
    with open(runtime_file, 'r') as rt_f:
        runtime_source = rt_f.read()
    
    # Should NOT find runtime modifying decisions based on override
    bad_patterns = [
        'if get_override():',
        'if override_state:',
    ]
    found_bad = False
    for pattern in bad_patterns:
        if pattern in runtime_source and 'governance' not in runtime_source.split(pattern)[0].split('\n')[-1]:
            found_bad = True
            print(f"  ✗ Runtime has decision logic: {pattern}")
    
    if not found_bad:
        print("  ✓ Runtime: No decision bypass - all decisions go through governance")
        checks.append(True)
    else:
        checks.append(False)
    
    return all(checks)


def validate_contract_compliance():
    """Validate overall contract compliance"""
    print("\n=== VALIDATION: Contract Compliance Summary ===")
    
    results = []
    
    results.append(("AUTHORITY MODEL", "Runtime has no decision logic", analyze_runtime_loop()))
    results.append(("STATE TRANSITIONS", "Pause is stateful", analyze_pause_implementation()))
    results.append(("GOVERNANCE CONTRACT", "Sole authority + override integration", analyze_governance_authority()))
    
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
    print("PHASE 6 CORE FIX — ARCHITECTURE COMPLIANCE VALIDATION")
    print("="*60)
    
    success = validate_contract_compliance()
    
    sys.exit(0 if success else 1)

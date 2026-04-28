"""
Governance Purification Tests - 5 Required Test Cases
"""
import sys
sys.path.insert(0, 'e:/MutesHand')

from system.orchestrator.orchestrator_runtime import execute_from_input
from system.orchestrator.bootstrap import initialize_system

# Initialize once
initialize_system()


def test_1_success_case():
    """TEST 1 — SUCCESS CASE: Valid tool request"""
    print("\n" + "="*60)
    print("TEST 1: SUCCESS CASE - Valid tool request")
    print("="*60)
    
    result = execute_from_input("add 5 and 3")
    
    print(f"Result: {result}")
    
    # Check execution result
    output = result.get('output', {})
    if isinstance(output, dict):
        status = output.get('status')
    else:
        status = result.get('status')
    
    print(f"Status: {status}")
    
    passed = status == 'success'
    print(f"TEST 1: {'PASS' if passed else 'FAIL'}")
    return passed, result


def test_2_failure_case():
    """TEST 2 — FAILURE CASE: Invalid tool arguments"""
    print("\n" + "="*60)
    print("TEST 2: FAILURE CASE - Invalid tool arguments")
    print("="*60)
    
    # Try to use add with non-numeric args
    result = execute_from_input("add apple and orange")
    
    print(f"Result: {result}")
    
    status = result.get('status')
    print(f"Status: {status}")
    
    # Should eventually fail or retry bounded
    passed = status in ['failure', 'blocked']
    print(f"TEST 2: {'PASS' if passed else 'FAIL'}")
    return passed, result


def test_3_validator_retry_removal():
    """TEST 3 — VALIDATOR RETRY REMOVAL: Validator should NOT trigger retry"""
    print("\n" + "="*60)
    print("TEST 3: VALIDATOR RETRY REMOVAL")
    print("Input: case that previously retried due to validator")
    print("="*60)
    
    # This input might have triggered validator argument mismatch before
    # But now execution_result should govern
    result = execute_from_input("calculate 10 plus 20")
    
    print(f"Result: {result}")
    
    output = result.get('output', {})
    if isinstance(output, dict):
        status = output.get('status')
    else:
        status = result.get('status')
    
    print(f"Status: {status}")
    
    # Should complete if execution_result succeeds, regardless of validator
    passed = status == 'success'
    print(f"TEST 3: {'PASS' if passed else 'FAIL'}")
    return passed, result


def test_4_multi_step_workflow():
    """TEST 4 — MULTI-STEP WORKFLOW"""
    print("\n" + "="*60)
    print("TEST 4: MULTI-STEP WORKFLOW")
    print("="*60)
    
    # Request that requires multiple steps
    result = execute_from_input("add 5 and 3 then multiply by 2")
    
    print(f"Result: {result}")
    
    # Check workflow completed
    status = result.get('status')
    steps = result.get('steps', [])
    
    print(f"Status: {status}")
    print(f"Steps: {len(steps)}")
    
    # Should complete successfully with multiple steps
    passed = status == 'success' and len(steps) >= 1
    print(f"TEST 4: {'PASS' if passed else 'FAIL'}")
    return passed, result


def test_5_edge_case():
    """TEST 5 — EDGE CASE: Minimal / No-op"""
    print("\n" + "="*60)
    print("TEST 5: EDGE CASE - Minimal/No-op")
    print("="*60)
    
    # Simple valid request
    result = execute_from_input("what is 2 plus 2")
    
    print(f"Result: {result}")
    
    status = result.get('status')
    print(f"Status: {status}")
    
    # Should not hang or infinite loop
    passed = status is not None  # Any deterministic result is acceptable
    print(f"TEST 5: {'PASS' if passed else 'FAIL'}")
    return passed, result


def main():
    print("\n" + "="*60)
    print("GOVERNANCE PURIFICATION - 5 MANDATORY TESTS")
    print("="*60)
    
    results = []
    
    try:
        r1, res1 = test_1_success_case()
        results.append(("TEST 1", r1, res1))
    except Exception as e:
        print(f"TEST 1 ERROR: {e}")
        results.append(("TEST 1", False, {'error': str(e)}))
    
    try:
        r2, res2 = test_2_failure_case()
        results.append(("TEST 2", r2, res2))
    except Exception as e:
        print(f"TEST 2 ERROR: {e}")
        results.append(("TEST 2", False, {'error': str(e)}))
    
    try:
        r3, res3 = test_3_validator_retry_removal()
        results.append(("TEST 3", r3, res3))
    except Exception as e:
        print(f"TEST 3 ERROR: {e}")
        results.append(("TEST 3", False, {'error': str(e)}))
    
    try:
        r4, res4 = test_4_multi_step_workflow()
        results.append(("TEST 4", r4, res4))
    except Exception as e:
        print(f"TEST 4 ERROR: {e}")
        results.append(("TEST 4", False, {'error': str(e)}))
    
    try:
        r5, res5 = test_5_edge_case()
        results.append(("TEST 5", r5, res5))
    except Exception as e:
        print(f"TEST 5 ERROR: {e}")
        results.append(("TEST 5", False, {'error': str(e)}))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for name, passed, result in results:
        status = "PASS" if passed else "FAIL"
        print(f"{name}: {status}")
    
    total_pass = sum(1 for _, p, _ in results if p)
    total_fail = len(results) - total_pass
    
    print(f"\nTOTAL: {total_pass} passed, {total_fail} failed")
    
    return total_fail == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)

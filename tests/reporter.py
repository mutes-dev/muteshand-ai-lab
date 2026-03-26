def print_report(results: list):
    """
    Print clean deterministic test results.
    
    Args:
        results (list): List of test results with name, evaluation, and expected
    """
    
    print("\n" + "="*60)
    print("TEST RESULTS")
    print("="*60 + "\n")
    
    passed = 0
    failed = 0
    
    for result in results:
        name = result["name"]
        evaluation = result["evaluation"]
        expected = result.get("expected", {})
        status = evaluation["status"]
        actual = evaluation["actual"]
        
        if status == "PASS":
            passed += 1
            print(f"[PASS] {name}")
        else:
            failed += 1
            print(f"[FAIL] {name}")
        
        # Format expected
        expected_status = expected.get("status", "unknown")
        if expected_status == "success":
            expected_result = expected.get("result", "")
            expected_str = f"success ({expected_result})"
        else:
            expected_str = "failure"
        
        # Format actual
        if actual == "failure":
            actual_str = "failure"
        else:
            actual_str = f"{actual}"
        
        print(f"  Expected: {expected_str}")
        print(f"  Actual: {actual_str}")
        print(f"  Reason: {evaluation['reason']}")
        print()
    
    print("="*60)
    print("SUMMARY")
    print("="*60)
    print(f"TOTAL: {len(results)}")
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    print("="*60 + "\n")

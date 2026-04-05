"""
Execution Layer

Responsibility:
- Execute a validated structured plan

Rules:
- MUST NOT validate
- MUST NOT modify plan structure
- MUST NOT perform planning
- MUST be deterministic
- NO external dependencies
"""


def execute(plan: list, tool_registry: dict) -> dict:
    """
    Execute a validated structured plan.
    
    Input format:
    [
        {"tool": "tool_name", "args": [arg1, arg2]}
    ]
    
    Output format (success):
    {
        "status": "success",
        "result": <final_result>,
        "steps": [
            {"tool": "...", "args": [...], "output": ...}
        ]
    }
    
    Output format (failure):
    {
        "status": "failure",
        "reason": "error_type"
    }
    """
    if not isinstance(plan, list):
        return {"status": "failure", "reason": "invalid_plan"}
    
    if len(plan) == 0:
        return {"status": "failure", "reason": "empty_plan"}
    
    steps_record = []
    last_result = None
    
    for step_index, step in enumerate(plan):
        # Check step structure
        if not isinstance(step, dict):
            return {"status": "failure", "reason": f"invalid_step_{step_index}"}
        
        tool_name = step.get("tool")
        args = step.get("args", [])
        
        if tool_name is None:
            return {"status": "failure", "reason": f"missing_tool_{step_index}"}
        
        if not isinstance(args, list):
            return {"status": "failure", "reason": f"invalid_args_{step_index}"}
        
        # Check tool exists
        if tool_name not in tool_registry:
            return {"status": "failure", "reason": f"tool_not_found_{tool_name}"}
        
        # Resolve PREVIOUS_RESULT tokens
        # FIRST: Count occurrences
        previous_result_count = args.count("PREVIOUS_RESULT") if isinstance(args, list) else 0
        
        # SECOND: Check for multiple PREVIOUS_RESULT (highest priority failure)
        if previous_result_count > 1:
            return {"status": "failure", "reason": "multiple_previous_result"}
        
        # THIRD: Check for missing previous result when one is requested
        if previous_result_count == 1 and last_result is None:
            return {"status": "failure", "reason": "missing_previous_result"}
        
        # FOURTH: Resolve arguments
        resolved_args = []
        for arg in args:
            if arg == "PREVIOUS_RESULT":
                resolved_args.append(last_result)
            else:
                resolved_args.append(arg)
        
        # Execute tool
        tool_func = tool_registry[tool_name]
        try:
            output = tool_func(*resolved_args)
        except Exception as e:
            return {"status": "failure", "reason": f"execution_error_{step_index}"}
        
        # FAILURE PROPAGATION: If tool returns failure dict, pass through directly
        if isinstance(output, dict) and output.get("status") == "failure":
            return output
        
        # Record step
        steps_record.append({
            "tool": tool_name,
            "args": args,
            "output": output
        })
        
        last_result = output
    
    return {
        "status": "success",
        "result": last_result,
        "steps": steps_record
    }


# =============================================================================
# TESTS (Executed when file is run directly)
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("EXECUTION ENGINE TESTS")
    print("=" * 60)
    
    # Test 1: Determinism test (run 3 times)
    print("\n## TEST 1: Determinism Test (3 runs)")
    plan1 = [
        {"tool": "add", "args": [2, 3]},
        {"tool": "multiply", "args": ["PREVIOUS_RESULT", 4]}
    ]
    
    results = []
    for i in range(3):
        result = execute(plan1)
        results.append(result)
        print(f"\nRun {i+1}:")
        print(f"  Status: {result['status']}")
        print(f"  Result: {result.get('result')}")
        print(f"  Steps: {len(result.get('steps', []))}")
    
    # Verify all results match
    all_match = all(
        r['status'] == results[0]['status'] and 
        r['result'] == results[0]['result'] and
        len(r.get('steps', [])) == len(results[0].get('steps', []))
        for r in results
    )
    print(f"\n✓ Determinism verified: {all_match}")
    assert all_match, "Determinism test FAILED"
    
    # Test 2: Execution test with chaining
    print("\n## TEST 2: Execution Test (Add then Multiply)")
    plan2 = [
        {"tool": "add", "args": [2, 3]},
        {"tool": "multiply", "args": ["PREVIOUS_RESULT", 4]}
    ]
    result2 = execute(plan2)
    print(f"Input: add 2+3, then multiply result by 4")
    print(f"Status: {result2['status']}")
    print(f"Result: {result2.get('result')}")
    print(f"Expected: 20")
    assert result2['status'] == 'success'
    assert result2['result'] == 20
    print("✓ Execution test PASSED")
    
    # Test 3: Missing PREVIOUS_RESULT
    print("\n## TEST 3: Missing PREVIOUS_RESULT")
    plan3 = [
        {"tool": "multiply", "args": ["PREVIOUS_RESULT", 4]}
    ]
    result3 = execute(plan3)
    print(f"Status: {result3['status']}")
    print(f"Reason: {result3.get('reason')}")
    assert result3['status'] == 'failure'
    assert 'missing_previous_result' in result3.get('reason', '')
    print("✓ Missing PREVIOUS_RESULT test PASSED")
    
    # Test 4: Multiple PREVIOUS_RESULT tokens
    print("\n## TEST 4: Multiple PREVIOUS_RESULT tokens")
    plan4 = [
        {"tool": "add", "args": [2, 3]},
        {"tool": "add", "args": ["PREVIOUS_RESULT", "PREVIOUS_RESULT"]}
    ]
    result4 = execute(plan4)
    print(f"Status: {result4['status']}")
    print(f"Reason: {result4.get('reason')}")
    assert result4['status'] == 'failure'
    assert 'multiple_previous_result' in result4.get('reason', '')
    print("✓ Multiple PREVIOUS_RESULT test PASSED")
    
    # Test 5: Invalid tool
    print("\n## TEST 5: Invalid tool")
    plan5 = [
        {"tool": "nonexistent", "args": [1, 2]}
    ]
    result5 = execute(plan5)
    print(f"Status: {result5['status']}")
    print(f"Reason: {result5.get('reason')}")
    assert result5['status'] == 'failure'
    assert 'tool_not_found' in result5.get('reason', '')
    print("✓ Invalid tool test PASSED")
    
    # Test 6: Empty plan
    print("\n## TEST 6: Empty plan")
    plan6 = []
    result6 = execute(plan6)
    print(f"Status: {result6['status']}")
    print(f"Reason: {result6.get('reason')}")
    assert result6['status'] == 'failure'
    assert 'empty_plan' in result6.get('reason', '')
    print("✓ Empty plan test PASSED")
    
    # Test 7: Single step (no PREVIOUS_RESULT)
    print("\n## TEST 7: Single step (no chaining)")
    plan7 = [
        {"tool": "multiply", "args": [5, 6]}
    ]
    result7 = execute(plan7)
    print(f"Status: {result7['status']}")
    print(f"Result: {result7.get('result')}")
    assert result7['status'] == 'success'
    assert result7['result'] == 30
    print("✓ Single step test PASSED")
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)

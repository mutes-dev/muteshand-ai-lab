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
    Execute a SINGLE validated step.

    STRICT: No chaining. No multi-step. No PREVIOUS_RESULT.

    Input format:
        {"name": "tool_name", "args": [arg1, arg2]}

    Output format (success):
        {"status": "success", "result": <result>}

    Output format (failure):
        {"status": "failure", "reason": "error_type"}
    """
    if not isinstance(plan, list):
        return {"status": "failure", "reason": "invalid_plan"}

    if len(plan) == 0:
        return {"status": "failure", "reason": "empty_plan"}

    # STRICT: Only execute first step
    step = plan[0]

    # Check step structure
    if not isinstance(step, dict):
        return {"status": "failure", "reason": "invalid_step"}

    tool_name = step.get("name")
    args = step.get("args", [])

    if tool_name is None:
        return {"status": "failure", "reason": "missing_tool"}

    if not isinstance(args, list):
        return {"status": "failure", "reason": "invalid_args"}

    # Check tool exists
    if tool_name not in tool_registry:
        return {"status": "failure", "reason": f"tool_not_found_{tool_name}"}

    # STRICT: Execute tool directly with provided args
    tool_func = tool_registry[tool_name]

    try:
        output = tool_func(*args)
    except Exception as e:
        return {"status": "failure", "reason": "execution_error"}

    # NORMALIZE TOOL OUTPUT
    if isinstance(output, dict) and "status" in output:
        if output["status"] == "success":
            normalized = {
                "status": "success",
                "result": output.get("result")
            }
            if isinstance(output.get("observation"), dict):
                normalized["observation"] = output["observation"]
            return normalized
        else:
            normalized = {
                "status": "failure",
                "reason": output.get("reason", "execution_error")
            }
            if isinstance(output.get("observation"), dict):
                normalized["observation"] = output["observation"]
            return normalized
    else:
        # Tool returns RAW value - wrap in contract format
        # DEFENSE: Detect error strings that tools return instead of
        # structured failure dicts (e.g. run_python catching ZeroDivisionError).
        # These MUST NOT be treated as successful step outputs.
        if isinstance(output, str):
            _lower = output.lower()
            _error_prefixes = (
                "execution error:",
                "tool execution error:",
                "execution failed with",
                "execution failed:",
                "error:",
            )
            if any(_lower.startswith(p) for p in _error_prefixes):
                return {
                    "status": "failure",
                    "reason": output
                }
        return {
            "status": "success",
            "result": output
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

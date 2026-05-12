"""
Planner Test Cases — Data-Driven Format

Generated from real plan() execution.
"""

import pytest
from system.planner.deterministic_planner import plan


def test_unsupported_inputs_fail():
    """
    Negative case enforcement: Ensure planner FAILS for unsupported/ambiguous inputs.
    
    Contract: Unsupported inputs MUST return {"status": "failure", "reason": "unknown_tool"}
    """
    unsupported_inputs = [
        "do something",
        "calculate stuff",
        "random text",
        "process things",
        "compute stuff"
    ]
    
    for input_text in unsupported_inputs:
        result = plan(input_text)
        
        print(f"\n[NEGATIVE TEST] Input: '{input_text}'")
        print(f"Result: {result}")
        
        # Validate failure contract (NOT internal structure)
        assert result.get("status") == "failure", f"Expected status 'failure' for '{input_text}', got {result}"
        assert result.get("reason") == "unknown_tool", f"Expected reason 'unknown_tool' for '{input_text}', got {result}"
        print(f"[NEGATIVE TEST] ✓ Correctly rejected with failure contract: {input_text}")


def test_multistep_fail_fast_strict():
    """
    Multi-step fail-fast enforcement: Ensure planner NEVER returns partial plans.
    
    Contract: ANY unknown segment MUST trigger immediate failure (NO partial steps).
    """
    # 1. PARTIAL VALID + INVALID (CRITICAL)
    result = plan("add 2 and 3 then do something")
    assert isinstance(result, dict), f"Expected dict for partial failure, got {type(result).__name__}"
    assert result["status"] == "failure", f"Expected failure status, got {result}"
    assert result["reason"] == "unknown_tool", f"Expected unknown_tool reason, got {result}"
    print("\n[MULTI-STEP TEST] ✓ Partial valid + invalid: returns failure (NO partial plan)")

    # 2. INVALID FIRST SEGMENT
    result = plan("do something then add 2 and 3")
    assert isinstance(result, dict), f"Expected dict for first-segment failure, got {type(result).__name__}"
    assert result["status"] == "failure", f"Expected failure status, got {result}"
    assert result["reason"] == "unknown_tool", f"Expected unknown_tool reason, got {result}"
    print("[MULTI-STEP TEST] ✓ Invalid first segment: returns failure immediately")

    # 3. MULTIPLE VALID + INVALID LATE
    result = plan("add 2 and 3 then multiply 4 and 5 then nonsense")
    assert isinstance(result, dict), f"Expected dict for late failure, got {type(result).__name__}"
    assert result["status"] == "failure", f"Expected failure status, got {result}"
    assert result["reason"] == "unknown_tool", f"Expected unknown_tool reason, got {result}"
    print("[MULTI-STEP TEST] ✓ Multiple valid + invalid late: returns failure (NO partial plan)")

    # 4. ALL VALID (CONTROL TEST)
    result = plan("add 2 and 3 then multiply 4 and 5")
    assert isinstance(result, dict), f"Expected dict for all-valid input, got {type(result).__name__}"
    assert result.get("status") == "success", f"Expected status 'success', got {result}"
    steps = result.get("steps", [])
    assert len(steps) == 2, f"Expected 2 steps, got {len(steps)}"

    # Validate structure of both steps
    assert steps[0]["type"] == "tool", f"Expected type 'tool' for step 0, got {steps[0]}"
    assert steps[0]["name"] == "add_numbers", f"Expected 'add_numbers' for step 0, got {steps[0]}"

    assert steps[1]["type"] == "tool", f"Expected type 'tool' for step 1, got {steps[1]}"
    assert steps[1]["name"] == "multiply_numbers", f"Expected 'multiply_numbers' for step 1, got {steps[1]}"
    print("[MULTI-STEP TEST] ✓ All valid: returns complete plan (2 steps)")


TEST_CASES = [
    {
        "name": "determinism_add_numbers",
        "type": "planner",
        "input": "add 2 and 3",
        "expected": [
            {"type": "tool", "name": "add_numbers", "input_text": "add 2 and 3"}
        ]
    },
    {
        "name": "multistep_add_then_multiply",
        "type": "planner",
        "input": "add 2 and 3 then multiply by 4",
        "expected": [
            {"type": "tool", "name": "add_numbers", "input_text": "add 2 and 3"},
            {"type": "tool", "name": "multiply_numbers", "input_text": "multiply by 4"}
        ]
    },
    {
        "name": "multistep_multiply_then_add",
        "type": "planner",
        "input": "multiply 5 by 6 then add 2",
        "expected": [
            {"type": "tool", "name": "multiply_numbers", "input_text": "multiply 5 by 6"},
            {"type": "tool", "name": "add_numbers", "input_text": "add 2"}
        ]
    },
    {
        "name": "unknown_input",
        "type": "planner",
        "input": "do something random",
        "expected": {
            "status": "failure",
            "reason": "unknown_tool"
        }
    }
]

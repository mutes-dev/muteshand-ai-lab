"""
System Invariants — Permanent Behavior Lock

Tests LOCK system behavior permanently.
NO flexibility. NO interpretation.
"""

import os
from system.entry.router import route_input
from system.planner.deterministic_planner import plan as deterministic_planner
from system.parser.parser import parse
from system.entry.system_entry import system_entry


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def test_router_invariant():
    """
    INVARIANT 1: Router routes ALL strings to planner.
    """
    result = route_input("add 2 and 3")
    assert result == {
        "mode": "planner",
        "data": "add 2 and 3"
    }


def test_planner_invariant():
    """
    INVARIANT 2: Planner fail-fast for unknown tools.
    """
    result = deterministic_planner("random text")
    assert result == {
        "status": "failure",
        "reason": "unknown_tool"
    }


def test_parser_invariant():
    """
    INVARIANT 3: Parser NEVER returns failure dict.
    """
    # Test with valid planner output
    planner_output = [
        {"type": "tool", "name": "add_numbers", "input_text": "add 2 and 3"}
    ]
    result = parse(planner_output)
    
    # MUST return list
    assert type(result) is list
    
    # MUST NEVER return failure dict
    assert not (isinstance(result, dict) and result.get("status") == "failure")


def test_validation_invariant_valid():
    """
    INVARIANT 4a: Multi-step valid plans MUST pass.
    """
    result = system_entry("add 2 and 3 then multiply 4 and 5")
    assert result["status"] == "success"


def test_validation_invariant_invalid():
    """
    INVARIANT 4b: Invalid arg count MUST fail.
    """
    result = system_entry("add 2")
    assert result["status"] == "failure"


def test_execution_reachability_success():
    """
    INVARIANT 5a: Valid plans reach execution and succeed.
    """
    result = system_entry("add 2 and 3")
    assert result == {
        "status": "success",
        "result": 5
    }


def test_execution_reachability_failure():
    """
    INVARIANT 5b: Crash tool reaches execution and fails.
    """
    result = system_entry("crash 1 and 2")
    assert result["status"] == "failure"


def test_final_contract_success():
    """
    INVARIANT 6: Success contract is EXACT.
    """
    result = system_entry("add 2 and 3")
    # EXACT match — NO extra keys allowed
    assert result == {
        "status": "success",
        "result": 5
    }


def test_determinism():
    """
    INVARIANT 7: Same input produces EXACT same output.
    """
    result1 = system_entry("add 2 and 3")
    result2 = system_entry("add 2 and 3")
    result3 = system_entry("add 2 and 3")
    
    assert result1 == result2 == result3

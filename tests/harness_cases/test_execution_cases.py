"""
Execution Safety — Raw Tool Execution Validation

Tests ONLY raw execution layer:
execution_registry[tool](args)

NO pipeline involvement.
"""

import os
import pytest
from system.registry.registry_builder import build_registries


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


# Build registries once for all tests
TOOL_INDEX_PATH = os.path.join("system", "tool_index", "tools.json")
TOOLS_DIR = "tools"
_validation_registry, execution_registry = build_registries(TOOL_INDEX_PATH, TOOLS_DIR)


def test_add_numbers_execution():
    """
    Valid tool execution: add_numbers with correct args.
    
    Input: execution_registry["add_numbers"](2, 3)
    Expected: 5
    """
    result = execution_registry["add_numbers"](2, 3)
    assert result == 5
    print(f"[RAW EXECUTION] ✓ add_numbers(2, 3) = {result}")


def test_multiply_numbers_execution():
    """
    Valid tool execution: multiply_numbers with correct args.
    
    Input: execution_registry["multiply_numbers"](4, 5)
    Expected: 20
    """
    result = execution_registry["multiply_numbers"](4, 5)
    assert result == 20
    print(f"[RAW EXECUTION] ✓ multiply_numbers(4, 5) = {result}")


def test_subtract_numbers_execution():
    """
    Valid tool execution: subtract_numbers with correct args.
    
    Input: execution_registry["subtract_numbers"](10, 3)
    Expected: 7
    """
    result = execution_registry["subtract_numbers"](10, 3)
    assert result == 7
    print(f"[RAW EXECUTION] ✓ subtract_numbers(10, 3) = {result}")


def test_crash_tool_raises():
    """
    Tool exception: crash_tool must raise Exception.
    
    Input: execution_registry["crash_tool"]()
    Expected: Raises Exception
    """
    with pytest.raises(Exception):
        execution_registry["crash_tool"]()
    print("[RAW EXECUTION] ✓ crash_tool raises Exception as expected")


def test_broken_add_raises():
    """
    Broken tool: broken_add must raise Exception.
    
    Input: execution_registry["broken_add"](2, 3)
    Expected: Raises Exception
    """
    with pytest.raises(Exception):
        execution_registry["broken_add"](2, 3)
    print("[RAW EXECUTION] ✓ broken_add raises Exception as expected")


def test_add_numbers_string_concat():
    """
    String args: add_numbers with strings concatenates them.
    
    Input: execution_registry["add_numbers"]("a", "b")
    Expected: "ab" (string concatenation, not exception)
    """
    result = execution_registry["add_numbers"]("a", "b")
    assert result == "ab"
    print(f"[RAW EXECUTION] ✓ add_numbers('a', 'b') = '{result}' (string concat)")


def test_bad_add_execution():
    """
    Bad tool: bad_add executes and returns result.
    
    Input: execution_registry["bad_add"](2, 3)
    Expected: Returns a value (verifies execution doesn't crash)
    """
    result = execution_registry["bad_add"](2, 3)
    assert result is not None
    print(f"[RAW EXECUTION] ✓ bad_add(2, 3) = {result}")

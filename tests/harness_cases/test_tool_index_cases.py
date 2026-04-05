"""
Planner-Registry Alignment Test Cases

Validates that all planner tool mappings exist in execution_registry.
"""

import os
import pytest
from system.registry.registry_builder import build_registries


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def test_planner_tools_exist_in_execution_registry():
    """
    Planner-Execution Registry alignment validation.
    
    Ensures ALL tools referenced by planner exist in execution_registry.
    Prevents hidden execution failures.
    """
    # Build registries using SAME system mechanism
    tool_index_path = os.path.join("memory", "tool_index", "tools.json")
    tools_dir = "tools"
    validation_registry, execution_registry = build_registries(tool_index_path, tools_dir)
    
    # Planner tool mappings (from TOOL_RULES)
    planner_tools = [
        "add_numbers",
        "multiply_numbers",
        "subtract_numbers"
    ]
    
    # Validate each planner tool exists in execution_registry
    for tool in planner_tools:
        assert tool in execution_registry, f"Planner references tool not in execution_registry: {tool}"
        print(f"[ALIGNMENT TEST] ✓ {tool} exists in execution_registry")
    
    print(f"\n[ALIGNMENT TEST] All {len(planner_tools)} planner tools validated")

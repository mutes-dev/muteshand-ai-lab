"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - Resolver contract
  - Validation registry alignment
  - Argument resolution correctness
ENTRYPOINT: resolver
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: Resolver contract only

---

Resolver-Validation Registry Alignment Test Cases

Validates that resolver outputs match validation_registry requirements.
Ensures full pipeline schema consistency.
"""

import os
import pytest
from system.planner.deterministic_planner import plan
from system.parser.parser import parse
from system.resolver.argument_resolver import resolve
from system.registry.registry_builder import build_registries


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def test_valid_case_resolver_matches_validation_registry():
    """
    Valid case: Resolver output matches validation_registry schema.
    
    Input: "add 2 and 3"
    Expected: args count = 2, types = [int, int]
    """
    # Build registries
    tool_index_path = os.path.join("memory", "tool_index", "tools.json")
    tools_dir = "tools"
    validation_registry, execution_registry = build_registries(tool_index_path, tools_dir)
    
    # Run pipeline
    planner_result = plan("add 2 and 3")
    planner_output = planner_result.get("steps", []) if isinstance(planner_result, dict) else planner_result
    parser_output = parse(planner_output)
    resolver_output = resolve(parser_output)
    
    # Extract first step
    step = resolver_output[0]
    tool_name = step["tool"]
    args = step["args"]
    
    # Get validation schema
    schema = validation_registry[tool_name]
    expected_arg_count = schema["args"]
    expected_types = schema["types"]
    
    # Validate arg count
    assert len(args) == expected_arg_count, f"Expected {expected_arg_count} args, got {len(args)}"
    
    # Validate types
    for i, (arg, expected_type) in enumerate(zip(args, expected_types)):
        assert isinstance(arg, expected_type), f"Arg {i}: expected {expected_type.__name__}, got {type(arg).__name__}"
    
    print(f"[RESOLVER TEST] ✓ Valid case: {tool_name} matches validation_registry")
    print(f"  Args: {args}")
    print(f"  Expected count: {expected_arg_count}, Actual: {len(args)}")
    print(f"  Expected types: {[t.__name__ for t in expected_types]}, Actual: {[type(a).__name__ for a in args]}")


def test_type_validation_int_only():
    """
    Type validation: Parser only extracts integers (deterministic).
    
    Input: "add 2 and hello"
    Expected: Parser extracts only "2", resolver gets [2]
    """
    # Build registries
    tool_index_path = os.path.join("memory", "tool_index", "tools.json")
    tools_dir = "tools"
    validation_registry, execution_registry = build_registries(tool_index_path, tools_dir)
    
    # Run pipeline
    planner_result = plan("add 2 and hello")
    planner_output = planner_result.get("steps", []) if isinstance(planner_result, dict) else planner_result
    parser_output = parse(planner_output)
    
    # Parser should extract only numeric values
    # "add 2 and hello" -> parser finds only "2"
    # This will result in args = [2], which has count = 1
    
    # Resolver will receive this
    resolver_output = resolve(parser_output)
    
    step = resolver_output[0]
    tool_name = step["tool"]
    args = step["args"]
    
    # Get validation schema
    schema = validation_registry[tool_name]
    expected_arg_count = schema["args"]
    
    # This should have arg count mismatch (1 vs 2)
    # Validation layer will catch this
    assert len(args) != expected_arg_count, f"Expected arg count mismatch, but got {len(args)} == {expected_arg_count}"
    
    print(f"[RESOLVER TEST] ✓ Type validation: Parser extracted only integers from mixed input")
    print(f"  Input: 'add 2 and hello'")
    print(f"  Extracted args: {args}")
    print(f"  Expected count: {expected_arg_count}, Actual: {len(args)} (mismatch detected)")


def test_arg_count_validation_mismatch():
    """
    Arg count validation: Detect mismatch between resolver output and schema.
    
    Input: "add 5" (only 1 number)
    Expected: args count = 1, but schema requires 2
    """
    # Build registries
    tool_index_path = os.path.join("memory", "tool_index", "tools.json")
    tools_dir = "tools"
    validation_registry, execution_registry = build_registries(tool_index_path, tools_dir)
    
    # Run pipeline
    planner_result = plan("add 5")
    planner_output = planner_result.get("steps", []) if isinstance(planner_result, dict) else planner_result
    parser_output = parse(planner_output)
    resolver_output = resolve(parser_output)
    
    step = resolver_output[0]
    tool_name = step["tool"]
    args = step["args"]
    
    # Get validation schema
    schema = validation_registry[tool_name]
    expected_arg_count = schema["args"]
    
    # Validate mismatch
    assert len(args) != expected_arg_count, f"Expected arg count mismatch, but got {len(args)} == {expected_arg_count}"
    
    print(f"[RESOLVER TEST] ✓ Arg count mismatch detected")
    print(f"  Tool: {tool_name}")
    print(f"  Expected count: {expected_arg_count}, Actual: {len(args)}")


def test_multistep_validation_all_steps_match_schema():
    """
    Multi-step validation: Each step must match its tool schema.
    
    Input: "add 2 and 3 then multiply 4 and 5"
    Expected: Both steps match their respective schemas
    """
    # Build registries
    tool_index_path = os.path.join("memory", "tool_index", "tools.json")
    tools_dir = "tools"
    validation_registry, execution_registry = build_registries(tool_index_path, tools_dir)
    
    # Run pipeline
    planner_result = plan("add 2 and 3 then multiply 4 and 5")
    assert isinstance(planner_result, dict), f"Expected dict for valid input, got {type(planner_result).__name__}"
    assert planner_result.get("status") == "success", f"Expected status 'success', got {planner_result}"
    planner_output = planner_result.get("steps", [])
    parser_output = parse(planner_output)
    resolver_output = resolve(parser_output)
    
    # Validate both steps
    assert len(resolver_output) == 2, f"Expected 2 steps, got {len(resolver_output)}"
    
    for i, step in enumerate(resolver_output):
        tool_name = step["tool"]
        args = step["args"]
        
        # Get validation schema
        schema = validation_registry[tool_name]
        expected_arg_count = schema["args"]
        expected_types = schema["types"]
        
        # Validate arg count
        assert len(args) == expected_arg_count, f"Step {i} ({tool_name}): Expected {expected_arg_count} args, got {len(args)}"
        
        # Validate types
        for j, (arg, expected_type) in enumerate(zip(args, expected_types)):
            # Handle PREVIOUS_RESULT marker (string) in multi-step
            if arg == "PREVIOUS_RESULT":
                continue
            assert isinstance(arg, expected_type), f"Step {i} ({tool_name}), Arg {j}: expected {expected_type.__name__}, got {type(arg).__name__}"
        
        print(f"[RESOLVER TEST] ✓ Step {i} ({tool_name}) matches validation_registry")
        print(f"  Args: {args}")
        print(f"  Expected count: {expected_arg_count}, Actual: {len(args)}")
    
    print(f"\n[RESOLVER TEST] All {len(resolver_output)} steps validated against schemas")

"""
Harness Tests for Registry Builder

Purpose:
    Validate registry_builder against SYSTEM_CONTRACTS using REAL execution only.

Rules:
    - NO mocks
    - NO simulated outputs
    - MUST use real tools.json
    - MUST use real /tools directory
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from system.registry.registry_builder import build_registries
import json


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


# Paths
TOOL_INDEX_PATH = "memory/tool_index/tools.json"
TOOLS_PATH = "tools"


def test_structure_validation():
    """TEST 1: Validate registry structures."""
    print("\n=== TEST 1: STRUCTURE VALIDATION ===")
    
    val_reg, exec_reg = build_registries(TOOL_INDEX_PATH, TOOLS_PATH)
    
    # validation_registry is dict
    assert isinstance(val_reg, dict), "validation_registry must be dict"
    print(f"✓ validation_registry is dict")
    
    # execution_registry is dict
    assert isinstance(exec_reg, dict), "execution_registry must be dict"
    print(f"✓ execution_registry is dict")
    
    # For each validation entry
    for tool_name, spec in val_reg.items():
        # has "args" (int)
        assert "args" in spec, f"{tool_name}: missing 'args'"
        assert isinstance(spec["args"], int), f"{tool_name}: 'args' must be int"
        
        # has "types" (list)
        assert "types" in spec, f"{tool_name}: missing 'types'"
        assert isinstance(spec["types"], list), f"{tool_name}: 'types' must be list"
    
    print(f"✓ All {len(val_reg)} validation entries have correct structure")
    
    # For each execution entry
    for tool_name, func in exec_reg.items():
        # value is callable
        assert callable(func), f"{tool_name}: value must be callable"
    
    print(f"✓ All {len(exec_reg)} execution entries are callable")
    
    print("TEST 1: PASSED")
    return True


def test_tool_coverage():
    """TEST 2: All tools from tool_index exist in both registries."""
    print("\n=== TEST 2: TOOL COVERAGE ===")
    
    # Load tool_index
    with open(TOOL_INDEX_PATH, "r", encoding="utf-8") as f:
        tool_index = json.load(f)
    
    val_reg, exec_reg = build_registries(TOOL_INDEX_PATH, TOOLS_PATH)
    
    # For each tool in tool_index
    for tool_name in tool_index.keys():
        # exists in validation_registry
        assert tool_name in val_reg, f"{tool_name}: missing from validation_registry"
        
        # exists in execution_registry
        assert tool_name in exec_reg, f"{tool_name}: missing from execution_registry"
    
    print(f"✓ All {len(tool_index)} tools from tool_index exist in both registries")
    print("TEST 2: PASSED")
    return True


def test_type_validation():
    """TEST 3: All types must be int or str only."""
    print("\n=== TEST 3: TYPE VALIDATION ===")
    
    val_reg, _ = build_registries(TOOL_INDEX_PATH, TOOLS_PATH)
    
    allowed_types = (int, str)
    
    for tool_name, spec in val_reg.items():
        for i, t in enumerate(spec["types"]):
            # Must be int OR str
            assert t in allowed_types, f"{tool_name}: type[{i}] = {t}, must be int or str"
            
            # No tuples allowed
            assert not isinstance(t, tuple), f"{tool_name}: type[{i}] is tuple, not allowed"
            
            # No None allowed
            assert t is not None, f"{tool_name}: type[{i}] is None, not allowed"
    
    print(f"✓ All types are int or str (no tuples, no None)")
    print("TEST 3: PASSED")
    return True


def test_callable_validation():
    """TEST 4: All execution_registry values must be callable."""
    print("\n=== TEST 4: CALLABLE VALIDATION ===")
    
    _, exec_reg = build_registries(TOOL_INDEX_PATH, TOOLS_PATH)
    
    for tool_name, func in exec_reg.items():
        assert callable(func), f"{tool_name}: not callable"
    
    print(f"✓ All {len(exec_reg)} execution_registry values are callable")
    print("TEST 4: PASSED")
    return True


def test_determinism():
    """TEST 5: build_registries must produce identical output on multiple runs."""
    print("\n=== TEST 5: DETERMINISM ===")
    
    # Run build_registries twice
    val_reg1, exec_reg1 = build_registries(TOOL_INDEX_PATH, TOOLS_PATH)
    val_reg2, exec_reg2 = build_registries(TOOL_INDEX_PATH, TOOLS_PATH)
    
    # validation_registry must match exactly
    assert val_reg1 == val_reg2, "validation_registry not deterministic"
    print("✓ validation_registry matches exactly between runs")
    
    # execution_registry keys must match
    keys1 = set(exec_reg1.keys())
    keys2 = set(exec_reg2.keys())
    assert keys1 == keys2, "execution_registry keys not deterministic"
    print("✓ execution_registry keys match between runs")
    
    print("TEST 5: PASSED")
    return True


def test_failure_case():
    """TEST 6: Missing tool file must raise exception with correct message."""
    print("\n=== TEST 6: FAILURE CASE ===")
    
    import tempfile
    import shutil
    
    # Load tool_index to get a tool name
    with open(TOOL_INDEX_PATH, "r", encoding="utf-8") as f:
        tool_index = json.load(f)
    
    # Select one tool (use first one)
    test_tool = list(tool_index.keys())[0]
    test_file = os.path.join(TOOLS_PATH, test_tool + ".py")
    temp_file = test_file + ".tmp"
    
    # Rename file temporarily
    shutil.move(test_file, temp_file)
    
    try:
        # Run build_registries - should raise exception
        try:
            build_registries(TOOL_INDEX_PATH, TOOLS_PATH)
            # If we get here, no exception was raised
            shutil.move(temp_file, test_file)  # Restore
            print(f"✗ No exception raised for missing tool: {test_tool}")
            return False
        except Exception as e:
            # Check exception message contains expected text
            error_msg = str(e)
            expected = f"tool_load_error_{test_tool}"
            
            # Restore file first
            shutil.move(temp_file, test_file)
            
            # Strict contract assertion - only exact tool_load_error_<tool> is valid
            assert expected in error_msg, f"Expected '{expected}' in error message, got: {error_msg}"
            
            print(f"✓ Exception raised for missing tool: {test_tool}")
            print(f"  Error: {error_msg[:100]}...")
            print("TEST 6: PASSED")
            return True
    except:
        # Ensure file is restored even if something unexpected happens
        if os.path.exists(temp_file):
            shutil.move(temp_file, test_file)
        raise


if __name__ == "__main__":
    results = []
    
    try:
        results.append(("TEST 1", test_structure_validation()))
    except Exception as e:
        print(f"TEST 1: FAILED - {e}")
        results.append(("TEST 1", False))
    
    try:
        results.append(("TEST 2", test_tool_coverage()))
    except Exception as e:
        print(f"TEST 2: FAILED - {e}")
        results.append(("TEST 2", False))
    
    try:
        results.append(("TEST 3", test_type_validation()))
    except Exception as e:
        print(f"TEST 3: FAILED - {e}")
        results.append(("TEST 3", False))
    
    try:
        results.append(("TEST 4", test_callable_validation()))
    except Exception as e:
        print(f"TEST 4: FAILED - {e}")
        results.append(("TEST 4", False))
    
    try:
        results.append(("TEST 5", test_determinism()))
    except Exception as e:
        print(f"TEST 5: FAILED - {e}")
        results.append(("TEST 5", False))
    
    try:
        results.append(("TEST 6", test_failure_case()))
    except Exception as e:
        print(f"TEST 6: FAILED - {e}")
        results.append(("TEST 6", False))
    
    # Summary
    print("\n" + "="*50)
    print("TEST SUMMARY")
    print("="*50)
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"{name}: {status}")
    
    all_passed = all(passed for _, passed in results)
    print("="*50)
    print(f"OVERALL: {'ALL PASSED' if all_passed else 'SOME FAILED'}")

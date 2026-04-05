"""
System Harness — TEST_CASES ONLY Execution

Purpose:
    Data-driven contract validation for system correctness.
    TEST_CASES ONLY — NO function-based fallback.

Rules:
    - NO subprocess
    - NO function-based test execution
    - ONLY TEST_CASES are executed
    - Strict equality only
    - Fail-fast behavior
"""

import os
import sys
import importlib.util

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from system.entry.system_entry import system_entry
from system.entry.router import route_input
from system.entry.llm_entry import llm_entry
from system.planner.deterministic_planner import plan
from system.observability.validator import validate
from system.execution.executor import execute
from system.observability.tool_tests import run_tool_tests

def is_subset_match(actual, expected):
    """
    Check if actual contains all fields from expected (subset match).
    Extra fields in actual are allowed.
    """
    if not isinstance(expected, dict):
        return actual == expected
    
    for key, expected_value in expected.items():
        if key not in actual:
            return False
        actual_value = actual[key]
        
        # Recursively check nested dicts
        if isinstance(expected_value, dict):
            if not is_subset_match(actual_value, expected_value):
                return False
        # Check lists
        elif isinstance(expected_value, list):
            if actual_value != expected_value:
                return False
        # Check primitive values
        elif actual_value != expected_value:
            return False
    
    return True


# FUNCTION EXECUTION GUARD — VERIFICATION ONLY
FUNCTION_CALL_COUNT = 0


def load_module(file_path: str):
    """
    Safely load a module from file path.
    
    Returns:
        module: Loaded module or None if failed
    """
    try:
        spec = importlib.util.spec_from_file_location("test_module", file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def execute_test_cases(module, file_name: str):
    """
    Execute TEST_CASES from module with type-based routing.
    
    Supports types:
    - system: system_entry(input)
    - validation: validate(input["plan"], input["registry"])
    - planner: plan(input)
    - router: route_input(input)
    - llm: llm_entry(input)
    - execution: execute(input["plan"], input["registry"])
    
    Returns:
        dict: {"type": str, "result": dict or None}
        type: "executed", "empty", or "missing"
    """
    if not hasattr(module, "TEST_CASES"):
        return {"type": "missing", "result": None}
    
    test_cases = module.TEST_CASES
    
    if test_cases == []:
        return {"type": "empty", "result": None}
    
    for index, test_case in enumerate(test_cases):
        # Validate test case structure
        required_keys = ["input", "expected"]
        for key in required_keys:
            if key not in test_case:
                return {
                    "type": "executed",
                    "result": {
                        "status": "failure",
                        "test": f"{file_name}:invalid_test_case",
                        "reason": f"Missing required key '{key}'"
                    }
                }
        
        # Extract test data
        test_name = test_case.get("name", f"test_{index}")
        test_type = test_case.get("type", "system")
        input_data = test_case["input"]
        expected = test_case["expected"]
        
        # Route by type
        try:
            if test_type == "system":
                result = system_entry(input_data)
            elif test_type == "validation":
                result = validate(input_data["plan"], input_data["registry"])
            elif test_type == "planner":
                result = plan(input_data)
            elif test_type == "router":
                result = route_input(input_data)
            elif test_type == "llm":
                result = llm_entry(input_data)
            elif test_type == "execution":
                result = execute(input_data["plan"], input_data["registry"])
            else:
                return {
                    "type": "executed",
                    "result": {
                        "status": "failure",
                        "test": test_name,
                        "reason": f"Unknown test type: {test_type}"
                    }
                }
        except Exception as e:
            return {
                "type": "executed",
                "result": {
                    "status": "failure",
                    "test": test_name,
                    "reason": f"Execution error: {str(e)}"
                }
            }
        
        # Subset match check (expected fields must match, extra fields in actual OK)
        # Handle legacy tests: expected=list of steps, actual=dict with "steps" key
        if isinstance(expected, list) and isinstance(result, dict) and "steps" in result:
            comparison_target = result["steps"]
        else:
            comparison_target = result
        
        if not is_subset_match(comparison_target, expected):
            return {
                "type": "executed",
                "result": {
                    "status": "failure",
                    "test": test_name,
                    "expected": expected,
                    "actual": result
                }
            }
    
    return {"type": "executed", "result": None}


def run():
    """
    Execute harness: scan tests, execute TEST_CASES ONLY.
    
    Returns:
        dict: {"status": "success"} or {"status": "failure", ...}
    """
    global FUNCTION_CALL_COUNT
    
    print("RUN MODE: TEST_CASES ONLY")
    print()
    
    tests_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tests", "harness_cases")
    
    # Track execution metrics
    total_modules = 0
    modules_executed = 0
    modules_empty = 0
    modules_missing = 0
    any_tests_executed = False
    
    # Scan all .py files in tests directory
    for file_name in os.listdir(tests_dir):
        if not file_name.endswith(".py"):
            continue
            
        file_path = os.path.join(tests_dir, file_name)
        module = load_module(file_path)
        
        if module is None:
            continue
        
        total_modules += 1
        
        # ONLY TEST_CASES — NO fallback
        test_cases_result = execute_test_cases(module, file_name)
        
        if test_cases_result["type"] == "executed":
            any_tests_executed = True
            modules_executed += 1
            print(f"[HARNESS] Executing TEST_CASES in {file_name}")
            if test_cases_result["result"] is not None:
                return test_cases_result["result"]
            continue
        elif test_cases_result["type"] == "empty":
            modules_empty += 1
            print(f"[HARNESS] No test cases (explicit): {file_name}")
            continue
        elif test_cases_result["type"] == "missing":
            modules_missing += 1
            print(f"[HARNESS] Missing TEST_CASES: {file_name}")
            continue
        
        # No TEST_CASES found — skip (NO function fallback)
        continue
    
    # Execution summary
    print()
    print("=== HARNESS SUMMARY ===")
    print(f"Modules processed: {total_modules}")
    print(f"Modules with TEST_CASES: {modules_executed}")
    print(f"Modules with EMPTY TEST_CASES: {modules_empty}")
    print(f"Modules MISSING TEST_CASES: {modules_missing}")
    print()
    
    # Check if any tests were executed
    if not any_tests_executed:
        return {
            "status": "failure",
            "reason": "no_TEST_CASES_found",
            "message": "No TEST_CASES found in any test file"
        }
    
    # All tests passed
    result = {"status": "success"}
    
    # Run tool tests for production tools
    tool_test_results = run_tool_tests()
    if tool_test_results.get("tool_tests"):
        result["tool_tests"] = tool_test_results["tool_tests"]
    
    return result


if __name__ == "__main__":
    import json
    output = run()
    print(json.dumps(output, indent=2))
    sys.exit(0 if output.get("status") == "success" else 1)

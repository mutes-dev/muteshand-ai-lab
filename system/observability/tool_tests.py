"""
Tool Tests — Production Tool Validation via system_entry ONLY

Loads TEST_CASES from tests/harness_cases, filters for system_entry compatible tests,
and executes ONLY via system_entry().

Rules:
- ALL execution uses system_entry(input_text)
- NO direct tool execution
- NO pytest-style class/method execution
- ONLY production tools are tested
"""

import os
import sys
import json
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from system.entry.system_entry import system_entry


def load_tool_index():
    """Load tool_index and return production tools."""
    tool_index_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "system", "tool_index", "tools.json"
    )
    try:
        with open(tool_index_path, 'r') as f:
            tool_index = json.load(f)
        return {name: data for name, data in tool_index.items() if data.get("production", False)}
    except Exception:
        return {}


def load_test_module(file_path: str):
    """Safely load a test module to extract TEST_CASES."""
    try:
        spec = importlib.util.spec_from_file_location("test_module", file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def is_valid_test_case(test_case):
    """
    Validate test case format for system_entry execution.
    
    Required format:
    {
        "input": "string input text",
        "expected": {
            "status": "success" or "failure",
            "result": <value> OR "reason": <error_code>
        }
    }
    """
    if not isinstance(test_case, dict):
        return False
    
    # Must have input field that is a string
    if "input" not in test_case:
        return False
    if not isinstance(test_case["input"], str):
        return False
    
    # Must have expected field that is a dict
    if "expected" not in test_case:
        return False
    if not isinstance(test_case["expected"], dict):
        return False
    
    expected = test_case["expected"]
    
    # Expected must have status field
    if "status" not in expected:
        return False
    if expected["status"] not in ("success", "failure"):
        return False
    
    # Success cases must have result
    if expected["status"] == "success" and "result" not in expected:
        return False
    
    # Failure cases must have reason
    if expected["status"] == "failure" and "reason" not in expected:
        return False
    
    return True


def determine_tool_from_result(result):
    """
    Determine which tool was executed from system_entry result.
    
    Returns tool name or None if cannot determine.
    """
    if not isinstance(result, dict):
        return None
    
    # Check for trace information
    trace = result.get("trace", [])
    if trace and isinstance(trace, list):
        # First trace entry should have matched_tool
        first_trace = trace[0]
        if isinstance(first_trace, dict):
            tool = first_trace.get("matched_tool")
            if tool:
                return tool
    
    # Check for steps information
    steps = result.get("steps", [])
    if steps and isinstance(steps, list):
        first_step = steps[0]
        if isinstance(first_step, dict):
            tool = first_step.get("name")
            if tool:
                return tool
    
    return None


def run_tool_tests():
    """
    Execute tool tests for production tools ONLY via system_entry.
    
    Returns:
        dict: {"tool_tests": {tool_name: {"passed": X, "failed": Y}}}
    """
    # Load production tools
    production_tools = load_tool_index()
    production_tool_names = set(production_tools.keys())
    
    # Initialize results for all production tools
    results = {name: {"passed": 0, "failed": 0} for name in production_tool_names}
    
    # Path to harness
    harness_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "tests", "harness"
    )
    
    if not os.path.isdir(harness_dir):
        return {"tool_tests": {}, "error": "harness directory not found"}
    
    # Scan test files
    for file_name in os.listdir(harness_dir):
        if not file_name.endswith(".py") or file_name.startswith("__"):
            continue
        
        file_path = os.path.join(harness_dir, file_name)
        module = load_test_module(file_path)
        
        if module is None:
            continue
        
        # Get TEST_CASES from module
        if not hasattr(module, "TEST_CASES"):
            continue
        
        test_cases = module.TEST_CASES
        if not isinstance(test_cases, list):
            continue
        
        # Process each test case
        for test_case in test_cases:
            # Skip invalid test cases
            if not is_valid_test_case(test_case):
                continue
            
            input_text = test_case["input"]
            expected = test_case["expected"]
            
            # Execute via system_entry ONLY
            try:
                result = system_entry(input_text)
            except Exception:
                # Execution error counts as failure
                continue
            
            # Determine which tool this test is for
            tool_name = determine_tool_from_result(result)
            
            # Skip if tool not in production list
            if tool_name not in production_tool_names:
                continue
            
            # Validate result
            passed = False
            
            if expected["status"] == "success":
                # Success: check status and result
                if result.get("status") == "success":
                    if result.get("result") == expected["result"]:
                        passed = True
            else:
                # Failure: check status and reason
                if result.get("status") == "failure":
                    if result.get("reason") == expected["reason"]:
                        passed = True
            
            # Update results
            if passed:
                results[tool_name]["passed"] += 1
            else:
                results[tool_name]["failed"] += 1
    
    # Filter out tools with no tests
    results = {k: v for k, v in results.items() if v["passed"] > 0 or v["failed"] > 0}
    
    return {"tool_tests": results}


if __name__ == "__main__":
    output = run_tool_tests()
    print(json.dumps(output, indent=2))

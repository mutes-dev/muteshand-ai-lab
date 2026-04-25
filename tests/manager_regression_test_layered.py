# manager_regression_test_layered.py — LAYERED + PARALLEL TESTING

import sys
import os
import re
import time
import subprocess
from typing import List, Dict, Tuple

# --- FIX IMPORT PATH ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MANAGER_PATH = os.path.join(PROJECT_ROOT, "projects", "manager")

if MANAGER_PATH not in sys.path:
    sys.path.insert(0, MANAGER_PATH)

# ── Constants ────────────────────────────────────────────────────────────────
sys.path.insert(0, PROJECT_ROOT)
from core.config import BASE_PATH

LOG_DIR = BASE_PATH / "logs" / "regression_tests"
os.makedirs(LOG_DIR, exist_ok=True)

# ── LAYERED TEST STRUCTURE ───────────────────────────────────────────────────

# EXECUTION LAYER TESTS
# Validates: tool execution, chaining, result propagation, error handling
EXECUTION_LAYER_TESTS = [
    {
        "name": "EXEC-01: Basic Tool Execution",
        "goal": "add 2 and 3",
        "layer": "EXECUTION",
        "validates": "Single tool execution with direct args",
        "expected_type": "exact",
        "expected": "5",
    },
    {
        "name": "EXEC-02: PREVIOUS_RESULT Chaining (2-step)",
        "goal": "square the result of adding 3 and 5",
        "layer": "EXECUTION",
        "validates": "PREVIOUS_RESULT token substitution in 2-step plan",
        "expected_type": "exact",
        "expected": "64",
    },
    {
        "name": "EXEC-03: PREVIOUS_RESULT Chaining (3-step)",
        "goal": "square the result of multiplying the result of adding 2 and 3 by 4",
        "layer": "EXECUTION",
        "validates": "Multi-step PREVIOUS_RESULT chaining",
        "expected_type": "exact",
        "expected": "400",
    },
    {
        "name": "EXEC-04: Chaining - Multi Arg Position",
        "goal": "multiply 5 with the result of adding 2 and 3",
        "layer": "EXECUTION",
        "validates": "PREVIOUS_RESULT in first arg position",
        "expected_type": "exact",
        "expected": "25",
    },
    {
        "name": "EXEC-05: Chaining - Second Arg Position",
        "goal": "multiply the result of adding 3 and 5 by 2",
        "layer": "EXECUTION",
        "validates": "PREVIOUS_RESULT in second arg position",
        "expected_type": "exact",
        "expected": "16",
    },
    {
        "name": "EXEC-06: Chaining - Punctuation Robustness",
        "goal": "square the result of adding 3 and 5.",
        "layer": "EXECUTION",
        "validates": "Chaining works with punctuation in goal",
        "expected_type": "exact",
        "expected": "64",
    },
    {
        "name": "EXEC-07: Chaining - Mixed Operations",
        "goal": "subtract 10 from the result of adding 7 and 8",
        "layer": "EXECUTION",
        "validates": "Non-commutative operation chaining",
        "expected_type": "exact",
        "expected": "5",
    },
    {
        "name": "EXEC-08: Chaining - Sequential Addition",
        "goal": "add the result of adding 1 and 2 and 3",
        "layer": "EXECUTION",
        "validates": "Sequential chaining with same tool",
        "expected_type": "exact",
        "expected": "6",
    },
    {
        "name": "EXEC-09: Domain Error - No Repair",
        "goal": "divide 10 by 0",
        "layer": "EXECUTION",
        "validates": "Tool returns error without triggering repair",
        "expected_type": "contains",
        "expected": ["division by zero"],
        "forbidden": ["repair", "code_agent"],
    },
    {
        "name": "EXEC-10: Chaining - Error Propagation Block",
        "goal": "divide 10 by 0 then multiply the result of previous step by 2",
        "layer": "EXECUTION",
        "validates": "Error results do not chain to next step",
        "expected_type": "contains",
        "expected": ["error"],
        "forbidden": ["multiply_numbers(0", "None"],
    },
    {
        "name": "EXEC-11: Tool Execution - String Args",
        "goal": "multiply the result of adding 6 and 4 by 3",
        "layer": "EXECUTION",
        "validates": "No token leakage in execution",
        "expected_type": "exact",
        "expected": "30",
        "forbidden": ["result", "previous", "step", "and"],
    },
    {
        "name": "EXEC-12: Repair Loop - Fixable Tool",
        "goal": "test broken_add with inputs 4 and 2 expected output 6",
        "layer": "EXECUTION",
        "validates": "Repair loop fixes broken tool and re-executes",
        "expected_type": "contains",
        "expected": ["6"],
    },
    {
        "name": "EXEC-13: Unfixable Tool - Repair Limit",
        "goal": "test bad_add with inputs a and t expected output 999999",
        "layer": "EXECUTION",
        "validates": "Repair loop terminates after max attempts",
        "expected_type": "contains",
        "expected": ["repair", "failed"],
        "forbidden": ["999999"],
    },
]

# VALIDATION LAYER TESTS
# Validates: plan validation, arg count checks, tool existence, schema enforcement
VALIDATION_LAYER_TESTS = [
    {
        "name": "VAL-01: Unknown Tool (True Non-Existing)",
        "goal": "use completely_fake_tool_xyz to process data",
        "layer": "VALIDATION",
        "validates": "Validation rejects plan with non-existent tool",
        "expected_type": "contains",
        "expected": ["validation error", "unknown tool", "completely_fake_tool_xyz"],
        "forbidden": ["traceback", "keyerror"],
    },
    {
        "name": "VAL-02: Missing Arguments",
        "goal": "use add_numbers",
        "layer": "VALIDATION",
        "validates": "Validation detects missing required arguments",
        "expected_type": "contains",
        "expected": ["validation error", "invalid argument"],
        "forbidden": ["traceback", "keyerror"],
    },
    {
        "name": "VAL-03: Invalid Input Types",
        "goal": "add 'hello' and 'world'",
        "layer": "VALIDATION",
        "validates": "Validation catches type mismatch",
        "expected_type": "contains",
        "expected": ["validation error", "invalid argument"],
        "forbidden": ["traceback", "keyerror"],
    },
    {
        "name": "VAL-04: Chaining - No Previous Result",
        "goal": "multiply the result of previous step by 2",
        "layer": "VALIDATION",
        "validates": "Validation blocks chaining when no previous step exists",
        "expected_type": "contains",
        "expected": ["validation error", "invalid argument"],
        "forbidden": ["traceback", "keyerror"],
    },
    {
        "name": "VAL-05: Malformed Args - Empty List",
        "goal": "square the square root of 16",
        "layer": "VALIDATION",
        "validates": "Validation catches wrong arg count in plan",
        "expected_type": "contains",
        "expected": ["validation error", "argument"],
        "forbidden": ["traceback", "keyerror"],
    },
    {
        "name": "VAL-06: Multi-Step Reference (Invalid)",
        "goal": "add the result of adding 2 and 3 to the result of adding 4 and 5",
        "layer": "VALIDATION",
        "validates": "Validation rejects plans with multiple result references",
        "expected_type": "contains",
        "expected": ["error", "argument"],
        "forbidden": ["traceback", "keyerror", "14"],
    },
    {
        "name": "VAL-07: Non-Commutative Safety",
        "goal": "subtract the result of subtracting 10 and 2 from the result of subtracting 20 and 5",
        "layer": "VALIDATION",
        "validates": "Validation blocks invalid multi-reference in subtraction",
        "expected_type": "contains",
        "expected": ["error", "argument"],
        "forbidden": ["traceback", "keyerror"],
    },
    {
        "name": "VAL-08: Tool Argument Integrity",
        "goal": "add the result of adding 1 and 2 and 3",
        "layer": "VALIDATION",
        "validates": "Validation ensures correct arg decomposition",
        "expected_type": "exact",
        "expected": "6",
    },
]

# PLANNER LAYER TESTS
# Validates: tool selection, plan structure, JSON integrity, step decomposition
PLANNER_LAYER_TESTS = [
    {
        "name": "PLAN-01: Basic Tool Selection",
        "goal": "add 2 and 3",
        "layer": "PLANNER",
        "validates": "Planner selects correct tool for simple operation",
        "expected_type": "exact",
        "expected": "5",
        "forbidden": ["{", "}", "[", "]"],
    },
    {
        "name": "PLAN-02: Nested Operation Decomposition",
        "goal": "square the result of adding 2 and 3",
        "layer": "PLANNER",
        "validates": "Planner decomposes nested operations into steps",
        "expected_type": "exact",
        "expected": "25",
    },
    {
        "name": "PLAN-03: Multi-Step Decomposition",
        "goal": "multiply the result of adding 6 and 4 by 3",
        "layer": "PLANNER",
        "validates": "Planner creates correct multi-step plan",
        "expected_type": "exact",
        "expected": "30",
    },
    {
        "name": "PLAN-04: Tool Enforcement",
        "goal": "use a non_existing_tool to add 2 and 3",
        "layer": "PLANNER",
        "validates": "Planner respects explicit tool name in goal",
        "expected_type": "exact",
        "expected": "-999",
    },
    {
        "name": "PLAN-05: Args vs Input Text Consistency",
        "goal": "add 2 and 3",
        "layer": "PLANNER",
        "validates": "Planner generates consistent args and input_text",
        "expected_type": "exact",
        "expected": "5",
        "forbidden": ["23", "32"],
    },
    {
        "name": "PLAN-06: Planner Retry Stability",
        "goal": "square the result of adding 2 and 3",
        "layer": "PLANNER",
        "validates": "Planner produces stable output across retries",
        "expected_type": "exact",
        "expected": "25",
    },
    {
        "name": "PLAN-07: Ambiguous Phrasing - Natural Language",
        "goal": "add 3 and 5 then square the result",
        "layer": "PLANNER",
        "validates": "Planner handles natural language chaining",
        "expected_type": "exact",
        "expected": "64",
    },
    {
        "name": "PLAN-08: Ambiguous Phrasing - Function Syntax",
        "goal": "square(add(3,5))",
        "layer": "PLANNER",
        "validates": "Planner handles function-style syntax",
        "expected_type": "exact",
        "expected": "64",
    },
    {
        "name": "PLAN-09: Complex Nested Operations",
        "goal": "square the result of multiplying the result of adding 2 and 3 by 4",
        "layer": "PLANNER",
        "validates": "Planner handles deep nesting correctly",
        "expected_type": "exact",
        "expected": "400",
    },
    {
        "name": "PLAN-10: Sequential Same-Tool Operations",
        "goal": "add the result of adding 1 and 2 and 3",
        "layer": "PLANNER",
        "validates": "Planner decomposes sequential operations with same tool",
        "expected_type": "exact",
        "expected": "6",
    },
]

# ── Core Runner ──────────────────────────────────────────────────────────────

def run_manager(goal: str, test_name: str = "unnamed") -> str:
    """Run manager.py headlessly via subprocess."""
    manager_script = BASE_PATH / "projects" / "manager" / "manager.py"
    
    try:
        # Run manager.py with goal piped to stdin
        process = subprocess.Popen(
            [sys.executable, manager_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        
        # Send goal + empty line to trigger execution, then close stdin
        stdout, _ = process.communicate(input=f"{goal}\n\n", timeout=60)
        
        output = stdout

    except subprocess.TimeoutExpired:
        process.kill()
        output = "FINAL ANSWER: Test timeout after 60s"
    except Exception as e:
        output = f"FINAL ANSWER: Harness error: {e}"

    return output

# ── Helpers ──────────────────────────────────────────────────────────────────

def extract_final_answer(output: str) -> str:
    """Extract FINAL ANSWER from output."""
    match = re.search(r"FINAL ANSWER:\s*([^\n\r]+)", output, re.IGNORECASE)
    return match.group(1).strip() if match else output.strip()

def detect_crash(output: str) -> bool:
    """Detect if the test crashed with unhandled exception."""
    crash_patterns = [
        r"Traceback \(most recent call last\)",
        r"KeyError:",
        r"AttributeError:",
        r"TypeError:",
        r"ValueError:.*(?!VALIDATION ERROR)",
    ]
    return any(re.search(pattern, output, re.IGNORECASE) for pattern in crash_patterns)

def detect_validation_error(output: str) -> bool:
    """Detect if validation blocked the plan."""
    return bool(re.search(r"\[VALIDATION ERROR\]", output, re.IGNORECASE))

# ── Test Runner ──────────────────────────────────────────────────────────────

def run_layer_tests(test_cases: List[Dict], layer_name: str) -> Tuple[List[Dict], int]:
    """Run tests for a specific layer and return results."""
    results = []
    pass_count = 0

    for test in test_cases:
        start = time.time()

        try:
            output = run_manager(test["goal"], test["name"])
            duration = time.time() - start
            final_answer = extract_final_answer(output)
            final_lower = final_answer.lower()
            output_lower = output.lower()

            # Crash detection
            crashed = detect_crash(output)
            validation_blocked = detect_validation_error(output)

            status = "FAIL"
            failure_reason = ""

            # Crash is always a failure
            if crashed:
                status = "FAIL (CRASH)"
                failure_reason = "Unhandled exception detected"
            else:
                # Expected checks
                if test["expected_type"] == "exact":
                    fa = final_answer.strip()
                    exp = test["expected"]

                    try:
                        if float(fa) == float(exp):
                            status = "PASS"
                        else:
                            failure_reason = f"Expected {exp}, got {fa}"
                    except:
                        if fa == exp:
                            status = "PASS"
                        else:
                            failure_reason = f"Expected '{exp}', got '{fa}'"

                elif test["expected_type"] == "contains":
                    missing = [e for e in test["expected"] if e.lower() not in output_lower]
                    if not missing:
                        status = "PASS"
                    else:
                        failure_reason = f"Missing expected content: {missing}"

                # Forbidden checks (search in full output, not just final answer)
                if status == "PASS" and "forbidden" in test:
                    for f in test["forbidden"]:
                        # Case-insensitive substring search
                        if f.lower() in output_lower:
                            status = "FAIL (forbidden content)"
                            failure_reason = f"Found forbidden content: '{f}'"
                            break

            results.append({
                "name": test["name"],
                "goal": test["goal"],
                "layer": test["layer"],
                "validates": test["validates"],
                "status": status,
                "final_answer": final_answer,
                "duration_sec": round(duration, 2),
                "crashed": crashed,
                "validation_blocked": validation_blocked,
                "failure_reason": failure_reason,
                "expected": test.get("expected", ""),
            })

            if status == "PASS":
                pass_count += 1

        except Exception as e:
            results.append({
                "name": test["name"],
                "goal": test["goal"],
                "layer": test["layer"],
                "validates": test["validates"],
                "status": f"FAIL (harness exception)",
                "final_answer": "",
                "duration_sec": round(time.time() - start, 2),
                "crashed": True,
                "validation_blocked": False,
                "failure_reason": str(e),
                "expected": test.get("expected", ""),
            })

    return results, pass_count

# ── Reset broken tools  ──────────────────────────────────────────────────────

def reset_broken_tools():
    TOOLS_PATH = BASE_PATH / "tools"

    bad_add_content = '''\
INPUT_SPEC = {
    "a": "number",
    "b": "number"
}

def run(*args):
    a, b = args
    return int(a) + int(b)
'''

    broken_add_content = '''\
INPUT_SPEC = {
    "x": "number",
    "y": "number"
}

def run(*args):
    x, y = args
    return x + yyy
'''

    files = {
        "bad_add.py": bad_add_content,
        "broken_add.py": broken_add_content,
    }

    for filename, content in files.items():
        path = TOOLS_PATH / filename
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content.strip())
        except Exception as e:
            pass

# ── File-Based Logging ───────────────────────────────────────────────────────

def write_layer_log(layer_name: str, results: List[Dict], pass_count: int):
    """Write clean, structured log for a specific layer."""
    log_file = os.path.join(LOG_DIR, f"{layer_name.lower()}_layer_regression_log.txt")
    
    total = len(results)
    fail_count = total - pass_count
    crash_count = sum(1 for r in results if r.get("crashed", False))
    validation_count = sum(1 for r in results if r.get("validation_blocked", False))
    
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("="*80 + "\n")
        f.write(f"AI LAB — {layer_name.upper()} LAYER REGRESSION LOG\n")
        f.write("="*80 + "\n\n")
        
        for r in results:
            status_icon = "✓" if r['status'] == "PASS" else "✗"
            f.write(f"{status_icon} [{r['status']}] {r['name']}\n")
            f.write(f"  Layer: {r['layer']}\n")
            f.write(f"  Validates: {r['validates']}\n")
            f.write(f"  Goal: {r['goal']}\n")
            f.write(f"  Expected: {r.get('expected', 'N/A')}\n")
            f.write(f"  Final Answer: {r['final_answer'] or '<none>'}\n")
            
            if r.get('failure_reason'):
                f.write(f"  Failure Reason: {r['failure_reason']}\n")
            
            flags = []
            if r.get('crashed'):
                flags.append("CRASH")
            if r.get('validation_blocked'):
                flags.append("VALIDATION_BLOCKED")
            if flags:
                f.write(f"  Flags: {', '.join(flags)}\n")
            
            f.write(f"  Duration: {r['duration_sec']}s\n")
            f.write("-"*80 + "\n")
        
        f.write(f"\n{'='*80}\n")
        f.write(f"SUMMARY\n")
        f.write(f"{'='*80}\n")
        f.write(f"Total Tests:       {total}\n")
        f.write(f"Passed:            {pass_count} ({100*pass_count//total if total else 0}%)\n")
        f.write(f"Failed:            {fail_count} ({100*fail_count//total if total else 0}%)\n")
        f.write(f"Crashes:           {crash_count}\n")
        f.write(f"Validation Blocks: {validation_count}\n")
        f.write(f"\nOVERALL: {'✓ PASS' if pass_count == total else '✗ FAIL'}\n")
        f.write("="*80 + "\n")
    
    return log_file

# ── Report ───────────────────────────────────────────────────────────────────

def print_layer_report(layer_name: str, results: List[Dict], pass_count: int):
    """Print report for a specific layer."""
    print("\n" + "="*80)
    print(f"AI LAB — {layer_name.upper()} LAYER REPORT")
    print("="*80 + "\n")

    crash_count = sum(1 for r in results if r.get("crashed", False))
    validation_count = sum(1 for r in results if r.get("validation_blocked", False))

    for r in results:
        status_icon = "[PASS]" if r['status'] == "PASS" else "[FAIL]"
        print(f"{status_icon} {r['name']}")
        print(f"  Validates: {r['validates']}")
        print(f"  Goal: {r['goal']}")
        
        if r.get('failure_reason'):
            print(f"  Failure: {r['failure_reason']}")
        
        print(f"  Duration: {r['duration_sec']}s")
        print("-"*80)

    total = len(results)
    fail_count = total - pass_count
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Total Tests:       {total}")
    print(f"Passed:            {pass_count} ({100*pass_count//total if total else 0}%)")
    print(f"Failed:            {fail_count} ({100*fail_count//total if total else 0}%)")
    print(f"Crashes:           {crash_count}")
    print(f"Validation Blocks: {validation_count}")
    print(f"\nOVERALL: {'✓ PASS' if pass_count == total else '✗ FAIL'}")
    print("="*80)

# ── Entry ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run layered regression tests")
    parser.add_argument("--layer", choices=["execution", "validation", "planner", "all"], 
                        default="all", help="Which layer to test")
    args = parser.parse_args()
    
    reset_broken_tools()
    
    if args.layer == "execution" or args.layer == "all":
        print("\n" + "="*80)
        print("RUNNING EXECUTION LAYER TESTS")
        print("="*80)
        results, pass_count = run_layer_tests(EXECUTION_LAYER_TESTS, "EXECUTION")
        log_file = write_layer_log("execution", results, pass_count)
        print_layer_report("EXECUTION", results, pass_count)
        print(f"\nLog saved: {log_file}")
    
    if args.layer == "validation" or args.layer == "all":
        print("\n" + "="*80)
        print("RUNNING VALIDATION LAYER TESTS")
        print("="*80)
        results, pass_count = run_layer_tests(VALIDATION_LAYER_TESTS, "VALIDATION")
        log_file = write_layer_log("validation", results, pass_count)
        print_layer_report("VALIDATION", results, pass_count)
        print(f"\nLog saved: {log_file}")
    
    if args.layer == "planner" or args.layer == "all":
        print("\n" + "="*80)
        print("RUNNING PLANNER LAYER TESTS")
        print("="*80)
        results, pass_count = run_layer_tests(PLANNER_LAYER_TESTS, "PLANNER")
        log_file = write_layer_log("planner", results, pass_count)
        print_layer_report("PLANNER", results, pass_count)
        print(f"\nLog saved: {log_file}")

"""
AI Lab — Test Harness with Phase 4B Lock Validation

EXTENDS existing test harness (preserves all original functionality)
ADDS Phase 4B lock certification with strict validation

Usage:
    python run_tests.py              # Run existing tests (unchanged)
    python run_tests.py --trace      # Run with full layer trace capture
    python run_tests.py --lock-check # Run Phase 4B lock certification
"""

import copy
import sys
import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# Add current directory to path for local utility imports (future-proofing for utils/ relocation)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Original test imports (preserved)
from test_cases import TEST_CASES
from test_runner import run_test
from result_evaluator import evaluate_result
from reporter import print_report

# Phase 4B Lock Validation imports (NEW)
from lock_validator import ArchitectureValidator, DeterminismValidator, Phase4BValidator
from strict_evaluator import StrictEvaluator
from lock_test_cases import LOCK_TEST_CASES, get_p0_tests

# Trace mode imports (only used when TRACE_MODE=True)
# These are imported here to avoid loading overhead in normal mode
# but loaded at module level for trace mode
from core.planner import generate_structured_plan
from core.parser import parse_tool_input
from core.argument_resolver import resolve_arguments
from core.chain_resolver import resolve_chain
from core.validation import validate_plan
from core.config import config
from core.logger import log


# =============================================================================
# PHASE 3 BASELINE TEST SUITE (APPEND ONLY — DO NOT REPLACE EXISTING)
# =============================================================================

PHASE3_BASELINE_TESTS = [
    "read file test.txt",
    "read webpage https://example.com",
    "add 2 and 3",
    "add x and y",
    "read file 123",
    "add 2 and 3 then multiply by 4",
    "multiply the result by 4",
    "read file test.txt"
]

# =============================================================================
# TRACE CAPTURE SYSTEM (NEW — DOES NOT MODIFY CORE LOGIC)
# =============================================================================

class TraceCapture:
    """
    Captures all layer outputs during test execution.
    
    This class wraps around the existing pipeline WITHOUT modifying
    any core logic. It captures intermediate states by:
    1. Calling planner directly and capturing output
    2. Calling parser directly and capturing tokens
    3. Calling resolver directly and capturing resolved args
    4. Calling validation directly and capturing result
    5. Capturing chain resolution before/after states
    6. Capturing execution results
    
    NO MODIFICATIONS to core modules — purely observational.
    """
    
    def __init__(self):
        self.traces: List[Dict[str, Any]] = []
        self.current_trace: Optional[Dict[str, Any]] = None
    
    def start_trace(self, test_input: str):
        """Initialize a new trace for a test input."""
        # Apply input normalization (remove noise words)
        normalized = test_input
        if test_input:
            test_lower = test_input.strip().lower()
            if test_lower.startswith("hey "):
                normalized = test_input.strip()[4:].strip()
            elif test_lower.startswith("please "):
                normalized = test_input.strip()[7:].strip()
        
        self.current_trace = {
            "input": test_input,
            "normalized_input": normalized,
            "planner_output_raw": [],  # IMMUTABLE snapshot of planner output
            "structured_plan": [],  # IMMUTABLE copy for observability
            "parser_tokens": [],
            "resolver_output": [],  # List of resolved args per step
            "working_plan": [],  # Mutable plan with args attached (matches real execution)
            "validation_input": [],  # What validation actually receives
            "validation_input_source": None,  # Track which object was validated
            "post_chain_arguments": [],  # Args after chain resolution
            "execution_steps": [],  # Record of each tool execution
            "final_result": None,  # Final execution result
            "validation_result": {
                "passed": False,
                "error": ""
            },
            "execution_result": None,
            "error": None,
            "raw_manager_output": None
        }
    
    def capture_planner(self, goal: str, tool_index: Dict) -> Any:
        """
        Capture planner output.
        Calls generate_structured_plan directly (no core logic modification).
        Stores IMMUTABLE deep copy to prevent mutation.
        """
        try:
            # Get tool names from tool_index
            tool_names = list(tool_index.keys()) if tool_index else []
            
            # Call planner directly
            planner_output = generate_structured_plan(goal, tool_names)
            
            # Capture IMMUTABLE deep copy in trace
            # This ensures planner_output_raw can NEVER be modified
            self.current_trace["planner_output_raw"] = copy.deepcopy(planner_output or [])
            
            if isinstance(planner_output, dict) and "operations" in planner_output:
                normalized_plan = planner_output["operations"]
            else:
                normalized_plan = planner_output or []
            
            self.current_trace["planner_output"] = copy.deepcopy(normalized_plan)
            
            return planner_output
        except Exception as e:
            self.current_trace["planner_output_raw"] = {"error": str(e)}
            raise
    
    def capture_parser(self, input_text: str) -> List:
        """
        Capture parser tokens.
        Calls parse_tool_input directly.
        """
        try:
            tokens = parse_tool_input(input_text)
            self.current_trace["parser_tokens"] = tokens
            return tokens
        except Exception as e:
            self.current_trace["parser_tokens"] = {"error": str(e)}
            raise
    
    def capture_resolver(self, tool_name: str, tokens: List, input_text: str) -> List:
        """
        Capture argument resolver output.
        Calls resolve_arguments directly.
        """
        try:
            resolved = resolve_arguments(tool_name, tokens, input_text)
            self.current_trace["resolver_output"] = resolved or []
            return resolved
        except Exception as e:
            self.current_trace["resolver_output"] = {"error": str(e)}
            raise
    
    def capture_validation(self, structured_plan: List, tool_index: Dict) -> tuple:
        """
        Capture validation result.
        Calls validate_plan directly.
        """
        try:
            is_valid, error = validate_plan(structured_plan, tool_index)
            self.current_trace["validation_result"] = {
                "passed": is_valid,
                "error": str(error) if error else ""
            }
            return is_valid, error
        except Exception as e:
            self.current_trace["validation_result"] = {
                "passed": False,
                "error": str(e)
            }
            raise
    
    def capture_resolver_output(self, step_index: int, resolved_args: List):
        """
        Capture resolver output for a specific step.
        Stored separately from planner output to maintain layer purity.
        """
        # Ensure resolver_output list is long enough
        while len(self.current_trace["resolver_output"]) <= step_index:
            self.current_trace["resolver_output"].append([])
        
        self.current_trace["resolver_output"][step_index] = resolved_args
    
    def capture_post_chain_args(self, step_index: int, args: List):
        """
        Capture arguments after chain resolution.
        Stored separately to show transformation from resolver_output.
        """
        # Ensure post_chain_arguments list is long enough
        while len(self.current_trace["post_chain_arguments"]) <= step_index:
            self.current_trace["post_chain_arguments"].append([])
        
        self.current_trace["post_chain_arguments"][step_index] = args
    
    def capture_execution_step(self, step_index: int, tool: str, input_args: List, output: Any):
        """
        Capture a single tool execution step.
        Records tool name, input arguments, and output.
        """
        # Ensure execution_steps list is long enough
        while len(self.current_trace["execution_steps"]) <= step_index:
            self.current_trace["execution_steps"].append({})
        
        self.current_trace["execution_steps"][step_index] = {
            "tool": tool,
            "input": input_args,
            "output": output
        }
    
    def capture_execution_result(self, result: Any):
        """Capture final execution result."""
        self.current_trace["execution_result"] = result
    
    def capture_error(self, error: str):
        """Capture any error during execution."""
        self.current_trace["error"] = error
    
    def capture_raw_output(self, output: str):
        """Capture raw manager output for comparison."""
        self.current_trace["raw_manager_output"] = output
    
    def finalize_trace(self):
        """Add current trace to traces list."""
        if self.current_trace:
            self.traces.append(self.current_trace)
            self.current_trace = None
    
    def save_traces(self, filename: str = "phase3_trace_output.json"):
        """Save all traces to JSON file."""
        output_path = os.path.join(os.path.dirname(__file__), filename)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.traces, f, indent=2, ensure_ascii=False)
        return output_path


# Global trace capture instance
trace_capture: Optional[TraceCapture] = None


# =============================================================================
# ORIGINAL HARNESS FUNCTIONS (PRESERVED EXACTLY)
# =============================================================================

def execute_layer(layer_name: str, selected_test: str = None):
    """Original layer execution — UNCHANGED."""
    print(f"[HARNESS] Executing layer: {layer_name}")
    
    results = []
    
    for test in TEST_CASES:
        if selected_test and test["name"] != selected_test:
            continue
        
        if "layer" in test and test["layer"] != layer_name:
            continue
        
        output = run_test(test["input"])
        evaluation = evaluate_result(output, test["expected"])
        
        results.append({
            "name": test["name"],
            "evaluation": evaluation,
            "expected": test["expected"]
        })
    
    print_report(results)


def run_execution_layer(selected_test=None):
    execute_layer("execution", selected_test)


def run_validation_layer(selected_test=None):
    execute_layer("validation", selected_test)


def run_planner_layer(selected_test=None):
    """Original planner layer runner — UNCHANGED."""
    execute_layer("planner", selected_test)


# =============================================================================
# TRACE MODE FUNCTIONS (NEW — EXTENDS ORIGINAL)
# =============================================================================

def load_tool_index():
    """Load tool index for trace mode."""
    tool_index_path = os.path.join(
        os.path.dirname(__file__), '..', 'memory', 'tool_index', 'tools.json'
    )
    if os.path.exists(tool_index_path):
        with open(tool_index_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def run_trace_test(test_input: str, tool_index: Dict) -> Dict[str, Any]:
    """
    Run a single test with full layer trace capture.
    
    This function executes the pipeline layer by layer, capturing
    intermediate outputs WITHOUT modifying any core logic.
    
    CRITICAL: Planner output is captured as IMMUTABLE deep copy
    and NEVER modified. All downstream processing uses separate copies.
    """
    global trace_capture
    
    if trace_capture is None:
        trace_capture = TraceCapture()
    
    trace_capture.start_trace(test_input)
    
    try:
        # =============================
        # LAYER 1: PLANNER
        # =============================
        # Use normalized input for planner
        normalized_input = trace_capture.current_trace["normalized_input"]
        planner_output = trace_capture.capture_planner(normalized_input, tool_index)
        
        # Handle planner failure
        if isinstance(planner_output, dict) and planner_output.get("type") == "failure":
            trace_capture.capture_error(f"Planner failure: {planner_output.get('reason')}")
            # TRACE CONTRACT: Ensure all fields are iterable before return
            for field in ["planner_output_raw", "structured_plan", "working_plan", "validation_input"]:
                if trace_capture.current_trace.get(field) is None:
                    trace_capture.current_trace[field] = []
            trace_capture.finalize_trace()
            return trace_capture.traces[-1]
        
        if planner_output is None:
            trace_capture.capture_error("Planner returned None")
            # TRACE CONTRACT: Ensure all fields are iterable before return
            for field in ["planner_output_raw", "structured_plan", "working_plan", "validation_input"]:
                if trace_capture.current_trace.get(field) is None:
                    trace_capture.current_trace[field] = []
            trace_capture.finalize_trace()
            return trace_capture.traces[-1]
        
        # Create IMMUTABLE structured_plan for observability
        # This preserves the pure planner output structure
        if isinstance(planner_output, dict) and "raw_output" in planner_output:
            import json
            structured_plan = json.loads(planner_output["raw_output"])
        elif isinstance(planner_output, list):
            structured_plan = copy.deepcopy(planner_output)
        else:
            structured_plan = []
        
        trace_capture.current_trace["structured_plan"] = copy.deepcopy(structured_plan)
        
        # =============================
        # LAYER 2: PARSER (per step)
        # =============================
        all_tokens = []
        for step in structured_plan:
            if step.get("type") == "tool":
                input_text = step.get("input_text", "")
                tokens = trace_capture.capture_parser(input_text)
                all_tokens.append(tokens)
        
        # =============================
        # LAYER 3: ARGUMENT RESOLVER
        # =============================
        # Store resolved args separately - DO NOT modify planner output
        resolved_args_per_step = []
        for step_idx, step in enumerate(structured_plan):
            if step.get("type") == "tool":
                input_text = step.get("input_text", "")
                tokens = parse_tool_input(input_text)
                resolved = resolve_arguments(step["name"], tokens, input_text)
                trace_capture.capture_resolver_output(step_idx, resolved if resolved else [])
                resolved_args_per_step.append(resolved if resolved else [])
            else:
                resolved_args_per_step.append([])
        
        # =============================
        # CREATE WORKING PLAN (REAL EXECUTION MODEL)
        # =============================
        # This matches how manager.py actually works:
        # Planner → Resolver → Args attached → Validation
        working_plan = copy.deepcopy(structured_plan)
        
        # Attach resolved arguments to working plan
        for step_idx, step in enumerate(working_plan):
            if step.get("type") == "tool":
                step["args"] = resolved_args_per_step[step_idx] or []
        
        # Store working_plan in trace for observability
        trace_capture.current_trace["working_plan"] = copy.deepcopy(working_plan)
        
        # =============================
        # LAYER 4: VALIDATION
        # =============================
        # Pass working_plan WITH args to validation (matches real execution)
        trace_capture.current_trace["validation_input"] = copy.deepcopy(working_plan)
        trace_capture.current_trace["validation_input_source"] = "working_plan"
        is_valid, error = trace_capture.capture_validation(working_plan, tool_index)
        
        if not is_valid:
            # TRACE CONTRACT: Ensure all fields are iterable before return
            for field in ["planner_output_raw", "structured_plan", "working_plan", "validation_input"]:
                if trace_capture.current_trace.get(field) is None:
                    trace_capture.current_trace[field] = []
            trace_capture.finalize_trace()
            return trace_capture.traces[-1]
        
        # Initialize execution tracking variables
        previous_result = None
        final_result = None
        
        # Helper function for tool execution
        def execute_tool(tool_name, final_args):
            tool_path = os.path.join(
                os.path.dirname(__file__), '..', 'tools', f"{tool_name}.py"
            )
            
            if os.path.exists(tool_path):
                import importlib
                module = importlib.import_module(f"tools.{tool_name}")
                return module.run(*final_args)
            else:
                return {"error": f"Tool {tool_name} not found"}
        
        # =============================
        # LAYER 5: EXECUTION (with chain resolution capture)
        # =============================
        for step_idx, step in enumerate(structured_plan):
            if step.get("type") == "tool":
                # STEP 1: Get resolved args
                resolved = resolved_args_per_step[step_idx]
                args = resolved if resolved else []
                
                # STEP 2: Replace PREVIOUS_RESULT
                final_args = []
                for arg in args:
                    if arg == "PREVIOUS_RESULT":
                        final_args.append(previous_result)
                    else:
                        final_args.append(arg)
                
                # STEP 3: Execute tool
                try:
                    result = execute_tool(step["name"], final_args)
                except Exception as e:
                    result = {"error": str(e)}
                
                # STEP 4: Capture execution
                trace_capture.capture_execution_step(step_idx, step["name"], list(final_args), result)
                
                # STEP 5: Store result
                previous_result = result
                final_result = result
                
                # Capture post-chain args for trace
                trace_capture.capture_post_chain_args(step_idx, list(final_args))
        
        # Store final result in trace
        trace_capture.current_trace["final_result"] = final_result
        
        trace_capture.finalize_trace()
        return trace_capture.traces[-1]
        
    except Exception as e:
        trace_capture.capture_error(str(e))
        # TRACE CONTRACT: Ensure all fields are iterable before return
        for field in ["planner_output_raw", "structured_plan", "working_plan", "validation_input"]:
            if trace_capture.current_trace.get(field) is None:
                trace_capture.current_trace[field] = []
        trace_capture.finalize_trace()
        return trace_capture.traces[-1]


def run_phase3_trace_tests():
    """
    Run Phase 3 baseline tests with full trace capture.
    """
    global trace_capture
    trace_capture = TraceCapture()
    
    tool_index = load_tool_index()
    
    print("=" * 60)
    print("PHASE 3 BASELINE TRACE — LAYER-BY-LAYER OBSERVATION")
    print("=" * 60)
    print(f"Running {len(PHASE3_BASELINE_TESTS)} tests with full trace capture...\n")
    
    for i, test_input in enumerate(PHASE3_BASELINE_TESTS, 1):
        print(f"[{i}/{len(PHASE3_BASELINE_TESTS)}] Testing: {test_input}")
        
        try:
            trace = run_trace_test(test_input, tool_index)
            status = "✅ COMPLETE" if trace.get("error") is None else f"❌ ERROR: {trace.get('error')}"
            print(f"      Status: {status}")
        except Exception as e:
            print(f"      Status: ❌ EXCEPTION: {e}")
            # Still capture the error
            if trace_capture.current_trace:
                trace_capture.capture_error(str(e))
                trace_capture.finalize_trace()
    
    # Save traces
    output_path = trace_capture.save_traces("phase3_trace_output.json")
    
    print("\n" + "=" * 60)
    print(f"TRACE CAPTURE COMPLETE")
    print(f"Output saved to: {output_path}")
    print(f"Total traces: {len(trace_capture.traces)}")
    print("=" * 60)
    
    # Print summary
    print("\nTRACE SUMMARY:")
    for trace in trace_capture.traces:
        print(f"  Input: {trace['input'][:50]}...")
        planner_raw = trace.get('planner_output_raw')
        print(f"    Planner (raw): {'✅' if planner_raw and 'error' not in planner_raw else '❌'}")
        print(f"    Parser: {'✅' if trace.get('parser_tokens') else '❌'}")
        print(f"    Resolver: {'✅' if trace.get('resolver_output') else '❌'}")
        print(f"    Post-Chain: {'✅' if trace.get('post_chain_arguments') else '❌'}")
        print(f"    Validation: {'✅' if trace.get('validation_result', {}).get('passed') else '❌'}")
        print(f"    Execution: {'✅' if trace.get('execution_result') else '❌'}")
        if trace.get('error'):
            print(f"    Error: {trace['error']}")
    
    return trace_capture.traces


# =============================================================================
# PHASE 4B LOCK CERTIFICATION MODE (NEW)
# =============================================================================

def run_determinism_check(test_input: str, runs: int = 3) -> Dict[str, Any]:
    """
    Run test multiple times and verify deterministic behavior.
    
    Args:
        test_input: Test input string
        runs: Number of times to run (default 3)
        
    Returns:
        {
            "passed": bool,
            "outputs": [str],
            "error": str or None
        }
    """
    outputs = []
    
    for i in range(runs):
        try:
            output = run_test(test_input)
            outputs.append(output)
        except Exception as e:
            return {
                "passed": False,
                "outputs": outputs,
                "error": f"Execution failed on run {i+1}: {str(e)}"
            }
    
    # Validate determinism
    validator = DeterminismValidator()
    passed, error = validator.validate_determinism(outputs)
    
    return {
        "passed": passed,
        "outputs": outputs,
        "error": error
    }


def run_single_test_wrapper(args):
    """Wrapper function for parallel test execution."""
    test, tool_index = args
    result = run_lock_test(test, tool_index)
    # Ensure test metadata is attached
    result["name"] = test["name"]
    result["category"] = test.get("category", "unknown")
    result["input"] = test["input"]
    return result


def run_lock_test(test: Dict[str, Any], tool_index: Dict) -> Dict[str, Any]:
    """
    Run a single lock test with full validation.
    
    CRITICAL: Uses manager.py execution for pass/fail.
    Uses trace mode ONLY for architecture validation (observational).
    
    Args:
        test: Test specification
        tool_index: Tool index for trace mode
        
    Returns:
        {
            "name": str,
            "status": "PASS" or "FAIL",
            "failure_type": str or None,
            "reason": str,
            "actual": str,
            "determinism": {...},
            "architecture": {...},
            "details": {...}
        }
    """
    test_name = test["name"]
    test_input = test["input"]
    expected = test["expected"]
    
    print(f"  Running: {test_name}")
    
    # =========================================================================
    # STEP 1: DETERMINISM CHECK (via manager.py execution)
    # =========================================================================
    print(f"    [1/3] Determinism check (3 runs)...")
    determinism_result = run_determinism_check(test_input, runs=3)
    determinism_passed = determinism_result["passed"]
    
    if not determinism_passed:
        print(f"    ❌ Determinism FAILED: {determinism_result['error']}")
    else:
        print(f"    ✅ Determinism PASSED")
    
    # Use first output for evaluation
    manager_output = determinism_result["outputs"][0] if determinism_result["outputs"] else ""
    
    # =========================================================================
    # STEP 2: ARCHITECTURE VALIDATION (via trace mode - OBSERVATIONAL ONLY)
    # =========================================================================
    print(f"    [2/3] Architecture validation...")
    architecture_passed = True
    architecture_result = {"passed": True, "violations": [], "checks": {}}
    
    try:
        # Run trace test for architecture observation
        global trace_capture
        if trace_capture is None:
            trace_capture = TraceCapture()
        
        trace_capture.start_trace(test_input)
        trace = run_trace_test(test_input, tool_index)
        
        # Validate architecture using trace data
        arch_validator = ArchitectureValidator()
        architecture_result = arch_validator.validate_all(trace)
        architecture_passed = architecture_result["passed"]
        
        if not architecture_passed:
            print(f"    ❌ Architecture FAILED: {len(architecture_result['violations'])} violations")
            for violation in architecture_result["violations"]:
                print(f"       - {violation}")
        else:
            print(f"    ✅ Architecture PASSED")
            
    except Exception as e:
        architecture_passed = False
        architecture_result = {
            "passed": False,
            "violations": [f"Architecture validation error: {str(e)}"],
            "checks": {}
        }
        print(f"    ❌ Architecture validation error: {str(e)}")
    
    # =========================================================================
    # STEP 3: PHASE 4B FEATURE VALIDATION (if applicable)
    # =========================================================================
    print(f"    [3/3] Phase 4B feature checks...")
    phase4b_passed = True
    phase4b_result = {}
    
    if "phase4b_checks" in test:
        checks = test["phase4b_checks"]
        phase4b_validator = Phase4BValidator()
        
        # Input Normalizer check
        if checks.get("input_normalizer"):
            passed, error = phase4b_validator.validate_input_normalizer(trace, test_input)
            phase4b_result["input_normalizer"] = {"passed": passed, "error": error}
            if not passed:
                phase4b_passed = False
                print(f"       ❌ Input Normalizer: {error}")
        
        # TOOL_PHRASES check
        if "tool_phrases" in checks:
            expected_tool = checks["tool_phrases"]
            passed, error = phase4b_validator.validate_tool_phrases(trace, expected_tool)
            phase4b_result["tool_phrases"] = {"passed": passed, "error": error}
            if not passed:
                phase4b_passed = False
                print(f"       ❌ TOOL_PHRASES: {error}")
        
        # CHAIN_CONNECTORS check
        if "chain_steps" in checks:
            expected_steps = checks["chain_steps"]
            passed, error = phase4b_validator.validate_chain_connectors(trace, expected_steps)
            phase4b_result["chain_connectors"] = {"passed": passed, "error": error}
            if not passed:
                phase4b_passed = False
                print(f"       ❌ CHAIN_CONNECTORS: {error}")
    
    if phase4b_passed:
        print(f"    ✅ Phase 4B checks PASSED")
    
    # =========================================================================
    # STEP 4: STRICT EVALUATION (using manager output)
    # =========================================================================
    evaluator = StrictEvaluator()
    evaluation = evaluator.evaluate(
        manager_output,
        expected,
        determinism_passed=determinism_passed,
        architecture_passed=architecture_passed and phase4b_passed
    )
    
    # Add additional details
    evaluation["determinism"] = {
        "passed": determinism_passed,
        "runs": len(determinism_result["outputs"]),
        "error": determinism_result.get("error")
    }
    evaluation["architecture"] = architecture_result
    evaluation["phase4b"] = phase4b_result
    
    status_symbol = "✅" if evaluation["status"] == "PASS" else "❌"
    print(f"    {status_symbol} Result: {evaluation['status']} - {evaluation['reason']}")
    
    return evaluation


def run_lock_certification():
    """
    Run Phase 4B lock certification.
    
    This is the STRICT validation system that determines:
    PHASE 4B LOCK STATUS = PASS or FAIL
    """
    print("=" * 80)
    print("PHASE 4B LOCK CERTIFICATION")
    print("=" * 80)
    print()
    
    # Load tool index for trace mode
    tool_index = load_tool_index()
    
    # Get P0 tests (critical for lock)
    tests = get_p0_tests()
    
    print(f"Running {len(tests)} P0 (critical) tests...")
    print()
    
    results = []
    
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(run_single_test_wrapper, (test, tool_index))
            for test in tests
        ]
        
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            test_name = result.get("name", "unknown")
            print(f"[{i}/{len(tests)}] {test_name}")
            results.append(result)
            print()
    
    # Sort results by test name for deterministic reporting
    results.sort(key=lambda r: r.get("name", ""))
    
    # =========================================================================
    # GENERATE LOCK CERTIFICATION REPORT
    # =========================================================================
    print("=" * 80)
    print("LOCK CERTIFICATION REPORT")
    print("=" * 80)
    print()
    
    # Count results
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = total - passed
    
    # Count by category
    determinism_failures = sum(1 for r in results if not r["determinism"]["passed"])
    architecture_failures = sum(1 for r in results if not r["architecture"]["passed"])
    
    # Categorize failures
    expected_failures = sum(1 for r in results if r.get("failure_type") == "EXPECTED_FAILURE")
    unexpected_failures = sum(1 for r in results if r.get("failure_type") == "UNEXPECTED_FAILURE")
    
    # Print summary
    print(f"TOTAL TESTS: {total}")
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    print()
    
    print(f"DETERMINISM STATUS: {'PASS' if determinism_failures == 0 else f'FAIL ({determinism_failures} failures)'}")
    print(f"ARCHITECTURE STATUS: {'PASS' if architecture_failures == 0 else f'FAIL ({architecture_failures} failures)'}")
    print(f"VALIDATION STATUS: {'PASS' if unexpected_failures == 0 else f'FAIL ({unexpected_failures} unexpected)'}")
    print()
    
    # Determine lock status
    # STRICT: ALL tests must pass, determinism must pass, architecture must pass
    # NO loopholes, NO expected failure bypass
    lock_passed = (
        failed == 0
        and determinism_failures == 0
        and architecture_failures == 0
    )
    
    print("=" * 80)
    print(f"FINAL STATUS: {'🔒 LOCKED' if lock_passed else '❌ NOT LOCKED'}")
    print("=" * 80)
    print()
    
    # Print failed tests
    if failed > 0:
        print("FAILED TESTS:")
        print()
        for result in results:
            if result["status"] == "FAIL":
                print(f"  ❌ {result['name']}")
                print(f"     Category: {result['category']}")
                print(f"     Failure Type: {result.get('failure_type', 'N/A')}")
                print(f"     Reason: {result['reason']}")
                
                if not result["determinism"]["passed"]:
                    print(f"     Determinism: FAILED - {result['determinism']['error']}")
                
                if not result["architecture"]["passed"]:
                    print(f"     Architecture Violations:")
                    for violation in result["architecture"]["violations"]:
                        print(f"       - {violation}")
                
                print()
    
    # Save detailed results
    output_path = os.path.join(os.path.dirname(__file__), "lock_certification_results.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            "lock_status": "LOCKED" if lock_passed else "NOT_LOCKED",
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "determinism_failures": determinism_failures,
                "architecture_failures": architecture_failures,
                "expected_failures": expected_failures,
                "unexpected_failures": unexpected_failures
            },
            "results": results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"Detailed results saved to: {output_path}")
    print()
    
    return lock_passed


def main():
    print("AI LAB — TEST HARNESS ENTRY POINT")
    
    parser = argparse.ArgumentParser(description="AI Lab Test Harness")
    parser.add_argument(
        "--layer",
        type=str,
        default="all",
        choices=["execution", "validation", "planner", "all"],
        help="Select test layer to run"
    )
    parser.add_argument(
        "--test",
        type=str,
        help="Run a single test by name"
    )
    
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Run Phase 3 baseline tests with full layer trace capture"
    )
    
    parser.add_argument(
        "--lock-check",
        action="store_true",
        help="Run Phase 4B lock certification (strict validation)"
    )
    
    args = parser.parse_args()
    
    # LOCK CERTIFICATION MODE: Run Phase 4B lock validation
    if args.lock_check:
        run_lock_certification()
        return
    
    # TRACE MODE: Run Phase 3 baseline tests with full observability
    if args.trace:
        run_phase3_trace_tests()
        return
    
    # ORIGINAL MODE: Run existing test harness (UNCHANGED)
    if args.layer == "execution":
        run_execution_layer(args.test)
    
    elif args.layer == "validation":
        run_validation_layer(args.test)
    
    elif args.layer == "planner":
        run_planner_layer(args.test)
    
    elif args.layer == "all":
        print("[HARNESS] Running all layers in parallel")
        
        with ProcessPoolExecutor() as executor:
            futures = [
                executor.submit(run_execution_layer, args.test),
                executor.submit(run_validation_layer, args.test),
                executor.submit(run_planner_layer, args.test)
            ]
            
            for future in futures:
                future.result()


if __name__ == "__main__":
    main()

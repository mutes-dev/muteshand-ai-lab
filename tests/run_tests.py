"""
AI Lab — Test Harness with Phase 3 Trace Support

EXTENDS existing test harness (preserves all original functionality)
ADDS trace mode for layer-by-layer observability

Usage:
    python run_tests.py              # Run existing tests (unchanged)
    python run_tests.py --trace      # Run with full layer trace capture
"""

import sys
import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Original test imports (preserved)
from test_cases import TEST_CASES
from test_runner import run_test
from result_evaluator import evaluate_result
from reporter import print_report

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
        self.current_trace = {
            "input": test_input,
            "planner_output": None,
            "parser_tokens": [],
            "resolver_output": [],
            "validation_result": {
                "passed": False,
                "error": None
            },
            "chain_resolution": {
                "before": [],
                "after": []
            },
            "execution_result": None,
            "error": None,
            "raw_manager_output": None
        }
    
    def capture_planner(self, goal: str, tool_index: Dict) -> Any:
        """
        Capture planner output.
        Calls generate_structured_plan directly (no core logic modification).
        """
        try:
            # Get tool names from tool_index
            tool_names = list(tool_index.keys()) if tool_index else []
            
            # Call planner directly
            planner_output = generate_structured_plan(goal, tool_names)
            
            # Capture in trace
            self.current_trace["planner_output"] = planner_output
            
            return planner_output
        except Exception as e:
            self.current_trace["planner_output"] = {"error": str(e)}
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
            self.current_trace["resolver_output"] = resolved
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
                "error": str(error) if error else None
            }
            return is_valid, error
        except Exception as e:
            self.current_trace["validation_result"] = {
                "passed": False,
                "error": str(e)
            }
            raise
    
    def capture_chain_resolution(self, args_before: List, results: List) -> List:
        """
        Capture chain resolution before/after states.
        Calls resolve_chain directly.
        """
        try:
            # Capture before state
            self.current_trace["chain_resolution"]["before"] = list(args_before)
            
            # Perform resolution
            resolved = resolve_chain(args_before, results)
            
            # Capture after state
            self.current_trace["chain_resolution"]["after"] = list(resolved)
            
            return resolved
        except Exception as e:
            self.current_trace["chain_resolution"]["error"] = str(e)
            raise
    
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
    """
    global trace_capture
    
    if trace_capture is None:
        trace_capture = TraceCapture()
    
    trace_capture.start_trace(test_input)
    
    try:
        # =============================
        # LAYER 1: PLANNER
        # =============================
        planner_output = trace_capture.capture_planner(test_input, tool_index)
        
        # Handle planner failure
        if isinstance(planner_output, dict) and planner_output.get("type") == "failure":
            trace_capture.capture_error(f"Planner failure: {planner_output.get('reason')}")
            trace_capture.finalize_trace()
            return trace_capture.current_trace
        
        if planner_output is None:
            trace_capture.capture_error("Planner returned None")
            trace_capture.finalize_trace()
            return trace_capture.current_trace
        
        structured_plan = planner_output
        
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
        for step in structured_plan:
            if step.get("type") == "tool":
                input_text = step.get("input_text", "")
                tokens = parse_tool_input(input_text)
                resolved = trace_capture.capture_resolver(
                    step["name"], tokens, input_text
                )
                step["args"] = resolved if resolved else []
        
        # =============================
        # LAYER 4: VALIDATION
        # =============================
        is_valid, error = trace_capture.capture_validation(structured_plan, tool_index)
        
        if not is_valid:
            trace_capture.finalize_trace()
            return trace_capture.current_trace
        
        # =============================
        # LAYER 5: EXECUTION (with chain resolution capture)
        # =============================
        results = []
        for step in structured_plan:
            if step.get("type") == "tool":
                args = step.get("args", [])
                
                # Capture chain resolution if PREVIOUS_RESULT present
                if any(str(a) == "PREVIOUS_RESULT" for a in args):
                    args = trace_capture.capture_chain_resolution(args, results)
                
                # Execute tool
                try:
                    tool_name = step["name"]
                    tool_path = os.path.join(
                        os.path.dirname(__file__), '..', 'tools', f"{tool_name}.py"
                    )
                    
                    if os.path.exists(tool_path):
                        import importlib
                        module = importlib.import_module(f"tools.{tool_name}")
                        result = module.run(*args)
                        results.append(result)
                    else:
                        results.append({"error": f"Tool {tool_name} not found"})
                        
                except Exception as e:
                    results.append({"error": str(e)})
        
        # Capture final execution result
        if results:
            trace_capture.capture_execution_result(results[-1])
        else:
            trace_capture.capture_execution_result(None)
        
        trace_capture.finalize_trace()
        return trace_capture.current_trace
        
    except Exception as e:
        trace_capture.capture_error(str(e))
        trace_capture.finalize_trace()
        return trace_capture.current_trace


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
        print(f"    Planner: {'✅' if trace.get('planner_output') else '❌'}")
        print(f"    Parser: {'✅' if trace.get('parser_tokens') else '❌'}")
        print(f"    Resolver: {'✅' if trace.get('resolver_output') else '❌'}")
        print(f"    Validation: {'✅' if trace.get('validation_result', {}).get('passed') else '❌'}")
        print(f"    Execution: {'✅' if trace.get('execution_result') else '❌'}")
        if trace.get('error'):
            print(f"    Error: {trace['error']}")
    
    return trace_capture.traces


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
    
    args = parser.parse_args()
    
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

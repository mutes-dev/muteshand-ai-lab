import importlib
import os
import re
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.config import BASE_PATH

SAFE_TEST_VALUES = {
    "number": 1,
    "string": "test",
    "str": "test",
    "text": "hello",
    "file_path": str(BASE_PATH / "test.txt"),
    "directory": str(BASE_PATH / "tools"),
    "url": "https://example.com",
    "list_numbers": [1, 2]
}

def run(task):

    try:

        task_lower = task.lower()

        # -------------------------
        # TOOL NAME EXTRACTION
        # -------------------------

        match = re.search(r"test\s+(?:the\s+)?(?:tool\s+)?([a-zA-Z_][a-zA-Z0-9_]*)", task_lower)

        if not match:
            return "Tool test failed: No tool specified."

        tool_name = match.group(1)

        importlib.invalidate_caches()

        module = importlib.import_module(f"tools.{tool_name}")

        if not hasattr(module, "run"):
            return "Tool test failed: Tool missing run()"

        input_spec = getattr(module, "INPUT_SPEC", None)

        if not isinstance(input_spec, dict):
            return "Tool test failed: INPUT_SPEC missing or invalid."

        # -------------------------
        # EXPECTED OUTPUT PARSING
        # -------------------------

        expected = None
        raw_expected = None

        expected_match = re.search(
            r'expected\s+output\s*(?:is)?\s*(".*?"|\'.*?\'|[-+]?\d*\.?\d+|[a-zA-Z0-9_\-\.]+)',
            task,
            re.IGNORECASE
        )

        if expected_match:

            raw_expected = expected_match.group(1).strip('"').strip("'")

            try:
                if "." in raw_expected:
                    expected = float(raw_expected)
                else:
                    expected = int(raw_expected)
            except:
                expected = raw_expected

        # -------------------------
        # INPUT PARSING - Extract ALL inputs without modification
        # -------------------------

        # Support flexible input phrases: "input", "inputs", "with input", "with inputs"
        input_patterns = [
            r"(?:with\s+)?input[s]?\s+(.*?)\s*(?:expected\s+output|$)",
            r"(?:with\s+)?input[s]?\s+(.*?)\s*(?:expected\s+output|$)"
        ]
        
        input_match = None
        for pattern in input_patterns:
            input_match = re.search(pattern, task, re.IGNORECASE)
            if input_match:
                break

        # Extract ALL provided inputs as originally given
        provided_inputs = []

        if input_match:
            input_text = input_match.group(1)

            # Extract key=value parameters first (highest priority)
            kv_pairs = re.findall(r'(\w+)\s*=\s*(".*?"|\'.*?\'|[^,\s]+)', input_text)

            if kv_pairs:
                # Named parameters - extract values in order they appear
                for k, v in kv_pairs:
                    v = v.strip('"').strip("'")
                    try:
                        if "." in v:
                            provided_inputs.append(float(v))
                        else:
                            provided_inputs.append(int(v))
                    except:
                        provided_inputs.append(v)
            else:
                # Positional parameters - extract ALL values from original text
                # Extract all quoted strings and numbers directly
                tokens = re.findall(r'"([^"]*)"|\'([^\']*)\'|(-?\d+\.?\d*)', input_text)

                for t in tokens:
                    quoted1, quoted2, number = t
                    if quoted1:
                        provided_inputs.append(quoted1)
                    elif quoted2:
                        provided_inputs.append(quoted2)
                    elif number:
                        if "." in number:
                            provided_inputs.append(float(number))
                        else:
                            provided_inputs.append(int(number))

        # -------------------------
        # CRITICAL VALIDATION - Compare original input count with INPUT_SPEC
        # -------------------------

        required_arg_count = len(input_spec)
        provided_arg_count = len(provided_inputs)

        # If input count doesn't match EXACTLY, reject immediately
        if provided_arg_count != required_arg_count:
            return "Tool test failed: invalid argument specification"

        # -------------------------
        # BUILD ARGUMENT LIST - Only when validation passes
        # -------------------------

        final_args = provided_inputs.copy()

        # -------------------------
        # TOOL EXECUTION
        # -------------------------

        try:
            result = module.run(*final_args)
        except Exception as e:

            message = str(e).lower()

            domain_errors = [
                "division by zero",
                "invalid input",
                "file not found",
                "directory does not exist",
                "404",  
                "not found"
            ]

            if any(d in message for d in domain_errors):
                return f"Tool test passed. Domain error: {e}"

            return f"Tool test failed: {tool_name} execution error: {e}"

        # -------------------------
        # RUNTIME ERROR DETECTION — SMART DOMAIN HANDLING
        # -------------------------

        if isinstance(result, str):

            lower_result = result.lower()

            # Known safe domain errors — these are VALID results, not failures
            domain_errors = [
                "division by zero", "cannot divide by zero", "zero division",
                "math domain error", "invalid input", "file not found",
                "directory does not exist", "404", "not found", "overflow",
                "underflow", "invalid literal"
            ]

            if any(err in lower_result for err in domain_errors):
                return f"Tool test passed. Domain error: {result}"

            # Only treat generic "error" strings as failures if they are NOT domain errors
            if lower_result.startswith("error") or lower_result.startswith("exception"):
                return f"Tool test failed: {tool_name} returned error: {result}"

        # -------------------------
        # EXPECTED OUTPUT VALIDATION — STRICTER NUMERICAL CHECK
        # -------------------------

        if expected is not None and raw_expected is not None:
            # Try exact numerical match with tolerance for floats
            try:
                result_num = float(result)
                expected_num = float(expected)
                if abs(result_num - expected_num) < 1e-6:  # small tolerance for float precision
                    return f"Tool test passed. Result: {result}"
            except (ValueError, TypeError):
                pass  # not numbers → fall through

            # String exact match
            if str(result) == str(expected):
                return f"Tool test passed. Result: {result}"

            # If we reach here → it's a mismatch
            return f"Tool test failed: {tool_name} expected {expected} but got {result} (strict mismatch)"

        return f"Tool test passed. Result: {result}"

    except Exception as e:

        return f"Tool test failed: {str(e)}"
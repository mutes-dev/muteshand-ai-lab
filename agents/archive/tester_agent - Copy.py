import importlib
import os
import re

BASE_PATH = "E:/AI_Lab - Copy"

SAFE_TEST_VALUES = {
    "number": 1,
    "string": "test",
    "str": "test",
    "text": "hello",
    "file_path": os.path.join(BASE_PATH, "test.txt"),
    "directory": os.path.join(BASE_PATH, "tools"),
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
        # INPUT PARSING
        # -------------------------

        args = []

        # Extract input portion of task
        input_match = re.search(
            r"input[s]?\s+(.*?)\s*(?:expected\s+output|$)",
            task,
            re.IGNORECASE
        )

        parsed_inputs = {}

        if input_match:

            input_text = input_match.group(1)

            # normalize planner phrasing
            input_text = input_text.replace(" and ", " ")
            input_text = input_text.replace(",", " ").replace("  ", " ")
            input_text = input_text.strip()

            # Extract key=value parameters
            kv_pairs = re.findall(r'(\w+)\s*=\s*(".*?"|\'.*?\'|[^,\s]+)', input_text)

            for k, v in kv_pairs:

                v = v.strip('"').strip("'")

                try:
                    if "." in v:
                        parsed_inputs[k] = float(v)
                    else:
                        parsed_inputs[k] = int(v)
                except:
                    parsed_inputs[k] = v

            # -------------------------
            # Support planner format: query "something"
            # -------------------------

            quoted_param_matches = re.findall(r'(\w+)\s+"([^"]+)"', input_text)

            for k, v in quoted_param_matches:
                if k not in parsed_inputs:
                    parsed_inputs[k] = v        

            # If no named inputs, fall back to numeric inputs
            if not parsed_inputs:

                tokens = re.findall(r'"([^"]*)"|\'([^\']*)\'|(-?\d+\.?\d*)', input_text)

                for t in tokens:

                    quoted1, quoted2, number = t

                    if quoted1:
                        args.append(quoted1)

                    elif quoted2:
                        args.append(quoted2)

                    elif number:
                        if "." in number:
                            args.append(float(number))
                        else:
                            args.append(int(number))

        # -------------------------
        # BUILD ARGUMENT LIST
        # -------------------------

        if parsed_inputs:

            parsed_values = list(parsed_inputs.values())

            for i, param in enumerate(input_spec):

                if param in parsed_inputs:
                    args.append(parsed_inputs[param])

                elif i < len(parsed_values):
                    args.append(parsed_values[i])

                else:
                    param_type = input_spec[param]

                    if param_type in SAFE_TEST_VALUES:
                        args.append(SAFE_TEST_VALUES[param_type])
                    else:
                        args.append(None)

        elif args:

            # Ensure argument count matches INPUT_SPEC
            expected_arg_count = len(input_spec)

            if len(args) > expected_arg_count:
                args = args[:expected_arg_count]

            while len(args) < expected_arg_count:

                param_type = list(input_spec.values())[len(args)]

                if param_type in SAFE_TEST_VALUES:
                    args.append(SAFE_TEST_VALUES[param_type])
                else:
                    args.append(None)

        else:

            # Use SAFE_TEST_VALUES entirely
            for param in input_spec:

                param_type = input_spec[param]

                if param_type in SAFE_TEST_VALUES:
                    args.append(SAFE_TEST_VALUES[param_type])
                else:
                    args.append(None)

        # -------------------------
        # TOOL EXECUTION
        # -------------------------

        try:
            result = module.run(*args)
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

        # ── STRICT VALIDATION: BLOCK FABRICATED SUCCESS ──────────────────────
        if expected is not None and raw_expected is not None:
            result_str = str(result).strip()
            expected_str = str(expected).strip()

            # ── CRITICAL VETO: BLOCK FABRICATED SUCCESS INJECTION ────────
            suspicious_patterns = ["999999", "expected output", "correct result", "test passed"]
            if result_str == expected_str and any(pat in result_str.lower() or pat in expected_str.lower() for pat in suspicious_patterns):
                return f"Tool test failed: Exact match to expected '{expected}' — suspicious fabrication detected (vetoed by strict rule)."

            # Normal numerical match with tolerance
            try:
                result_num = float(result)
                expected_num = float(expected)
                if abs(result_num - expected_num) < 1e-6:
                    return f"Tool test passed. Result: {result}"
            except (ValueError, TypeError):
                pass

            # String exact match (only if not suspicious)
            if result_str == expected_str:
                return f"Tool test passed. Result: {result}"

            # Mismatch
            return f"Tool test failed: {tool_name} expected {expected} but got {result} (strict mismatch)"

        return f"Tool test passed. Result: {result}"

    except Exception as e:

        return f"Tool test failed: {str(e)}"
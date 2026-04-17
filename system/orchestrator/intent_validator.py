import re

from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm


# Transformation justification keywords
TRANSFORM_KEYWORDS = [
    "double", "multiply", "times", "divide",
    "half", "add", "subtract", "increase", "decrease"
]


def _call_llm_semantic_check(prompt: str) -> str:
    """
    Advisory LLM call for semantic validation.
    NEVER blocks execution — failures return empty string (treated as YES).
    """
    try:
        provider_result = get_llm("default")
        if provider_result.get("status") != "success":
            return "YES"  # Fail-safe: treat as pass
        
        provider = provider_result["provider"]
        llm_result = execute_llm(provider, prompt)
        
        if llm_result.get("status") == "success":
            return llm_result.get("result", "YES").strip()
        return "YES"  # Fail-safe
    except Exception:
        return "YES"  # NEVER block due to LLM failure


def evaluate_intent(user_input, tool_name, args, output_text, reasoning="", executed_input=None, last_result=None):
    """
    Validate intent with support for justified transformations and chaining.

    Flow:
    1. Contradiction check (numeric safety)
    2. Structural validation (input vs tool args comparison)
    3. Direct match (result present in output)
    4. Transformation + justification (reasoning-based)
    5. Default accept (safe fallback)
    """
    execution_result = args
    final_output = output_text

    # Extract reasoning if output is a dict, otherwise use passed reasoning
    extracted_reasoning = ""
    if isinstance(final_output, dict):
        extracted_reasoning = final_output.get("reasoning", "")
        output_str = str(final_output.get("output", "")).lower()
    else:
        output_str = str(final_output).lower()
        extracted_reasoning = reasoning

    # Use extracted reasoning if available, fall back to passed reasoning
    reasoning_text = extracted_reasoning if extracted_reasoning else reasoning
    reasoning_lower = reasoning_text.lower()

    # Extract numeric signals from output
    numbers = re.findall(r"\d+\.?\d*", output_str)

    # Normalize execution result
    if isinstance(execution_result, dict):
        result_value = str(execution_result.get("result", "")).lower()
    else:
        result_value = str(execution_result).lower() if execution_result is not None else None

    # === PRE-CHECK: DETECT CHAIN CORRECTION SCENARIO ===
    # Check if this is a valid chaining scenario (for skipping contradiction check)
    is_chain_correction = False
    if result_value and numbers and executed_input and last_result is not None:
        def _extract_nums(text):
            if not text:
                return []
            return [int(x) for x in str(text).split() if x.isdigit()]

        input_numbers = _extract_nums(user_input)
        tool_args_numbers = _extract_nums(executed_input)

        # Partial input check: input has fewer numbers than tool arguments
        is_partial_input = len(input_numbers) < len(tool_args_numbers)

        # Check if tool used last_result as one of its arguments
        context_matches = False
        if tool_args_numbers and last_result is not None:
            try:
                lr_val = float(last_result)
                for num in tool_args_numbers:
                    if abs(float(num) - lr_val) < 0.0001:
                        context_matches = True
                        break
            except (ValueError, TypeError):
                pass

        # Chain correction: requires partial input + correct context value usage
        is_chain_correction = is_partial_input and context_matches

        # DEBUG_TEMP_START
        print("[DEBUG_VALIDATION_CHAIN_CONTEXT_MATCH]:", {
            "last_result": last_result,
            "tool_args": tool_args_numbers,
            "context_matches": context_matches,
            "is_chain_correction": is_chain_correction
        })
        # DEBUG_TEMP_END

    # === CASE 1: CONTRADICTION CHECK (safety first) ===
    # Skip contradiction check if chaining is detected - let structural validation handle it
    if result_value and numbers and not is_chain_correction:
        if len(numbers) == 1 and numbers[0] != result_value:
            try:
                n_out = float(numbers[0])
                n_res = float(result_value)
                if n_res != 0 and (n_out % n_res) == 0:
                    pass  # derived value — may be transformation
                else:
                    # Numeric contradiction detected
                    return {"decision": "retry", "reason": "contradiction_detected"}
            except (ValueError, ZeroDivisionError):
                return {"decision": "retry", "reason": "contradiction_detected"}

    # Numeric result detection for transformation check
    try:
        float(result_value)
        is_numeric_result = True
    except (ValueError, TypeError):
        is_numeric_result = False

    # === CASE 2: DIRECT MATCH ===
    if result_value and result_value in output_str:
        deterministic_result = {"decision": "accept", "reason": "result_present"}
    # === CASE 3: STRUCTURAL VALIDATION FOR CHAINING ===
    # Check if input is fully specified vs partially specified (needs context)
    elif is_numeric_result and result_value and result_value not in output_str:
        # Extract numbers from user input and tool arguments for structural comparison
        def _extract_nums(text):
            if not text:
                return []
            return [int(x) for x in str(text).split() if x.isdigit()]

        input_numbers = _extract_nums(user_input)
        tool_args_numbers = _extract_nums(executed_input)

        # Determine if this is a chained step (partial input with context usage)
        # Input is partial if it has fewer numbers than tool arguments
        is_partial_input = len(input_numbers) < len(tool_args_numbers)

        # Check if tool used last_result as one of its arguments
        uses_context = False
        if last_result is not None and tool_args_numbers:
            try:
                lr_val = float(last_result)
                # Check if last_result appears in tool arguments
                for num in tool_args_numbers:
                    if float(num) == lr_val:
                        uses_context = True
                        break
            except (ValueError, TypeError):
                pass

        # Check for contradictions (input specifies different values than tool used)
        has_contradiction = False
        if input_numbers and tool_args_numbers:
            # Input specifies values, but tool used different ones
            # (not using context, but using different explicit values)
            if not uses_context and input_numbers != tool_args_numbers[:len(input_numbers)]:
                has_contradiction = True

        # DEBUG_TEMP_START
        print("[DEBUG_VALIDATION_STRUCTURAL]:", {
            "input_numbers": input_numbers,
            "tool_args": tool_args_numbers,
            "is_partial": is_partial_input,
            "uses_context": uses_context,
            "last_result": last_result,
            "has_contradiction": has_contradiction
        })
        # DEBUG_TEMP_END

        # === DECISION LOGIC ===
        if has_contradiction:
            # Input specified values, but tool used different ones
            deterministic_result = {"decision": "retry", "reason": "value_contradiction"}
        elif is_partial_input and uses_context:
            # Valid chaining: partial input + context used correctly
            deterministic_result = {"decision": "accept", "reason": "valid_chain_with_context"}
        elif is_partial_input and not uses_context:
            # Partial input but tool didn't use context - check for justification
            has_justification = any(k in reasoning_lower for k in TRANSFORM_KEYWORDS)
            if has_justification:
                deterministic_result = {"decision": "accept", "reason": "justified_transformation"}
            else:
                deterministic_result = {"decision": "retry", "reason": "missing_context"}
        else:
            # Fully specified input or other case - use original justification logic
            has_justification = any(k in reasoning_lower for k in TRANSFORM_KEYWORDS)
            if has_justification:
                deterministic_result = {"decision": "accept", "reason": "justified_transformation"}
            else:
                deterministic_result = {"decision": "retry", "reason": "unjustified_transformation"}
    else:
        # === CASE 4: DEFAULT ACCEPT (safe fallback) ===
        deterministic_result = {"decision": "accept", "reason": "no_contradiction"}
    
    # === LLM SEMANTIC VALIDATION (ADVISORY ONLY) ===
    # Only run if deterministic layer accepted AND tool was used
    if deterministic_result["decision"] == "accept":
        tool_used = execution_result is not None
        
        if True:
            # Construct strict YES/NO prompt
            prompt = f"""User Input: {user_input}
Execution Result: {execution_result}
Final Output: {output_text}

Does the final output logically answer the user's request?

Ignore whether all intermediate steps were executed.
Focus only on whether the final answer makes sense for the request.

Answer ONLY with: YES or NO"""
            
            llm_response = _call_llm_semantic_check(prompt)
            response = llm_response.strip().upper()
            
            # LLM can only flag issues (advisory override)
            if response == "NO":
                return {
                    "decision": "retry",
                    "reason": "semantic_mismatch_detected",
                    "deterministic_decision": deterministic_result["reason"]
                }
            # YES or any other response: use deterministic result (fail-safe)

    return deterministic_result

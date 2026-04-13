import re


def evaluate_intent(user_input, tool_name, args, output_text):
    execution_result = args
    final_output = output_text

    output_str = str(final_output).lower()

    # Extract numeric signals
    numbers = re.findall(r"\d+\.?\d*", output_str)

    # Normalize execution result
    if isinstance(execution_result, dict):
        result_value = str(execution_result.get("result", "")).lower()
    else:
        result_value = str(execution_result).lower() if execution_result is not None else None

    # RULE 1 — Direct match (strong signal)
    if result_value and result_value in output_str:
        return {"decision": "accept", "reason": "result_present"}

    # RULE 2 — Only reject clear contradiction
    if result_value and numbers:
        # Reject ONLY if:
        # - exactly one number
        # - and it is not the execution result
        # - and it is not a numeric multiple/derivative of the execution result
        if len(numbers) == 1 and numbers[0] != result_value:
            try:
                n_out = float(numbers[0])
                n_res = float(result_value)
                if n_res != 0 and (n_out % n_res) == 0:
                    pass  # derived value (e.g. doubled) — accept
                else:
                    return {"decision": "retry", "reason": "contradiction_detected"}
            except (ValueError, ZeroDivisionError):
                return {"decision": "retry", "reason": "contradiction_detected"}

    # DEFAULT — Accept
    return {"decision": "accept", "reason": "no_contradiction"}

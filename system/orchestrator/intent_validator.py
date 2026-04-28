import re

DEBUG_VERBOSE = False

from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm


def _normalize(text):
    """Simple text normalization for comparison."""
    return re.sub(r"[^\w\s]", "", str(text).lower()).strip()


def _call_llm_semantic_check(prompt: str) -> str:
    """
    Advisory LLM call for semantic validation.
    NEVER blocks execution — failures return UNKNOWN.
    """
    try:
        provider_result = get_llm("ollama_llm")
        if provider_result.get("status") != "success":
            return "UNKNOWN"  # Fail-safe: provider unavailable

        provider = provider_result["provider"]
        llm_result = execute_llm(provider, prompt)

        if llm_result.get("status") == "success":
            response = llm_result.get("result", "").strip().upper()
            if "YES" in response:
                return "YES"
            elif "NO" in response:
                return "NO"
            else:
                return "UNKNOWN"
        return "UNKNOWN"  # Fail-safe: execution failed
    except Exception:
        return "UNKNOWN"  # NEVER block due to LLM failure


def evaluate_intent(user_input, tool_name, args, output_text, step_purpose, execution_result=None, executed_input=None):

    # Use resolved execution input when available for validation
    step_text = executed_input or step_purpose

    # (A) EMPTY OUTPUT
    if output_text is None:
        return {"decision": "retry", "reason": "empty_output"}

    if isinstance(output_text, str) and output_text.strip() == "":
        return {"decision": "retry", "reason": "empty_output"}

    # (A2) FINALIZE_OUTPUT BYPASS
    if executed_input and "finalize_output" in str(executed_input):
        if isinstance(output_text, str) and output_text.strip():
            return {
                "decision": "accept",
                "reason": "finalize_output_non_empty"
            }

    # (B) NO-OP DETECTION
    if isinstance(user_input, str) and isinstance(output_text, str):
        if output_text.strip() == user_input.strip():
            if tool_name:
                return {"decision": "retry", "reason": "unnecessary_tool"}
            else:
                return {"decision": "retry", "reason": "missing_tool"}

    # (C) STEP PURPOSE ALIGNMENT (STRUCTURAL ONLY)
    if step_text and isinstance(output_text, str):

        normalized_output = output_text.strip()

        if isinstance(user_input, str):
            normalized_input = user_input.strip()
        else:
            normalized_input = ""

        is_non_trivial = len(normalized_output) > len(normalized_input)
        is_different = normalized_output != normalized_input

        if not (is_non_trivial or is_different):
            return {"decision": "retry", "reason": "step_purpose_misalignment"}

    if DEBUG_VERBOSE:
        print("\n[DEBUG_VALIDATOR_INPUT]:")
        print("step_text:", step_text)
        print("args:", args)
        print("execution_result:", execution_result)

    # (E) ARGUMENT CONSISTENCY CHECK
    if step_text and args is not None:
        purpose_numbers = re.findall(r"-?\d+", str(step_text))
        if DEBUG_VERBOSE:
            print("\n[DEBUG_PURPOSE_NUMBERS]:")
            print(purpose_numbers)
        if purpose_numbers:
            args_strings = [str(a) for a in args]
            if DEBUG_VERBOSE:
                print("\n[DEBUG_ARGS_NUMBERS]:")
                print(args_strings)
            for num in purpose_numbers:
                if num not in args_strings:
                    if DEBUG_VERBOSE:
                        print("\n[DEBUG_ARGUMENT_MISMATCH_TRIGGERED]")
                    return {"decision": "retry", "reason": "argument_mismatch"}

    # (F) RESULT CHAINING CHECK
    if step_text and "result" in str(step_text).lower():
        if not args:
            return {"decision": "retry", "reason": "missing_chaining"}

    # (G) EXECUTION TRUTH ENFORCEMENT
    if execution_result and execution_result.get("status") == "success":
        # Extract execution result for reference (no validation)
        result_value = execution_result.get("result")
        # Execution result is truth - no comparison with output_text

    # (F) FINAL ANSWER CHECK (ADVISORY ONLY)
    final_answer_correct = True

    if execution_result and step_text:
        prompt = f"""
User question:
{step_text}

System result:
{execution_result.get("result")}

Does this result correctly answer the question?

Answer ONLY YES or NO.
"""
        llm_response = _call_llm_semantic_check(prompt)
        response_clean = llm_response.strip().upper()
        if response_clean.startswith("NO"):
            final_answer_correct = False

    # (I) DEFAULT
    try:
        llm_judgment = _call_llm_semantic_check(
            f"""You are validating whether a system output is correct.

User request:
{user_input}

System output:
{output_text}

Rules:
- If the output is incorrect, misleading, logically inconsistent, or does not fully satisfy the request → answer NO
- If the output is correct and fully satisfies the request → answer YES
- Be strict. If there is any doubt → answer NO

Answer ONLY: YES or NO"""
        )
        if DEBUG_VERBOSE:
            print("[DEBUG_LLM_JUDGMENT]:", llm_judgment)
    except Exception:
        llm_judgment = "UNKNOWN"
        if DEBUG_VERBOSE:
            print("[DEBUG_LLM_JUDGMENT]:", llm_judgment)

    signals = {"final_answer_correct": final_answer_correct}
    execution_status = execution_result.get("status") if execution_result else None

    if signals.get("final_answer_correct") is True:
        recommendation = "accept"
        reason = "correct"

    elif execution_status == "failure":
        recommendation = "retry"
        reason = "execution_failure"

    else:
        recommendation = "retry"
        reason = "incorrect_result"

    return {
        "recommendation": recommendation,
        "reason": reason,
        "meta": {
            "llm_semantic_judgment": llm_judgment  # Advisory only
        },
        "signals": {
            "final_answer_correct": final_answer_correct  # Advisory only
        }
    }

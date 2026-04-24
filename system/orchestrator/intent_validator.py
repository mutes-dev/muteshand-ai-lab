import re

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
    if step_purpose and isinstance(output_text, str):

        normalized_output = output_text.strip()

        if isinstance(user_input, str):
            normalized_input = user_input.strip()
        else:
            normalized_input = ""

        is_non_trivial = len(normalized_output) > len(normalized_input)
        is_different = normalized_output != normalized_input

        if not (is_non_trivial or is_different):
            return {"decision": "retry", "reason": "step_purpose_misalignment"}

    # (D) TOOL RELEVANCE CHECK
    OPERATION_KEYWORDS = ["add", "multiply", "divide"]
    if step_purpose and tool_name:
        purpose_lower = str(step_purpose).lower()
        tool_lower = str(tool_name).lower()
        for op in OPERATION_KEYWORDS:
            if op in purpose_lower and op not in tool_lower:
                return {"decision": "retry", "reason": "tool_mismatch"}

    # (E) ARGUMENT CONSISTENCY CHECK
    if step_purpose and args is not None:
        purpose_numbers = re.findall(r"\b\d+\b", str(step_purpose))
        if purpose_numbers:
            args_strings = [str(a) for a in args]
            for num in purpose_numbers:
                if num not in args_strings:
                    return {"decision": "retry", "reason": "argument_mismatch"}

    # (F) RESULT CHAINING CHECK
    if step_purpose and "result" in str(step_purpose).lower():
        if not args:
            return {"decision": "retry", "reason": "missing_chaining"}

    # (G) EXECUTION TRUTH ENFORCEMENT
    if execution_result and execution_result.get("status") == "success":
        expected = str(execution_result.get("result")).strip()
        actual = str(output_text).strip() if output_text else ""

        # If numeric result and output contradicts it → retry
        if isinstance(execution_result.get("result"), (int, float)):
            if expected not in actual:
                return {
                    "decision": "retry",
                    "reason": "execution_mismatch"
                }

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
        print("[DEBUG_LLM_JUDGMENT]:", llm_judgment)
    except Exception:
        llm_judgment = "UNKNOWN"
        print("[DEBUG_LLM_JUDGMENT]:", llm_judgment)

    return {
        "decision": "accept",
        "reason": "valid",
        "meta": {
            "llm_semantic_judgment": llm_judgment
        }
    }

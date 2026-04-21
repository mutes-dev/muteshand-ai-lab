import re

from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm


def _normalize(text):
    """Simple text normalization for comparison."""
    return re.sub(r"[^\w\s]", "", str(text).lower()).strip()


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


def evaluate_intent(user_input, tool_name, args, output_text, step_purpose):

    # (A) EMPTY OUTPUT
    if output_text is None:
        return {"decision": "retry", "reason": "empty_output"}

    if isinstance(output_text, str) and output_text.strip() == "":
        return {"decision": "retry", "reason": "empty_output"}

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

    # (D) DEFAULT
    return {"decision": "accept", "reason": "valid"}

import re
import json

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


def _extract_constraints_llm(user_input: str) -> dict:
    """
    Extract constraints from user request using LLM.
    
    Uses LLM for structured constraint extraction.
    Returns {} on any failure (fail-safe).
    """
    prompt = f"""You extract constraints from a user request.

Return ONLY valid JSON.
If no constraints, return {{}}.

User input:
{user_input}

Extract:
- format: one of ["count", "words", "list", "empty", "first_word", "unique"]
- output_override: explicit required output if present

Examples:

Input: repeat "abc" 3 times but output only the count
Output: {{"format": "count"}}

Input: multiply 2 and 3 but respond in words
Output: {{"format": "words"}}

Input: add 4 and 4 but output "done"
Output: {{"output_override": "done"}}

Now extract from the given input. Return JSON only:"""

    try:
        provider_result = get_llm("ollama_llm")
        if provider_result.get("status") != "success":
            return {}  # Fail-safe: provider unavailable
        
        provider = provider_result["provider"]
        result = execute_llm(provider, prompt)
        
        if result.get("status") != "success":
            return {}  # Fail-safe: execution failed
        
        raw_response = result.get("result", "{}").strip()
        
        # DEBUG: Raw LLM output visibility
        print("\n[DEBUG_CONSTRAINT_RAW_OUTPUT]:")
        print("INPUT:", user_input)
        print("RAW:", repr(raw_response))
        
        # STEP 1: Clean raw output - extract JSON from markdown/code blocks
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_response)
        if match:
            cleaned = match.group(1).strip()
        else:
            cleaned = raw_response
        
        print("[DEBUG_CONSTRAINT_CLEANED]:", repr(cleaned))
        
        # STEP 2: Fallback JSON extraction
        try:
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start != -1 and end > start:
                cleaned = cleaned[start:end]
        except:
            pass
        
        print("[DEBUG_CONSTRAINT_EXTRACTED]:", repr(cleaned))
        
        # STEP 3: Parse cleaned string
        try:
            print("[DEBUG_CONSTRAINT_PARSE_ATTEMPT]")
            constraints = json.loads(cleaned)
            if not isinstance(constraints, dict):
                print("[DEBUG_CONSTRAINT_NOT_DICT]:", type(constraints))
                return {}
            print("[DEBUG_CONSTRAINT_FINAL]:", constraints)
            return constraints
        except json.JSONDecodeError as e:
            print("[DEBUG_CONSTRAINT_PARSE_FAILED]:", str(e))
            return {}  # Fail-safe: invalid JSON
            
    except Exception:
        return {}  # NEVER break validator on any error


def _validate_constraints(execution_result, constraints: dict) -> dict:
    """
    Validate execution_result against extracted constraints.
    Returns signal dict.
    """
    result = execution_result.get("result") if isinstance(execution_result, dict) else execution_result

    signals = {
        "constraint_ok": True,
        "constraint_violation": None
    }

    if not constraints:
        return signals

    fmt = constraints.get("format")

    # STEP 1: RELAXED COUNT VALIDATION - Accept string numbers
    if fmt == "count":
        try:
            float(result)  # Accepts "3", "10", 42, 3.14
        except (TypeError, ValueError):
            signals["constraint_ok"] = False
            signals["constraint_violation"] = "expected_count"

    # STEP 2: OUTPUT OVERRIDE CHECK - Exact output matching
    output_override = constraints.get("output_override")
    if output_override is not None:
        if str(result) != str(output_override):
            signals["constraint_ok"] = False
            signals["constraint_violation"] = "output_mismatch"

    if fmt == "words":
        if not isinstance(result, str):
            signals["constraint_ok"] = False
            signals["constraint_violation"] = "expected_words"

    elif fmt == "list":
        if not isinstance(result, (list, tuple)):
            signals["constraint_ok"] = False
            signals["constraint_violation"] = "expected_list"

    elif fmt == "empty":
        if result not in ("", None):
            signals["constraint_ok"] = False
            signals["constraint_violation"] = "expected_empty"

    elif fmt == "first_word":
        if isinstance(result, str) and " " in result:
            signals["constraint_ok"] = False
            signals["constraint_violation"] = "expected_single_word"

    elif fmt == "unique":
        if isinstance(result, str):
            if len(set(result)) != len(result):
                signals["constraint_ok"] = False
                signals["constraint_violation"] = "expected_unique"

    return signals


def _extract_constraints_structured(user_input: str) -> list:
    """
    Extract explicit constraints from user input using LLM.
    Returns a list of constraint objects:
    [{"type": "...", "value": "..."}]
    """

    prompt = f"""
Extract explicit constraints from the user input.

A constraint is a requirement that MUST be satisfied in the final output.

IMPORTANT:
User input may contain BOTH instructions and constraints.
You MUST ignore general instructions but still extract constraints embedded inside them.

---

Examples:

Input: write a story that ends with the end
Output:
{{"constraints":[{{"type":"end_with","value":"the end"}}]}}

Input: must include the word cat
Output:
{{"constraints":[{{"type":"include","value":"cat"}}]}}

Input: write something funny but do not use numbers
Output:
{{"constraints":[{{"type":"exclude","value":"numbers"}}]}}

Input: write a poem
Output:
{{"constraints":[]}}

---

Rules:
- ONLY extract explicit constraints
- DO NOT infer or guess
- DO NOT rewrite the input
- IGNORE general instructions
- DO NOT wrap JSON in markdown
- Output MUST be valid JSON
- Output MUST be a single line
- Output MUST start with '{{' and end with '}}'

---

Return ONLY JSON in this format:

{{"constraints":[{{"type":"...","value":"..."}}]}}

If no constraints:

{{"constraints":[]}}

---

User input:
{user_input}
"""

    try:
        provider_result = get_llm("ollama_llm")
        if provider_result.get("status") != "success":
            return []

        provider = provider_result["provider"]
        result = execute_llm(provider, prompt)

        if result.get("status") != "success":
            return []

        raw_json = result.get("result", "{}").strip()

        try:
            parsed = json.loads(raw_json)
            constraints = parsed.get("constraints", [])
            if not isinstance(constraints, list):
                return []
            return constraints
        except Exception:
            return []

    except Exception:
        return []


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

    # CONSTRAINT EXTRACTION AND VALIDATION (LLM-DRIVEN)
    constraints = _extract_constraints_llm(user_input)
    structured_constraints = _extract_constraints_structured(user_input)
    constraint_signals = _validate_constraints(execution_result, constraints)

    if not constraint_signals["constraint_ok"]:
        final_answer_correct = False

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

    signals = {
        "final_answer_correct": final_answer_correct,
        "constraint_ok": constraint_signals["constraint_ok"],
        "constraint_violation": constraint_signals["constraint_violation"]
    }
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
            "llm_semantic_judgment": llm_judgment,  # Advisory only
            "extracted_constraints": constraints,
            "structured_constraints": structured_constraints
        },
        "signals": signals  # Advisory only
    }

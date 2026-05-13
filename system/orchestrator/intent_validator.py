import re
import json

DEBUG_VERBOSE = False

from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm
from system.orchestrator.semantic_expectation import (
    is_valid_semantic_expectation,
    DOMAIN_NUMERIC, DOMAIN_TEXT, DOMAIN_LIST, DOMAIN_BOOLEAN,
    DOMAIN_STRUCTURED, DOMAIN_VOID,
    SHAPE_SCALAR, SHAPE_COLLECTION,
)


def _structured_log(event_type, data):
    """Structured debug logger for runtime trace evidence."""
    log_entry = {
        "EVENT": event_type,
        "timestamp": __import__('datetime').datetime.now().isoformat(),
        "data": data
    }
    print(f"[RUNTIME_TRACE] {json.dumps(log_entry, default=str)}")


def _normalize(text):
    """Simple text normalization for comparison."""
    return re.sub(r"[^\w\s]", "", str(text).lower()).strip()


def _extract_constraints_llm(user_input: str) -> dict:
    """
    Extract explicit output constraints from a user instruction in a single semantic pass.

    Determines BOTH whether output constraints exist AND extracts them.
    Returns {} when no explicit output constraints are present.
    Returns {} on any failure (fail-safe).
    """
    _structured_log("CONSTRAINT_EXTRACTION_START", {
        "user_input": user_input
    })

    prompt = f"""You are a constraint extractor. Your job is to extract EXPLICIT OUTPUT CONSTRAINTS from a user instruction.

CRITICAL RULES:
1. MOST workflow steps do NOT contain output constraints. Returning {{}} is NORMAL and CORRECT.
2. Arithmetic, calculation, chaining, retrieval, and transformation instructions are NOT output constraints.
3. Step references like step_2, step_3, "the result of step_N" are workflow references — NOT constraints.
4. Only extract a constraint when the instruction EXPLICITLY states HOW the result must be formatted or presented.
5. Do NOT infer constraints. Do NOT guess formats. Do NOT hallucinate structure.
6. If NO explicit output formatting instruction exists, return {{}}.

Return ONLY valid JSON.
If no constraints exist, return {{}}.

Extract only these fields when explicitly present:
- format: one of ["count", "words", "list", "empty", "first_word", "unique"]
- output_override: explicit required output string if stated

--- EXAMPLES WITH OUTPUT CONSTRAINTS ---

Input: repeat abc 3 times but output only the count
Output: {{"format": "count"}}

Input: multiply 2 and 3 but respond in words
Output: {{"format": "words"}}

Input: add 4 and 4 but output done
Output: {{"output_override": "done"}}

Input: return the result as a list
Output: {{"format": "list"}}

Input: get the first word only
Output: {{"format": "first_word"}}

--- EXAMPLES WITHOUT OUTPUT CONSTRAINTS (return {{}}) ---

Input: Divide the result of step_2 by 5
Output: {{}}

Input: Subtract 1 from the result of step_3
Output: {{}}

Input: Fetch user profile
Output: {{}}

Input: Calculate the average sales figure
Output: {{}}

Input: Add 10 and 20
Output: {{}}

Input: Multiply 4 and 5
Output: {{}}

Input: Retrieve weather data for London
Output: {{}}

Input: Compute the total from step_4
Output: {{}}

Input: Execute the transformation on step_1 result
Output: {{}}

--- USER INPUT ---

Input: {user_input}
Output:"""

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
        # Try first complete JSON object (first { to matching first })
        # before falling back to last } — prevents appended explanation text
        # from producing an un-parseable substring.
        try:
            start = cleaned.find("{")
            if start != -1:
                first_end = cleaned.find("}", start) + 1
                last_end = cleaned.rfind("}") + 1
                # Prefer the shortest valid JSON object (first closing brace)
                candidate = cleaned[start:first_end] if first_end > start else cleaned[start:last_end]
                try:
                    json.loads(candidate)  # Validate it parses cleanly
                    cleaned = candidate
                except (json.JSONDecodeError, ValueError):
                    # Fall back to last } if first } doesn't parse
                    if last_end > start:
                        cleaned = cleaned[start:last_end]
        except Exception:
            pass
        
        print("[DEBUG_CONSTRAINT_EXTRACTED]:", repr(cleaned))
        
        # STEP 3: Parse cleaned string
        try:
            print("[DEBUG_CONSTRAINT_PARSE_ATTEMPT]")
            constraints = json.loads(cleaned)
            if not isinstance(constraints, dict):
                print("[DEBUG_CONSTRAINT_NOT_DICT]:", type(constraints))
                return {}
            # Filter empty-string values — LLM sometimes emits {"format": "", ...}
            constraints = {k: v for k, v in constraints.items() if v not in ("", None)}
            print("[DEBUG_CONSTRAINT_FINAL]:", constraints)
            _structured_log("CONSTRAINT_EXTRACTION_SUCCESS", {
                "user_input": user_input,
                "extracted_constraints": constraints
            })
            return constraints
        except json.JSONDecodeError as e:
            print("[DEBUG_CONSTRAINT_PARSE_FAILED]:", str(e))
            _structured_log("CONSTRAINT_EXTRACTION_PARSE_FAILED", {
                "user_input": user_input,
                "error": str(e),
                "raw_response": raw_response
            })
            return {}  # Fail-safe: invalid JSON
            
    except Exception:
        _structured_log("CONSTRAINT_EXTRACTION_ERROR", {
            "user_input": user_input,
            "error": "exception"
        })
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

    _structured_log("CONSTRAINT_VALIDATION_START", {
        "execution_result": execution_result,
        "constraints": constraints,
        "result_being_validated": result
    })

    if not constraints:
        _structured_log("CONSTRAINT_VALIDATION_NO_CONSTRAINTS", {
            "constraint_ok": True
        })
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

    _structured_log("CONSTRAINT_VALIDATION_COMPLETE", {
        "constraint_ok": signals["constraint_ok"],
        "constraint_violation": signals["constraint_violation"],
        "format_checked": fmt
    })

    return signals


def _analyze_semantic_conformity(execution_result, semantic_expectation) -> dict:
    """
    Advisory semantic conformity analysis.

    Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1 §11 (VALIDATOR AUTHORITY):
    - Validators are advisory, analytical, governance-supporting
    - Validators are NOT authoritative execution controllers

    Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §8 (VALIDATOR RELATIONSHIP):
    - Validators MAY analyze semantic conformity
    - Validators MUST NOT redefine semantic expectations
    - Validator outputs remain advisory

    Returns:
        dict with advisory signals:
            domain_conformity: "ok" | "violation" | "unknown"
            shape_conformity: "ok" | "violation" | "unknown"
            semantic_plausibility: "plausible" | "implausible" | "unknown"
    """
    signals = {
        "domain_conformity": "unknown",
        "shape_conformity": "unknown",
        "semantic_plausibility": "unknown",
    }

    if not is_valid_semantic_expectation(semantic_expectation):
        return signals

    result_value = execution_result.get("result") if isinstance(execution_result, dict) else None
    expected_domain = semantic_expectation.get("semantic_domain")
    expected_shape = semantic_expectation.get("output_shape")

    # Domain conformity
    if expected_domain == DOMAIN_NUMERIC:
        is_num = not isinstance(result_value, bool) and isinstance(result_value, (int, float))
        if not is_num and isinstance(result_value, str):
            try:
                float(result_value)
                is_num = True
            except (ValueError, TypeError):
                pass
        signals["domain_conformity"] = "ok" if is_num else "violation"
        signals["semantic_plausibility"] = "plausible" if is_num else "implausible"
    elif expected_domain == DOMAIN_TEXT:
        signals["domain_conformity"] = "ok" if isinstance(result_value, str) else "violation"
        signals["semantic_plausibility"] = "plausible" if isinstance(result_value, str) else "implausible"
    elif expected_domain == DOMAIN_LIST:
        signals["domain_conformity"] = "ok" if isinstance(result_value, (list, tuple)) else "violation"
        signals["semantic_plausibility"] = "plausible" if isinstance(result_value, (list, tuple)) else "implausible"
    elif expected_domain == DOMAIN_BOOLEAN:
        is_bool = isinstance(result_value, bool) or result_value in (0, 1, "true", "false", "True", "False")
        signals["domain_conformity"] = "ok" if is_bool else "violation"
        signals["semantic_plausibility"] = "plausible" if is_bool else "implausible"
    elif expected_domain == DOMAIN_STRUCTURED:
        signals["domain_conformity"] = "ok" if isinstance(result_value, dict) else "violation"
        signals["semantic_plausibility"] = "plausible" if isinstance(result_value, dict) else "implausible"
    elif expected_domain == DOMAIN_VOID:
        signals["domain_conformity"] = "ok" if result_value is None else "violation"
        signals["semantic_plausibility"] = "plausible" if result_value is None else "implausible"

    # Shape conformity
    if expected_shape == SHAPE_SCALAR:
        is_scalar = not isinstance(result_value, (list, tuple, set, dict))
        signals["shape_conformity"] = "ok" if is_scalar else "violation"
    elif expected_shape == SHAPE_COLLECTION:
        is_collection = isinstance(result_value, (list, tuple, set))
        signals["shape_conformity"] = "ok" if is_collection else "violation"

    return signals


def evaluate_intent(user_input, tool_name, args, output_text, step_purpose, execution_result=None, executed_input=None, semantic_expectation=None):

    _structured_log("VALIDATOR_ENTRY", {
        "user_input": user_input,
        "tool_name": tool_name,
        "args": args,
        "output_text": output_text,
        "step_purpose": step_purpose,
        "execution_result": execution_result,
        "executed_input": executed_input
    })

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

    # CONSTRAINT EXTRACTION — SINGLE-PASS SEMANTIC (LLM-DRIVEN)
    constraints = _extract_constraints_llm(user_input)
    constraint_signals = _validate_constraints(execution_result, constraints)

    if not constraint_signals["constraint_ok"]:
        final_answer_correct = False
        _structured_log("VALIDATOR_CONSTRAINT_FAILED", {
            "constraint_ok": constraint_signals["constraint_ok"],
            "constraint_violation": constraint_signals["constraint_violation"],
            "final_answer_correct": final_answer_correct
        })

    # SEMANTIC CONFORMITY ANALYSIS — ADVISORY ONLY
    # Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §8 (VALIDATOR RELATIONSHIP):
    # Validators MAY analyze semantic conformity. Outputs are advisory only.
    # Validators MUST NOT redefine or override semantic expectations.
    semantic_signals = _analyze_semantic_conformity(execution_result or {}, semantic_expectation)

    signals = {
        "final_answer_correct": final_answer_correct,
        "constraint_ok": constraint_signals["constraint_ok"],
        "constraint_violation": constraint_signals["constraint_violation"],
        "domain_conformity": semantic_signals["domain_conformity"],
        "shape_conformity": semantic_signals["shape_conformity"],
        "semantic_plausibility": semantic_signals["semantic_plausibility"],
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

    _structured_log("VALIDATOR_EXIT", {
        "recommendation": recommendation,
        "reason": reason,
        "signals": signals,
        "execution_status": execution_status,
        "extracted_constraints": constraints,
        "semantic_expectation": semantic_expectation,
    })

    return {
        "recommendation": recommendation,
        "reason": reason,
        "meta": {
            "extracted_constraints": constraints,
            "semantic_signals": semantic_signals,  # Advisory only
        },
        "signals": signals  # Advisory only
    }

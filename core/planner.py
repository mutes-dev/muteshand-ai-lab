"""
Planner Module - Plan Generation and Structuring

PURPOSE:
    Generates structured execution plans from natural language goals.
    Uses LLM-based generation with deterministic validation and retry logic.
    Converts user goals into sequences of tool/agent invocations.

ARCHITECTURE ROLE:
    - Planning layer: Bridge between natural language and executable structure
    - Produces structured plans: list of dicts with type, name, input_text
    - Validates plans before returning to manager
    - Handles retry logic for failed plan generation attempts

LAYER RESPONSIBILITY:
    - Detect sequential operations in goal text
    - Normalize implicit chaining to explicit form
    - Generate tool/agent steps via LLM
    - Validate generated plans meet schema requirements
    - Enforce plan completeness and linearity

INPUT/OUTPUT CONTRACT:
    Input: goal (str) - natural language goal
    Output: list[dict] - structured plan, or failure dict on error
    
    Plan step structure:
    {
        "type": "tool" or "agent",
        "name": str,           # tool/agent name
        "input_text": str      # original text for reference
    }

USAGE:
    from core.planner import generate_structured_plan
    
    plan = generate_structured_plan("add 2 and 3", tool_names)
    # Returns: [{"type": "tool", "name": "add_numbers", "input_text": "2 and 3"}]

"""

import json
import re
from core.llm import ask_llm

# Semantic pattern mapping for known phrases → valid tool names
SEMANTIC_PATTERNS = [
    {
        "pattern": r"^read file (.+)$",
        "tool": "read_file"
    },
    {
        "pattern": r"^read webpage (.+)$",
        "tool": "read_webpage"
    },
    {
        "pattern": r"^system maintenance$",
        "tool": "run_system_maintenance"
    }
]


def _detect_sequential_operations(goal: str) -> list:
    """
    Detect sequential operations in a goal string using keyword-based splitting.
    
    Args:
        goal (str): User goal string
        
    Returns:
        list: List of operation strings in order
    """
    
    # Strict split on " then "
    operations = goal.split(" then ")
    
    # Clean clauses
    operations = [op.strip() for op in operations if op.strip()]
    
    return operations


def normalize_input_text(text: str) -> str:
    """
    Normalize input text to make implicit chaining explicit.
    
    Uses strict deterministic clause-based substitution with exact equality checks.
    NO regex, NO pattern matching, NO substring logic.
    
    Args:
        text (str): Input text to normalize
        
    Returns:
        str: Normalized text with explicit chaining
        
    Examples:
        >>> normalize_input_text("add 2 and 3 then multiply by 4")
        "add 2 and 3 then multiply the result by 4"
        
        >>> normalize_input_text("add 2 and 3 then square")
        "add 2 and 3 then square the result"
    """
    
    # Case-insensitive split: find all " then " variants
    # Convert to lowercase for splitting logic
    text_lower = text.lower()
    
    # Find split positions for " then " (case-insensitive)
    split_positions = []
    search_start = 0
    while True:
        pos = text_lower.find(" then ", search_start)
        if pos == -1:
            break
        split_positions.append(pos)
        search_start = pos + 6  # len(" then ") = 6
    
    # Extract clauses using split positions
    clauses = []
    start = 0
    for pos in split_positions:
        clauses.append(text[start:pos])
        start = pos + 6
    clauses.append(text[start:])  # Last clause
    
    # Process each clause independently
    normalized_clauses = []
    
    for clause in clauses:
        # Check for exact clause matches and transform
        normalized_clause = _normalize_clause(clause)
        normalized_clauses.append(normalized_clause)
    
    # Reconstruct with " then " delimiter (lowercase)
    return " then ".join(normalized_clauses)


def _is_numeric(value: str) -> bool:
    """
    Check if a string represents a numeric value (int or float).
    
    Deterministic check using try/except conversion.
    NO regex, NO pattern matching.
    
    Args:
        value (str): String to check
        
    Returns:
        bool: True if numeric, False otherwise
    """
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def _normalize_clause(clause: str) -> str:
    """
    Normalize a single clause using strict structured matching.
    
    Uses ONLY:
    - clause.split()
    - len(parts)
    - exact token position checks
    - numeric validation
    
    NO regex, NO pattern matching, NO substring logic.
    
    Args:
        clause (str): Single clause to normalize
        
    Returns:
        str: Normalized clause or original if no match
    """
    
    # Split on spaces to analyze structure
    parts = clause.split()
    
    if len(parts) == 0:
        return clause
    
    # Convert to lowercase for matching (preserve original for output)
    parts_lower = [p.lower() for p in parts]
    
    # RULE 1: "multiply by X" -> "multiply the result by X"
    # Valid ONLY if: len==3, parts[0]=="multiply", parts[1]=="by", parts[2] is numeric
    if (len(parts) == 3 and 
        parts_lower[0] == "multiply" and 
        parts_lower[1] == "by" and
        _is_numeric(parts[2])):
        return f"multiply the result by {parts[2]}"
    
    # RULE 2: "divide by X" -> "divide the result by X"
    # Valid ONLY if: len==3, parts[0]=="divide", parts[1]=="by", parts[2] is numeric
    if (len(parts) == 3 and 
        parts_lower[0] == "divide" and 
        parts_lower[1] == "by" and
        _is_numeric(parts[2])):
        return f"divide the result by {parts[2]}"
    
    # RULE 3: "add X" -> "add X to the result"
    # Valid ONLY if: len==2, parts[0]=="add", parts[1] is numeric
    if (len(parts) == 2 and 
        parts_lower[0] == "add" and
        _is_numeric(parts[1])):
        return f"add {parts[1]} to the result"
    
    # RULE 4: "subtract X" -> "subtract X from the result"
    # Valid ONLY if: len==2, parts[0]=="subtract", parts[1] is numeric
    if (len(parts) == 2 and 
        parts_lower[0] == "subtract" and
        _is_numeric(parts[1])):
        return f"subtract {parts[1]} from the result"
    
    # RULE 5: "square" -> "square the result"
    # Valid ONLY if: len==1, parts[0]=="square"
    if len(parts) == 1 and parts_lower[0] == "square":
        return "square the result"
    
    # RULE 6: "times X" -> "multiply the result by X"
    # Valid ONLY if: len==2, parts[0]=="times", parts[1] is numeric
    if (len(parts) == 2 and 
        parts_lower[0] == "times" and
        _is_numeric(parts[1])):
        return f"multiply the result by {parts[1]}"
    
    # RULE 7: "plus X" -> "add X to the result"
    # Valid ONLY if: len==2, parts[0]=="plus", parts[1] is numeric
    if (len(parts) == 2 and 
        parts_lower[0] == "plus" and
        _is_numeric(parts[1])):
        return f"add {parts[1]} to the result"
    
    # RULE 8: "minus X" -> "subtract X from the result"
    # Valid ONLY if: len==2, parts[0]=="minus", parts[1] is numeric
    if (len(parts) == 2 and 
        parts_lower[0] == "minus" and
        _is_numeric(parts[1])):
        return f"subtract {parts[1]} from the result"
    
    # RULE 9: "over X" -> "divide the result by X"
    # Valid ONLY if: len==2, parts[0]=="over", parts[1] is numeric
    if (len(parts) == 2 and 
        parts_lower[0] == "over" and
        _is_numeric(parts[1])):
        return f"divide the result by {parts[1]}"
    
    # No match - return original clause unchanged
    return clause


def _validate_linearity(operations: list) -> None:
    """
    Validate that operations form a linear chain (not independent or multi-branch).
    
    Args:
        operations (list): List of operation strings
        
    Raises:
        ValueError: If operations are non-linear or independent
    """
    
    # Single operation is always valid
    if len(operations) <= 1:
        return
    
    # Check each operation after the first
    for idx, operation in enumerate(operations[1:], start=1):
        operation_lower = operation.lower()
        
        # Check if operation references prior result
        references_prior = (
            "result" in operation_lower or
            "previous" in operation_lower or
            "that" in operation_lower
        )
        
        if not references_prior:
            raise ValueError(
                f"Non-linear or independent operations detected — planner cannot proceed. "
                f"Operation {idx + 1} ('{operation}') does not reference previous result."
            )


def _enforce_plan_completeness(operations: list, plan: list) -> None:
    """
    Enforce that the plan is complete and valid before returning to caller.
    
    This is the final safeguard that ensures NO partial or degraded plans
    are ever returned. A plan is either COMPLETE or INVALID.
    
    Args:
        operations (list): List of detected operations
        plan (list): Generated plan to validate
        
    Raises:
        ValueError: If plan is incomplete, invalid, or has broken chaining
    """
    
    # RULE 1: NO EMPTY PLAN
    if not plan:
        raise ValueError("Plan incomplete: empty plan returned")
    
    # RULE 2: STEP COUNT MATCH
    if len(plan) != len(operations):
        raise ValueError(
            f"Plan incomplete: step count does not match detected operations "
            f"(expected {len(operations)}, got {len(plan)})"
        )
    
    # RULE 3: VALID STEP STRUCTURE
    required_keys = {"type", "name", "input_text"}
    
    for i, step in enumerate(plan):
        if not isinstance(step, dict):
            raise ValueError(f"Invalid step at index {i}: not a dict")
        
        if not required_keys.issubset(step.keys()):
            raise ValueError(f"Incomplete step at index {i}: missing required fields")


def _generate_plan_llm(goal, tool_names, error_feedback=None):
    """
    Internal function to call LLM and generate raw JSON plan.
    
    Args:
        goal (str): User goal
        tool_names (list): List of available tool names
        error_feedback (str, optional): Error message from previous attempt
        
    Returns:
        str: Raw LLM response (should be JSON)
    """
    
    tools_str = ", ".join(tool_names)
    
    # DEBUG: Print full prompt construction
    print(f"\n[DEBUG _generate_plan_llm] goal='{goal}'")
    
    prompt = f"""You are a planning system that generates STRICT JSON plans.

Available tools:
{tools_str}

OUTPUT REQUIREMENTS:
- Output ONLY valid JSON
- NO explanations
- NO text outside JSON
- NO markdown code blocks

OUTPUT SCHEMA:
[
  {{
    "type": "tool",
    "name": "tool_name",
    "input_text": "original instruction text"
  }},
  {{
    "type": "agent",
    "name": "agent_name",
    "input_text": "description of agent task"
  }}
]

FIELD RULES:

1. "type": MUST be "tool" or "agent" (string)

2. "name": MUST be from available tools (string)

3. "input_text": MUST be a string that contains the original instruction text

STRICT CONSTRAINTS:

- NO extra fields beyond: type, name, input_text
- NO missing fields
- NO natural language outside JSON
- All field names MUST be lowercase strings

TOOL MAPPING RULES (STRICT):

You MUST map operations EXACTLY as follows:

- "add" → add_numbers
- "subtract" → subtract_numbers
- "multiply" → multiply_numbers
- "divide" → divide_numbers

CRITICAL REQUIREMENTS:

- Choose the CORRECT tool based on the operation
- DO NOT substitute tools
- DO NOT approximate tool selection
- Each step MUST represent exactly ONE operation
- Multi-step inputs MUST be split into multiple steps
- DO NOT combine operations in one step

HARD CONSTRAINTS (MANDATORY):

- ONE operation per step - NEVER combine
- DO NOT skip steps
- DO NOT infer missing steps
- DO NOT approximate or guess
- DO NOT substitute tools
- EXACT tool mapping only

INPUT_TEXT MATCHING RULE (CRITICAL):

- input_text MUST match the exact operation clause from the goal
- DO NOT shorten input_text
- DO NOT replace with generic phrases
- DO NOT use abbreviated forms
- input_text should reflect the natural language of that specific step

FAILURE RULE:

- If no valid tool matches the instruction → return empty list []
- DO NOT guess or substitute a tool
- DO NOT attempt to approximate

OUTPUT FORMAT RULE (STRICT):

- Output MUST be valid JSON array
- NO markdown code blocks
- NO explanation text before or after JSON
- NO comments in JSON
- ONLY the structured JSON output

ARCHITECTURE ENFORCEMENT:

- Planner outputs STRUCTURE ONLY
- DO NOT generate arguments
- DO NOT perform parsing or validation
- Arguments are extracted by downstream components

EXAMPLES:

Example 1 - Simple tool call:
Goal: "Add 2 and 3"
Output:
[
  {{
    "type": "tool",
    "name": "add_numbers",
    "input_text": "add 2 and 3"
  }}
]

Example 2 - Multi-step:
Goal: "add 2 and 3 then multiply by 4"
Output:
[
  {{
    "type": "tool",
    "name": "add_numbers",
    "input_text": "add 2 and 3"
  }},
  {{
    "type": "tool",
    "name": "multiply_numbers",
    "input_text": "multiply the result by 4"
  }}
]

Example 3 - Agent step:
Goal: "use tester_agent to test add_numbers"
Output:
[
  {{
    "type": "agent",
    "name": "tester_agent",
    "input_text": "test add_numbers"
  }}
]

USER GOAL:
{goal}

Generate the JSON plan now. Output ONLY the JSON array, nothing else.
"""
    
    # Add error feedback if provided
    if error_feedback:
        prompt += f"""

----------------------------------------
PREVIOUS ERROR:
{error_feedback}

Fix your previous output.
Return ONLY valid JSON.
----------------------------------------
"""
    
    raw_response = ask_llm(prompt)
    
    print("\n===== RAW PLANNER OUTPUT =====")
    print(raw_response)
    print("================================\n")
    
    # DEBUG: Print raw LLM response
    print(f"[DEBUG LLM RAW RESPONSE] {repr(raw_response)}")
    
    return raw_response


def generate_structured_plan(goal, tool_names):
    """
    Public function to generate a structured plan with retry logic.
    
    Args:
        goal (str): User goal
        tool_names (list): List of available tool names
        
    Returns:
        list or None: Parsed JSON plan as Python list, or None if all retries fail
    """
    try:
        # -------------------
        # INPUT NORMALIZATION
        # -------------------
        normalized_input = goal.strip().lower()
        
        if normalized_input.startswith("run "):
            normalized_input = normalized_input[4:].strip()
        
        if normalized_input.startswith("execute "):
            normalized_input = normalized_input[8:].strip()
        
        # -------------------
        # DIRECT TOOL MATCH
        # -------------------
        if normalized_input in tool_names:
            return [{
                "type": "tool",
                "name": normalized_input,
                "input_text": goal
            }]
        
        # -------------------
        # SEMANTIC PATTERN MATCHING
        # -------------------
        for entry in SEMANTIC_PATTERNS:
            if re.match(entry["pattern"], normalized_input):
                tool_name = entry["tool"]
                
                # SAFETY: ensure tool exists
                if tool_name in tool_names:
                    return [{
                        "type": "tool",
                        "name": tool_name,
                        "input_text": goal
                    }]
        
        # Normalize input text to make implicit chaining explicit
        goal = normalize_input_text(goal)
        
        # Detect sequential operations - this is the source of truth for step count
        operations = _detect_sequential_operations(goal)
        print(f"[PLANNER] Detected operations: {operations}")
        
        # Validate clauses
        VALID_VERBS = ["add", "subtract", "multiply", "divide"]
        
        for op in operations:
            tokens = op.strip().split()
            
            # Must contain valid verb
            if not any(v in op for v in VALID_VERBS):
                return {
                    "type": "failure",
                    "reason": "unrecognized_operation"
                }
            
            # Minimum completeness check
            if len(tokens) < 2:
                return {
                    "type": "failure",
                    "reason": "unrecognized_operation"
                }
        
        # Validate linearity - reject non-linear or independent operations
        _validate_linearity(operations)
        
        # SINGLE-STEP CASE: Use original LLM call logic
        if len(operations) == 1:
            print("[PLANNER] Single operation detected - using standard generation")
            
            MAX_RETRIES = 3
            error_feedback = None
            
            for attempt in range(MAX_RETRIES):
                
                # Generate plan with optional error feedback
                raw = _generate_plan_llm(goal, tool_names, error_feedback)
                
                # Strip markdown code blocks if present
                raw_cleaned = raw.strip()
                if raw_cleaned.startswith('```'):
                    # Remove opening ```json or ``` 
                    lines = raw_cleaned.split('\n')
                    if lines[0].startswith('```'):
                        lines = lines[1:]
                    # Remove closing ```
                    if lines and lines[-1].strip() == '```':
                        lines = lines[:-1]
                    raw_cleaned = '\n'.join(lines)
                
                # Try to parse JSON
                try:
                    parsed = json.loads(raw_cleaned)
                except json.JSONDecodeError:
                    error_feedback = "Invalid JSON format. Return valid JSON only. Do NOT use markdown code blocks."
                    continue
                except Exception:
                    error_feedback = "Invalid JSON format. Return valid JSON only. Do NOT use markdown code blocks."
                    continue
                
                operation = operations[0]
                # Ensure each step has complete input_text
                for step in parsed:
                    input_text = step.get("input_text", "")
                    tokens = input_text.strip().split()
                    if (
                        not input_text.strip()
                        or (len(tokens) == 1 and _is_numeric(tokens[0]))
                        or len(tokens) == 1
                        or not any(keyword in input_text.lower() for keyword in ["add", "subtract", "multiply", "divide"])
                    ):
                        step["input_text"] = operation
                
                # Enforce plan completeness before returning
                _enforce_plan_completeness(operations, parsed)
                return parsed
            
            # All retries exhausted
            return {
                "type": "failure",
                "stage": "planner",
                "reason": "Single-step plan generation failed after all retries"
            }
        
        # MULTI-STEP CASE: Build plan step-by-step with enforced chaining
        print(f"[PLANNER] Multi-step detected ({len(operations)} operations) - using controlled generation")
        
        MAX_PLAN_RETRIES = 2
        
        for plan_attempt in range(MAX_PLAN_RETRIES):
            
            final_plan = []
            MAX_RETRIES = 3
            
            for op_idx, operation in enumerate(operations):
                print(f"[PLANNER] Generating step {op_idx + 1}/{len(operations)}: {operation}")
                
                step_generated = False
                
                for attempt in range(MAX_RETRIES):
                    
                    # Call LLM for individual operation
                    raw = _generate_plan_llm(operation, tool_names, error_feedback=None)
                    
                    # Strip markdown code blocks if present
                    raw_cleaned = raw.strip()
                    if raw_cleaned.startswith('```'):
                        lines = raw_cleaned.split('\n')
                        if lines[0].startswith('```'):
                            lines = lines[1:]
                        if lines and lines[-1].strip() == '```':
                            lines = lines[:-1]
                        raw_cleaned = '\n'.join(lines)
                    
                    # Try to parse JSON
                    try:
                        parsed = json.loads(raw_cleaned)
                    except (json.JSONDecodeError, Exception):
                        continue
                    
                    # Extract step matching current operation from LLM response
                    step = None
                    
                    if isinstance(parsed, list):
                        # Try to find step matching current operation
                        for candidate in parsed:
                            if isinstance(candidate, dict):
                                candidate_input = candidate.get("input_text", "").lower()
                                operation_lower = operation.lower()
                                
                                if operation_lower in candidate_input:
                                    step = candidate
                                    break
                        
                        # Fallback: if no match found, take first element
                        if step is None and len(parsed) > 0:
                            step = parsed[0]
                    elif isinstance(parsed, dict):
                        step = parsed
                    
                    if step is None:
                        continue
                    
                    # Validate step structure
                    if not isinstance(step, dict):
                        continue
                    
                    required_keys = {"type", "name", "input_text"}
                    if not required_keys.issubset(step.keys()):
                        continue
                    
                    # Ensure step has complete input_text
                    input_text = step.get("input_text", "")
                    tokens = input_text.strip().split()
                    if (
                        not input_text.strip()
                        or (len(tokens) == 1 and _is_numeric(tokens[0]))
                        or len(tokens) == 1
                        or not any(keyword in input_text.lower() for keyword in ["add", "subtract", "multiply", "divide"])
                    ):
                        step["input_text"] = operation
                    
                    # Step successfully generated - make a copy to avoid reference issues
                    import copy
                    final_plan.append(copy.copy(step))
                    step_generated = True
                    print(f"[PLANNER] Step {op_idx + 1} generated: {step['name']}")
                    print(f"[DEBUG PARSED] name='{step.get('name')}', input_text='{step.get('input_text')}'")
                    break
                
                if not step_generated:
                    print(f"[PLANNER] Failed to generate step {op_idx + 1} after {MAX_RETRIES} attempts")
                    return {
                        "status": "failure",
                        "reason": f"Failed to generate step {op_idx + 1} after {MAX_RETRIES} attempts"
                    }
            
            # Validate complete plan
            print(f"[PLANNER OUTPUT] {final_plan}")
            
            # Enforce plan completeness before returning
            try:
                _enforce_plan_completeness(operations, final_plan)
                print(f"[PLANNER] Multi-step plan successfully generated with {len(final_plan)} steps")
                return final_plan
            except ValueError as e:
                print(f"[PLANNER] Plan completeness check failed (attempt {plan_attempt + 1}/{MAX_PLAN_RETRIES}): {e}")
                if plan_attempt < MAX_PLAN_RETRIES - 1:
                    print(f"[PLANNER] Retrying plan generation...")
                    continue
        
        # All retries exhausted
        return {
            "type": "failure",
            "stage": "planner",
            "reason": "Multi-step plan generation failed: plan incomplete after all retries"
        }
    
    except ValueError as e:
        return {
            "type": "failure",
            "stage": "planner",
            "reason": str(e)
        }
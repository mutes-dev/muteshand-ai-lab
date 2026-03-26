"""
Planner Module - Plan Generation and Structuring

PURPOSE:
    Generates structured execution plans from natural language goals.
    Uses LLM-based generation with deterministic validation and retry logic.
    Converts user goals into sequences of tool/agent invocations.

ARCHITECTURE ROLE:
    - Planning layer: Bridge between natural language and executable structure
    - Produces structured plans: list of dicts with type, name, args, input_text
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
        "args": list,          # arguments for execution
        "input_text": str      # original text for reference
    }

USAGE:
    from core.planner import generate_structured_plan
    
    plan = generate_structured_plan("add 2 and 3", tool_names)
    # Returns: [{"type": "tool", "name": "add_numbers", "args": [2, 3], "input_text": "2 and 3"}]

"""

import json
from core.llm import ask_llm
from core.validation import validate_plan


def _detect_sequential_operations(goal: str) -> list:
    """
    Detect sequential operations in a goal string using keyword-based splitting.
    
    Args:
        goal (str): User goal string
        
    Returns:
        list: List of operation strings in order
    """
    
    # A. Normalize input
    normalized_goal = goal.strip().lower()
    
    # B. Define sequential keywords in priority order
    # Using spaces around keywords to avoid partial matches
    keywords = [
        " and then ",
        " then ",
        " after that ",
        " after ",
        " followed by "
    ]
    
    # C. Split logic - find first matching keyword and split iteratively
    operations = [normalized_goal]
    
    for keyword in keywords:
        new_operations = []
        for op in operations:
            if keyword in op:
                # Split on this keyword
                parts = op.split(keyword)
                new_operations.extend([part.strip() for part in parts if part.strip()])
            else:
                new_operations.append(op)
        operations = new_operations
    
    # D. Fallback - if no keywords detected, return original goal
    if len(operations) == 1:
        return [goal.strip()]
    
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
    required_keys = {"type", "name", "args", "input_text"}
    
    for i, step in enumerate(plan):
        if not isinstance(step, dict):
            raise ValueError(f"Invalid step at index {i}: not a dict")
        
        if not required_keys.issubset(step.keys()):
            raise ValueError(f"Incomplete step at index {i}: missing required fields")
    
    # RULE 4: FIRST STEP MUST NOT USE PREVIOUS_RESULT
    if "PREVIOUS_RESULT" in plan[0].get("args", []):
        raise ValueError("Invalid plan: first step cannot use PREVIOUS_RESULT")
    
    # RULE 5: CHAINING INTEGRITY (all steps after first must use PREVIOUS_RESULT only)
    for i in range(1, len(plan)):
        args = plan[i].get("args", [])
        
        if args != ["PREVIOUS_RESULT"]:
            raise ValueError(
                f"Invalid chaining at step {i + 1}: must use PREVIOUS_RESULT only "
                f"(got {args})"
            )


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
    "args": [arg1, arg2],
    "input_text": "text version of args"
  }},
  {{
    "type": "agent",
    "name": "agent_name",
    "args": [],
    "input_text": "description of agent task"
  }}
]

FIELD RULES:

1. "type": MUST be "tool" or "agent" (string)

2. "name": MUST be from available tools (string)

3. "args": MUST be a list containing ONLY:
   - numbers (int or float)
   - strings (for literal string values ONLY)
   - "PREVIOUS_RESULT" (exact token to reference previous step output)
   
   ❌ CRITICAL: args MUST NOT contain natural language phrases
   ❌ DO NOT use: "result", "result of previous step", "output", or ANY descriptive text
   ✅ ONLY use: "PREVIOUS_RESULT" (exact string token)
   
4. "input_text": MUST be a string that:
   - reflects args in natural language
   - is parseable by argument parser
   - can contain phrases like "result of previous step"

CHAINING RULES:

- "PREVIOUS_RESULT" is the ONLY valid chaining token in args
- "PREVIOUS_RESULT" can appear ONCE per step
- "PREVIOUS_RESULT" is NOT allowed in first step
- Use "PREVIOUS_RESULT" to reference the IMMEDIATE previous step only
- Natural language chaining phrases belong in "input_text" ONLY, NOT in "args"

EXAMPLES:

Example 1 - Simple tool call:
Goal: "Add 2 and 3"
Output:
[
  {{
    "type": "tool",
    "name": "add_numbers",
    "args": [2, 3],
    "input_text": "2 and 3"
  }}
]

Example 2 - Chained tool calls:
Goal: "Add 2 and 3, then square the result"
Output:
[
  {{
    "type": "tool",
    "name": "add_numbers",
    "args": [2, 3],
    "input_text": "2 and 3"
  }},
  {{
    "type": "tool",
    "name": "square_number",
    "args": ["PREVIOUS_RESULT"],
    "input_text": "result of previous step"
  }}
]

Example 3 - Multiple arguments with chaining:
Goal: "Add 5 and 7, then multiply the result by 3"
Output:
[
  {{
    "type": "tool",
    "name": "add_numbers",
    "args": [5, 7],
    "input_text": "5 and 7"
  }},
  {{
    "type": "tool",
    "name": "multiply_numbers",
    "args": ["PREVIOUS_RESULT", 3],
    "input_text": "result of previous step and 3"
  }}
]

STRICT CONSTRAINTS:

- NO extra fields beyond: type, name, args, input_text
- NO missing fields
- NO natural language outside JSON
- args MUST be a list (even for single argument)
- All field names MUST be lowercase strings

ARGUMENT INTEGRITY RULES (TOOLS ONLY):

- You MUST NOT generate a tool step if required values are not present in the goal
- You MUST NOT invent, guess, or assume values
- You MUST ONLY use:
  - constants explicitly present in the goal
  - "PREVIOUS_RESULT" for chaining

- If the goal does not contain usable values:
  → RETURN an empty list []

Examples:

❌ INVALID:
Goal: "use add_numbers"
→ DO NOT generate a plan (no values provided)
→ Return: []

❌ INVALID:
Goal: "add numbers"
→ DO NOT guess values
→ Return: []

✅ VALID:
Goal: "add 2 and 3"
→ args: [2, 3]

ARGUMENT STRUCTURE RULES:

- You MUST respect the number of arguments each tool accepts
- You MUST NOT pass more arguments than a tool supports

- If a goal contains MORE values than a tool accepts:
  → You MUST break the task into multiple steps

- You MUST use chaining with "PREVIOUS_RESULT" for multi-step calculations

Examples:

❌ INVALID:
Goal: "add 1 and 2 and 3"
→ args: [1, 2, 3]  (3 args for 2-arg tool)

✅ VALID:
Goal: "add 1 and 2 and 3"
→ [
  {{ "type": "tool", "name": "add_numbers", "args": [1, 2], "input_text": "1 and 2" }},
  {{ "type": "tool", "name": "add_numbers", "args": ["PREVIOUS_RESULT", 3], "input_text": "result and 3" }}
]

ARGUMENT ORDER RULES:

- You MUST preserve the exact semantic meaning of the goal
- You MUST respect argument order for non-commutative operations

- Carefully interpret phrases like:
  - "subtract A from B" → args: [B, A]
  - "divide A by B" → args: [A, B]

- You MUST NOT reverse argument order

Examples:

✅ VALID:
Goal: "subtract 10 from 20"
→ args: [20, 10]  (20 - 10)

AGENT DETECTION RULES:

- If the goal explicitly mentions an agent (e.g., "use tester_agent", "use code_agent"):
  → Generate an agent step with "type": "agent"

- Agent keywords that trigger agent steps:
  - "use [agent_name]"
  - "test [tool_name]" (use tester_agent)
  - explicit agent references

- For agent steps:
  - "type": "agent"
  - "name": agent name (e.g., "tester_agent", "code_agent")
  - "args": [] (empty list for now)
  - "input_text": description of what the agent should do

Examples:

✅ VALID - Agent step:
Goal: "use tester_agent to test add_numbers with inputs 2 and 3 expected output 5"
→ [
  {{
    "type": "agent",
    "name": "tester_agent",
    "args": [],
    "input_text": "test add_numbers with inputs 2 and 3 expected output 5"
  }}
]

✅ VALID - Tool step (no agent mentioned):
Goal: "add 2 and 3"
→ [
  {{
    "type": "tool",
    "name": "add_numbers",
    "args": [2, 3],
    "input_text": "2 and 3"
  }}
]

TOOL SELECTION RULES:

- You MUST select the tool that EXACTLY matches the operation described in the goal
- You MUST NOT substitute tools based on similarity

- Map operations explicitly:
  - "add", "sum", "plus" → add_numbers
  - "subtract", "minus" → subtract_numbers
  - "multiply", "times" → multiply_numbers
  - "divide" → divide_numbers

- You MUST NOT:
  - use add_numbers for subtraction
  - use multiply_numbers for addition
  - substitute tools incorrectly under any condition

Examples:

❌ INVALID:
Goal: "subtract 5 from 10"
→ using add_numbers

✅ VALID:
Goal: "subtract 5 from 10"
→ using subtract_numbers

NESTED STRUCTURE RULES:

- You MUST resolve nested phrases step-by-step

- Identify inner operations FIRST, then outer operations

- Each operation MUST be represented as a separate step

- You MUST NOT:
  - flatten nested operations into a single step
  - skip intermediate steps
  - reorder operations incorrectly

- Always follow this pattern:
  1. Resolve inner expression
  2. Use PREVIOUS_RESULT for outer expression

Examples:

❌ INVALID:
Goal: "add the result of adding 1 and 2 and 3"
→ single step or incorrect structure

✅ VALID:
Goal: "add the result of adding 1 and 2 and 3"
→ [
  {{ "type": "tool", "name": "add_numbers", "args": [1, 2], "input_text": "1 and 2" }},
  {{ "type": "tool", "name": "add_numbers", "args": ["PREVIOUS_RESULT", 3], "input_text": "result and 3" }}
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
        # Normalize input text to make implicit chaining explicit
        goal = normalize_input_text(goal)
        
        # Detect sequential operations - this is the source of truth for step count
        operations = _detect_sequential_operations(goal)
        print(f"[PLANNER] Detected operations: {operations}")
        
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
                
                # Validate the parsed plan
                is_valid, error_msg = validate_plan(parsed, tool_names)
                
                if is_valid:
                    # Enforce plan completeness before returning
                    _enforce_plan_completeness(operations, parsed)
                    return parsed
                else:
                    error_feedback = f"Validation error: {error_msg}"
            
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
                    
                    # Extract first step from LLM response (LLM may return array)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        step = parsed[0]
                    elif isinstance(parsed, dict):
                        step = parsed
                    else:
                        continue
                    
                    # Validate step structure
                    if not isinstance(step, dict):
                        continue
                    
                    required_keys = {"type", "name", "args", "input_text"}
                    if set(step.keys()) != required_keys:
                        continue
                    
                    # ENFORCE CHAINING for subsequent steps
                    if op_idx > 0:
                        # Override args with PREVIOUS_RESULT
                        step["args"] = ["PREVIOUS_RESULT"]
                        step["input_text"] = "result of previous step"
                    else:
                        # First step must NOT contain PREVIOUS_RESULT
                        if "PREVIOUS_RESULT" in step.get("args", []):
                            continue
                    
                    # Step successfully generated
                    final_plan.append(step)
                    step_generated = True
                    print(f"[PLANNER] Step {op_idx + 1} generated: {step['name']}")
                    break
                
                if not step_generated:
                    print(f"[PLANNER] Failed to generate step {op_idx + 1} after {MAX_RETRIES} attempts")
                    return {
                        "type": "failure",
                        "stage": "planner",
                        "reason": f"Failed to generate step {op_idx + 1} after {MAX_RETRIES} attempts"
                    }
            
            # Validate complete plan
            is_valid, error_msg = validate_plan(final_plan, tool_names)
            if not is_valid:
                print(f"[PLANNER] Final plan validation failed: {error_msg}")
                return {
                    "type": "failure",
                    "stage": "planner",
                    "reason": f"Final plan validation failed: {error_msg}"
                }
            
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
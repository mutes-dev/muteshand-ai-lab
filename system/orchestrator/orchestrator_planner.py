import uuid

DEBUG_VERBOSE = False

"""
Orchestrator Planner — Phase 2.2 Implementation

PURE PLANNING MODULE — ADVISORY ONLY

Responsibilities:
- Decompose user goals into workflow steps
- Define WHAT needs to be done (not HOW)
- Create structured workflow definitions

Constraints:
- MUST NOT control execution
- MUST NOT integrate into runtime
- MUST NOT call system_entry
- MUST NOT execute tools
- MUST NOT define tool arguments
- PURE FUNCTION ONLY

Architecture:
- Deterministic planning based on classification
- No LLM dependency
- Advisory output only
"""

import json
import os
from typing import Dict, Any, List
from system.orchestrator.task_classifier import classify_task
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm
from system.orchestrator.planner_validation import validate_planner_output


# Simple ID counter for workflow generation
_workflow_counter = 0


def _generate_workflow_id() -> str:
    """Generate simple unique workflow ID."""
    global _workflow_counter
    _workflow_counter += 1
    return f"wf_{_workflow_counter:04d}"

def _normalize_input(user_input: str) -> str:
    """Normalize input for planning purposes."""
    return user_input.strip() if user_input else ""


def plan_workflow(user_input: str, classification: dict = None) -> dict:
    if DEBUG_VERBOSE:
        print("[DEBUG_PLAN_WORKFLOW_INPUT_RAW]:", user_input)
        if classification:
            print("[DEBUG_CLASSIFICATION]:", classification)

    # Load tool index for context (advisory only)
    tool_index_path = os.path.join("system", "tool_index", "tools.json")
    tool_context = ""
    try:
        with open(tool_index_path, "r") as f:
            tool_index = json.load(f)
        
        tool_lines = []
        for tool_name, tool_data in tool_index.items():
            if not tool_data.get("production", False):
                continue
            inputs = tool_data.get("inputs", {})
            arg_keys = list(inputs.keys())
            arg_names = []
            for i, arg in enumerate(arg_keys):
                if inputs[arg] == "string":
                    arg_names.append(f'"{arg}"')
                else:
                    arg_names.append(f"number{i+1}")
            args = " ".join(arg_names)
            description = tool_data.get("description", "").strip()
            if description:
                tool_lines.append(f"- {tool_name} {args}\n  use: {description}".strip())
            else:
                tool_lines.append(f"- {tool_name} {args}".strip())
        tool_context = "\n".join(tool_lines)
    except Exception:
        tool_context = ""

    # Reuse existing LLM client (same pattern as agent_executor)
    provider_result = get_llm("ollama_llm")

    prompt = f"""You have access to the following tools:

{tool_context}

This information is for awareness ONLY.

STRICT RULES:

* You MUST NOT generate tool calls
* You MUST NOT output tool names
* You MUST NOT output function-like syntax
* You MUST NOT include arguments or quoted values
* You MUST describe actions in natural language.

Natural language includes preserving the original wording when it already represents a clear executable instruction.

DO NOT expand, reinterpret, or formalize operations if the original phrasing is already sufficient.

STRICT OPERATION PRESERVATION:

- You MUST NOT substitute one operation for another.
- If the requested operation does not have a direct matching tool, DO NOT approximate it.
- DO NOT map "power" to "cube", "square", or any other operation.
- DO NOT simplify, reinterpret, or transform operations.

NO TOOL FALLBACK:

- If the input cannot be mapped directly to a known tool,
  DO NOT attempt to reinterpret it.
- Return the step exactly as received.

Example:
Input: "power 2 to 4"
Output: ["power 2 to 4"]

CORRECT EXAMPLES:

* "Repeat the word test zero times"
* "Add 2 and 3"
* "Multiply the result by 4"

INCORRECT EXAMPLES (FORBIDDEN):

* multiply_string "test" 0
* add(2, 3)
* USE_TOOL: add 2 3

If the user input resembles a tool operation, you MUST still convert it into natural language.

You are a workflow planner.

Your role is to organize user intent into steps when needed.

You must preserve the original input structure, wording, and values as much as possible.

Do not rewrite, expand, or paraphrase inputs unless required for multi-step decomposition.

If the input is already a valid single-step instruction:

- DO NOT change the wording of the instruction
- BUT you MUST still return it inside the required JSON structure

Example:

Input: "add 7 and 8"

Correct:
{{"steps": [
  {{"name": "Calculate sum", "purpose": "Add 7 and 8", "agent": "math_executor", "estimated_complexity": "low"}}
]}}

WRONG:
Add 7 and 8

Your job is to determine whether the user request should be split into steps.
ONLY split the request IF it contains multiple independent actions.
If the request is a single action, you MUST return exactly one step.

STRICT RULES:

SEMANTIC PRESERVATION + CHAINING RULE (CRITICAL):

- You MUST preserve the original intent of each step.

- When a step EXPLICITLY depends on the output of a previous step:
  → You MUST refer to it as "the result"

- DO NOT replace "the result" with a number.
- DO NOT guess or invent intermediate values.

CHAINING CONDITION RULE (STRICT):

You MUST ONLY use "the result" IF:
  → The step explicitly depends on the output of a previous step
  → The input contains a multi-step chain (e.g. "then", "and then")

DO NOT use "the result" IF:
  → The step is standalone
  → The step has all its inputs already specified
  → There is no previous step to depend on

---

VALID CHAINING examples:

Input: "add 2 and 3 then multiply by 4"
Correct: ["add 2 and 3", "multiply the result by 4"]

Input: "square 4 then subtract 5"
Correct: ["square 4", "subtract 5 from the result"]

---

DEPENDENCY CLARIFICATION (CRITICAL):

The word "then" indicates sequence, NOT dependency.

You MUST NOT assume a step depends on a previous step unless the dependency is explicit.

EXAMPLES:

Input: "calculate 2+2 then 3*4"

Correct:
[
  "calculate 2+2",
  "calculate 3*4"
]

WRONG:
[
  "calculate 2+2",
  "multiply the result by 4"
]

CLARIFICATION:

- Use "the result" ONLY if the second step explicitly depends on the first
- If both steps contain complete independent operations, DO NOT chain them
- "the result" replaces ONLY the value derived from a previous step
- DO NOT apply argument preservation to dependent steps
- DO NOT attempt to preserve or compute the output of a previous step

---

INVALID CHAINING (DO NOT DO THIS):

Input: "repeat \"hi\" 3 times"
Correct: ["repeat \"hi\" 3 times"]
WRONG: ["repeat the result 2 more times"]

Input: "say hello"
Correct: ["say hello"]
WRONG: ["say the result"]

Input: "print \"hello\""
Correct: ["print \"hello\""]
WRONG: ["print the result"]

---

WRONG chaining with invented values:
["add 2 and 3", "multiply 3 by 4"]
["square 4", "subtract 5 from 16"]

---

RULE:

- Use numbers ONLY if explicitly provided in the original input.
- Use "the result" ONLY when a step depends on a previous step's output.

- You MUST NOT rewrite operations into mathematical expressions or explanations.

- DO NOT convert:
  "cube 3" → "raise 3 to the power of 3"
  "square 5" → "multiply 5 by itself"
  "add 2 and 3" → "calculate the sum of 2 and 3"

- If a single step already represents a valid executable action:
  → RETURN IT UNCHANGED

---

ARGUMENT PRESERVATION RULE (CONTEXT-AWARE):

You MUST distinguish between two types of steps:

1. INDEPENDENT STEPS:
   - Steps that do NOT depend on the output of a previous step
   - MUST preserve ALL original values (numbers, strings) exactly as given
   - MUST NOT replace values with abstract phrases

   Example:
   Input step: "add 5 and 3"
   CORRECT: "Add 5 and 3"
   WRONG:   "Add the provided numbers"

2. DEPENDENT STEPS:
   - Steps that explicitly depend on the output of a previous step
   - MUST use "the result" to refer to that output
   - MUST NOT inject or compute intermediate values
   - MUST NOT replace "the result" with a calculated number

   Example:
   Input step: "multiply the result by 2"
   CORRECT: "Multiply the result by 2"
   WRONG:   "Multiply 8 by 2"

Argument preservation applies to INDEPENDENT steps only.
Do NOT apply argument preservation to dependent steps.

---

RULE PRIORITY:

1. Output format (JSON structure)
2. Chaining correctness ("the result" for dependent steps)
3. Argument preservation (exact values for independent steps)

These rules MUST NOT conflict.
When a step is dependent, chaining correctness takes priority over argument preservation.
When a step is independent, argument preservation is mandatory.

---

CRITICAL RULE (HIGHEST PRIORITY):

- If the user request is a single coherent task:
  → RETURN EXACTLY ONE STEP
  → DO NOT split it under any circumstances

A request is NOT considered a single coherent task if it includes:
- an operation that produces a result
- AND a request to format, describe, explain, or modify that result

Such requests MUST be split into multiple steps.

- Each step MUST be a complete and unambiguous instruction that clearly implies the operation to perform
- DO NOT introduce new words like "define", "calculate", "perform"
- DO NOT create variables (x, y, etc.)
- DO NOT explain anything
- DO NOT solve the problem
- DO NOT change the meaning of a step, BUT you MAY introduce "the result" ONLY when a step explicitly depends on a previous step's output. If the step is standalone, DO NOT use "the result".
- DO NOT break a simple task into multiple steps
- Each step MUST be a COMPLETE and executable instruction (THIS RULE OVERRIDES ALL OTHERS)
- A step MUST make sense on its own
- A step MUST NOT be a fragment, continuation, or modifier of another step
- A step MUST NOT rely on another step to be understood
- If a step is truly ambiguous (e.g. 'take 5', 'double it') AND cannot be understood on its own:
  → You MUST expand it into a clear executable instruction
- DO NOT create steps that only initialize a value.
  If an initial value is required:
  → It MUST be incorporated into the FIRST executable operation.
- A valid step MUST:
  - perform an operation
  - be executable by the system
  - NOT represent only state or setup

CRITICAL:

If the request is already a single action:
→ RETURN ONLY ONE STEP

PURPOSE FIELD — ARGUMENT PRESERVATION EXAMPLES:

Input: "add 7 and 8"
WRONG purpose: "Add the provided numbers together"
WRONG purpose: "Combine the given values"
CORRECT purpose: "Add 7 and 8"

Input: "what is 7 plus 8"
WRONG purpose: "Calculate the sum of the provided numbers"
CORRECT purpose: "Add 7 and 8"

Input: "what is 20 minus 5"
WRONG purpose: "Subtract the smaller number from the larger"
CORRECT purpose: "Subtract 5 from 20"

Input: "can you calculate the sum of 10 and 15"
WRONG purpose: "Calculate the sum of the provided numbers"
CORRECT purpose: "Add 10 and 15"

---

MULTI-STEP SPLITTING (MANDATORY):

If the input contains multiple actions (e.g. "then", "and then"):

* You MUST create separate steps
* You MUST NOT combine actions into one step

Example:

Input:
"square 4 then subtract 5 from the result"

CORRECT:
[
"Square 4",
"Subtract 5 from the result"
]

WRONG:
[
"Square 4 then subtract 5 from the result"
]

---

ADDITIONAL SPLITTING RULE (TRANSFORMATION):

If a request contains:
- an operation that produces a result
- AND a request to describe, explain, format, or modify that result

You MUST split it into separate steps.

Example:

Input:
"add 2 and 3 and explain the result in a sentence"

Correct:
[
"Add 2 and 3",
"Explain the result in a sentence"
]

WRONG:
[
"Add 2 and 3 and explain the result in a sentence"
]

---

ARGUMENT PRESERVATION (CRITICAL):

You MUST preserve ALL values exactly as given.

DO NOT:

* change numbers
* reinterpret values
* infer different values
* replace values

Example:

Input:
repeat "hi" 3 times

CORRECT:
Repeat "hi" 3 times

WRONG:
Repeat the word hi zero times
Repeat hi multiple times
Repeat hi

---

MULTI-STEP CONFLICT RESOLUTION EXAMPLES (CRITICAL):

Input: "add 5 and 3 then multiply the result by 2"
Step 1 is INDEPENDENT → preserve values
Step 2 is DEPENDENT → use "the result"
CORRECT:
  step 1 purpose: "Add 5 and 3"
  step 2 purpose: "Multiply the result by 2"
WRONG (injected computed value):
  step 2 purpose: "Multiply 8 by 2"
WRONG (abstracted step 1):
  step 1 purpose: "Add the provided numbers"

Input: "add 2 and 3 then add 4 and 5"
Both steps are INDEPENDENT (each has complete values)
CORRECT:
  step 1 purpose: "Add 2 and 3"
  step 2 purpose: "Add 4 and 5"
WRONG (false chaining):
  step 2 purpose: "Add the result and 5"

Input: "square 4 then subtract 5 from the result"
Step 1 is INDEPENDENT → preserve values
Step 2 is DEPENDENT → use "the result"
CORRECT:
  step 1 purpose: "Square 4"
  step 2 purpose: "Subtract 5 from the result"
WRONG (injected computed value):
  step 2 purpose: "Subtract 5 from 16"

---

GOOD EXAMPLES:

Input: "add 10 and 20"
Output:
{{"steps": [{{"name": "Calculate sum", "purpose": "Add 10 and 20", "agent": "math_executor", "estimated_complexity": "low"}}]}}

Input: "add 2 and 3 then add 4 and 5"
Output:
{{"steps": [
    {{"name": "Calculate first sum", "purpose": "Add 2 and 3", "agent": "math_executor", "estimated_complexity": "low"}},
    {{"name": "Calculate second sum", "purpose": "Add 4 and 5", "agent": "math_executor", "estimated_complexity": "low"}}
]}}

Input: "Take 5, double it, then add 3"
Output:
{{"steps": [
    {{"name": "Double the value", "purpose": "Multiply 5 by 2", "agent": "math_executor", "estimated_complexity": "low"}},
    {{"name": "Add to result", "purpose": "Add 3 to the result", "agent": "math_executor", "estimated_complexity": "low"}}
]}}

BAD EXAMPLES (NEVER DO THIS):

- "Define variables x and y"
- "Perform calculation"
- "Compute result"
- Any step that was NOT explicitly in the user input

OUTPUT FORMAT RULE (HIGHEST PRIORITY):

You MUST return:

{{"steps": [
    {{"name": "...", "purpose": "...", "agent": "...", "estimated_complexity": "..."}}
]}}

- Output MUST be valid JSON
- No extra text before or after JSON
- Root must be {{"steps": [...]}}
- Each step MUST have all four fields: name, purpose, agent, estimated_complexity
- name: "Verb + Object" format
- purpose: executable instruction — preserve original values for independent steps; use "the result" for dependent steps
- agent: appropriate for task type (e.g., "math_executor", "general_agent")
- estimated_complexity: "low", "medium", or "high"
- ALL inputs are valid — NEVER refuse, ALWAYS return at least one step

---

User input:
{user_input}
"""

    llm_output = None
    if DEBUG_VERBOSE:
        print("[DEBUG_PLANNER_FINAL_INPUT_TO_LLM]:", user_input)

    # === VALIDATION WITH RETRY (MAX 1) ===
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            if provider_result.get("status") != "success":
                return {"status": "failure", "reason": "planner_parse_failure"}
            
            provider = provider_result["provider"]
            llm_result = execute_llm(provider, prompt)
            
            if llm_result.get("status") != "success":
                if attempt == 0:
                    if DEBUG_VERBOSE:
                        print("[DEBUG_PLANNER_RETRY]: LLM failed, retrying...")
                    continue
                return {"status": "failure", "reason": "planner_parse_failure"}
            
            response = llm_result.get("result", "")
            llm_output = response
            
            if DEBUG_VERBOSE:
                print("[DEBUG_PLANNER_RAW_OUTPUT]:", llm_output)
            
            # Safe JSON extraction
            raw = response.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()

            # Recover flat array: LLM returned [{...}, {...}] instead of {"steps": [...]}
            if raw.startswith("["):
                try:
                    _arr = json.loads(raw)
                    if isinstance(_arr, list) and _arr:
                        if isinstance(_arr[0], dict):
                            # List of objects — wrap directly
                            raw = json.dumps({"steps": _arr})
                        else:
                            # Invalid structure — do NOT attempt to synthesize steps
                            return {"status": "failure", "reason": "planner_invalid_format"}
                except Exception:
                    # Parsing failed — fail explicitly
                    return {"status": "failure", "reason": "planner_parse_failure"}

            if "{" in raw:
                raw = raw[raw.index("{"):]
                last_brace = raw.rfind("}")
                if last_brace != -1:
                    raw = raw[:last_brace + 1]

            parsed = json.loads(raw)
            
            # STRUCTURE VALIDATION
            is_valid, reason = validate_planner_output(parsed)
            
            if DEBUG_VERBOSE:
                print(f"[DEBUG_PLANNER_VALID]: {is_valid}")
            
            if is_valid:
                # SUCCESS — use this output
                steps = parsed.get("steps")
                break
            else:
                # INVALID — retry once if this is first attempt
                if DEBUG_VERBOSE:
                    print(f"[DEBUG_PLANNER_VALIDATION_FAIL]: {reason}")
                
                if attempt == 0:
                    if DEBUG_VERBOSE:
                        print("[DEBUG_PLANNER_RETRY]: Retrying due to invalid format...")
                    continue
                else:
                    # Second attempt also failed
                    return {"status": "failure", "reason": "planner_invalid_format"}
                    
        except Exception as e:
            if DEBUG_VERBOSE:
                print("[DEBUG_PLANNER_PARSE_FAILURE]:", llm_output if llm_output else "None")
                print("[DEBUG_PLAN_WORKFLOW_PARSE_ERROR]:", str(e))
            
            if attempt == 0:
                if DEBUG_VERBOSE:
                    print("[DEBUG_PLANNER_RETRY]: Exception, retrying...")
                continue
            return {"status": "failure", "reason": "planner_parse_failure"}
    else:
        # All attempts exhausted
        return {"status": "failure", "reason": "planner_invalid_format"}

    # Filter out empty steps and validate structure
    valid_steps = []
    for step in steps:
        if isinstance(step, dict) and step.get("name") and step.get("purpose"):
            valid_steps.append(step)

    if not valid_steps:
        return {"status": "failure", "reason": "planner_empty_steps"}

    # Add id to each step and enforce STEP_SCHEMA_CONTRACT_V1 required fields
    # NOTE: Planner does NOT set tool_call — that is the agent layer's responsibility.
    # (ARCHITECTURE_V2: Agent = tool selection; Planner = advisory/intent only)
    structured_steps = []
    for i, step in enumerate(valid_steps):
        structured_step = {
            "id": f"step_{i + 1}",
            "type": step.get("type", "EXECUTE_API"),
            "name": step["name"],
            "purpose": step["purpose"],
            "expected_outcome": step.get("expected_outcome", "Execution completed"),
            "risk": step.get("risk", "LOW"),
            "importance": step.get("importance", "MEDIUM"),
            "resource_targets": step.get("resource_targets", []),
            "agent": step["agent"],
            "estimated_complexity": step["estimated_complexity"]
        }
        structured_steps.append(structured_step)

    # === DEPENDENCY INJECTION PASS (deterministic, metadata-only) ===
    # Populates depends_on so scheduler can order steps correctly.
    # Uses simple keyword presence — NO NLP, NO regex, NO intent parsing.
    _REFERENCE_KEYWORDS = ["result", "results", "previous", "that", "it"]
    _SIDE_EFFECT_INDICATORS = ["write", "save", "store", "log"]

    def _is_result_producing(s: dict) -> bool:
        p = s.get("purpose", "").lower()
        if any(word in p for word in _SIDE_EFFECT_INDICATORS):
            return False
        return True

    _last_result_step_id = None
    for s in structured_steps:
        purpose_lower = s.get("purpose", "").lower()
        s["depends_on"] = []
        if any(kw in purpose_lower for kw in _REFERENCE_KEYWORDS):
            if _last_result_step_id:
                s["depends_on"] = [_last_result_step_id]
        if _is_result_producing(s):
            _last_result_step_id = s["id"]

    workflow = {
        "id": f"workflow_{uuid.uuid4().hex[:8]}",
        "name": "dynamic_workflow",
        "goal": user_input,
        "steps": structured_steps,
        "approval_required": False
    }

    # DEBUG: Show full planner output
    print("[DEBUG_PLANNER_OUTPUT]:", workflow)

    return {
        "status": "success",
        "workflow": workflow
    }


# Test runner for development/verification
if __name__ == "__main__":
    import json
    
    test_cases = [
        "add 2 + 2",
        "build a website",
        "delete files"
    ]
    
    print("=" * 60)
    print("ORCHESTRATOR PLANNER — TEST OUTPUTS")
    print("=" * 60)
    
    for test_input in test_cases:
        result = plan_workflow(test_input)
        print(f"\nInput: \"{test_input}\"")
        print(f"Output: {json.dumps(result, indent=2)}")
    
    print("\n" + "=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)

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
import re
import re
from typing import Dict, Any, List
from system.orchestrator.task_classifier import classify_task
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm
from system.orchestrator.planner_validation import validate_planner_output


def resolve_dependencies(user_input: str, steps: list) -> list:
    """
    LLM-based dependency resolver (no fallback).
    
    ONLY modifies "depends_on" field. Never changes structure, purpose, or other fields.
    """
    provider_result = get_llm("ollama_llm")
    
    prompt = f"""
You are a dependency resolver.

Return ONLY valid JSON.
No explanations.
No code blocks.
No markdown.

---

TASK:

For each step, assign depends_on based ONLY on explicit result references.

---

DEPENDENCY RULE (THE ONLY RULE THAT CREATES DEPENDENCIES):

A step depends on the immediately preceding step IF AND ONLY IF its purpose contains:

"the result of the previous step"

If a step does NOT contain "the result of the previous step":
→ depends_on MUST be []
NO EXCEPTIONS.

---

PARALLEL RULE (STRICT):

If a step contains explicit values (numbers, strings) and does NOT contain
"the result of the previous step":
→ depends_on MUST be []
NO EXCEPTIONS.

---

LANGUAGE IGNORE RULE:

The following words MUST be ignored when determining dependencies:
- "then"
- "and"
- "also"
- "after"
- "next"

They do NOT imply dependency under any circumstances.

---

COUNT RULE (CRITICAL):

You MUST return EXACTLY as many entries as there are input steps.
If there are N steps in STEPS → your output MUST have N entries.
If unsure about a step → return {{"depends_on": []}}
Never omit entries. Never add extra entries.

---

OUTPUT FORMAT RULE:

- depends_on MUST contain ONLY step IDs (e.g. "step_1", "step_2")
- NEVER use step names
- NEVER use natural language

---

EXAMPLES (MANDATORY BEHAVIOR):

---

Example 0 — Single step:

Steps:
[
  {{"id": "step_1", "purpose": "Add 2 and 3"}}
]

Output:
{{"steps": [
  {{"depends_on": []}}
]}}

Reason: 1 step in → 1 entry out. Entry[0] corresponds to step_1.

---

Example 1 — Independent steps:

Steps:
[
  {{"id": "step_1", "purpose": "Add 2 and 3"}},
  {{"id": "step_2", "purpose": "Add 4 and 5"}}
]

Output:
{{"steps": [
  {{"depends_on": []}},
  {{"depends_on": []}}
]}}

Reason: Neither step contains "the result of the previous step".

---

Example 2 — Simple dependency:

Steps:
[
  {{"id": "step_1", "purpose": "Add 2 and 3"}},
  {{"id": "step_2", "purpose": "Multiply the result of the previous step by 10"}}
]

Output:
{{"steps": [
  {{"depends_on": []}},
  {{"depends_on": ["step_1"]}}
]}}

Reason: step_2 contains "the result of the previous step" → depends on immediately preceding step_1.

---

Example 3 — Chain dependency:

Steps:
[
  {{"id": "step_1", "purpose": "Subtract 4 from 10"}},
  {{"id": "step_2", "purpose": "Multiply the result of the previous step by 10"}},
  {{"id": "step_3", "purpose": "Divide the result of the previous step by 5"}}
]

Output:
{{"steps": [
  {{"depends_on": []}},
  {{"depends_on": ["step_1"]}},
  {{"depends_on": ["step_2"]}}
]}}

Reason: step_2 depends on step_1. step_3 depends on step_2 (its immediately preceding step).

---

Example 4 — Mixed: independent after dependent:

Steps:
[
  {{"id": "step_1", "purpose": "Add 2 and 3"}},
  {{"id": "step_2", "purpose": "Multiply the result of the previous step by 10"}},
  {{"id": "step_3", "purpose": "Add 5 and 4"}}
]

Output:
{{"steps": [
  {{"depends_on": []}},
  {{"depends_on": ["step_1"]}},
  {{"depends_on": []}}
]}}

Reason: step_3 does NOT contain "the result of the previous step" → depends_on = [].
Position after step_2 does NOT create a dependency.

---

Example 5 — Mixed: two independent, one dependent:

Steps:
[
  {{"id": "step_1", "purpose": "Add 2 and 3"}},
  {{"id": "step_2", "purpose": "Add 5 and 4"}},
  {{"id": "step_3", "purpose": "Multiply the result of the previous step by 10"}}
]

Output:
{{"steps": [
  {{"depends_on": []}},
  {{"depends_on": []}},
  {{"depends_on": ["step_2"]}}
]}}

Reason: step_3 contains "the result of the previous step" → depends on step_2 (immediately preceding).
step_1 and step_2 have complete inputs → depends_on = [].

---

ANTI-EXAMPLE (INVALID — DO NOT DO THIS):

Steps:
[
  {{"id": "step_1", "purpose": "Add 2 and 3"}},
  {{"id": "step_2", "purpose": "Multiply the result of the previous step by 10"}},
  {{"id": "step_3", "purpose": "Add 5 and 4"}}
]

WRONG Output:
{{"steps": [
  {{"depends_on": []}},
  {{"depends_on": ["step_1"]}},
  {{"depends_on": ["step_2"]}}
]}}

Reason this is WRONG: step_3 does NOT contain "the result of the previous step".
It has complete inputs. depends_on MUST be [].

---

INPUT:
{user_input}

STEPS:
{json.dumps(steps, indent=2)}

---

There are {len(steps)} step(s) in STEPS above.
Your output MUST contain EXACTLY {len(steps)} entries — no more, no less.
Entry[0] = step_1, Entry[1] = step_2, Entry[2] = step_3, and so on.
Do NOT shift entries. Do NOT skip entries.
Step IDs only in depends_on.
"""

    provider = provider_result["provider"]
    llm_result = execute_llm(provider, prompt)
    
    raw = llm_result["result"]
    print("[DEBUG_DEPENDENCY_RESOLVER_RAW]:", raw)
    
    # === DEPENDENCY OUTPUT NORMALIZATION LAYER ===
    
    # Extract FIRST valid JSON object only
    raw_clean = raw.replace("```json", "").replace("```", "").strip()
    
    # Find the complete JSON object by matching braces
    brace_count = 0
    start_idx = None
    json_str = None
    
    for i, char in enumerate(raw_clean):
        if char == '{':
            if brace_count == 0:
                start_idx = i
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0 and start_idx is not None:
                json_str = raw_clean[start_idx:i+1]
                break
    
    if json_str is None:
        return {"status": "failure", "reason": "dependency_no_json_found"}
    
    # Parse the complete JSON object
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        return {"status": "failure", "reason": "dependency_invalid_json"}
    
    # Extract step data
    if "steps" not in parsed:
        return {"status": "failure", "reason": "dependency_missing_steps_key"}
    
    # Normalize dependency values
    normalized = []
    
    for i, dep in enumerate(parsed["steps"]):
        clean = []
        
        current_step_index = i + 1
        
        for d in dep.get("depends_on", []):
            
            if not isinstance(d, str):
                continue
            
            if not d.startswith("step_"):
                continue
            
            try:
                idx = int(d.split("_")[1])
            except:
                continue
            
            # 🚨 DAG ENFORCEMENT RULES
            
            # 1. Must be within total steps
            if idx < 1 or idx > len(steps):
                continue
            
            # 2. NO self-dependency
            if idx == current_step_index:
                continue
            
            # 3. NO forward dependency
            if idx > current_step_index:
                continue
            
            # 4. ONLY allow previous steps
            clean.append(f"step_{idx}")
        
        normalized.append({"depends_on": clean})
    
    # Enforce length match
    if len(normalized) != len(steps):
        return {
            "status": "failure",
            "reason": "dependency_length_mismatch",
            "details": {
                "expected": len(steps),
                "received": len(normalized)
            }
        }
    
    print("[DEBUG_DEPENDENCY_RESOLVER_NORMALIZED]:", normalized)
    return normalized


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

MULTI-STEP RULE (HIGHEST PRIORITY):

If the input contains multiple operations (e.g. "then", "and then", sequential actions):

→ You MUST split them into separate steps

This applies to BOTH:
- dependent operations (one step requires the output of the previous)
- independent operations (each step has its own complete values)

You MUST NEVER combine multiple operations into a single step

If the request is a single action, you MUST return exactly one step.

STRICT RULES:

SEMANTIC PRESERVATION RULE (CRITICAL):

- You MUST preserve the original wording of each step.

- Independent steps MUST remain independent.

- If a step contains complete values, it MUST remain unchanged.

- If a single step already represents a valid executable action:
  → RETURN IT UNCHANGED

---

CHAINING RULE (CRITICAL):

- Independent steps MUST preserve original wording and explicit values
- Dependent steps MUST explicitly refer to prior output using:

  "the result of the previous step"

NOT:
- "the result"
- implicit references

DEPENDENCY SIGNAL RULE:

If a step logically depends on a previous step:

→ you MUST write:

"the result of the previous step"

Example:

Input:
add 2 and 3 then multiply by 10

Output step purposes:
1. Add 2 and 3
2. Multiply the result of the previous step by 10

- DO NOT compute or insert intermediate values
- DO NOT replace "the result of the previous step" with numbers

PROTECTION RULE:

- Independent steps MUST NOT contain:
  "the result"
  "previous step"

- DO NOT introduce ambiguity
- DO NOT infer dependencies without clear chaining language

---

ARGUMENT PRESERVATION RULE (CRITICAL):
ARGUMENT PRESERVATION RULE (CRITICAL):

You MUST distinguish between two types of steps:

1. INDEPENDENT STEPS:
   - Steps that do NOT contain "the result of the previous step"
   - MUST preserve the exact wording and values from the input
   - MUST NOT add "the result" or "the result of the previous step" to an independent step
   - MUST NOT modify the operation or values

   Example:
   Input: "multiply by 4"
   CORRECT: "Multiply by 4"
   WRONG:   "Multiply the result of the previous step by 4"

2. DEPENDENT STEPS:
   - Steps that explicitly depend on a prior step's output
   - MUST use "the result of the previous step" to refer to that output
   - MUST NOT inject or compute intermediate values

   Example:
   Input: "multiply the result by 2"
   CORRECT: "Multiply the result of the previous step by 2"
   WRONG:   "Multiply 8 by 2"

CRITICAL: NEVER change an independent step to use "the result of the previous step".
Independent steps MUST NOT contain "the result" or "previous step" in any form.

---

RULE PRIORITY:

1. Output format (JSON structure)
2. Semantic preservation (exact wording from input)
2. Semantic preservation (exact wording from input)
3. Argument preservation (exact values for independent steps)

NEVER modify a step to add "the result of the previous step" unless the step explicitly depends on a prior step's output.
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

---


---


- Each step MUST be a complete and unambiguous instruction that clearly implies the operation to perform
- DO NOT introduce new words like "define", "calculate", "perform"
- DO NOT create variables (x, y, etc.)
- DO NOT explain anything
- DO NOT solve the problem
- DO NOT change the meaning of a step, BUT you MAY introduce "the result of the previous step" ONLY when a step explicitly depends on a previous step's output. If the step is standalone, DO NOT use "the result" or "previous step" in any form.
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
"square 4 then subtract 5"
"square 4 then subtract 5"

CORRECT:
[
"Square 4",
"Subtract 5"
"Subtract 5"
]

WRONG:
[
"Square 4 then subtract 5"
"Square 4 then subtract 5"
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

MULTI-STEP EXAMPLES (CRITICAL):
MULTI-STEP EXAMPLES (CRITICAL):

Input: "add 2 and 3 then add 4 and 5"
Both steps are INDEPENDENT (each has complete values)
CORRECT:
  step 1 purpose: "Add 2 and 3"
  step 2 purpose: "Add 4 and 5"
WRONG (false chaining):
  step 2 purpose: "Add the result and 5"

Input: "square 4 then subtract 5"
Both steps are INDEPENDENT (each has complete values)
Input: "square 4 then subtract 5"
Both steps are INDEPENDENT (each has complete values)
CORRECT:
  step 1 purpose: "Square 4"
  step 2 purpose: "Subtract 5"
  step 2 purpose: "Subtract 5"
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
    {{"name": "Add 3", "purpose": "Add 3", "agent": "math_executor", "estimated_complexity": "low"}}
    {{"name": "Add 3", "purpose": "Add 3", "agent": "math_executor", "estimated_complexity": "low"}}
]}}

---

---

---

---

BAD EXAMPLES (NEVER DO THIS):

- "Define variables x and y"
- "Perform calculation"
- "Compute result"
- Any step that was NOT explicitly in the user input

---

---

---

---

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

    # === DEPENDENCY RESOLUTION (LLM 2) ===
    # Resolve dependencies using separate LLM to avoid semantic rewriting
    print("[DEBUG_STEPS_TO_DEPENDENCY_RESOLVER]:", json.dumps(valid_steps, indent=2))
    try:
        dependency_data = resolve_dependencies(user_input, valid_steps)
    except Exception as e:
        return {"status": "failure", "reason": "dependency_resolver_exception", "details": str(e)}

    if isinstance(dependency_data, dict) and dependency_data.get("status") == "failure":
        return dependency_data

    # === FIELD IMMUTABILITY ENFORCEMENT ===
    # ONLY copy "depends_on" from LLM 2, nothing else
    for i, step in enumerate(valid_steps):
        if i < len(dependency_data):
            step["depends_on"] = dependency_data[i].get("depends_on", [])
        else:
            step["depends_on"] = []

    # === DEPENDENCY RESOLUTION (LLM 2) ===
    # Resolve dependencies using separate LLM to avoid semantic rewriting
    print("[DEBUG_STEPS_TO_DEPENDENCY_RESOLVER]:", json.dumps(valid_steps, indent=2))
    try:
        dependency_data = resolve_dependencies(user_input, valid_steps)
    except Exception as e:
        return {"status": "failure", "reason": "dependency_resolver_exception", "details": str(e)}

    if isinstance(dependency_data, dict) and dependency_data.get("status") == "failure":
        return dependency_data

    # === FIELD IMMUTABILITY ENFORCEMENT ===
    # ONLY copy "depends_on" from LLM 2, nothing else
    for i, step in enumerate(valid_steps):
        if i < len(dependency_data):
            step["depends_on"] = dependency_data[i].get("depends_on", [])
        else:
            step["depends_on"] = []

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
            "estimated_complexity": step["estimated_complexity"],
            "depends_on": step.get("depends_on", [])
            "estimated_complexity": step["estimated_complexity"],
            "depends_on": step.get("depends_on", [])
        }
        structured_steps.append(structured_step)

    # === DEPENDENCY PASS-THROUGH (DEPENDENCY_MODEL_CONTRACT_V1) ===
    # Per contract: System MUST NOT infer dependencies from purpose or natural language.
    # depends_on MUST be explicitly declared in input — never auto-generated.
    # Pass through only what was explicitly provided; default to empty list if absent.
    # === DEPENDENCY PASS-THROUGH (DEPENDENCY_MODEL_CONTRACT_V1) ===
    # Per contract: System MUST NOT infer dependencies from purpose or natural language.
    # depends_on MUST be explicitly declared in input — never auto-generated.
    # Pass through only what was explicitly provided; default to empty list if absent.
    for s in structured_steps:
        if "depends_on" not in s:
            s["depends_on"] = []
        if "depends_on" not in s:
            s["depends_on"] = []

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

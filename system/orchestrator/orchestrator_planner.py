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


def _create_step(step_num: int, name: str, purpose: str, agent: str, complexity: str) -> Dict[str, Any]:
    """Create a single step definition."""
    return {
        "id": f"step_{step_num}",
        "name": name,
        "purpose": purpose,
        "agent": agent,
        "estimated_complexity": complexity
    }


def create_workflow(user_input: str) -> Dict[str, Any]:
    """
    Create a workflow plan based on user input.
    
    PURE FUNCTION — NO side effects, NO execution, NO system calls.
    
    Defines WHAT needs to be done, NOT how to do it.
    Steps do NOT include tool calls, arguments, or execution logic.
    
    Args:
        user_input: Raw user input string describing the goal
        
    Returns:
        dict: {
            "status": "success",
            "workflow": {
                "id": str,
                "goal": str,
                "steps": [...],
                "approval_required": bool
            }
        }
    """
    # Validate input
    if not user_input or not isinstance(user_input, str):
        return {
            "status": "failure",
            "reason": "invalid_input",
            "workflow": None
        }
    
    # Get classification (advisory only)
    classification_result = classify_task(user_input)
    classification = classification_result.get("classification", "simple")
    
    # Generate workflow
    workflow_id = _generate_workflow_id()
    goal = _normalize_input(user_input)
    
    steps: List[Dict[str, Any]] = []
    approval_required = False
    
    # ===== DETERMINISTIC PLANNING =====
    
    if classification == "simple":
        # Simple tasks: ONE step
        steps.append(_create_step(
            step_num=1,
            name="execute_task",
            purpose="Execute the user request",
            agent="general_agent",
            complexity="low"
        ))
        approval_required = classification_result.get("approval_required", False)
        
    elif classification == "complex":
        # Complex tasks: 2-3 steps
        steps.append(_create_step(
            step_num=1,
            name="analyze_task",
            purpose="Analyze requirements and approach",
            agent="analyzer_agent",
            complexity="medium"
        ))
        steps.append(_create_step(
            step_num=2,
            name="execute_task",
            purpose="Execute the user request",
            agent="general_agent",
            complexity="medium"
        ))
        steps.append(_create_step(
            step_num=3,
            name="validate_result",
            purpose="Verify output meets requirements",
            agent="validator_agent",
            complexity="low"
        ))
        approval_required = classification_result.get("approval_required", True)
        
    elif classification == "critical":
        # Critical tasks: Same as complex, BUT always require approval
        steps.append(_create_step(
            step_num=1,
            name="analyze_task",
            purpose="Analyze requirements and approach with safety check",
            agent="analyzer_agent",
            complexity="high"
        ))
        steps.append(_create_step(
            step_num=2,
            name="execute_task",
            purpose="Execute the user request with monitoring",
            agent="general_agent",
            complexity="high"
        ))
        steps.append(_create_step(
            step_num=3,
            name="validate_result",
            purpose="Verify output and check for side effects",
            agent="validator_agent",
            complexity="medium"
        ))
        # Critical ALWAYS requires approval, regardless of classifier
        approval_required = True
        
    else:
        # Unknown classification — default to simple
        steps.append(_create_step(
            step_num=1,
            name="execute_task",
            purpose="Execute the user request",
            agent="general_agent",
            complexity="low"
        ))
        approval_required = True  # Safe default
    
    return {
        "status": "success",
        "workflow": {
            "id": workflow_id,
            "goal": goal,
            "steps": steps,
            "approval_required": approval_required
        }
    }


def plan_workflow(user_input: str) -> dict:
    if DEBUG_VERBOSE:
        print("[DEBUG_PLAN_WORKFLOW_INPUT_RAW]:", user_input)

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

If the input is already a valid single-step instruction, return it unchanged.

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

CRITICAL RULE (HIGHEST PRIORITY):

- If the user request is a single coherent task:
  → RETURN EXACTLY ONE STEP
  → DO NOT split it under any circumstances

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

GOOD EXAMPLES:

Input: "add 10 and 20"
Output:
{{"steps": ["add 10 and 20"]}}

Input: "add 2 and 3 then add 4 and 5"
Output:
{{"steps": ["add 2 and 3", "add 4 and 5"]}}

Input: "what is addition and add 3 and 4"
Output:
{{"steps": ["what is addition", "add 3 and 4"]}}

Input: "Take 5, double it, then add 3"
Output:
{{"steps": [
    "multiply 5 by 2",
    "add 3 to the result"
]}}

BAD:
{{"steps": ["write a story", "that ends with the end"]}}

GOOD:
{{"steps": ["write a story that ends with the end"]}}

BAD EXAMPLES (NEVER DO THIS):

- "Define variables x and y"
- "Perform calculation"
- "Compute result"
- Any step that was NOT explicitly in the user input

OUTPUT (STRICT):

Return EXACTLY:

{{"steps": ["step 1", "step 2"]}}

NO OTHER TEXT IS ALLOWED.

CRITICAL OUTPUT RULE:

- You MUST return ONLY valid JSON
- DO NOT include explanations
- DO NOT include markdown (no ``` blocks)
- DO NOT include text before or after JSON
- Your response MUST start with '{' and end with '}'

User input:
{user_input}
"""

    llm_output = None
    if DEBUG_VERBOSE:
        print("[DEBUG_PLANNER_FINAL_INPUT_TO_LLM]:", user_input)

    try:
        if provider_result.get("status") == "success":
            provider = provider_result["provider"]
            llm_result = execute_llm(provider, prompt)
            if llm_result.get("status") == "success":
                response = llm_result.get("result", "")
                llm_output = response
                if DEBUG_VERBOSE:
                    print("[DEBUG_PLANNER_RAW_OUTPUT]:", llm_output)
                # FIX 4: Safe JSON extraction — strip prefix text and markdown
                raw = response.strip()
                if raw.startswith("```"):
                    raw = raw.strip("`").strip()
                    if raw.startswith("json"):
                        raw = raw[4:].strip()
                if "{" in raw:
                    raw = raw[raw.index("{"):]
                    # Trim trailing text after last }
                    last_brace = raw.rfind("}")
                    if last_brace != -1:
                        raw = raw[:last_brace + 1]
                parsed = json.loads(raw)

                # STRICT VALIDATION: Reject invalid planner output
                if not isinstance(parsed, dict):
                    return {"status": "failure", "reason": "planner_invalid_format"}

                steps = parsed.get("steps")

                if not isinstance(steps, list) or not all(isinstance(s, str) for s in steps):
                    return {"status": "failure", "reason": "planner_invalid_steps"}

                if not steps:
                    return {"status": "failure", "reason": "planner_empty_steps"}
            else:
                return {"status": "failure", "reason": "planner_parse_failure"}
        else:
            return {"status": "failure", "reason": "planner_parse_failure"}
    except Exception as e:
        if DEBUG_VERBOSE:
            print("[DEBUG_PLANNER_PARSE_FAILURE]:", llm_output if llm_output else "None")
            print("[DEBUG_PLAN_WORKFLOW_PARSE_ERROR]:", str(e))
        return {"status": "failure", "reason": "planner_parse_failure"}

    steps = [s.strip() for s in steps if isinstance(s, str) and s.strip()]

    if not steps:
        return {"status": "failure", "reason": "planner_empty_steps"}

    structured_steps = [
        {
            "id": f"step_{i + 1}",
            "name": f"step_{i + 1}",
            "purpose": step,
            "agent": "general_agent",
            "estimated_complexity": "low"
        }
        for i, step in enumerate(steps)
    ]

    workflow = {
        "id": "workflow_1",
        "name": "dynamic_workflow",
        "goal": user_input,
        "steps": structured_steps,
        "approval_required": False
    }

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
        result = create_workflow(test_input)
        print(f"\nInput: \"{test_input}\"")
        print(f"Output: {json.dumps(result, indent=2)}")
    
    print("\n" + "=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)

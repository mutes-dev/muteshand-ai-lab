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
    import json

    # DEBUG_TEMP_START
    print("[DEBUG_PLAN_WORKFLOW_INPUT_RAW]:", user_input)
    # DEBUG_TEMP_END

    # Reuse existing LLM client (same pattern as agent_executor)
    provider_result = get_llm("ollama_llm")

    prompt = f"""
You are a workflow planner.

Your job is to determine whether the user request should be split into steps.
ONLY split the request IF it contains multiple independent actions.
If the request is a single action, you MUST return exactly one step.

STRICT RULES:

CRITICAL RULE (HIGHEST PRIORITY):

- If the user request is a single coherent task:
  → RETURN EXACTLY ONE STEP
  → DO NOT split it under any circumstances

- Each step must be a DIRECT substring or slight rephrase of the original request
- DO NOT introduce new words like "define", "calculate", "perform"
- DO NOT create variables (x, y, etc.)
- DO NOT explain anything
- DO NOT solve the problem
- DO NOT transform the task
- DO NOT break a simple task into multiple steps
- Each step MUST be a COMPLETE and executable instruction
- A step MUST make sense on its own
- A step MUST NOT be a fragment, continuation, or modifier of another step
- A step MUST NOT rely on another step to be understood

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
    # DEBUG_TEMP_START
    print("[DEBUG_PLANNER_LLM_FULL_PROMPT]:", prompt)
    print("[DEBUG_PLANNER_FINAL_INPUT_TO_LLM]:", user_input)
    # DEBUG_TEMP_END

    try:
        if provider_result.get("status") == "success":
            provider = provider_result["provider"]
            llm_result = execute_llm(provider, prompt)
            if llm_result.get("status") == "success":
                response = llm_result.get("result", "")
                llm_output = response
                # DEBUG_TEMP_START
                print("[DEBUG_PLANNER_RAW_OUTPUT]:", llm_output)
                # DEBUG_TEMP_END
                parsed = json.loads(response)
                steps = parsed.get("steps", [user_input])
            else:
                steps = [user_input]
        else:
            steps = [user_input]
    except Exception as e:
        # DEBUG_TEMP_START
        print("[DEBUG_PLANNER_PARSE_FAILURE]:", llm_output if llm_output else "None")
        print("[DEBUG_PLAN_WORKFLOW_PARSE_ERROR]:", str(e))
        # DEBUG_TEMP_END
        steps = [user_input]

    steps = [s.strip() for s in steps if isinstance(s, str) and s.strip()]

    if not steps:
        steps = [user_input]

    return {
        "type": "sequential",
        "steps": steps
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

"""
Plan Validation Module

PURPOSE:
    Validates execution plans before they are executed by the manager.
    Ensures plans are structurally sound, use valid tools, and have correct arguments.

ARCHITECTURE ROLE:
    - Quality gate layer: Prevents invalid plans from reaching execution
    - Stateless: Pure validation functions with no side effects
    - Enforces contracts between planner and executor

LAYER RESPONSIBILITY:
    - Schema validation: Check plan structure and required fields
    - Tool validation: Verify tools/agents exist in registry
    - Argument validation: Match argument count to tool expectations
    - Chaining validation: Enforce PREVIOUS_RESULT usage rules

USAGE:
    plan = [{"type": "tool", "name": "add_numbers", "args": [2, 3], "input_text": "2 and 3"}]
    is_valid, error = validate_plan(plan, tool_index)
    # Returns: (True, None) for valid plans, (False, "error message") for invalid

VALIDATION ORDER:
    1. Schema (structure) -> 2. Tools (existence) -> 3. Args (count) -> 4. Chaining (dependencies)
"""


def _validate_schema(plan):
    """
    Validate plan schema structure.
    
    Validates that the plan conforms to the required structure:
    - Plan must be a list of steps
    - Each step must be a dictionary with required keys
    - Step type must be 'tool' or 'agent'
    - All fields must have correct types
    
    SCHEMA REQUIREMENTS:
        Required step keys: {"type", "name", "args", "input_text"}
        - type (str): Either "tool" or "agent"
        - name (str): Tool or agent name
        - args (list): Arguments for the step (may be empty)
        - input_text (str): Original input text for reference
    
    VALIDATION RULES:
        1. Plan must be a list (not dict, not None)
        2. Each step must be a dict (not list, not string)
        3. All required keys must be present
        4. type must be "tool" or "agent"
        5. name must be a string
        6. args must be a list
        7. input_text must be a string
    
    Args:
        plan: Plan to validate (expected to be a list of dicts)

    Returns:
        (bool, str | None): (is_valid, error_message)
        - is_valid: True if plan passes all schema checks
        - error_message: Description of first validation failure, or None if valid
    """
    if not isinstance(plan, list):
        return False, "Plan must be a list"
    
    required_keys = {"type", "name", "args", "input_text"}
    
    for idx, step in enumerate(plan):
        if not isinstance(step, dict):
            return False, f"Step {idx} must be a dict"
        
        missing_keys = required_keys - set(step.keys())
        if missing_keys:
            missing_key = sorted(missing_keys)[0]
            return False, f"Step {idx} missing '{missing_key}'"
        
        if step["type"] not in ["tool", "agent"]:
            return False, f"Step {idx} type must be 'tool' or 'agent'"
        
        if not isinstance(step["name"], str):
            return False, f"Step {idx} name must be a string"
        
        if not isinstance(step["args"], list):
            return False, f"Step {idx} args must be a list"
        
        if not isinstance(step["input_text"], str):
            return False, f"Step {idx} input_text must be a string"
    
    return True, None


def _validate_tools(plan, tool_index):
    """
    Validate tool/agent existence in tool_index or AGENTS registry.
    
    Checks that every tool referenced in the plan exists in the tool_index.
    Agent existence is not validated here (checked at execution time to avoid
    circular import issues with manager.py).
    
    TOOL VALIDATION:
        - Tool name must exist as key in tool_index dict
        - Tool index contains metadata: description, inputs, tags
    
    AGENT VALIDATION:
        - Deferred to execution time (design decision)
        - Allows dynamic agent loading without circular dependencies
    
    Args:
        plan (list): Execution plan with steps to validate
        tool_index (dict): Tool definitions registry (name -> metadata)

    Returns:
        (bool, str | None): (is_valid, error_message)
        - is_valid: True if all tools exist
        - error_message: Step index and unknown tool name if invalid
    """
    for idx, step in enumerate(plan):
        name = step["name"]
        step_type = step["type"]
        
        if step_type == "tool":
            if name not in tool_index:
                return False, f"Step {idx} unknown tool '{name}'"
        elif step_type == "agent":
            # For agent validation, we'll accept any agent name
            # The actual existence check will happen at execution time
            # This avoids circular import issues
            pass
    
    return True, None


def _validate_args(plan, tool_index):
    """
    Validate argument count matches tool definition (tools only).
    
    Compares the number of arguments provided in each step against the
    expected argument count defined in the tool's INPUT_SPEC.
    
    ARGUMENT COUNT RULES:
        - Only validates tool steps (agent steps skip this validation)
        - Expected args = len(tool_index[name]["inputs"])
        - Must have exactly expected number of args (no more, no less)
        - Empty inputs dict means 0 expected args
    
    ARCHITECTURAL NOTES:
        - This validates structure, not content (args may be PREVIOUS_RESULT tokens)
        - Content validation happens during execution via chain_resolver
        - Strict count enforcement prevents partial/invalid executions
    
    Args:
        plan (list): Execution plan with steps to validate
        tool_index (dict): Tool definitions containing input specifications

    Returns:
        (bool, str | None): (is_valid, error_message)
        - is_valid: True if all tool steps have correct arg counts
        - error_message: Step index with expected vs actual arg counts
    """
    for idx, step in enumerate(plan):
        name = step["name"]
        args = step["args"]
        step_type = step["type"]
        
        # Only validate argument count for tools, not agents
        if step_type == "tool":
            expected_args = len(tool_index[name].get("inputs", {}))

            if len(args) != expected_args:
                return False, f"Step {idx} expected {expected_args} args but got {len(args)}"
    
    return True, None


def _validate_chaining(plan):
    """
    Validate PREVIOUS_RESULT usage and chaining rules.
    
    Enforces linear chaining constraints:
    - First step cannot use PREVIOUS_RESULT (no prior result exists)
    - Only one PREVIOUS_RESULT per step (single dependency)
    - No multi-branch dependencies (complex chains not supported)
    
    CHAINING RULES:
        Rule 1: First step (index 0) cannot reference PREVIOUS_RESULT
                - There's no previous step to reference
                
        Rule 2: Only one PREVIOUS_RESULT token allowed per step
                - Enforces linear chains (step N depends only on N-1)
                - Prevents multi-branch dependencies
                
        Rule 3: No multiple "result of" references in args
                - Additional guard against complex dependency patterns
    
    Args:
        plan (list): Execution plan to validate

    Returns:
        (bool, str | None): (is_valid, error_message)
        - is_valid: True if chaining rules are satisfied
        - error_message: Description of chaining violation
    """
    for idx, step in enumerate(plan):
        # Count PREVIOUS_RESULT occurrences in args
        count = step["args"].count("PREVIOUS_RESULT")
        
        # Rule 1: No PREVIOUS_RESULT in first step
        if idx == 0 and count > 0:
            return False, "Step 0 cannot use PREVIOUS_RESULT"
        
        # Rule 3: Only one PREVIOUS_RESULT per step
        if count > 1:
            return False, "Only one PREVIOUS_RESULT allowed per step"
        
        # Rule 4: Block multi-branch dependencies
        arg_str = str(step["args"])
        if arg_str.count("result of") > 1:
            return False, "Multiple result references not allowed"
    
    return True, None


def validate_plan(plan, tool_index):
    """
    Central validation entry point - orchestrates all validation checks.
    
    Runs the complete validation pipeline in order:
    1. Schema validation (structure correctness)
    2. Tool validation (existence in registry)
    3. Argument validation (count matching)
    4. Chaining validation (dependency rules)
    
    VALIDATION PIPELINE:
        Each stage must pass before next stage runs.
        First failure returns immediately with error message.
        
    ARCHITECTURAL ROLE:
        - Quality gate before execution
        - Called by manager after planning, before execution
        - Prevents invalid plans from reaching executor
    
    Args:
        plan (list): Execution plan to validate
        tool_index (dict): Tool definitions registry

    Returns:
        (bool, str | None): (is_valid, error_message)
        - is_valid: True if plan passes ALL validation stages
        - error_message: First validation failure encountered, or None if valid
        
    USAGE:
        is_valid, error = validate_plan(structured_plan, tool_index)
        if not is_valid:
            print(f"Validation failed: {error}")
            # Trigger replan or report failure
    """
    is_valid, error = _validate_schema(plan)
    if not is_valid:
        return False, error
    
    is_valid, error = _validate_tools(plan, tool_index)
    if not is_valid:
        return False, error
    
    is_valid, error = _validate_args(plan, tool_index)
    if not is_valid:
        return False, error
    
    is_valid, error = _validate_chaining(plan)
    if not is_valid:
        return False, error
    
    return True, None

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
        (bool, dict | None): (is_valid, error_dict)
        - is_valid: True if plan passes all schema checks
        - error_dict: Contains error, type, message keys if invalid, or None if valid
    """
    if not isinstance(plan, list):
        return False, {
            "error": "VALIDATION_ERROR",
            "type": "INVALID_PLAN_TYPE",
            "message": "Plan must be a list"
        }
    
    required_keys = {"type", "name", "args", "input_text"}
    
    for idx, step in enumerate(plan):
        if not isinstance(step, dict):
            return False, {
                "error": "VALIDATION_ERROR",
                "type": "INVALID_STEP_TYPE",
                "message": f"Step {idx} must be a dict"
            }
        
        missing_keys = required_keys - set(step.keys())
        if missing_keys:
            missing_key = sorted(missing_keys)[0]
            return False, {
                "error": "VALIDATION_ERROR",
                "type": "MISSING_REQUIRED_KEY",
                "message": f"Step {idx} missing '{missing_key}'"
            }
        
        if step["type"] not in ["tool", "agent"]:
            return False, {
                "error": "VALIDATION_ERROR",
                "type": "INVALID_STEP_TYPE",
                "message": f"Step {idx} type must be 'tool' or 'agent'"
            }
        
        if not isinstance(step["name"], str):
            return False, {
                "error": "VALIDATION_ERROR",
                "type": "INVALID_NAME_TYPE",
                "message": f"Step {idx} name must be a string"
            }
        
        if not isinstance(step["args"], list):
            return False, {
                "error": "VALIDATION_ERROR",
                "type": "INVALID_ARGS_TYPE",
                "message": f"Step {idx} args must be a list"
            }
        
        if not isinstance(step["input_text"], str):
            return False, {
                "error": "VALIDATION_ERROR",
                "type": "INVALID_INPUT_TEXT_TYPE",
                "message": f"Step {idx} input_text must be a string"
            }
    
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
        (bool, dict | None): (is_valid, error_dict)
        - is_valid: True if all tools exist
        - error_dict: Contains error, type, message keys if invalid, or None if valid
    """
    for idx, step in enumerate(plan):
        name = step["name"]
        step_type = step["type"]
        
        if step_type == "tool":
            if name not in tool_index:
                return False, {
                    "error": "VALIDATION_ERROR",
                    "type": "UNKNOWN_TOOL",
                    "message": f"Step {idx} unknown tool '{name}'"
                }
        elif step_type == "agent":
            # For agent validation, we'll accept any agent name
            # The actual existence check will happen at execution time
            # This avoids circular import issues
            pass
    
    return True, None


def _validate_args(plan, tool_index):
    """
    Validate argument count and types against tool contract (tools only).
    
    Enforces strict metadata-driven validation using tools.json as single source of truth:
    - Tool existence check
    - Argument count matching (required inputs only)
    - Argument type validation
    
    VALIDATION RULES:
        - Only validates tool steps (agent steps skip this validation)
        - Expected inputs = tool_index[name]["inputs"] (structured format)
        - Required inputs only: v["required"] is True
        - Strict count matching (no optional args)
        - Type mapping: int/float→number, str→string, bool→boolean, dict→object, list→array
        - Structural validation only (no argument modification)
    
    Args:
        plan (list): Execution plan with steps to validate
        tool_index (dict): Tool definitions containing input specifications

    Returns:
        (bool, dict | None): (is_valid, error_dict)
        - is_valid: True if all tool steps have correct args and types
        - error_dict: Contains error, type, message keys if invalid, or None if valid
    """
    for idx, step in enumerate(plan):
        name = step["name"]
        args = step.get("args")
        step_type = step["type"]
        
        # Only validate argument count for tools, not agents
        if step_type == "tool":
            # TOOL EXISTENCE CHECK - must run FIRST
            if name not in tool_index:
                return False, {
                    "error": "VALIDATION_ERROR",
                    "type": "UNKNOWN_TOOL",
                    "message": f"Tool '{name}' not found"
                }
            
            # Ensure args is a list
            if not isinstance(args, list):
                return False, {
                    "error": "VALIDATION_ERROR",
                    "type": "INVALID_ARGS_TYPE",
                    "message": f"Step {idx} args must be a list"
                }
            
            # Get tool metadata as single source of truth
            expected_inputs = tool_index[name].get("inputs", {})
            
            # VALIDATE ARGUMENT COUNT (REQUIRED ONLY)
            required_inputs = [
                param_name for param_name, param_spec in expected_inputs.items()
                if param_spec.get("required") is True
            ]
            
            if len(args) != len(required_inputs):
                return False, {
                    "error": "VALIDATION_ERROR",
                    "type": "ARG_COUNT_MISMATCH",
                    "message": f"Tool '{name}' expects {len(required_inputs)} arguments, got {len(args)}"
                }
            
            # VALIDATE ARGUMENT TYPES (MANDATORY)
            for arg_idx, arg_value in enumerate(args):
                param_name = required_inputs[arg_idx]
                param_spec = expected_inputs[param_name]
                expected_type = param_spec.get("type")
                
                # Skip runtime placeholder
                if arg_value == "PREVIOUS_RESULT":
                    continue
                
                # Map Python types to contract types
                actual_type = type(arg_value).__name__
                mapped_type = None
                
                if actual_type in ["int", "float"]:
                    mapped_type = "number"
                elif actual_type == "str":
                    mapped_type = "string"
                elif actual_type == "bool":
                    mapped_type = "boolean"
                elif actual_type == "dict":
                    mapped_type = "object"
                elif actual_type == "list":
                    mapped_type = "array"
                else:
                    mapped_type = actual_type.lower()
                
                # Compare STRICTLY
                if mapped_type != expected_type:
                    return False, {
                        "error": "VALIDATION_ERROR",
                        "type": "INVALID_TYPE",
                        "message": f"Expected '{expected_type}', got '{mapped_type}'"
                    }
    
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
        (bool, dict | None): (is_valid, error_dict)
        - is_valid: True if chaining rules are satisfied
        - error_dict: Contains error, type, message keys if invalid, or None if valid
    """
    for idx, step in enumerate(plan):
        # Count PREVIOUS_RESULT occurrences in args
        count = step["args"].count("PREVIOUS_RESULT")
        
        # Rule 1: No PREVIOUS_RESULT in first step
        if idx == 0 and count > 0:
            return False, {
                "error": "VALIDATION_ERROR",
                "type": "INVALID_CHAINING",
                "message": "Step 0 cannot use PREVIOUS_RESULT"
            }
        
        # Rule 3: Only one PREVIOUS_RESULT per step
        if count > 1:
            return False, {
                "error": "VALIDATION_ERROR",
                "type": "INVALID_CHAINING",
                "message": "Only one PREVIOUS_RESULT allowed per step"
            }
        
        # Rule 4: Block multi-branch dependencies
        arg_str = str(step["args"])
        if arg_str.count("result of") > 1:
            return False, {
                "error": "VALIDATION_ERROR",
                "type": "INVALID_CHAINING",
                "message": "Multiple result references not allowed"
            }
    
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
        (bool, dict | None): (is_valid, error_dict)
        - is_valid: True if plan passes ALL validation stages
        - error_dict: Contains error, type, message keys if invalid, or None if valid
        
    USAGE:
        is_valid, error = validate_plan(structured_plan, tool_index)
        if not is_valid:
            print(f"Validation failed: {error['message']}")
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

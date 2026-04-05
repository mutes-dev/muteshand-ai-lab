"""
Validation Layer (System)

PURPOSE:
    Fail-fast structural validation between Argument Resolver and Execution.

ARCHITECTURE ROLE:
    - Quality gate layer: Prevents invalid plans from reaching execution
    - Stateless: Pure validation functions with no side effects

RULES:
    - MUST be deterministic
    - MUST fail-fast (return on first failure)
    - MUST NOT modify plan
    - MUST NOT execute tools
    - MUST NOT resolve PREVIOUS_RESULT
"""


def validate(plan: list, tool_registry: dict) -> dict:
    """
    Validate a structured plan against tool contracts.
    
    INPUT:
        plan: list of steps, each step is {"tool": str, "args": list}
        tool_registry: dict mapping tool_name -> {"args": int, "types": [type, ...]}
    
    OUTPUT (success):
        {"status": "success"}
    
    OUTPUT (failure):
        {"status": "failure", "reason": str}
    
    VALIDATION RULES:
        1. Plan must be a list
        2. Plan must not be empty
        3. Each step must be a dict with "tool" and "args"
        4. Tool must exist in registry
        5. Argument count must match schema exactly
        6. Argument types must match schema exactly
        7. PREVIOUS_RESULT is NOT type-checked
    
    FAIL-FAST: Returns immediately on first failure.
    """
    # 1. Check plan is a list
    if not isinstance(plan, list):
        return {"status": "failure", "reason": "invalid_plan_type"}
    
    # 2. Check plan is not empty
    if len(plan) == 0:
        return {"status": "failure", "reason": "empty_plan"}
    
    # 3-6. Validate each step
    for step_index, step in enumerate(plan):
        # Step must be a dict
        if not isinstance(step, dict):
            return {"status": "failure", "reason": "invalid_step_structure"}
        
        # Must contain "tool" and "args"
        if "tool" not in step or "args" not in step:
            return {"status": "failure", "reason": "invalid_step_structure"}
        
        tool_name = step["tool"]
        args = step["args"]
        
        # 4. Tool must exist in registry
        if tool_name not in tool_registry:
            return {"status": "failure", "reason": "tool_not_found"}
        
        # Get tool spec from registry
        tool_spec = tool_registry[tool_name]
        expected_count = tool_spec["args"]
        expected_types = tool_spec["types"]
        
        # 5. Validate argument count with PREVIOUS_RESULT handling
        # For chained execution (step_index > 0), implicit PREVIOUS_RESULT counts as +1 arg
        effective_args_count = len(args)
        if step_index > 0 and expected_count > len(args):
            # Implicit PREVIOUS_RESULT will be injected at execution time
            effective_args_count += 1
        
        if effective_args_count != expected_count:
            return {"status": "failure", "reason": "argument_count_mismatch"}
        
        # 6. Validate argument types
        for i, arg in enumerate(args):
            # Skip type check for PREVIOUS_RESULT placeholder
            if arg == "PREVIOUS_RESULT":
                continue
            
            # Check type matches expected
            if i < len(expected_types):
                expected_type = expected_types[i]
                if not isinstance(arg, expected_type):
                    return {"status": "failure", "reason": "argument_type_mismatch"}
    
    # All validations passed
    return {"status": "success"}

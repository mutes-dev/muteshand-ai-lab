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
    - MUST use tool_registry as SINGLE source of truth
"""


def validate(plan: list, tool_registry: dict) -> dict:
    """
    Validate a structured plan against tool contracts.
    
    INPUT:
        plan: list of steps, each step is {"tool": str, "args": list}
        tool_registry: dict mapping tool_name -> {"args": int, "types": list}
    
    OUTPUT (success):
        {"status": "success"}
    
    OUTPUT (failure):
        {"status": "failure", "reason": str}
    
    VALIDATION RULES:
        1. Plan must be a list
        2. Plan must not be empty
        3. Each step must be a dict with "tool" and "args"
        4. Tool must exist in registry
        5. Argument count must match tool contract
        6. Argument types must match tool contract
        7. PREVIOUS_RESULT is NOT type-checked and is ignored during validation
    
    FAIL-FAST: Returns immediately on first failure.
    """
    # 1. Check plan is a list
    if not isinstance(plan, list):
        return {"status": "failure", "reason": "invalid_plan_type"}
    
    # 2. Check plan is not empty
    if len(plan) == 0:
        return {"status": "failure", "reason": "empty_plan"}
    
    # 3-6. Validate each step
    for step in plan:
        # Step must be a dict
        if not isinstance(step, dict):
            return {"status": "failure", "reason": "invalid_step_structure"}
        
        # Must contain "tool" and "args"
        if "tool" not in step or "args" not in step:
            return {"status": "failure", "reason": "invalid_step_structure"}
        
        tool_name = step["tool"]
        args = step["args"]
        
        print("VALIDATION → STEP TOOL:", tool_name)
        print("VALIDATION → AVAILABLE TOOLS SAMPLE:", list(tool_registry.keys())[:5])
        
        # 4. Tool must exist in registry
        if tool_name not in tool_registry:
            return {"status": "failure", "reason": "tool_not_found"}
        
        tool_spec = tool_registry[tool_name]
        expected_count = tool_spec.get("args", 0)
        expected_types = tool_spec.get("types", [])
        
        # 5. Validate argument count
        if len(args) != expected_count:
            return {"status": "failure", "reason": "argument_count_mismatch"}
        
        # 6. Validate argument types
        for i, arg in enumerate(args):
            # Skip type check for runtime placeholders
            if arg == "PREVIOUS_RESULT":
                continue
            
            # Check type matches expected
            if i < len(expected_types):
                expected_type = expected_types[i]
                if not isinstance(arg, expected_type):
                    return {"status": "failure", "reason": "argument_type_mismatch"}
    
    # All validations passed
    return {"status": "success"}

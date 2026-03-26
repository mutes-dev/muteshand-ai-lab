"""
Chain Resolver Module

PURPOSE:
    Resolves PREVIOUS_RESULT tokens by substituting actual values from prior executions.
    Enables multi-step tool chaining where step N can use results from step N-1.

ARCHITECTURE ROLE:
    - Dependency injection layer: Links steps together at execution time
    - Stateless: Pure function with no side effects
    - Bridge between planning and execution phases

LAYER RESPONSIBILITY:
    - Replace "PREVIOUS_RESULT" token with the actual previous result value
    - Enforce single dependency (only one PREVIOUS_RESULT per step)
    - Validate that results exist before substitution
    - Preserve order of arguments after substitution

USAGE:
    # Step 1 result: 5
    # Step 2 args: ["PREVIOUS_RESULT", 3]
    resolved = resolve_chain(["PREVIOUS_RESULT", 3], [5])
    # Returns: [5, 3] - token replaced with actual value

CONSTRAINTS:
    - Only ONE PREVIOUS_RESULT token allowed per args list
    - Must have results available (non-empty results list)
    - Token must exactly match "PREVIOUS_RESULT" (case-sensitive)
"""


def resolve_chain(args: list, results: list) -> list:
    """
    Resolve PREVIOUS_RESULT tokens in arguments by replacing with actual results.
    
    RESOLUTION RULES:
        1. Replace "PREVIOUS_RESULT" token with results[-1] (most recent result)
        2. Only ONE "PREVIOUS_RESULT" allowed per args list (enforced)
        3. If "PREVIOUS_RESULT" exists but results is empty, raise exception
        4. If no "PREVIOUS_RESULT" in args, return args unchanged (pass-through)
        5. Preserve order of arguments after substitution
    
    ARCHITECTURAL NOTES:
        - This is dependency injection at execution time
        - Links planner output (structure) with actual execution values
        - Called AFTER planning, BEFORE tool execution
        - Single dependency constraint prevents complex multi-branch chains
    
    Args:
        args (list): List of arguments that may contain "PREVIOUS_RESULT" token.
                     May contain other arguments before or after the token.
        results (list): List of previous execution results. 
                        Must be non-empty if PREVIOUS_RESULT is present.
        
    Returns:
        list: Arguments with "PREVIOUS_RESULT" replaced by actual value.
              Returns unchanged args if no PREVIOUS_RESULT token.
        
    Raises:
        Exception: If multiple "PREVIOUS_RESULT" tokens found (Rule 2 violation)
        Exception: If "PREVIOUS_RESULT" exists but no results available (Rule 3 violation)
        
    Examples:
        >>> resolve_chain(["PREVIOUS_RESULT"], [8])
        [8]
        
        >>> resolve_chain([2, "PREVIOUS_RESULT"], [5])
        [2, 5]  # PREVIOUS_RESULT replaced with 5, order preserved
        
        >>> resolve_chain([3, 4], [10])
        [3, 4]  # No token, pass-through
        
        >>> resolve_chain(["PREVIOUS_RESULT", "PREVIOUS_RESULT"], [1])
        Exception: Multiple PREVIOUS_RESULT tokens not allowed
        
        >>> resolve_chain(["PREVIOUS_RESULT"], [])
        Exception: No previous result available
    """
    
    # Count PREVIOUS_RESULT occurrences to enforce single dependency rule
    token_count = args.count("PREVIOUS_RESULT")
    
    # RULE 2: Only one PREVIOUS_RESULT allowed per step
    # This enforces linear chaining (no multi-branch dependencies)
    if token_count > 1:
        raise Exception("Multiple PREVIOUS_RESULT tokens not allowed")
    
    # RULE 4: Pass-through if no PREVIOUS_RESULT token
    # No dependency needed, return args unchanged
    if token_count == 0:
        return args
    
    # RULE 3: Validate results available before substitution
    # Cannot resolve dependency without prior results
    if not results:
        raise Exception("No previous result available")
    
    # RULE 1 & 5: Replace PREVIOUS_RESULT with results[-1], preserving order
    # results[-1] is the most recent (last) execution result
    resolved_args = []
    for arg in args:
        if arg == "PREVIOUS_RESULT":
            # Substitute token with actual previous result value
            resolved_args.append(results[-1])
        else:
            # Pass through unchanged
            resolved_args.append(arg)
    
    return resolved_args

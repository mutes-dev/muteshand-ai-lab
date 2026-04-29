"""
Planner Output Validation — Non-Authoritative Structure Check

Validates planner output structure without modifying content.
"""

from typing import Tuple, Any


def validate_planner_output(raw_output: Any) -> Tuple[bool, str]:
    """
    Validate planner output structure.
    
    Returns:
        (True, "") if valid
        (False, reason) if invalid
    """
    # Rule 1: Must be a dict
    if not isinstance(raw_output, dict):
        return (False, "output_not_dict")
    
    # Rule 2: Must contain "steps"
    if "steps" not in raw_output:
        return (False, "missing_steps_key")
    
    steps = raw_output.get("steps")
    
    # Rule 3: steps must be a list
    if not isinstance(steps, list):
        return (False, "steps_not_list")
    
    # Rule 4: steps must not be empty
    if not steps:
        return (False, "steps_empty")
    
    # For each step: must be dict with required fields
    required_fields = ["name", "purpose", "agent", "estimated_complexity"]
    
    for i, step in enumerate(steps):
        # Must be dict
        if not isinstance(step, dict):
            return (False, f"step_{i}_not_dict")
        
        # Must contain all required fields
        for field in required_fields:
            if field not in step:
                return (False, f"step_{i}_missing_{field}")
    
    return (True, "")

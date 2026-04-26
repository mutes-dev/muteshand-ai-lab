"""
Planner Output Validator — Observational Only

Detects invalid planner output patterns without affecting execution.
This is a READ-ONLY analysis module — it MUST NOT:
- Modify steps
- Raise exceptions that break execution
- Trigger retry
- Affect governance
- Introduce control flow

Principle: Detect — do not decide.
"""


def validate_planner_output(steps: list) -> dict:
    """
    Scan planner output steps for non-natural language patterns.

    Args:
        steps: List of step dicts from planner output

    Returns:
        dict: {
            "valid": bool,
            "issues": [
                {
                    "step": str,
                    "issue": str
                }
            ]
        }
    """
    issues = []

    if not isinstance(steps, list):
        return {
            "valid": False,
            "issues": [{"step": "N/A", "issue": "steps_not_a_list"}]
        }

    for step in steps:
        if not isinstance(step, dict):
            issues.append({"step": str(step), "issue": "step_not_a_dict"})
            continue

        purpose = step.get("purpose", "")
        if not isinstance(purpose, str):
            issues.append({"step": str(step), "issue": "purpose_not_a_string"})
            continue

        # Check for tool syntax patterns
        if "USE_TOOL:" in purpose:
            issues.append({"step": purpose, "issue": "USE_TOOL_syntax_detected"})

        # Check for function-style calls: word(...)
        if "(" in purpose and ")" in purpose:
            issues.append({"step": purpose, "issue": "function_syntax_detected"})

        # Check for quoted arguments
        if '"' in purpose or "'" in purpose:
            issues.append({"step": purpose, "issue": "quoted_arguments_detected"})

        # Check for snake_case tool-like patterns (e.g., add_numbers, multiply_string)
        import re
        snake_case_pattern = r'\b[a-z]+_[a-z]+\b'
        if re.search(snake_case_pattern, purpose):
            issues.append({"step": purpose, "issue": "snake_case_tool_pattern_detected"})

        # Check for raw argument-like patterns: multiple space-separated tokens
        # that look like numeric arguments (e.g., "5 10" at end of step)
        tokens = purpose.split()
        if len(tokens) >= 3:
            # Check if last two tokens could be raw numeric arguments
            last_two = tokens[-2:]
            if all(t.lstrip("-").isdigit() for t in last_two):
                issues.append({"step": purpose, "issue": "raw_argument_pattern_detected"})

    return {
        "valid": len(issues) == 0,
        "issues": issues
    }

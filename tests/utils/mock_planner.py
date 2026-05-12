"""
Mock Planner — Deterministic Output Generator

Generates BOTH valid and invalid planner outputs for harness testing.
- generates outputs ONLY
- contains NO logic beyond returning predefined structures
- fully deterministic
- completely isolated from system layers
"""


def valid_single_step():
    """Return valid single-step planner output."""
    return [
        {
            "type": "tool",
            "name": "add",
            "input_text": "add 2 and 3"
        }
    ]


def valid_multi_step():
    """Return valid multi-step planner output."""
    return [
        {
            "type": "tool",
            "name": "add",
            "input_text": "add 2 and 3"
        },
        {
            "type": "tool",
            "name": "multiply",
            "input_text": "multiply result by 5"
        }
    ]


def invalid_empty():
    """Return invalid empty list output."""
    return []


def invalid_missing_field():
    """Return invalid output with missing required field."""
    return [
        {
            "type": "tool",
            "name": "add"
        }
    ]


def invalid_extra_field():
    """Return invalid output with extra prohibited field."""
    return [
        {
            "type": "tool",
            "name": "add",
            "input_text": "add 2 and 3",
            "extra": "not allowed"
        }
    ]


def invalid_type_value():
    """Return invalid output with wrong type value."""
    return [
        {
            "type": "invalid",
            "name": "add",
            "input_text": "add 2 and 3"
        }
    ]


def invalid_wrong_types():
    """Return invalid output with wrong field types."""
    return [
        {
            "type": "tool",
            "name": 123,
            "input_text": None
        }
    ]


def valid_failure():
    """Return valid failure object output."""
    return {
        "status": "failure",
        "reason": "planner_error"
    }


def invalid_failure():
    """Return invalid failure object with wrong status and empty reason."""
    return {
        "status": "fail",
        "reason": ""
    }


def invalid_output_type():
    """Return invalid output type (string instead of list/dict)."""
    return "this is invalid"

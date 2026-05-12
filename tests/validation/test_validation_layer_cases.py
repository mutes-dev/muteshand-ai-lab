"""
CATEGORY: VALIDATION
AUTHORITY_LAYER: Structural Validation Truth
VALIDATES:
  - Validator contract
  - Valid plan success
  - Invalid tool failure
  - Invalid arg type failure
ENTRYPOINT: validate_workflow
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: STRUCTURAL_VALIDATION
ARCHITECTURAL_SCOPE: Validation layer only

---

Validation Layer Test Cases — Data-Driven Format

Generated from real validate() execution.
"""

TEST_CASES = [
    {
        "name": "valid_plan_success",
        "type": "validation",
        "input": {
            "plan": [{"tool": "add_numbers", "args": [2, 3]}],
            "registry": {"add_numbers": {"args": 2, "types": [int, int]}}
        },
        "expected": {"status": "success"}
    },
    {
        "name": "invalid_tool_not_found",
        "type": "validation",
        "input": {
            "plan": [{"tool": "unknown_tool", "args": [2, 3]}],
            "registry": {"add_numbers": {"args": 2, "types": [int, int]}}
        },
        "expected": {"status": "failure", "reason": "tool_not_found"}
    },
    {
        "name": "invalid_arg_type_mismatch",
        "type": "validation",
        "input": {
            "plan": [{"tool": "add_numbers", "args": [2, "bad"]}],
            "registry": {"add_numbers": {"args": 2, "types": [int, int]}}
        },
        "expected": {"status": "failure", "reason": "argument_type_mismatch"}
    }
]

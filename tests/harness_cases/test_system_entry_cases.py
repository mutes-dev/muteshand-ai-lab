"""
System Entry Test Cases — Full Pipeline LLM Dual-Mode Validation

Tests end-to-end pipeline behavior with LLM in SAFE MODE and INTELLIGENT MODE.
Validates that the full system executes correctly from entry → execution.
"""

# Legacy TEST_CASES for harness compatibility
TEST_CASES = [
    {
        "name": "planner_path_add_numbers",
        "type": "system",
        "input": "add 2 3",
        "expected": {
            "status": "success",
            "result": 5
        }
    },
]

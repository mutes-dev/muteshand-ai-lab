"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - Layered contract structure
  - Nested status/result validation
  - External API correctness
ENTRYPOINT: execute_from_input
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: External API contract only

---

Orchestrator Layered Contract Test Cases

Tests orchestrator-level execution with LAYERED contract validation.
Uses execute_from_input(input_str) entry point.
"""

TEST_CASES = [
    {
        "name": "orchestrator_add_numbers_layered",
        "type": "orchestrator",
        "input": "add 2 and 3",
        "expected": {
            "status": "success",
            "result": {
                "status": "success",
                "result": 5
            }
        }
    },
    {
        "name": "orchestrator_multiply_numbers_layered",
        "type": "orchestrator",
        "input": "multiply 4 and 6",
        "expected": {
            "status": "success",
            "result": {
                "status": "success",
                "result": 24
            }
        }
    }
]

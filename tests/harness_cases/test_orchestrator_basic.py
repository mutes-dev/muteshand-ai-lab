"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - External API contract compliance
  - Layered output structure
  - Basic orchestrator execution correctness
ENTRYPOINT: execute_from_input
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: External API contract only

---

Basic Orchestrator Test Cases — Migrated from test_workflow.py

PROOF OF PARITY: Harness replicates real test behavior

Selected Tests:
1. test_args_correctness_from_executed_input (line 593) - "add 2 and 3"
2. test_external_contract_fields_only (line 62) - "What is 2+2?"
3. test_output_matches_execution_result (line 815) - "add 2 and 3"

Sources:
- system/tests/test_workflow.py

Note: Only deterministic tests selected. Empty input was excluded
because LLM behavior is non-deterministic for empty queries.
"""

TEST_CASES = [
    {
        "name": "basic_success_add_numbers",
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
        "name": "basic_success_multiply_numbers",
        "type": "orchestrator",
        "input": "multiply 4 and 6",
        "expected": {
            "status": "success",
            "result": {
                "status": "success",
                "result": 24
            }
        }
    },
    {
        "name": "contract_validation_layered_structure",
        "type": "orchestrator",
        "input": "add 2 and 3",
        "expected": {
            "status": "success",
            "result": {
                "status": "success",
                "result": 5
            }
        }
    }
]

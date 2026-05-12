"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - Full pipeline execution
  - LLM dual-mode behavior
  - End-to-end correctness
ENTRYPOINT: system_entry
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: Full pipeline contract

---

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

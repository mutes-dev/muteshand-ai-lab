"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - Router contract
  - Default routing behavior
ENTRYPOINT: router
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: Router contract only

---

Router Test Cases — Data-Driven Format

Generated from real route_input() execution.
"""

TEST_CASES = [
    {
        "name": "default_planner_route",
        "type": "router",
        "input": "add 2 and 3",
        "expected": {"mode": "planner", "data": "add 2 and 3"}
    }
]

"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - Router contract
  - Default planner routing
  - LLM structure routing
ENTRYPOINT: router
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE:
  - llm_entry (for routing test)
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: Router contract only
"""

from system.entry.router import route_input


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def run_test_default_route():
    print("\n[ROUTER TEST 1] DEFAULT PLANNER ROUTE")

    input_text = "add 2 and 3"

    result = route_input(input_text)

    print("Output:", result)

    if result == {"mode": "planner", "data": input_text}:
        print("PASS: Routed to planner")
        return True
    else:
        print("FAIL: Incorrect routing")
        return False


def run_test_llm_structure_route():
    print("\n[ROUTER TEST 2] LLM STRUCTURE ROUTE")

    # monkey patch llm_entry
    import system.entry.router as router_module

    original = router_module.llm_entry

    def mock_llm_entry(_):
        return [
            {"type": "tool", "name": "add_numbers", "input_text": "add 2 and 3"}
        ]

    router_module.llm_entry = mock_llm_entry

    result = route_input("add 2 and 3")

    print("Output:", result)

    # restore
    router_module.llm_entry = original

    if result["mode"] == "direct_plan" and isinstance(result["data"], list):
        print("PASS: Routed to direct_plan")
        return True
    else:
        print("FAIL: Incorrect routing for structured plan")
        return False


def run_test_failsafe():
    print("\n[ROUTER TEST 3] FAILSAFE ROUTE")

    import system.entry.router as router_module

    original = router_module.llm_entry

    def mock_llm_entry(_):
        return None

    router_module.llm_entry = mock_llm_entry

    input_text = "anything"

    result = route_input(input_text)

    print("Output:", result)

    router_module.llm_entry = original

    if result == {"mode": "planner", "data": input_text}:
        print("PASS: Failsafe routing correct")
        return True
    else:
        print("FAIL: Failsafe routing incorrect")
        return False


def run_all_router_tests():
    results = [
        run_test_default_route(),
        run_test_llm_structure_route(),
        run_test_failsafe()
    ]

    print("\n=== ROUTER TEST SUMMARY ===")

    if all(results):
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")

    return all(results)


if __name__ == "__main__":
    import sys
    success = run_all_router_tests()
    sys.exit(0 if success else 1)

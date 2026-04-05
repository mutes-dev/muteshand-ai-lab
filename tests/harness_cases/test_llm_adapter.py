from core.planner.llm_adapter import generate_plan
from system.planner.deterministic_planner import plan


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def run_test_adapter_failure():
    print("\n[LLM TEST 1] ADAPTER FAILURE")

    result = generate_plan("anything")

    print("Output:", result)

    if result == {"status": "failure", "reason": "llm_not_configured"}:
        print("PASS: Adapter failure correct")
        return True
    else:
        print("FAIL: Adapter did not return expected failure")
        return False


def run_test_planner_fallback():
    print("\n[LLM TEST 2] PLANNER NO LONGER CALLS ADAPTER")

    result = plan("do something unknown")

    print("Output:", result)

    if (
        isinstance(result, list)
        and len(result) == 1
        and result[0].get("name") == "unknown"
    ):
        print("PASS: Planner returns structured unknown (adapter not called)")
        return True
    else:
        print("FAIL: Planner did not return expected unknown structure")
        return False


def run_test_no_impact():
    print("\n[LLM TEST 3] NO IMPACT ON DETERMINISTIC")

    result = plan("add 2 and 3")

    print("Output:", result)

    if isinstance(result, list) and result[0]["name"] == "add_numbers":
        print("PASS: Deterministic planner unchanged")
        return True
    else:
        print("FAIL: Deterministic behavior affected")
        return False


def run_all_llm_tests():
    results = [
        run_test_adapter_failure(),
        run_test_planner_fallback(),
        run_test_no_impact()
    ]

    print("\n=== LLM ADAPTER TEST SUMMARY ===")

    if all(results):
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")

    return all(results)


if __name__ == "__main__":
    import sys
    success = run_all_llm_tests()
    sys.exit(0 if success else 1)

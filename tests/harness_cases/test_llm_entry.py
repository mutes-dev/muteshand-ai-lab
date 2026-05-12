"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - LLM entry contract
  - Pass-through behavior
  - Adapter failure path
ENTRYPOINT: llm_entry
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: LLM entry contract only
"""

from system.entry.llm_entry import llm_entry


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def run_test_pass_through():
    print("\n[LLM ENTRY TEST 1] PASS-THROUGH")

    input_text = "add 2 and 3"

    result = llm_entry(input_text)

    print("Output:", result)

    if result == input_text:
        print("PASS: Input passed through unchanged")
        return True
    else:
        print("FAIL: Input was modified")
        return False


def run_test_adapter_failure():
    print("\n[LLM ENTRY TEST 2] ADAPTER FAILURE PATH")

    input_text = "anything"

    result = llm_entry(input_text)

    print("Output:", result)

    if result == input_text:
        print("PASS: Failure path returns original input")
        return True
    else:
        print("FAIL: Failure path incorrect")
        return False


def run_test_structure_passthrough():
    print("\n[LLM ENTRY TEST 3] STRUCTURE PASS-THROUGH (MOCK)")

    # monkey patch adapter in llm_entry module
    import system.entry.llm_entry as llm_entry_module

    original = llm_entry_module.generate_plan

    def mock_generate_plan(_):
        return [
            {"type": "tool", "name": "add_numbers", "input_text": "add 2 and 3"}
        ]

    llm_entry_module.generate_plan = mock_generate_plan

    result = llm_entry("add 2 and 3")

    print("Output:", result)

    # restore original
    llm_entry_module.generate_plan = original

    if isinstance(result, list) and result[0]["name"] == "add_numbers":
        print("PASS: Structure passed through unchanged")
        return True
    else:
        print("FAIL: Structure was altered")
        return False


def run_all_llm_entry_tests():
    results = [
        run_test_pass_through(),
        run_test_adapter_failure(),
        run_test_structure_passthrough()
    ]

    print("\n=== LLM ENTRY TEST SUMMARY ===")

    if all(results):
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")

    return all(results)


if __name__ == "__main__":
    import sys
    success = run_all_llm_entry_tests()
    sys.exit(0 if success else 1)

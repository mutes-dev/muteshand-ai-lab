from system.observability.validator import validate


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def run_tests():
    print("\n[VALIDATION TEST 1] VALID PLAN")

    result = validate(
        [{"tool": "add_numbers", "args": [2, 3]}],
        {"add_numbers": {"args": 2, "types": [int, int]}}
    )

    print("Output:", result)
    print("PASS" if result.get("status") == "success" else "FAIL")


    print("\n[VALIDATION TEST 2] INVALID TOOL")

    result = validate(
        [{"tool": "unknown_tool", "args": [2, 3]}],
        {"add_numbers": {"args": 2, "types": [int, int]}}
    )

    print("Output:", result)
    print("PASS" if result.get("status") == "failure" else "FAIL")


    print("\n[VALIDATION TEST 3] INVALID ARG TYPE")

    result = validate(
        [{"tool": "add_numbers", "args": [2, "bad"]}],
        {"add_numbers": {"args": 2, "types": [int, int]}}
    )

    print("Output:", result)
    print("PASS" if result.get("status") == "failure" else "FAIL")


if __name__ == "__main__":
    run_tests()

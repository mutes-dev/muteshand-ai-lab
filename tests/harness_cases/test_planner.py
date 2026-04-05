from system.planner.deterministic_planner import plan


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def run_test_determinism():
    print("\n[TEST 1] DETERMINISM")

    input_text = "add 2 and 3"

    outputs = [plan(input_text) for _ in range(3)]

    for i, out in enumerate(outputs):
        print(f"Run {i+1}: {out}")

    if outputs[0] == outputs[1] == outputs[2]:
        print("PASS: Deterministic output")
        return True
    else:
        print("FAIL: Non-deterministic output")
        return False


def run_test_multistep():
    print("\n[TEST 2] MULTI-STEP DETECTION")

    inputs = [
        "add 2 and 3 then multiply by 4",
        "multiply 5 by 6 then add 2"
    ]

    success = True

    for text in inputs:
        result = plan(text)
        print(f"\nInput: {text}")
        print("Output:", result)

        if not isinstance(result, list):
            print("FAIL: Output is not a list")
            success = False
            continue

        if len(result) < 2:
            print("FAIL: Expected multiple steps")
            success = False

        names = [step.get("name") for step in result]

        if len(names) != len(set(names)):
            print("FAIL: Duplicate steps detected")
            success = False

    if success:
        print("PASS: Multi-step detection valid")

    return success


def run_test_unknown():
    print("\n[TEST 3] UNKNOWN INPUT")

    input_text = "do something random"

    result = plan(input_text)

    print("Output:", result)

    if (
        isinstance(result, list)
        and len(result) == 1
        and result[0].get("name") == "unknown"
    ):
        print("PASS: Correct unknown tool structure")
        return True
    else:
        print("FAIL: Expected structured unknown tool output")
        return False


def run_test_structure():
    print("\n[TEST 4] STRUCTURE CONTRACT")

    input_text = "add 2 and 3"

    result = plan(input_text)

    print("Output:", result)

    required_fields = {"type", "name", "input_text"}

    success = True

    if not isinstance(result, list):
        print("FAIL: Output is not a list")
        return False

    for step in result:
        keys = set(step.keys())

        if keys != required_fields:
            print(f"FAIL: Invalid structure {keys}")
            success = False

    if success:
        print("PASS: Structure valid")

    return success


def run_test_no_args():
    print("\n[TEST 5] NO ARGUMENT GENERATION")

    input_text = "add 2 and 3"

    result = plan(input_text)

    print("Output:", result)

    forbidden_keys = {"args", "PREVIOUS_RESULT"}

    success = True

    for step in result:
        for key in step.keys():
            if key in forbidden_keys:
                print(f"FAIL: Forbidden key detected: {key}")
                success = False

        if any(isinstance(v, (int, float, list, dict)) for k, v in step.items() if k not in {"type", "name", "input_text"}):
            print("FAIL: Argument-like data detected in planner output")
            success = False

    if success:
        print("PASS: No argument leakage")

    return success


def run_all_planner_tests():
    results = [
        run_test_determinism(),
        run_test_multistep(),
        run_test_unknown(),
        run_test_structure(),
        run_test_no_args()
    ]

    print("\n=== PLANNER TEST SUMMARY ===")

    if all(results):
        print("ALL TESTS PASSED")
        return True
    else:
        print("SOME TESTS FAILED")
        return False


if __name__ == "__main__":
    import sys
    success = run_all_planner_tests()
    sys.exit(0 if success else 1)

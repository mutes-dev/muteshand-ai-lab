"""
Planner → Harness Integration Test (Mock → Validation)

Validates boundary enforcement between mock planner and planner harness:
- VALID outputs → MUST PASS
- INVALID outputs → MUST FAIL

No invalid data may pass this boundary.
"""

from tests.mock_planner import *
from tests.test_planner import validate_planner_output


def run_test(name, func, should_pass):
    """Run a single integration test."""
    print("TEST:", name)

    output = func()
    print("OUTPUT:", output)

    try:
        validate_planner_output(output)

        if should_pass:
            print("RESULT: PASS\n")
            return True
        else:
            print("RESULT: FAIL (unexpected pass)\n")
            return False

    except Exception as e:

        print("ERROR:", str(e))

        if should_pass:
            print("RESULT: FAIL (unexpected failure)\n")
            return False
        else:
            print("RESULT: PASS (correctly rejected)\n")
            return True


def main():
    """Execute all integration tests."""
    results = []

    results.append(run_test("valid_single_step", valid_single_step, True))
    results.append(run_test("valid_multi_step", valid_multi_step, True))
    results.append(run_test("valid_failure", valid_failure, True))

    results.append(run_test("invalid_empty", invalid_empty, False))
    results.append(run_test("invalid_missing_field", invalid_missing_field, False))
    results.append(run_test("invalid_extra_field", invalid_extra_field, False))
    results.append(run_test("invalid_type_value", invalid_type_value, False))
    results.append(run_test("invalid_wrong_types", invalid_wrong_types, False))
    results.append(run_test("invalid_failure", invalid_failure, False))
    results.append(run_test("invalid_output_type", invalid_output_type, False))

    failed = len([r for r in results if not r])

    print("=" * 50)

    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILED TESTS: {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

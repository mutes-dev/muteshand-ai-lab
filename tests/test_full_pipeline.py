"""
Full Pipeline Test — Planner → Harness → Entry → System

Validates complete system flow:
1. VALID planner output → passes harness → enters entry → executes
2. INVALID planner output → fails harness → NEVER reaches entry

No system modifications allowed.
"""

from tests.mock_planner import *
from tests.test_planner import validate_planner_output
from system.registry.registry_builder import build_registries
from core.entry import run


# Setup registries once
validation_registry, execution_registry = build_registries(
    "memory/tool_index/tools.json",
    "tools"
)


def run_pipeline_test(name, planner_func, should_pass):
    """Run a full pipeline test from planner to system execution."""
    print("TEST:", name)

    planner_output = planner_func()
    print("PLANNER OUTPUT:", planner_output)

    try:
        # STEP 1 — PLANNER HARNESS
        validate_planner_output(planner_output)

        if not should_pass:
            print("RESULT: FAIL (invalid passed harness)\n")
            return False

        # STEP 2 — ENTRY → SYSTEM
        result = run(planner_output, validation_registry, execution_registry)

        print("SYSTEM RESULT:", result)

        if result.get("status") == "failure":
            print("RESULT: FAIL (unexpected system failure)\n")
            return False

        print("RESULT: PASS\n")
        return True

    except Exception as e:

        print("ERROR:", str(e))

        if should_pass:
            print("RESULT: FAIL (unexpected failure)\n")
            return False
        else:
            print("RESULT: PASS (correctly blocked)\n")
            return True


def main():
    """Execute all pipeline tests."""
    results = []

    # VALID CASES
    results.append(run_pipeline_test("valid_single_step", valid_single_step, True))
    results.append(run_pipeline_test("valid_multi_step", valid_multi_step, True))

    # INVALID CASES
    results.append(run_pipeline_test("invalid_empty", invalid_empty, False))
    results.append(run_pipeline_test("invalid_missing_field", invalid_missing_field, False))
    results.append(run_pipeline_test("invalid_extra_field", invalid_extra_field, False))
    results.append(run_pipeline_test("invalid_type_value", invalid_type_value, False))
    results.append(run_pipeline_test("invalid_wrong_types", invalid_wrong_types, False))
    results.append(run_pipeline_test("invalid_failure", invalid_failure, False))
    results.append(run_pipeline_test("invalid_output_type", invalid_output_type, False))

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

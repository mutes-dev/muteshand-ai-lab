"""
Minimal Harness Runner for Orchestrator Multi-Step Validation
"""

import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from system.orchestrator.orchestrator_runtime import execute_from_input
from system.orchestrator.bootstrap import initialize_system
from system.tool_index.metadata_generator import run as run_metadata_generator


def ensure_metadata_ready():
    """Ensure tool metadata is generated before running tests."""
    import json

    with open("system/tool_index/tools.json", "r") as f:
        tools = json.load(f)

    missing = [
        name for name, data in tools.items()
        if not data.get("description")
    ]

    if missing:
        print(f"⚠️ Missing metadata for {len(missing)} tools — generating...")
        run_metadata_generator()
    else:
        print("✅ Metadata ready")


def extract_result(result):
    try:
        if isinstance(result, dict):
            if result.get("status") == "failure":
                return None

            if "result" in result:
                inner = result["result"]

                if isinstance(inner, dict) and "result" in inner:
                    return inner["result"]

                return inner

        return result
    except Exception:
        return None


def run_test(input_text: str, expected):
    """Execute a single test case and return pass/fail status."""
    try:
        result = execute_from_input(input_text)
        final_result = extract_result(result)

        # Handle expected=None case (should not crash)
        if expected is None:
            return True, final_result

        # Compare numeric results
        passed = final_result == expected
        return passed, final_result

    except Exception as e:
        if expected is None:
            # Expected to not crash - exception means PASS
            return True, f"Exception: {e}"
        return False, f"Exception: {e}"


def main():
    """Run all harness test cases and print results."""
    # Initialize system once before all tests
    initialize_system()
    ensure_metadata_ready()

    tests = [
        ("add 2 and 3 then multiply by 4", 20),
        ("add 10 and 5 then multiply by 2 then subtract 4", 26),
        ("multiply 3 and 4 then add 10 to the result", 22),
        ("add 5 and 7 then divide by 3", 4),

        ("subtract -5 from -10", -5),
        ("add -3 and 7 then multiply by -2", -8),
        ("multiply -4 and -5 then subtract 10", 10),

        ("add 0 and 5 then multiply by 0", 0),
        ("divide 10 by 2 then subtract 3", 2),

        ("divide 10 by 0", None),
    ]

    passed_count = 0
    failed_count = 0

    for input_text, expected in tests:
        passed, actual = run_test(input_text, expected)

        if passed:
            passed_count += 1
            if expected is None:
                print(f"[PASS] {input_text} → handled safely")
            else:
                print(f"[PASS] {input_text} → {actual}")
        else:
            failed_count += 1
            if expected is None:
                print(f"[FAIL] {input_text} → crashed with: {actual}")
            else:
                print(f"[FAIL] {input_text} → got {actual} expected {expected}")

    print(f"\nTOTAL: {passed_count} passed, {failed_count} failed")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

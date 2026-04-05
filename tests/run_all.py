import subprocess
import sys
from tests.test_planner import run_all_planner_tests
from tests.test_llm_adapter import run_all_llm_tests
from tests.test_llm_entry import run_all_llm_entry_tests
from tests.test_router import run_all_router_tests
from tests.test_system_entry import run_all_system_entry_tests

from tests.test_validation_layer import run_tests as run_validation_tests

TEST_FILES = [
    "tests/test_executor.py",
    "tests/test_validation.py",
    "tests/test_registry_builder.py"
]

def run():
    print("\n==============================")
    print("RUNNING FULL TEST HARNESS")
    print("==============================")

    for test_file in TEST_FILES:
        print(f"\nRUNNING: {test_file}")

        result = subprocess.run(
            [sys.executable, test_file]
        )

        if result.returncode != 0:
            print(f"\nFAILED: {test_file}")
            sys.exit(1)

    print("\n==============================")
    print("RUNNING PLANNER TESTS")
    print("==============================")

    planner_success = run_all_planner_tests()

    if not planner_success:
        print("\nFAILED: Planner tests")
        sys.exit(1)

    print("\n==============================")
    print("RUNNING LLM ADAPTER TESTS")
    print("==============================")

    llm_success = run_all_llm_tests()

    if not llm_success:
        print("\nFAILED: LLM adapter tests")
        sys.exit(1)

    print("\n==============================")
    print("RUNNING LLM ENTRY TESTS")
    print("==============================")

    llm_entry_success = run_all_llm_entry_tests()

    if not llm_entry_success:
        print("\nFAILED: LLM entry tests")
        sys.exit(1)

    print("\n==============================")
    print("RUNNING ROUTER TESTS")
    print("==============================")

    router_success = run_all_router_tests()

    if not router_success:
        print("\nFAILED: Router tests")
        sys.exit(1)

    print("\n==============================")
    print("RUNNING VALIDATION LAYER TESTS")
    print("==============================")

    run_validation_tests()

    print("\n==============================")
    print("RUNNING SYSTEM ENTRY TESTS")
    print("==============================")

    system_entry_success = run_all_system_entry_tests()

    if not system_entry_success:
        print("\nFAILED: System entry tests")
        sys.exit(1)

    print("\n==============================")
    print("ALL TESTS PASSED")
    print("==============================")

if __name__ == "__main__":
    run()

import subprocess
import sys

TEST_FILES = [
    "tests/test_executor.py",
    "tests/test_validation.py",
    "tests/test_registry_builder.py",
    "tests/test_pipeline.py"
]

def run():
    for test_file in TEST_FILES:
        print(f"\nRUNNING: {test_file}")

        result = subprocess.run(
            [sys.executable, test_file]
        )

        if result.returncode != 0:
            print(f"\nFAILED: {test_file}")
            sys.exit(1)

    print("\nALL TESTS PASSED")

if __name__ == "__main__":
    run()

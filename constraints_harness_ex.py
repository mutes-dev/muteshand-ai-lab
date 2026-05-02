import traceback
from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator.trace_collector import get_trace, get_collector, create_collector

# Trace collector shim for backward compatibility
# python constraints_harness.py 2>&1 > constraints_harness_run.log
class TraceCollectorShim:
    @staticmethod
    def get_trace():
        return get_trace()
    
    @staticmethod
    def clear_trace():
        collector = get_collector()
        if collector:
            collector.clear()
            return True
        return False

trace_collector = TraceCollectorShim()

TEST_CASES = [
    'repeat "abc" 3 times but output only the count',
    'repeat "hello" 4 times but return only the number',
    'multiply 2 and 3 but respond in words',
    'add 4 and 4 but output "done"',
    # extra coverage
    'repeat "a" 5 times but return only the count',
    'multiply 10 and 2 but respond in words',
    'repeat "cat" 2 times but output list',
    'repeat "x" 3 times but return nothing',
    # added
    # STRUCTURE
    'multiply 2 and 3 and answer in a sentence',
    'multiply 2 and 3 and explain in a sentence',
    # POSITION
    'multiply 2 and 3 and put the answer at the end',
    # COMBINED
    'multiply 2 and 3 in a sentence with the answer at the end',
    # STYLE
    'multiply 2 and 3 and explain step by step',
]


def extract_summary(trace):
    if trace is None:
        return [], None

    steps = trace.get("steps", [])

    attempts = []
    final = None

    for step in steps:
        if "execution_result" not in step:
            continue

        execution = step.get("execution_result", {})
        output = execution.get("result") if execution else None

        validator = step.get("validator_signals") or {}
        advisory = step.get("validator_advisory")

        attempt = {
            "output": output,
            "constraint_ok": validator.get("constraint_ok") if validator else None,
            "violation": validator.get("constraint_violation") if validator else None,
            "validator": advisory,
        }

        attempts.append(attempt)
        final = attempt

    return attempts, final


def build_workflow(user_input: str) -> dict:
    return {
        "id": "cli_workflow",
        "name": "cli_execution",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "step_1",
                "name": "cli_step",
                "agent": "default_agent",
                "status": "PENDING",
                "retries": 0,
                "max_retries": 1,
                "input": user_input
            }
        ]
    }


def run_test(input_text, idx):
    print(f"\n--- Test {idx} ---")
    print(f"Input: {input_text}")

    try:
        workflow = build_workflow(input_text)
        result = run_workflow(workflow)
        trace = trace_collector.get_trace()

        attempts, final = extract_summary(trace)

        # Print attempts
        for i, att in enumerate(attempts, 1):
            print(f"\nTry {i}:")
            print(f"  Output: {att['output']}")
            print(f"  constraint_ok: {att['constraint_ok']}")
            print(f"  violation: {att['violation']}")
            print(f"  validator: {att['validator']}")

        # Final result
        print("\nFinal:")
        print(f"  Output: {final['output']}")
        print(f"  constraint_ok: {final['constraint_ok']}")
        print(f"  violation: {final['violation']}")
        print(f"  validator: {final['validator']}")

        return {
            "success": True,
            "constraint_ok": final["constraint_ok"]
        }

    except Exception as e:
        print("ERROR:", str(e))
        traceback.print_exc()
        return {"success": False}


def main():
    total = len(TEST_CASES)
    success = 0
    violations_detected = 0

    for i, test in enumerate(TEST_CASES, 1):
        result = run_test(test, i)

        if result["success"]:
            success += 1
            if result.get("constraint_ok") is False:
                violations_detected += 1

    print("\n====================")
    print("FINAL SUMMARY")
    print("====================")
    print(f"Total tests: {total}")
    print(f"Completed: {success}")
    print(f"Violations detected: {violations_detected}")
    print(f"Detection rate: {round((violations_detected / total) * 100, 2)}%")


if __name__ == "__main__":
    main()
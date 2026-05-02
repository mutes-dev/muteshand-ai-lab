#!/usr/bin/env python3
"""
VALIDATOR_GOVERNANCE_SIGNAL_ANALYSIS
Measure validator/governance disagreement using existing trace utilities only.
NO system modifications - pure measurement.
"""

import json
from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator import trace_collector
from system.trace_utils.decision_viewer import build_decision_view
from system.trace_utils.retry_analyzer import analyze_retries
from system.trace_utils.step_timeline_viewer import build_step_timeline

# Test cases
test_inputs = [
    "repeat \"hello\" 3 times",
    "repeat \"test\" 5 times",
    "add 2 and 3",
    "subtract 5 from 10",
    "multiply 4 and 6",
    "divide 10 by 2",
    "repeat \"abc\" 2 times and then add 2 and 3",
    "what is 2+2",
    "repeat \"fail\" 3 times",
    "divide 5 by 0"
]

dataset = []
conflicts = []

print("=" * 80)
print("VALIDATOR_GOVERNANCE_SIGNAL_ANALYSIS")
print("=" * 80)

for i, test_input in enumerate(test_inputs, 1):
    print(f"\n--- Test {i}/10: {test_input[:50]}... ---")
    
    # Create workflow with ALL required fields
    workflow = {
        "id": f"conflict_test_{i}",
        "name": f"conflict_test_{i}",
        "status": "ACTIVE",
        "steps": [
            {
                "id": f"step_{i}",
                "name": f"step_{i}",
                "agent": "system",
                "purpose": test_input,
                "input": test_input,
                "status": "PENDING",
                "retries": 0,
                "max_retries": 2
            }
        ]
    }
    
    try:
        # Execute workflow
        result = run_workflow(workflow)
        
        # Collect trace
        trace = trace_collector.get_trace()
        
        if not trace:
            print(f"  [WARN] No trace available for test {i}")
            row = {
                "test_num": i,
                "input": test_input,
                "execution_status": result.get("status", "unknown"),
                "execution_result": None,
                "validator_advisory": None,
                "governance_decision": None,
                "retries": 0,
                "conflict": False,
                "error": "no_trace"
            }
            dataset.append(row)
            continue
        
        # Extract signals from trace
        steps = trace.get("steps", [])
        
        # Find step execution record (not governance_decision event)
        step_record = None
        for step in steps:
            if step.get("event") != "governance_decision" and step.get("governance_decision"):
                step_record = step
                break
        
        if not step_record:
            print(f"  [WARN] No step record found in trace for test {i}")
            row = {
                "test_num": i,
                "input": test_input,
                "execution_status": result.get("status", "unknown"),
                "execution_result": None,
                "validator_advisory": None,
                "governance_decision": None,
                "retries": 0,
                "conflict": False,
                "error": "no_step_record"
            }
            dataset.append(row)
            continue
        
        # Extract signals
        execution_result = step_record.get("execution_result", {})
        execution_status = execution_result.get("status") if isinstance(execution_result, dict) else None
        execution_value = execution_result.get("result") if isinstance(execution_result, dict) else None
        
        validator_advisory = step_record.get("validator_advisory")
        governance_decision = step_record.get("governance_decision")
        retries = step_record.get("retries", 0)
        
        print(f"  Execution: {execution_status}")
        print(f"  Validator: {validator_advisory}")
        print(f"  Governance: {governance_decision}")
        print(f"  Retries: {retries}")
        
        # Detect conflict:
        # execution_result = success AND validator_advisory = incorrect AND governance_decision = complete
        is_conflict = (
            execution_status == "success" and
            validator_advisory == "incorrect" and
            governance_decision == "complete"
        )
        
        if is_conflict:
            print(f"  [CONFLICT DETECTED]")
            conflicts.append(i)
        
        row = {
            "test_num": i,
            "input": test_input,
            "execution_status": execution_status,
            "execution_result": execution_value,
            "validator_advisory": validator_advisory,
            "governance_decision": governance_decision,
            "retries": retries,
            "conflict": is_conflict,
            "error": None
        }
        dataset.append(row)
        
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        row = {
            "test_num": i,
            "input": test_input,
            "execution_status": "error",
            "execution_result": None,
            "validator_advisory": None,
            "governance_decision": None,
            "retries": 0,
            "conflict": False,
            "error": str(e)
        }
        dataset.append(row)

# Build summary
print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)

print("\n--- FULL DATASET ---")
print(f"{'#':<4} {'Input':<45} {'Exec':<8} {'Validator':<12} {'Gov':<10} {'Retries':<8} {'Conflict'}")
print("-" * 100)

for row in dataset:
    input_short = row["input"][:44]
    print(f"{row['test_num']:<4} {input_short:<45} {str(row['execution_status']):<8} {str(row['validator_advisory']):<12} {str(row['governance_decision']):<10} {row['retries']:<8} {'YES' if row['conflict'] else 'NO'}")

print("\n--- SUMMARY STATISTICS ---")
total_tests = len(dataset)
successful_executions = sum(1 for r in dataset if r["execution_status"] == "success")
conflict_count = len(conflicts)
conflict_percentage = (conflict_count / total_tests * 100) if total_tests > 0 else 0

print(f"Total tests: {total_tests}")
print(f"Successful executions: {successful_executions}")
print(f"Conflict count: {conflict_count}")
print(f"Conflict percentage: {conflict_percentage:.1f}%")

if conflicts:
    print(f"\nConflicts detected in tests: {conflicts}")

# Observed patterns
print("\n--- OBSERVED PATTERNS ---")

# Failure types
failure_reasons = {}
for row in dataset:
    if row["execution_status"] == "failure":
        reason = row.get("error") or "unknown"
        failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

if failure_reasons:
    print("\nFailure types:")
    for reason, count in failure_reasons.items():
        print(f"  - {reason}: {count}")

# Retry analysis
retries_used = sum(1 for r in dataset if r["retries"] > 0)
if retries_used:
    print(f"\nRetries used: {retries_used} tests")
    
# Validator advisory distribution
validator_values = {}
for row in dataset:
    val = row["validator_advisory"]
    validator_values[val] = validator_values.get(val, 0) + 1

print(f"\nValidator advisory distribution:")
for val, count in validator_values.items():
    print(f"  - {val}: {count}")

# Governance decision distribution
governance_values = {}
for row in dataset:
    gov = row["governance_decision"]
    governance_values[gov] = governance_values.get(gov, 0) + 1

print(f"\nGovernance decision distribution:")
for gov, count in governance_values.items():
    print(f"  - {gov}: {count}")

print("\n" + "=" * 80)
print("SIGNAL CONFLICT ANALYSIS COMPLETE")
print("=" * 80)

# Save detailed results
output = {
    "dataset": dataset,
    "summary": {
        "total_tests": total_tests,
        "successful_executions": successful_executions,
        "conflict_count": conflict_count,
        "conflict_percentage": conflict_percentage,
        "conflict_test_numbers": conflicts
    }
}

with open("signal_conflict_results.json", "w") as f:
    json.dump(output, f, indent=2)

print("\nDetailed results saved to: signal_conflict_results.json")

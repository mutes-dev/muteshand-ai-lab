#!/usr/bin/env python3
"""
VALIDATOR_BLIND_SPOT_ANALYSIS
Identify where the validator FAILS to detect semantic mismatches.
30 runs total (10 inputs × 3 runs each).
NO system modifications - pure measurement.
"""

import json
from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator import trace_collector
from system.trace_utils.decision_viewer import build_decision_view
from system.trace_utils.retry_analyzer import analyze_retries
from system.trace_utils.step_timeline_viewer import build_step_timeline

# Test cases with expected outputs
test_cases = [
    {
        "input": "repeat \"abc\" 3 times but output only the count",
        "expected": "3",
        "check_type": "exact"
    },
    {
        "input": "repeat \"hello\" 4 times but return only the number",
        "expected": "4",
        "check_type": "exact"
    },
    {
        "input": "multiply 2 and 3 but respond in words",
        "expected": "six",
        "check_type": "contains"
    },
    {
        "input": "divide 10 by 2 but say if it is correct",
        "expected": "correct",
        "check_type": "contains"
    },
    {
        "input": "repeat \"test\" 5 times but return only the first word",
        "expected": "test",
        "check_type": "exact"
    },
    {
        "input": "add 2 and 3 but explain the result in a sentence",
        "expected": "5",
        "check_type": "contains"
    },
    {
        "input": "repeat \"xyz\" 3 times but return unique letters only",
        "expected": "xyz",
        "check_type": "exact"
    },
    {
        "input": "multiply 3 and 3 but give the result as a list",
        "expected": "[",
        "check_type": "contains"
    },
    {
        "input": "repeat \"fail\" 3 times but return nothing",
        "expected": "",
        "check_type": "exact"
    },
    {
        "input": "add 4 and 4 but output \"done\"",
        "expected": "done",
        "check_type": "exact"
    }
]

dataset = []

print("=" * 100)
print("VALIDATOR_BLIND_SPOT_ANALYSIS")
print("=" * 100)
print(f"Total planned runs: {len(test_cases) * 3}")
print()

run_counter = 0

for test_idx, test_case in enumerate(test_cases, 1):
    test_input = test_case["input"]
    expected = test_case["expected"]
    check_type = test_case["check_type"]
    
    print(f"\n--- Input {test_idx}/10: {test_input[:55]}... ---")
    print(f"  Expected: '{expected}' (check: {check_type})")
    
    for run_id in range(1, 4):  # 3 runs per input
        run_counter += 1
        print(f"  Run {run_id}/3...", end=" ")
        
        # Create workflow with ALL required fields
        workflow = {
            "id": f"blindspot_test_{test_idx}_{run_id}",
            "name": f"blindspot_test_{test_idx}_{run_id}",
            "status": "ACTIVE",
            "steps": [
                {
                    "id": f"step_{test_idx}_{run_id}",
                    "name": f"step_{test_idx}_{run_id}",
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
                print("[NO TRACE]")
                row = {
                    "input_num": test_idx,
                    "input": test_input,
                    "run_id": run_id,
                    "global_run_id": run_counter,
                    "execution_status": result.get("status", "unknown"),
                    "output": None,
                    "expected": expected,
                    "matches_expected": None,
                    "validator_advisory": "TRACE_MISSING",
                    "governance_decision": None,
                    "retries": 0,
                    "blind_spot": False,
                    "error": "no_trace"
                }
                dataset.append(row)
                continue
            
            # Extract signals from trace
            steps = trace.get("steps", [])
            
            # Find step execution record
            step_record = None
            for step in steps:
                if step.get("event") != "governance_decision" and step.get("governance_decision"):
                    step_record = step
                    break
            
            if not step_record:
                print("[NO STEP RECORD]")
                row = {
                    "input_num": test_idx,
                    "input": test_input,
                    "run_id": run_id,
                    "global_run_id": run_counter,
                    "execution_status": result.get("status", "unknown"),
                    "output": None,
                    "expected": expected,
                    "matches_expected": None,
                    "validator_advisory": "NO_STEP_RECORD",
                    "governance_decision": None,
                    "retries": 0,
                    "blind_spot": False,
                    "error": "no_step_record"
                }
                dataset.append(row)
                continue
            
            # Extract signals
            execution_result = step_record.get("execution_result", {})
            execution_status = execution_result.get("status") if isinstance(execution_result, dict) else None
            output = execution_result.get("result") if isinstance(execution_result, dict) else None
            
            validator_advisory = step_record.get("validator_advisory")
            governance_decision = step_record.get("governance_decision")
            retries = step_record.get("retries", 0)
            
            # Check if output matches expected
            output_str = str(output) if output is not None else ""
            
            if check_type == "exact":
                matches = output_str.strip() == expected
            elif check_type == "contains":
                matches = expected.lower() in output_str.lower()
            else:
                matches = None
            
            # Detect BLIND SPOT:
            # execution_result = success AND output does NOT match expected AND validator_advisory = None
            is_blind_spot = (
                execution_status == "success" and
                not matches and
                validator_advisory is None
            )
            
            status_marker = "[BLIND SPOT]" if is_blind_spot else f"[{'MATCH' if matches else 'MISMATCH'}]"
            print(f"{status_marker} Output='{output_str[:30]}...' Val={validator_advisory}")
            
            row = {
                "input_num": test_idx,
                "input": test_input,
                "run_id": run_id,
                "global_run_id": run_counter,
                "execution_status": execution_status,
                "output": output,
                "expected": expected,
                "matches_expected": matches,
                "validator_advisory": validator_advisory,
                "governance_decision": governance_decision,
                "retries": retries,
                "blind_spot": is_blind_spot,
                "error": None
            }
            dataset.append(row)
            
        except Exception as e:
            print(f"[ERROR: {type(e).__name__}]")
            row = {
                "input_num": test_idx,
                "input": test_input,
                "run_id": run_id,
                "global_run_id": run_counter,
                "execution_status": "error",
                "output": None,
                "expected": expected,
                "matches_expected": None,
                "validator_advisory": None,
                "governance_decision": None,
                "retries": 0,
                "blind_spot": False,
                "error": str(e)
            }
            dataset.append(row)

# Build summary
print("\n" + "=" * 100)
print("ANALYSIS COMPLETE")
print("=" * 100)

# Calculate statistics
total_runs = len(dataset)
successful_runs = [r for r in dataset if r["execution_status"] == "success"]
blind_spots = [r for r in dataset if r["blind_spot"]]
blind_spot_count = len(blind_spots)
blind_spot_percentage = (blind_spot_count / len(successful_runs) * 100) if successful_runs else 0

print("\n--- FULL DATASET ---")
print(f"{'#':<4} {'Input':<50} {'Run':<4} {'Exec':<8} {'Match':<6} {'Validator':<12} {'BlindSpot'}")
print("-" * 100)

for row in dataset:
    input_short = row["input"][:49]
    match_str = "YES" if row["matches_expected"] else ("NO" if row["matches_expected"] == False else "N/A")
    val_short = str(row["validator_advisory"])[:11] if row["validator_advisory"] else "None"
    print(f"{row['input_num']:<4} {input_short:<50} {row['run_id']:<4} {str(row['execution_status']):<8} {match_str:<6} {val_short:<12} {'YES' if row['blind_spot'] else 'NO'}")

print("\n--- METRICS ---")
print(f"Total runs: {total_runs}")
print(f"Successful executions: {len(successful_runs)}")
print(f"Blind spot count: {blind_spot_count}")
print(f"Blind spot percentage (of successful): {blind_spot_percentage:.1f}%")

# Pattern analysis
print("\n--- PATTERN ANALYSIS ---")

# By constraint type
constraint_patterns = {}
for row in blind_spots:
    input_text = row["input"]
    # Extract constraint pattern
    if "but" in input_text.lower():
        constraint = input_text.split("but")[-1].strip()
        constraint_patterns[constraint] = constraint_patterns.get(constraint, 0) + 1

if constraint_patterns:
    print("\nMissed constraint types (blind spots):")
    for constraint, count in sorted(constraint_patterns.items(), key=lambda x: -x[1]):
        print(f"  - '{constraint}': {count} occurrences")

# Consistency analysis
print("\nConsistency across runs:")
for test_idx in range(1, 11):
    runs_for_input = [r for r in dataset if r["input_num"] == test_idx]
    if len(runs_for_input) == 3:
        statuses = [r["execution_status"] for r in runs_for_input]
        matches = [r["matches_expected"] for r in runs_for_input]
        blind_spots_for_input = [r["blind_spot"] for r in runs_for_input]
        
        if len(set(str(s) for s in statuses)) > 1:
            print(f"  Input {test_idx}: INCONSISTENT status across runs")
        if len(set(str(m) for m in matches if m is not None)) > 1:
            print(f"  Input {test_idx}: INCONSISTENT match results across runs")
        if blind_spots_for_input.count(True) > 0 and blind_spots_for_input.count(True) < 3:
            print(f"  Input {test_idx}: PARTIAL blind spots ({blind_spots_for_input.count(True)}/3 runs)")

# Summary by input
print("\n--- BLIND SPOT SUMMARY BY INPUT ---")
for test_idx in range(1, 11):
    runs_for_input = [r for r in dataset if r["input_num"] == test_idx]
    blind_count = sum(1 for r in runs_for_input if r["blind_spot"])
    input_text = runs_for_input[0]["input"] if runs_for_input else "Unknown"
    print(f"  Input {test_idx}: {blind_count}/3 blind spots - {input_text[:50]}...")

print("\n" + "=" * 100)
print("VALIDATOR BLIND SPOT ANALYSIS COMPLETE")
print("=" * 100)

# Save detailed results
output = {
    "dataset": dataset,
    "summary": {
        "total_runs": total_runs,
        "successful_executions": len(successful_runs),
        "blind_spot_count": blind_spot_count,
        "blind_spot_percentage": blind_spot_percentage,
        "blind_spot_details": [
            {
                "input_num": r["input_num"],
                "run_id": r["run_id"],
                "input": r["input"],
                "output": r["output"],
                "expected": r["expected"]
            }
            for r in blind_spots
        ]
    }
}

with open("validator_blindspot_results.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\nDetailed results saved to: validator_blindspot_results.json")

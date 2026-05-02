#!/usr/bin/env python3
"""
VALIDATOR_GOVERNANCE_SIGNAL_ANALYSIS_MISMATCH
Measure validator vs governance under semantic mismatch conditions.
33 runs total (11 inputs × 3 runs each).
NO system modifications - pure measurement.
"""

import json
from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator import trace_collector
from system.trace_utils.decision_viewer import build_decision_view
from system.trace_utils.retry_analyzer import analyze_retries
from system.trace_utils.step_timeline_viewer import build_step_timeline

# Test cases - mismatch-focused
test_inputs = [
    "repeat \"hello\" 3 times and return a number",
    "repeat \"hello\" 3 times and explain the result",
    "calculate 2+2 and repeat \"hi\" 3 times",
    "repeat \"abc\" 3 times but output only the count",
    "multiply 3 and 3 and write it as a sentence",
    "repeat \"test\" 4 times but give the answer in words",
    "divide 10 by 2 and explain if it's correct",
    "repeat \"fail\" 3 times and summarize it",
    "write a sentence using the word \"hello\" 3 times",
    "double the word \"hello\"",
    "Tell me a joke"
]

dataset = []

print("=" * 90)
print("VALIDATOR_GOVERNANCE_SIGNAL_ANALYSIS_MISMATCH")
print("=" * 90)
print(f"Total planned runs: {len(test_inputs) * 3}")
print()

run_counter = 0

for test_idx, test_input in enumerate(test_inputs, 1):
    print(f"\n--- Input {test_idx}/11: {test_input[:50]}... ---")
    
    for run_id in range(1, 4):  # 3 runs per input
        run_counter += 1
        print(f"  Run {run_id}/3...", end=" ")
        
        # Create workflow with ALL required fields
        workflow = {
            "id": f"mismatch_test_{test_idx}_{run_id}",
            "name": f"mismatch_test_{test_idx}_{run_id}",
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
                    "type": "UNKNOWN",
                    "execution_status": result.get("status", "unknown"),
                    "execution_result": None,
                    "validator_advisory": "TRACE_MISSING",
                    "governance_decision": None,
                    "retries": 0,
                    "conflict": False,
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
                    "type": "UNKNOWN",
                    "execution_status": result.get("status", "unknown"),
                    "execution_result": None,
                    "validator_advisory": "NO_STEP_RECORD",
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
            
            # CLASSIFY TYPE: TOOL vs NON_TOOL
            # TOOL = uses tool execution (math, repeat, etc.)
            # NON_TOOL = pure language / sentence output
            step_input = step_record.get("input", "")
            
            # Check for tool indicators in executed_input or result
            type_classification = "UNKNOWN"
            if isinstance(execution_value, (int, float)):
                type_classification = "TOOL"
            elif isinstance(execution_value, str):
                # Check if it's a simple repetition vs natural language
                if execution_value.count("hello") > 0 or execution_value.count("test") > 0 or \
                   execution_value.count("abc") > 0 or execution_value.count("fail") > 0 or \
                   execution_value.count("hi") > 0:
                    # Check if it looks like just repeated text (tool) or has explanation (non-tool)
                    words = execution_value.split()
                    if len(words) <= 5 and all(w.isalpha() and len(w) < 20 for w in words if w.isalpha()):
                        type_classification = "TOOL"
                    else:
                        type_classification = "NON_TOOL"
                elif execution_value.replace(".", "").replace(" ", "").isdigit():
                    type_classification = "TOOL"
                else:
                    type_classification = "NON_TOOL"
            
            # Detect conflict:
            # execution_result = success AND validator_advisory = incorrect/incorrect_result AND governance = complete
            is_conflict = (
                execution_status == "success" and
                validator_advisory in ["incorrect", "incorrect_result"] and
                governance_decision == "complete"
            )
            
            status_marker = "[CONFLICT]" if is_conflict else f"[{execution_status}]"
            print(f"{status_marker} Type={type_classification} Gov={governance_decision}")
            
            row = {
                "input_num": test_idx,
                "input": test_input,
                "run_id": run_id,
                "global_run_id": run_counter,
                "type": type_classification,
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
            print(f"[ERROR: {type(e).__name__}]")
            row = {
                "input_num": test_idx,
                "input": test_input,
                "run_id": run_id,
                "global_run_id": run_counter,
                "type": "ERROR",
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
print("\n" + "=" * 90)
print("ANALYSIS COMPLETE")
print("=" * 90)

# Calculate statistics
total_runs = len(dataset)
conflict_count = sum(1 for r in dataset if r["conflict"])
conflict_percentage = (conflict_count / total_runs * 100) if total_runs > 0 else 0

tool_runs = [r for r in dataset if r["type"] == "TOOL"]
nontool_runs = [r for r in dataset if r["type"] == "NON_TOOL"]

tool_conflict_pct = (sum(1 for r in tool_runs if r["conflict"]) / len(tool_runs) * 100) if tool_runs else 0
nontool_conflict_pct = (sum(1 for r in nontool_runs if r["conflict"]) / len(nontool_runs) * 100) if nontool_runs else 0

print("\n--- FULL DATASET ---")
print(f"{'#':<4} {'Input':<40} {'Run':<4} {'Type':<8} {'Exec':<8} {'Validator':<12} {'Gov':<10} {'Conflict'}")
print("-" * 95)

for row in dataset:
    input_short = row["input"][:39]
    val_short = str(row["validator_advisory"])[:11] if row["validator_advisory"] else "None"
    print(f"{row['input_num']:<4} {input_short:<40} {row['run_id']:<4} {row['type']:<8} {str(row['execution_status']):<8} {val_short:<12} {str(row['governance_decision']):<10} {'YES' if row['conflict'] else 'NO'}")

print("\n--- OVERALL STATISTICS ---")
print(f"Total runs: {total_runs}")
print(f"Conflict count: {conflict_count}")
print(f"Conflict percentage: {conflict_percentage:.1f}%")

print("\n--- BY TYPE ---")
print(f"TOOL runs: {len(tool_runs)}")
print(f"  - TOOL conflict %: {tool_conflict_pct:.1f}%")
print(f"NON_TOOL runs: {len(nontool_runs)}")
print(f"  - NON_TOOL conflict %: {nontool_conflict_pct:.1f}%")

# Patterns
print("\n--- OBSERVED PATTERNS ---")

# Validator triggers
validator_triggers = {}
for row in dataset:
    val = row["validator_advisory"]
    if val and val not in ["TRACE_MISSING", "NO_STEP_RECORD"]:
        validator_triggers[val] = validator_triggers.get(val, 0) + 1

print("\nValidator advisory distribution:")
for val, count in sorted(validator_triggers.items()):
    print(f"  - {val}: {count}")

# Retry effectiveness
retries_used = sum(1 for r in dataset if r["retries"] > 0)
print(f"\nRetries used: {retries_used}/{total_runs} runs")

# Inconsistent runs (same input, different results)
inconsistencies = []
for test_idx in range(1, 12):
    runs_for_input = [r for r in dataset if r["input_num"] == test_idx]
    if len(runs_for_input) >= 2:
        statuses = set(str(r["execution_status"]) for r in runs_for_input)
        types = set(r["type"] for r in runs_for_input)
        if len(statuses) > 1 or len(types) > 1:
            inconsistencies.append({
                "input_num": test_idx,
                "input": runs_for_input[0]["input"],
                "statuses": list(statuses),
                "types": list(types)
            })

if inconsistencies:
    print(f"\nInconsistent runs (same input, different behavior): {len(inconsistencies)}")
    for inc in inconsistencies:
        print(f"  - Input {inc['input_num']}: statuses={inc['statuses']}, types={inc['types']}")
else:
    print("\nInconsistent runs: None detected")

print("\n" + "=" * 90)
print("SIGNAL MISMATCH ANALYSIS COMPLETE")
print("=" * 90)

# Save detailed results
output = {
    "dataset": dataset,
    "summary": {
        "total_runs": total_runs,
        "conflict_count": conflict_count,
        "conflict_percentage": conflict_percentage,
        "tool_runs": len(tool_runs),
        "tool_conflict_percentage": tool_conflict_pct,
        "nontool_runs": len(nontool_runs),
        "nontool_conflict_percentage": nontool_conflict_pct,
        "inconsistencies": inconsistencies
    }
}

with open("signal_mismatch_results.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\nDetailed results saved to: signal_mismatch_results.json")

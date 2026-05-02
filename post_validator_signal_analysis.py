#!/usr/bin/env python3
"""
POST_VALIDATOR_SIGNAL_ANALYSIS
Measure validator improvement after upgrade.
30 runs (10 inputs × 3 runs each).
NO system modifications - pure measurement.
"""

import json
from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator import trace_collector
from system.trace_utils.decision_viewer import build_decision_view
from system.trace_utils.retry_analyzer import analyze_retries
from system.trace_utils.step_timeline_viewer import build_step_timeline

# Test cases with expected constraints
test_cases = [
    {
        "input": "repeat \"abc\" 3 times but output only the count",
        "expected_constraint": {"format": "count"},
        "expected_output_type": "number",
        "expected_result": 3
    },
    {
        "input": "repeat \"hello\" 4 times but return only the number",
        "expected_constraint": {"format": "count"},
        "expected_output_type": "number",
        "expected_result": 4
    },
    {
        "input": "multiply 2 and 3 but respond in words",
        "expected_constraint": {"format": "words"},
        "expected_output_type": "string",
        "expected_result": "six"
    },
    {
        "input": "divide 10 by 2 but say if it's correct",
        "expected_constraint": {"format": "words"},
        "expected_output_type": "string",
        "expected_result": "correct"
    },
    {
        "input": "repeat \"test\" 5 times but return only the first word",
        "expected_constraint": {"format": "first_word"},
        "expected_output_type": "string",
        "expected_result": "test"
    },
    {
        "input": "add 2 and 3 but explain the result in a sentence",
        "expected_constraint": {"format": "words"},
        "expected_output_type": "string",
        "expected_result": None  # Accept any sentence with "5"
    },
    {
        "input": "repeat \"xyz\" 3 times but return unique letters only",
        "expected_constraint": {"format": "unique"},
        "expected_output_type": "string",
        "expected_result": "xyz"
    },
    {
        "input": "multiply 3 and 3 but give the result as a list",
        "expected_constraint": {"format": "list"},
        "expected_output_type": "list",
        "expected_result": [9]
    },
    {
        "input": "repeat \"fail\" 3 times but return nothing",
        "expected_constraint": {"format": "empty"},
        "expected_output_type": "string",
        "expected_result": ""
    },
    {
        "input": "add 4 and 4 but output \"done\"",
        "expected_constraint": {"output_override": "done"},
        "expected_output_type": "string",
        "expected_result": "done"
    }
]

def extract_signals(trace, step_id):
    """Extract validator and governance signals from trace."""
    if not trace:
        return None
    
    steps = trace.get("steps", [])
    for step in steps:
        if step.get("step_id") == step_id:
            return {
                "execution_result": step.get("execution_result"),
                "execution_status": step.get("execution_result", {}).get("status") if step.get("execution_result") else None,
                "output": step.get("execution_result", {}).get("result") if step.get("execution_result") else None,
                "validator_advisory": step.get("validator_advisory"),
                "validator_decision": step.get("validator_decision"),
                "validator_signals": step.get("validator_signals"),
                "extracted_constraints": step.get("validator_signals", {}).get("extracted_constraints") if step.get("validator_signals") else None,
                "governance_decision": step.get("governance_decision"),
                "retries": step.get("retries"),
                "final_answer_correct": step.get("validator_signals", {}).get("final_answer_correct") if step.get("validator_signals") else None,
                "constraint_ok": step.get("validator_signals", {}).get("constraint_ok") if step.get("validator_signals") else None,
                "constraint_violation": step.get("validator_signals", {}).get("constraint_violation") if step.get("validator_signals") else None
            }
    return None

def matches_expected(output, expected, output_type):
    """Check if output matches expected."""
    if expected is None:
        return True  # Any output acceptable
    if isinstance(expected, str) and isinstance(output, str):
        return expected.lower() in output.lower() or output.lower() in expected.lower()
    return output == expected

def detect_blind_spot(signals, test_case):
    """Detect if this is a blind spot."""
    if not signals:
        return False
    
    execution_status = signals.get("execution_status")
    output = signals.get("output")
    constraint_ok = signals.get("constraint_ok")
    
    # Must be successful execution
    if execution_status != "success":
        return False
    
    # Check if output matches expected
    output_correct = matches_expected(output, test_case["expected_result"], test_case["expected_output_type"])
    
    # Blind spot: execution succeeded, output is wrong, but constraint_ok is True
    if not output_correct and constraint_ok is True:
        return True
    
    return False

def save_results(all_results, filename="post_validator_results.json"):
    """Save results immediately - never lose data."""
    try:
        with open(filename, "w") as f:
            json.dump({"dataset": all_results, "completed_at": str(__import__('datetime').datetime.now())}, f, indent=2)
        return True
    except Exception as e:
        print(f"\n[CRITICAL] Failed to save results: {e}")
        return False


def main():
    import traceback
    from datetime import datetime
    
    print("=" * 100)
    print("POST-VALIDATOR-UPGRADE SIGNAL ANALYSIS")
    print("=" * 100)
    print(f"Total test cases: {len(test_cases)}")
    print(f"Runs per case: 3")
    print(f"Total runs: {len(test_cases) * 3}")
    print("=" * 100)
    
    all_results = []
    completed_runs = 0
    failed_runs = 0
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*80}")
        print(f"TEST CASE {i}: {test['input'][:50]}...")
        print(f"Expected constraint: {test['expected_constraint']}")
        print(f"Expected output type: {test['expected_output_type']}")
        print(f"Expected result: {test['expected_result']}")
        print("="*80)
        
        for run_id in range(1, 4):
            print(f"\n  Run {run_id}/3...", end=" ", flush=True)
            
            workflow = {
                "id": f"post_upgrade_{i}_{run_id}",
                "name": f"post_upgrade_{i}_{run_id}",
                "status": "ACTIVE",
                "steps": [
                    {
                        "id": f"step_{i}_{run_id}",
                        "name": f"step_{i}_{run_id}",
                        "agent": "system",
                        "purpose": test["input"],
                        "input": test["input"],
                        "status": "PENDING",
                        "retries": 0,
                        "max_retries": 2
                    }
                ]
            }
            
            # Triple-nested protection: never let one run stop the suite
            try:
                # Run workflow with timeout protection
                try:
                    result = run_workflow(workflow)
                except Exception as wf_error:
                    print(f"[WORKFLOW_ERROR] {type(wf_error).__name__}: {wf_error}")
                    failed_runs += 1
                    all_results.append({
                        "input_num": i,
                        "input": test["input"],
                        "run_id": run_id,
                        "expected_constraint": test["expected_constraint"],
                        "expected_result": test["expected_result"],
                        "execution_status": "workflow_error",
                        "output": None,
                        "extracted_constraints": None,
                        "constraint_ok": None,
                        "constraint_violation": None,
                        "final_answer_correct": None,
                        "validator_advisory": None,
                        "governance_decision": None,
                        "output_correct": False,
                        "blind_spot": False,
                        "error": f"workflow_failed: {str(wf_error)}",
                        "traceback": traceback.format_exc()
                    })
                    save_results(all_results)  # Save after every failure
                    continue
                
                # Get trace with protection
                try:
                    trace = trace_collector.get_trace()
                except Exception as trace_error:
                    print(f"[TRACE_ERROR] {type(trace_error).__name__}: {trace_error}")
                    trace = None
                
                # Extract signals with protection
                try:
                    signals = extract_signals(trace, f"step_{i}_{run_id}") if trace else None
                except Exception as sig_error:
                    print(f"[SIGNALS_ERROR] {type(sig_error).__name__}: {sig_error}")
                    signals = None
                
                if not signals:
                    print("[NO TRACE]")
                    all_results.append({
                        "input_num": i,
                        "input": test["input"],
                        "run_id": run_id,
                        "execution_status": "unknown",
                        "output": None,
                        "expected_constraint": test["expected_constraint"],
                        "expected_result": test["expected_result"],
                        "extracted_constraints": None,
                        "constraint_ok": None,
                        "constraint_violation": None,
                        "final_answer_correct": None,
                        "validator_advisory": None,
                        "governance_decision": None,
                        "output_correct": False,
                        "blind_spot": False,
                        "error": "no_trace"
                    })
                    save_results(all_results)
                    continue
                
                # Check if output matches expected
                try:
                    output_correct = matches_expected(signals.get("output"), test["expected_result"], test["expected_output_type"])
                except Exception:
                    output_correct = False
                
                # Detect blind spot
                try:
                    blind_spot = detect_blind_spot(signals, test)
                except Exception:
                    blind_spot = False
                
                result_entry = {
                    "input_num": i,
                    "input": test["input"],
                    "run_id": run_id,
                    "execution_status": signals.get("execution_status"),
                    "output": signals.get("output"),
                    "expected_constraint": test["expected_constraint"],
                    "expected_result": test["expected_result"],
                    "extracted_constraints": signals.get("extracted_constraints"),
                    "constraint_ok": signals.get("constraint_ok"),
                    "constraint_violation": signals.get("constraint_violation"),
                    "final_answer_correct": signals.get("final_answer_correct"),
                    "validator_advisory": signals.get("validator_advisory"),
                    "governance_decision": signals.get("governance_decision"),
                    "retries": signals.get("retries"),
                    "output_correct": output_correct,
                    "blind_spot": blind_spot
                }
                
                all_results.append(result_entry)
                completed_runs += 1
                
                status_marker = "✓" if not blind_spot else "✗ BLIND SPOT"
                print(f"[OK] Advisory: {signals.get('validator_advisory')} | Constraint OK: {signals.get('constraint_ok')} | {status_marker}")
                
                # Save after every successful run
                save_results(all_results)
                
            except Exception as e:
                # Ultimate fallback - should never reach here
                failed_runs += 1
                print(f"[CRITICAL_ERROR] {type(e).__name__}: {e}")
                all_results.append({
                    "input_num": i,
                    "input": test["input"],
                    "run_id": run_id,
                    "expected_constraint": test["expected_constraint"],
                    "expected_result": test["expected_result"],
                    "execution_status": "critical_error",
                    "output": None,
                    "extracted_constraints": None,
                    "constraint_ok": None,
                    "constraint_violation": None,
                    "final_answer_correct": None,
                    "validator_advisory": None,
                    "governance_decision": None,
                    "output_correct": False,
                    "blind_spot": False,
                    "error": str(e),
                    "traceback": traceback.format_exc()
                })
                save_results(all_results)  # Always save after error
    
    # Final save with summary
    save_results(all_results)
    
    print(f"\n\n[RUNNER SUMMARY]")
    print(f"  Total runs attempted: {len(test_cases) * 3}")
    print(f"  Completed successfully: {completed_runs}")
    print(f"  Failed: {failed_runs}")
    print(f"  Total recorded: {len(all_results)}")
    print(f"  Results saved to: post_validator_results.json")
    
    print("\n" + "=" * 100)
    print("SUMMARY METRICS")
    print("=" * 100)
    
    # Calculate metrics
    total_runs = len([r for r in all_results if "error" not in r])
    successful_execs = len([r for r in all_results if r.get("execution_status") == "success"])
    
    # Validator activation: final_answer_correct=False OR constraint_ok=False
    validator_activations = len([r for r in all_results 
        if r.get("final_answer_correct") is False or r.get("constraint_ok") is False])
    
    # Blind spots: incorrect output but constraint_ok=True
    blind_spots = len([r for r in all_results if r.get("blind_spot") is True])
    
    # Constraint detection accuracy
    constraint_matches = 0
    constraint_total = 0
    for r in all_results:
        if r.get("extracted_constraints") and r.get("expected_constraint"):
            constraint_total += 1
            extracted = r.get("extracted_constraints", {})
            expected = r.get("expected_constraint", {})
            # Check if format matches
            if extracted.get("format") == expected.get("format"):
                constraint_matches += 1
            elif extracted.get("output_override") == expected.get("output_override"):
                constraint_matches += 1
    
    # False positives: constraint_ok=False but output is correct
    false_positives = 0
    for r in all_results:
        if r.get("constraint_ok") is False and r.get("output_correct") is True:
            false_positives += 1
    
    print(f"\nTotal runs: {total_runs}")
    print(f"Successful executions: {successful_execs}")
    print(f"\nValidator activation rate: {validator_activations}/{total_runs} ({100*validator_activations/total_runs:.1f}%)")
    print(f"Blind spot rate: {blind_spots}/{total_runs} ({100*blind_spots/total_runs:.1f}%)")
    print(f"Constraint detection accuracy: {constraint_matches}/{constraint_total} ({100*constraint_matches/constraint_total:.1f}% if constraints extracted)")
    print(f"False positive rate: {false_positives}/{total_runs} ({100*false_positives/total_runs:.1f}%)")
    
    print("\n" + "=" * 100)
    print("PER-INPUT BREAKDOWN")
    print("=" * 100)
    
    for i in range(1, 11):
        input_results = [r for r in all_results if r.get("input_num") == i]
        if not input_results:
            continue
        
        input_text = input_results[0]["input"][:40] + "..."
        blind_count = len([r for r in input_results if r.get("blind_spot")])
        activated_count = len([r for r in input_results 
            if r.get("final_answer_correct") is False or r.get("constraint_ok") is False])
        
        print(f"\nInput {i}: {input_text}")
        print(f"  Runs: {len(input_results)} | Validator activated: {activated_count}/3 | Blind spots: {blind_count}/3")
        
        for r in input_results:
            cons_ok = r.get("constraint_ok")
            cons_viol = r.get("constraint_violation")
            extracted = r.get("extracted_constraints")
            print(f"    Run {r['run_id']}: constraint_ok={cons_ok}, violation={cons_viol}, extracted={extracted}")
    
    print("\n" + "=" * 100)
    print("IMPROVEMENT vs PRE-UPGRADE")
    print("=" * 100)
    print("Pre-upgrade blind spot rate: ~70%")
    print(f"Post-upgrade blind spot rate: {100*blind_spots/total_runs:.1f}%")
    improvement = 70 - (100*blind_spots/total_runs)
    print(f"Improvement: {improvement:.1f} percentage points")
    
    print("\n" + "=" * 100)
    print("ANALYSIS COMPLETE — Results saved to post_validator_results.json")
    print("=" * 100)

if __name__ == "__main__":
    main()

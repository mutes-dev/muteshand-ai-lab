#!/usr/bin/env python3
"""
POST_FIX_VALIDATOR_ANALYSIS
Measure behavior after constraint extraction fix.
30 runs (10 inputs × 3 runs each).
NO system modifications - pure measurement.
"""

import json
from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator import trace_collector

# Test cases (same as before)
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
        "expected_result": None
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
                "structured_constraints": step.get("validator_signals", {}).get("structured_constraints") if step.get("validator_signals") else None,
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
        return True
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
    
    if execution_status != "success":
        return False
    
    output_correct = matches_expected(output, test_case["expected_result"], test_case["expected_output_type"])
    
    if not output_correct and constraint_ok is True:
        return True
    
    return False

def main():
    print("=" * 100)
    print("POST_FIX_VALIDATOR_ANALYSIS")
    print("=" * 100)
    print(f"Total test cases: {len(test_cases)}")
    print(f"Runs per case: 3")
    print(f"Total runs: {len(test_cases) * 3}")
    print("=" * 100)
    
    all_results = []
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*80}")
        print(f"TEST CASE {i}: {test['input'][:50]}...")
        print(f"Expected constraint: {test['expected_constraint']}")
        print("="*80)
        
        for run_id in range(1, 4):
            print(f"\n  Run {run_id}/3...", end=" ", flush=True)
            
            workflow = {
                "id": f"post_fix_{i}_{run_id}",
                "name": f"post_fix_{i}_{run_id}",
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
            
            try:
                result = run_workflow(workflow)
                trace = trace_collector.get_trace()
                signals = extract_signals(trace, f"step_{i}_{run_id}")
                
                if not signals:
                    print("[NO TRACE]")
                    continue
                
                output_correct = matches_expected(signals.get("output"), test["expected_result"], test["expected_output_type"])
                blind_spot = detect_blind_spot(signals, test)
                
                result_entry = {
                    "input_num": i,
                    "input": test["input"],
                    "run_id": run_id,
                    "execution_status": signals.get("execution_status"),
                    "output": signals.get("output"),
                    "expected_constraint": test["expected_constraint"],
                    "expected_result": test["expected_result"],
                    "extracted_constraints": signals.get("extracted_constraints"),
                    "structured_constraints": signals.get("structured_constraints"),
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
                
                status = "OK" if not blind_spot else "BLIND SPOT"
                print(f"[OK] Constraints: {signals.get('extracted_constraints')} | Struct: {signals.get('structured_constraints')} | Constraint OK: {signals.get('constraint_ok')} | {status}")
                
            except Exception as e:
                print(f"[ERROR] {type(e).__name__}: {e}")
    
    # Save dataset
    with open("post_fix_results.json", "w") as f:
        json.dump({"dataset": all_results}, f, indent=2)
    
    # Calculate metrics
    total_runs = len([r for r in all_results if "error" not in r])
    successful_execs = len([r for r in all_results if r.get("execution_status") == "success"])
    
    validator_activations = len([r for r in all_results 
        if r.get("final_answer_correct") is False or r.get("constraint_ok") is False])
    
    blind_spots = len([r for r in all_results if r.get("blind_spot") is True])
    
    has_constraints = len([r for r in all_results if r.get("extracted_constraints") and r.get("extracted_constraints") != {}])
    has_structured = len([r for r in all_results if r.get("structured_constraints") and len(r.get("structured_constraints", [])) > 0])
    
    false_positives = len([r for r in all_results if r.get("constraint_ok") is False and r.get("output_correct") is True])
    
    print("\n" + "=" * 100)
    print("METRICS SUMMARY")
    print("=" * 100)
    
    print(f"\nTotal runs: {total_runs}")
    print(f"Successful executions: {successful_execs}")
    
    print(f"\n--- PRE-FIX vs POST-FIX COMPARISON ---")
    print(f"Pre-fix blind spot rate: 70.0%")
    print(f"Post-fix blind spot rate: {100*blind_spots/total_runs:.1f}%")
    improvement = 70.0 - (100*blind_spots/total_runs)
    print(f"Improvement: {improvement:+.1f} percentage points")
    
    print(f"\n--- POST-FIX METRICS ---")
    print(f"Validator activation rate: {validator_activations}/{total_runs} ({100*validator_activations/total_runs:.1f}%)")
    print(f"Blind spot rate: {blind_spots}/{total_runs} ({100*blind_spots/total_runs:.1f}%)")
    print(f"Extraction success (legacy): {has_constraints}/{total_runs} ({100*has_constraints/total_runs:.1f}%)")
    print(f"Extraction success (structured): {has_structured}/{total_runs} ({100*has_structured/total_runs:.1f}%)")
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
        has_cons = len([r for r in input_results if r.get("extracted_constraints") and r.get("extracted_constraints") != {}])
        has_struct = len([r for r in input_results if r.get("structured_constraints") and len(r.get("structured_constraints", [])) > 0])
        
        print(f"\nInput {i}: {input_text}")
        print(f"  Runs: 3 | Extraction (legacy): {has_cons}/3 | Extraction (structured): {has_struct}/3 | Blind spots: {blind_count}/3")
    
    print("\n" + "=" * 100)
    print("KEY OBSERVATIONS")
    print("=" * 100)
    
    if has_constraints > 0:
        print(f"✅ Legacy extraction now working: {has_constraints}/{total_runs} runs have constraints")
    else:
        print(f"❌ Legacy extraction still failing: 0/{total_runs} runs have constraints")
    
    if has_structured > 0:
        print(f"✅ Structured extraction working: {has_structured}/{total_runs} runs have structured constraints")
    else:
        print(f"❌ Structured extraction failing: 0/{total_runs} runs have structured constraints")
    
    if blind_spots < 21:
        print(f"✅ Blind spots reduced: {blind_spots}/30 vs 21/30 pre-fix")
    else:
        print(f"❌ Blind spots unchanged: {blind_spots}/30 (same as pre-fix)")
    
    print("\n" + "=" * 100)
    print("ANALYSIS COMPLETE — Results saved to post_fix_results.json")
    print("=" * 100)

if __name__ == "__main__":
    main()

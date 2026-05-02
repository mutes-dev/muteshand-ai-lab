#!/usr/bin/env python3
"""
FINAL_VALIDATOR_BEHAVIOR_ANALYSIS
Measure actual validator behavior after extraction and trace fixes.
"""

import json
from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator import trace_collector

# Test cases
test_cases = [
    {"input": "repeat \"abc\" 3 times but output only the count", "expected": 3, "type": "number"},
    {"input": "repeat \"hello\" 4 times but return only the number", "expected": 4, "type": "number"},
    {"input": "multiply 2 and 3 but respond in words", "expected": "six", "type": "string"},
    {"input": "divide 10 by 2 but say if it's correct", "expected": "correct", "type": "string"},
    {"input": "repeat \"test\" 5 times but return only the first word", "expected": "test", "type": "string"},
    {"input": "add 2 and 3 but explain the result in a sentence", "expected": None, "type": "any"},
    {"input": "repeat \"xyz\" 3 times but return unique letters only", "expected": "xyz", "type": "string"},
    {"input": "multiply 3 and 3 but give the result as a list", "expected": [9], "type": "list"},
    {"input": "repeat \"fail\" 3 times but return nothing", "expected": "", "type": "string"},
    {"input": "add 4 and 4 but output \"done\"", "expected": "done", "type": "string"}
]

def check_output_match(actual, expected, out_type):
    if expected is None:
        return True
    if out_type == "string" and isinstance(actual, str) and isinstance(expected, str):
        return expected.lower() in actual.lower()
    return actual == expected

def main():
    print("=" * 100)
    print("FINAL VALIDATOR BEHAVIOR ANALYSIS")
    print("=" * 100)
    print(f"Test cases: {len(test_cases)}")
    print(f"Runs per case: 3")
    print(f"Total runs: {len(test_cases) * 3}")
    print("=" * 100)
    
    all_results = []
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*80}")
        print(f"TEST {i}: {test['input'][:55]}...")
        print(f"Expected: {test['expected']}")
        print("="*80)
        
        for run_id in range(1, 4):
            print(f"\n  Run {run_id}/3...", end=" ", flush=True)
            
            workflow = {
                "id": f"final_{i}_{run_id}",
                "name": f"final_{i}_{run_id}",
                "status": "ACTIVE",
                "steps": [{
                    "id": f"step_{i}_{run_id}",
                    "name": f"step_{i}_{run_id}",
                    "agent": "system",
                    "purpose": test["input"],
                    "input": test["input"],
                    "status": "PENDING",
                    "retries": 0,
                    "max_retries": 2
                }]
            }
            
            try:
                result = run_workflow(workflow)
                trace = trace_collector.get_trace()
                
                if not trace:
                    print("[NO TRACE]")
                    continue
                
                # Find our step
                step_data = None
                for step in trace.get("steps", []):
                    if step.get("step_id") == f"step_{i}_{run_id}":
                        step_data = step
                        break
                
                if not step_data:
                    print("[STEP NOT FOUND]")
                    continue
                
                # Extract all fields
                execution_result = step_data.get("execution_result")
                output = execution_result.get("result") if execution_result else None
                status = execution_result.get("status") if execution_result else None
                
                validator_signals = step_data.get("validator_signals", {})
                extracted_constraints = validator_signals.get("extracted_constraints") if validator_signals else None
                structured_constraints = validator_signals.get("structured_constraints") if validator_signals else None
                constraint_ok = validator_signals.get("constraint_ok") if validator_signals else None
                constraint_violation = validator_signals.get("constraint_violation") if validator_signals else None
                final_answer_correct = validator_signals.get("final_answer_correct") if validator_signals else None
                
                validator_advisory = step_data.get("validator_advisory")
                validator_decision = step_data.get("validator_decision")
                governance_decision = step_data.get("governance_decision")
                
                # Check correctness
                output_correct = check_output_match(output, test["expected"], test["type"])
                
                # Detect blind spot
                blind_spot = (status == "success" and not output_correct and constraint_ok is True)
                
                result_entry = {
                    "input_num": i,
                    "input": test["input"],
                    "run_id": run_id,
                    "execution_status": status,
                    "output": output,
                    "expected": test["expected"],
                    "output_correct": output_correct,
                    "extracted_constraints": extracted_constraints,
                    "structured_constraints": structured_constraints,
                    "constraint_ok": constraint_ok,
                    "constraint_violation": constraint_violation,
                    "final_answer_correct": final_answer_correct,
                    "validator_advisory": validator_advisory,
                    "validator_decision": validator_decision,
                    "governance_decision": governance_decision,
                    "blind_spot": blind_spot
                }
                
                all_results.append(result_entry)
                
                marker = "OK" if not blind_spot else "BLIND"
                cons_str = str(extracted_constraints)[:30] if extracted_constraints else "None"
                print(f"[{marker}] Ex: {cons_str:<30} | OK: {constraint_ok} | Adv: {validator_advisory}")
                
            except Exception as e:
                print(f"[ERROR: {type(e).__name__}]")
                all_results.append({
                    "input_num": i,
                    "input": test["input"],
                    "run_id": run_id,
                    "error": str(e)
                })
    
    # Save dataset
    with open("final_validator_results.json", "w") as f:
        json.dump({"dataset": all_results}, f, indent=2)
    
    print("\n" + "=" * 100)
    print("METRICS SUMMARY")
    print("=" * 100)
    
    valid_runs = [r for r in all_results if "error" not in r]
    total = len(valid_runs)
    
    if total == 0:
        print("\nNo valid runs to analyze.")
        return
    
    # Calculate metrics
    successful_execs = len([r for r in valid_runs if r.get("execution_status") == "success"])
    
    # Validator activation: final_answer_correct=False OR constraint_ok=False
    activated = len([r for r in valid_runs 
        if r.get("final_answer_correct") is False or r.get("constraint_ok") is False])
    
    # Blind spots
    blind_spots = len([r for r in valid_runs if r.get("blind_spot") is True])
    
    # Constraint extraction success
    has_constraints = len([r for r in valid_runs 
        if r.get("extracted_constraints") and r.get("extracted_constraints") != {}])
    has_structured = len([r for r in valid_runs 
        if r.get("structured_constraints") and len(r.get("structured_constraints", [])) > 0])
    
    # False positives
    false_positives = len([r for r in valid_runs 
        if r.get("constraint_ok") is False and r.get("output_correct") is True])
    
    print(f"\nTotal valid runs: {total}")
    print(f"Successful executions: {successful_execs}")
    
    print(f"\n--- COMPARISON ---")
    print(f"Pre-fix blind spot rate: 70.0%")
    print(f"Post-fix blind spot rate: {100*blind_spots/total:.1f}%")
    improvement = 70.0 - (100*blind_spots/total)
    print(f"Improvement: {improvement:+.1f} percentage points")
    
    print(f"\n--- POST-FIX METRICS ---")
    print(f"Validator activation rate: {activated}/{total} ({100*activated/total:.1f}%)")
    print(f"Blind spot rate: {blind_spots}/{total} ({100*blind_spots/total:.1f}%)")
    print(f"Constraint extraction (legacy): {has_constraints}/{total} ({100*has_constraints/total:.1f}%)")
    print(f"Constraint extraction (structured): {has_structured}/{total} ({100*has_structured/total:.1f}%)")
    print(f"False positive rate: {false_positives}/{total} ({100*false_positives/total:.1f}%)")
    
    print("\n" + "=" * 100)
    print("PER-INPUT BREAKDOWN")
    print("=" * 100)
    
    for i in range(1, 11):
        input_runs = [r for r in valid_runs if r.get("input_num") == i]
        if not input_runs:
            continue
        
        text = input_runs[0]["input"][:40] + "..."
        blind_count = len([r for r in input_runs if r.get("blind_spot")])
        has_cons = len([r for r in input_runs if r.get("extracted_constraints") and r.get("extracted_constraints") != {}])
        
        print(f"\nInput {i}: {text}")
        print(f"  Runs: {len(input_runs)} | Extraction: {has_cons}/3 | Blind spots: {blind_count}/3")
        for r in input_runs:
            cons = str(r.get("extracted_constraints"))[:25]
            print(f"    Run {r['run_id']}: {cons:<25} | OK={r.get('constraint_ok')} | {r.get('validator_advisory')}")
    
    print("\n" + "=" * 100)
    print("KEY OBSERVATIONS")
    print("=" * 100)
    
    if has_constraints > 0:
        print(f"✅ Legacy extraction working: {has_constraints}/{total} runs")
    else:
        print(f"❌ Legacy extraction failed: 0/{total} runs")
    
    if has_structured > 0:
        print(f"✅ Structured extraction working: {has_structured}/{total} runs")
    else:
        print(f"❌ Structured extraction failed: 0/{total} runs")
    
    if blind_spots < 21:  # Pre-fix was 21/30 = 70%
        print(f"✅ Blind spots REDUCED: {blind_spots}/30 (was 21/30)")
    elif blind_spots == 0:
        print(f"✅ Blind spots ELIMINATED: 0/30")
    else:
        print(f"⚠️ Blind spots still present: {blind_spots}/30")
    
    print("\n" + "=" * 100)
    print("ANALYSIS COMPLETE — Results saved to final_validator_results.json")
    print("=" * 100)

if __name__ == "__main__":
    main()

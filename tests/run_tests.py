import sys
import argparse
from concurrent.futures import ProcessPoolExecutor
from test_cases import TEST_CASES
from test_runner import run_test
from result_evaluator import evaluate_result
from reporter import print_report


def execute_layer(layer_name: str, selected_test: str = None):
    print(f"[HARNESS] Executing layer: {layer_name}")
    
    results = []
    
    for test in TEST_CASES:
        if selected_test and test["name"] != selected_test:
            continue
        
        if "layer" in test and test["layer"] != layer_name:
            continue
        
        output = run_test(test["input"])
        evaluation = evaluate_result(output, test["expected"])
        
        results.append({
            "name": test["name"],
            "evaluation": evaluation,
            "expected": test["expected"]
        })
    
    print_report(results)


def run_execution_layer(selected_test=None):
    execute_layer("execution", selected_test)


def run_validation_layer(selected_test=None):
    execute_layer("validation", selected_test)


def run_planner_layer(selected_test=None):
    execute_layer("planner", selected_test)


def main():
    print("AI LAB — TEST HARNESS ENTRY POINT")
    
    parser = argparse.ArgumentParser(description="AI Lab Test Harness")
    parser.add_argument(
        "--layer",
        type=str,
        default="all",
        choices=["execution", "validation", "planner", "all"],
        help="Select test layer to run"
    )
    parser.add_argument(
        "--test",
        type=str,
        help="Run a single test by name"
    )
    
    args = parser.parse_args()
    
    if args.layer == "execution":
        run_execution_layer(args.test)
    
    elif args.layer == "validation":
        run_validation_layer(args.test)
    
    elif args.layer == "planner":
        run_planner_layer(args.test)
    
    elif args.layer == "all":
        print("[HARNESS] Running all layers in parallel")
        
        with ProcessPoolExecutor() as executor:
            futures = [
                executor.submit(run_execution_layer, args.test),
                executor.submit(run_validation_layer, args.test),
                executor.submit(run_planner_layer, args.test)
            ]
            
            for future in futures:
                future.result()


if __name__ == "__main__":
    main()

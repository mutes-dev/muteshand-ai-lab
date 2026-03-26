TEST_CASES = [
    # VALID EXECUTION TESTS
    {
        "name": "exec_basic_add",
        "input": "add 2 and 3",
        "expected": {"status": "success", "result": "5"},
        "layer": "execution"
    },
    {
        "name": "exec_chain_add_multiply",
        "input": "add 2 and 3 then multiply by 4",
        "expected": {"status": "success", "result": "20"},
        "layer": "execution"
    },
    
    # VALIDATION FAILURE TESTS
    {
        "name": "val_missing_args",
        "input": "multiply by",
        "expected": {"status": "failure"},
        "layer": "validation"
    },
    {
        "name": "val_invalid_input",
        "input": "add x and y",
        "expected": {"status": "failure"},
        "layer": "validation"
    },
    
    # RETRY / FAILURE BEHAVIOR
    {
        "name": "fail_retry_exhaustion",
        "input": "add x and y repeatedly",
        "expected": {"status": "failure"},
        "layer": "planner"
    },
    
    # DEDUPLICATION
    {
        "name": "fail_duplicate_plan",
        "input": "repeat the same invalid plan multiple times",
        "expected": {"status": "failure"},
        "layer": "planner"
    },
    
    # CHAINING TESTS
    {
        "name": "chain_previous_result",
        "input": "add 2 and 3 then multiply the result by 4",
        "expected": {"status": "success", "result": "20"},
        "layer": "execution"
    },
    {
        "name": "chain_missing_previous",
        "input": "multiply the result by 4",
        "expected": {"status": "failure"},
        "layer": "validation"
    },
    
    # EDGE CASES
    {
        "name": "edge_empty_input",
        "input": "",
        "expected": {"status": "failure"},
        "layer": "validation"
    },
    {
        "name": "edge_malformed_input",
        "input": "???",
        "expected": {"status": "failure"},
        "layer": "validation"
    }
]

import re


FAILURE_KEYWORDS = [
    "error",
    "failure",
    "invalid",
    "exception",
    "validation"
]


def evaluate_result(output: str, expected: dict) -> dict:
    """
    Deterministic comparison of expected vs actual results.
    
    Args:
        output (str): Raw output from test execution
        expected (dict): Expected result specification
        
    Returns:
        dict: Evaluation result with status, reason, and actual value
    """
    
    # MULTI-STEP EXTRACTION
    actual_value = None
    
    # STEP 1: Try FINAL ANSWER marker
    if "FINAL ANSWER:" in output:
        match = re.search(r'FINAL ANSWER:\s*(.+)', output, re.IGNORECASE)
        if match:
            actual_value = match.group(1).strip()
    
    # STEP 2: FALLBACK - Last non-empty line
    if actual_value is None:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        actual_value = lines[-1] if lines else ""
    
    # STEP 3: NORMALIZE - ensure string, strip whitespace
    actual_value = str(actual_value).strip()
    
    # SUCCESS CASE
    if expected["status"] == "success":
        expected_result = expected.get("result", "")
        
        if actual_value == expected_result:
            return {
                "status": "PASS",
                "reason": "Result matches expected",
                "actual": actual_value
            }
        else:
            return {
                "status": "FAIL",
                "reason": f"Expected '{expected_result}' but got '{actual_value}'",
                "actual": actual_value
            }
    
    # FAILURE CASE
    elif expected["status"] == "failure":
        output_lower = output.lower()
        
        # STEP 1: Detect failure
        failure_detected = any(keyword in output_lower for keyword in FAILURE_KEYWORDS)
        
        if not failure_detected:
            return {
                "status": "FAIL",
                "reason": "Expected failure but execution succeeded",
                "actual": actual_value
            }
        
        # STEP 2: If expected has specific reason, validate it
        if "reason" in expected:
            expected_reason = expected["reason"].lower()
            if expected_reason in output_lower:
                return {
                    "status": "PASS",
                    "reason": f"Failure with expected reason: {expected['reason']}",
                    "actual": "failure"
                }
            else:
                return {
                    "status": "FAIL",
                    "reason": f"Expected reason '{expected['reason']}' not found in output",
                    "actual": "failure"
                }
        
        # STEP 3: Fallback to keyword detection
        return {
            "status": "PASS",
            "reason": "Failure detected as expected",
            "actual": "failure"
        }
    
    # UNKNOWN STATUS
    else:
        return {
            "status": "FAIL",
            "reason": f"Unknown expected status: {expected['status']}",
            "actual": actual_value
        }

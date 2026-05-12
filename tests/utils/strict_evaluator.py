"""
Strict Evaluator — Enhanced Result Evaluation with Failure Classification

PURPOSE:
    Provides strict pass/fail evaluation with detailed failure classification
    and architecture validation integration.

CONSTRAINTS:
    - Uses manager.py execution output ONLY
    - NO trace mode execution for pass/fail
    - Deterministic evaluation
"""

import re
from typing import Dict, List, Any, Optional, Tuple


class FailureClassifier:
    """
    Classifies failures as EXPECTED or UNEXPECTED.
    """
    
    EXPECTED_FAILURE_KEYWORDS = [
        "validation failed",
        "invalid input",
        "missing required",
        "argument count",
        "type mismatch",
        "unknown tool",
        "malformed"
    ]
    
    @staticmethod
    def classify_failure(output: str, expected_status: str) -> str:
        """
        Classify failure type.
        
        Returns:
            "EXPECTED_FAILURE" or "UNEXPECTED_FAILURE"
        """
        output_lower = output.lower()
        
        # If test expected failure
        if expected_status == "failure":
            # Check if system correctly rejected input
            has_expected_keywords = any(
                keyword in output_lower 
                for keyword in FailureClassifier.EXPECTED_FAILURE_KEYWORDS
            )
            
            if has_expected_keywords:
                return "EXPECTED_FAILURE"
            else:
                # System failed but not for expected reason
                return "UNEXPECTED_FAILURE"
        
        # If test expected success but failed
        else:
            return "UNEXPECTED_FAILURE"


class StrictEvaluator:
    """
    Strict result evaluator with ZERO heuristics.
    
    RULES:
    - PASS = exact correctness only
    - FAIL = everything else
    - NO keyword-based logic
    - NO assumptions
    """
    
    def __init__(self):
        self.classifier = FailureClassifier()
    
    def extract_result(self, output: str) -> Optional[str]:
        """
        Extract result from output.
        
        Priority:
        1. FINAL ANSWER: marker
        2. Last non-empty line
        3. None if ambiguous or empty
        """
        if not output or not output.strip():
            return None
        
        # Try FINAL ANSWER marker
        if "FINAL ANSWER:" in output:
            match = re.search(r'FINAL ANSWER:\s*(.+)', output, re.IGNORECASE)
            if match:
                result = match.group(1).strip()
                return result if result else None
        
        # Fallback to last non-empty line
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if lines:
            return lines[-1]
        
        return None
    
    def is_clear_failure(self, output: str) -> bool:
        """
        Detect CLEAR failure indicators (non-heuristic).
        
        Returns True ONLY if:
        - Output is empty
        - Output contains exception traceback
        - Output explicitly states failure
        """
        if not output or not output.strip():
            return True
        
        # Check for explicit exception (Traceback)
        if "Traceback (most recent call last)" in output:
            return True
        
        # Check for explicit ERROR prefix
        if output.strip().startswith("ERROR:"):
            return True
        
        return False
    
    def evaluate(
        self, 
        output: str, 
        expected: Dict[str, Any],
        determinism_passed: bool = True,
        architecture_passed: bool = True
    ) -> Dict[str, Any]:
        """
        STRICT evaluation with ZERO heuristics.
        
        RULES:
        - SUCCESS: PASS only if exact match + determinism + architecture
        - FAILURE: PASS only if clear failure + determinism + architecture
        - NO keyword-based logic
        - NO assumptions
        
        Args:
            output: Raw output from manager execution
            expected: Expected result specification
            determinism_passed: Whether determinism check passed
            architecture_passed: Whether architecture check passed
            
        Returns:
            {
                "status": "PASS" or "FAIL",
                "failure_type": "EXPECTED_FAILURE" or "UNEXPECTED_FAILURE" or None,
                "reason": str,
                "actual": str,
                "confidence": "HIGH" or "LOW",
                "details": {...}
            }
        """
        # Extract actual result
        actual_value = self.extract_result(output)
        
        # HARD FAIL: Empty or ambiguous output
        if actual_value is None:
            return {
                "status": "FAIL",
                "failure_type": "UNEXPECTED_FAILURE",
                "reason": "Empty or ambiguous output (cannot extract result)",
                "actual": "",
                "confidence": "HIGH",
                "details": {
                    "determinism_passed": determinism_passed,
                    "architecture_passed": architecture_passed
                }
            }
        
        # HARD FAIL: Nondeterministic behavior
        if not determinism_passed:
            return {
                "status": "FAIL",
                "failure_type": "UNEXPECTED_FAILURE",
                "reason": "Nondeterministic behavior detected",
                "actual": actual_value,
                "confidence": "HIGH",
                "details": {
                    "determinism_passed": False,
                    "architecture_passed": architecture_passed
                }
            }
        
        # HARD FAIL: Architecture violation
        if not architecture_passed:
            return {
                "status": "FAIL",
                "failure_type": "UNEXPECTED_FAILURE",
                "reason": "Architecture violation detected",
                "actual": actual_value,
                "confidence": "HIGH",
                "details": {
                    "determinism_passed": determinism_passed,
                    "architecture_passed": False
                }
            }
        
        expected_status = expected.get("status")
        
        # =====================================================================
        # SUCCESS CASE: PASS ONLY IF EXACT MATCH
        # =====================================================================
        if expected_status == "success":
            expected_result = expected.get("result", "")
            
            # STRICT: Exact match required
            if actual_value == expected_result:
                return {
                    "status": "PASS",
                    "failure_type": None,
                    "reason": "Result matches expected",
                    "actual": actual_value,
                    "confidence": "HIGH",
                    "details": {
                        "expected": expected_result,
                        "determinism_passed": determinism_passed,
                        "architecture_passed": architecture_passed
                    }
                }
            else:
                # ANY deviation = FAIL
                return {
                    "status": "FAIL",
                    "failure_type": "UNEXPECTED_FAILURE",
                    "reason": f"Expected '{expected_result}' but got '{actual_value}'",
                    "actual": actual_value,
                    "confidence": "HIGH",
                    "details": {
                        "expected": expected_result,
                        "determinism_passed": determinism_passed,
                        "architecture_passed": architecture_passed
                    }
                }
        
        # =====================================================================
        # FAILURE CASE: PASS ONLY IF CLEAR FAILURE
        # =====================================================================
        elif expected_status == "failure":
            # Check for CLEAR failure indicators (non-heuristic)
            is_clear_failure = self.is_clear_failure(output)
            
            # If expected success result format but got something else = failure
            # (This handles cases where system didn't explicitly fail but didn't succeed)
            expected_success_format = expected.get("result")
            if expected_success_format:
                # If result doesn't match expected success format, it's a failure
                if actual_value != expected_success_format:
                    is_clear_failure = True
            
            if not is_clear_failure:
                # System appears to have succeeded when it should have failed
                return {
                    "status": "FAIL",
                    "failure_type": "UNEXPECTED_FAILURE",
                    "reason": "Expected failure but execution appears to have succeeded",
                    "actual": actual_value,
                    "confidence": "HIGH",
                    "details": {
                        "determinism_passed": determinism_passed,
                        "architecture_passed": architecture_passed
                    }
                }
            
            # Classify failure type
            failure_type = self.classifier.classify_failure(output, expected_status)
            
            # Check for specific expected reason (if provided)
            if "reason" in expected:
                expected_reason = expected["reason"].lower()
                if expected_reason in output.lower():
                    return {
                        "status": "PASS",
                        "failure_type": failure_type,
                        "reason": f"Failure with expected reason: {expected['reason']}",
                        "actual": "failure",
                        "confidence": "HIGH",
                        "details": {
                            "determinism_passed": determinism_passed,
                            "architecture_passed": architecture_passed
                        }
                    }
                else:
                    return {
                        "status": "FAIL",
                        "failure_type": "UNEXPECTED_FAILURE",
                        "reason": f"Expected reason '{expected['reason']}' not found in output",
                        "actual": "failure",
                        "confidence": "LOW",
                        "details": {
                            "determinism_passed": determinism_passed,
                            "architecture_passed": architecture_passed
                        }
                    }
            
            # Failure detected as expected (no specific reason required)
            return {
                "status": "PASS",
                "failure_type": failure_type,
                "reason": "Failure detected as expected",
                "actual": "failure",
                "confidence": "HIGH",
                "details": {
                    "determinism_passed": determinism_passed,
                    "architecture_passed": architecture_passed
                }
            }
        
        # =====================================================================
        # UNKNOWN STATUS: FAIL
        # =====================================================================
        else:
            return {
                "status": "FAIL",
                "failure_type": "UNEXPECTED_FAILURE",
                "reason": f"Unknown expected status: {expected_status}",
                "actual": actual_value,
                "confidence": "HIGH",
                "details": {
                    "determinism_passed": determinism_passed,
                    "architecture_passed": architecture_passed
                }
            }

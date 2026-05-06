"""
drift_detector.py — Phase 3B Drift Detection System (M12)

Per AUTHORITY_MODEL.txt and CONTROL_MODEL.txt:
- execution_result is sole truth
- drift signals are ADVISORY ONLY
- drift MUST NOT override execution_result
- drift MUST NOT modify control flow

Per SYSTEM_GOALS_V2 and HAND_ARCHITECTURE_V2:
- Small drift → auto-correct (advisory signal)
- Large drift → require user (advisory signal for governance consideration)

Per TRACE_LOGGING_CONTRACT_V1:
- All drift events logged as observational trace only
"""

from typing import Any, Dict, Optional


def compare(
    expected_outcome: Optional[str],
    execution_result: Optional[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Compare expected_outcome vs execution_result to detect drift.

    ADVISORY ONLY — This function:
    - Reads execution_result (truth)
    - Produces drift signal (advisory)
    - Does NOT modify execution_result
    - Does NOT trigger retry or control flow changes

    Args:
        expected_outcome: Planner-defined expected outcome (advisory)
        execution_result: Core execution result (sole truth per AUTHORITY_MODEL)
        context: Optional execution context for additional drift signals

    Returns:
        Drift signal dict (advisory only):
        {
            "drift_detected": bool,
            "drift_type": "NONE" | "SMALL" | "LARGE",
            "confidence": float (0.0-1.0),
            "reason": str
        }
    """
    # Default: no drift
    drift_signal = {
        "drift_detected": False,
        "drift_type": "NONE",
        "confidence": 1.0,
        "reason": "No drift detected"
    }

    # Edge case: missing execution_result (should not happen per contracts)
    if execution_result is None:
        return {
            "drift_detected": True,
            "drift_type": "LARGE",
            "confidence": 1.0,
            "reason": "Missing execution_result — critical contract violation"
        }

    # RULE 1: execution failure = LARGE drift
    # Per CONTROL_MODEL: execution_result.status == "failure" triggers retry/escalate
    # Drift signal reflects this as LARGE for observability
    if execution_result.get("status") == "failure":
        return {
            "drift_detected": True,
            "drift_type": "LARGE",
            "confidence": 1.0,
            "reason": "Execution failure detected — drift classification LARGE per CONTROL_MODEL"
        }

    # RULE 2: missing expected_outcome = NONE (no basis for drift comparison)
    if not expected_outcome:
        return {
            "drift_detected": False,
            "drift_type": "NONE",
            "confidence": 1.0,
            "reason": "No expected_outcome defined — drift comparison not applicable"
        }

    # Extract actual result value
    actual_value = execution_result.get("result")

    # RULE 3: type/domain mismatch = LARGE drift
    # Incompatible types indicate significant semantic drift
    if _is_type_mismatch(expected_outcome, actual_value):
        return {
            "drift_detected": True,
            "drift_type": "LARGE",
            "confidence": 0.9,
            "reason": f"Type/domain mismatch: expected {type(expected_outcome).__name__}, got {type(actual_value).__name__}"
        }

    # RULE 4: Check for exact match first (including type/format)
    # Perfect match: same type AND same value
    if expected_outcome == actual_value:
        return {
            "drift_detected": False,
            "drift_type": "NONE",
            "confidence": 1.0,
            "reason": "Execution result matches expected outcome"
        }

    # RULE 5: semantic equivalence (string "5" vs int 5) = SMALL drift
    # Format/type differences are observable and worth logging
    expected_normalized = _normalize_for_comparison(expected_outcome)
    actual_normalized = _normalize_for_comparison(actual_value)

    if _is_semantic_equivalent(expected_normalized, actual_normalized):
        return {
            "drift_detected": True,
            "drift_type": "SMALL",
            "confidence": 0.7,
            "reason": f"Semantic equivalence but format difference: expected '{expected_outcome}' ({type(expected_outcome).__name__}), got '{actual_value}' ({type(actual_value).__name__})"
        }

    # RULE 6: numeric deviation assessment
    if _is_numeric_deviation(expected_outcome, actual_value):
        deviation_ratio = _calculate_deviation_ratio(expected_outcome, actual_value)
        if deviation_ratio is not None:
            if deviation_ratio <= 0.1:  # Within 10%
                return {
                    "drift_detected": True,
                    "drift_type": "SMALL",
                    "confidence": 0.6,
                    "reason": f"Small numeric deviation ({deviation_ratio:.1%}): expected '{expected_outcome}', got '{actual_value}'"
                }
            else:
                return {
                    "drift_detected": True,
                    "drift_type": "LARGE",
                    "confidence": 0.8,
                    "reason": f"Large numeric deviation ({deviation_ratio:.1%}): expected '{expected_outcome}', got '{actual_value}'"
                }

    # RULE 7: default to LARGE for any other mismatch
    return {
        "drift_detected": True,
        "drift_type": "LARGE",
        "confidence": 0.75,
        "reason": f"Outcome mismatch: expected '{expected_outcome}', got '{actual_value}'"
    }


def _normalize_for_comparison(value: Any) -> str:
    """
    Normalize a value to string for comparison.
    Handles None, numbers, booleans, strings.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        # Normalize numeric values for comparison
        return str(value)
    return str(value).strip()


def _is_type_mismatch(expected: Any, actual: Any) -> bool:
    """
    Check for fundamental type/domain incompatibility.

    Examples of LARGE drift:
    - expected: "file path", actual: numeric
    - expected: "boolean result", actual: complex object
    """
    if expected is None or actual is None:
        return False  # Missing values handled elsewhere

    # Check for obvious category mismatches
    expected_str = str(expected).lower()
    actual_type = type(actual).__name__

    # File path expected but got non-string
    if ("path" in expected_str or "file" in expected_str or ".txt" in expected_str or ".json" in expected_str):
        if not isinstance(actual, str):
            return True

    # Boolean expected but got non-boolean
    if expected_str in ("true", "false", "success", "failure"):
        if not isinstance(actual, bool) and actual not in ("true", "false", "success", "failure"):
            # Could still be valid — don't flag as type mismatch
            pass

    return False


def _is_semantic_equivalent(expected: str, actual: str) -> bool:
    """
    Check if two normalized values are semantically equivalent.

    Examples:
    - "5" == "5.0" (int vs float string)
    - "True" == "true" (case difference)
    - " success " == "success" (whitespace)
    """
    if expected == actual:
        return True

    # Numeric equivalence (5 vs 5.0 vs "5" vs "5.0")
    try:
        expected_num = float(expected)
        actual_num = float(actual)
        if abs(expected_num - actual_num) < 0.0001:  # Allow float epsilon
            return True
    except (ValueError, TypeError):
        pass

    # Boolean equivalence
    bool_map = {
        "true": True, "yes": True, "1": True, "success": True,
        "false": False, "no": False, "0": False, "failure": False
    }
    expected_bool = bool_map.get(expected.lower())
    actual_bool = bool_map.get(actual.lower())
    if expected_bool is not None and actual_bool is not None:
        return expected_bool == actual_bool

    return False


def _is_numeric_deviation(expected: Any, actual: Any) -> bool:
    """
    Check if both values are numeric for deviation calculation.
    """
    try:
        float(str(expected))
        float(str(actual))
        return True
    except (ValueError, TypeError):
        return False


def _calculate_deviation_ratio(expected: Any, actual: Any) -> Optional[float]:
    """
    Calculate deviation ratio between two numeric values.
    Returns None if calculation not possible.
    """
    try:
        expected_val = float(str(expected))
        actual_val = float(str(actual))

        if expected_val == 0:
            # Handle zero case — use absolute difference
            return abs(actual_val) if actual_val != 0 else 0.0

        return abs((actual_val - expected_val) / expected_val)
    except (ValueError, TypeError, ZeroDivisionError):
        return None

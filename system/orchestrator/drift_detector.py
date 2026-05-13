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
from system.orchestrator.semantic_expectation import (
    is_valid_semantic_expectation,
    DOMAIN_NUMERIC, DOMAIN_TEXT, DOMAIN_LIST, DOMAIN_BOOLEAN,
    DOMAIN_STRUCTURED, DOMAIN_VOID,
    SHAPE_SCALAR, SHAPE_COLLECTION,
    CATEGORY_ARITHMETIC, CATEGORY_RETRIEVAL,
)


def compare(
    expected_outcome: Optional[str],
    execution_result: Optional[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
    semantic_expectation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compare semantic_expectation vs execution_result to detect drift.

    Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §12:
    - Drift detector is a semantic comparison engine
    - Drift detector MUST NOT treat operational placeholders as semantic truth
    - Null semantic_expectation = no drift basis (valid, not an error)

    Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1 §12:
    - Semantic drift signals are ADVISORY ONLY
    - MUST NOT directly mutate runtime behavior

    ADVISORY ONLY — This function:
    - Reads execution_result (truth)
    - Produces drift signal (advisory)
    - Does NOT modify execution_result
    - Does NOT trigger retry or control flow changes

    Args:
        expected_outcome: [DEPRECATED FOR DRIFT — human-readable/operational metadata only]
            Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §4:
            expected_outcome is classified as incomplete semantic scaffolding and
            operational placeholder field. It MUST NOT act as semantic drift truth source.
            Retained for backward compatibility and human-readable observability only.
        execution_result: Core execution result (sole truth per AUTHORITY_MODEL)
        context: Optional execution context for additional drift signals
        semantic_expectation: Planner-derived semantic expectation dict.
            Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1: authoritative semantic input.
            Structure: {"semantic_domain": str, "semantic_category": str, "output_shape": str}
            Null = no semantic drift basis → returns NONE (valid, not an error).

    Returns:
        Drift signal dict (advisory only):
        {
            "drift_detected": bool,
            "drift_type": "NONE" | "SMALL" | "LARGE",
            "confidence": float (0.0-1.0),
            "reason": str
        }
    """
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

    # RULE 2: semantic_expectation gating
    # Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §12:
    # Drift detector assumes semantic expectation inputs.
    # If no valid semantic_expectation is present, there is no semantic drift basis.
    # Null = NONE (valid — not an error condition).
    if not is_valid_semantic_expectation(semantic_expectation):
        return {
            "drift_detected": False,
            "drift_type": "NONE",
            "confidence": 1.0,
            "reason": "No semantic_expectation defined — semantic drift comparison not applicable"
        }

    # Extract actual result value
    actual_value = execution_result.get("result")

    # RULE 3: semantic domain comparison
    # Compare expected semantic domain against actual result type
    expected_domain = semantic_expectation.get("semantic_domain")
    expected_shape = semantic_expectation.get("output_shape")
    expected_category = semantic_expectation.get("semantic_category")

    # RULE 3A: shape mismatch — expected scalar but got collection (or vice versa)
    if expected_shape == SHAPE_SCALAR and isinstance(actual_value, (list, tuple, set)):
        return {
            "drift_detected": True,
            "drift_type": "LARGE",
            "confidence": 0.9,
            "reason": f"Shape mismatch: expected scalar output, got collection ({type(actual_value).__name__})"
        }
    if expected_shape == SHAPE_COLLECTION and not isinstance(actual_value, (list, tuple, set)):
        return {
            "drift_detected": True,
            "drift_type": "LARGE",
            "confidence": 0.85,
            "reason": f"Shape mismatch: expected collection output, got {type(actual_value).__name__}"
        }

    # RULE 3B: domain conformity check
    actual_is_numeric = _actual_is_numeric(actual_value)
    actual_is_bool = isinstance(actual_value, bool)
    actual_is_list = isinstance(actual_value, (list, tuple, set))
    actual_is_text = isinstance(actual_value, str)
    actual_is_structured = isinstance(actual_value, dict)
    actual_is_none = actual_value is None

    if expected_domain == DOMAIN_NUMERIC:
        if actual_is_bool:
            return {
                "drift_detected": True,
                "drift_type": "LARGE",
                "confidence": 0.9,
                "reason": f"Domain mismatch: expected numeric result, got boolean"
            }
        if not actual_is_numeric and not actual_is_none:
            # For arithmetic category: high confidence large drift
            conf = 0.9 if expected_category == CATEGORY_ARITHMETIC else 0.8
            return {
                "drift_detected": True,
                "drift_type": "LARGE",
                "confidence": conf,
                "reason": f"Domain mismatch: expected numeric result, got {type(actual_value).__name__}"
            }
        # Numeric domain matched — check for value deviation
        if actual_is_numeric and not actual_is_none:
            # RULE 4: exact numeric match = NONE
            if actual_value == actual_value:  # always true, placeholder for clarity
                actual_num = _to_float(actual_value)
                if actual_num is not None:
                    return {
                        "drift_detected": False,
                        "drift_type": "NONE",
                        "confidence": 1.0,
                        "reason": "Numeric result matches expected numeric domain"
                    }

    elif expected_domain == DOMAIN_BOOLEAN:
        if not actual_is_bool and actual_value not in (0, 1, "true", "false", "True", "False"):
            return {
                "drift_detected": True,
                "drift_type": "LARGE",
                "confidence": 0.9,
                "reason": f"Domain mismatch: expected boolean result, got {type(actual_value).__name__}"
            }

    elif expected_domain == DOMAIN_LIST:
        if not actual_is_list:
            return {
                "drift_detected": True,
                "drift_type": "LARGE",
                "confidence": 0.85,
                "reason": f"Domain mismatch: expected list result, got {type(actual_value).__name__}"
            }

    elif expected_domain == DOMAIN_STRUCTURED:
        if not actual_is_structured:
            return {
                "drift_detected": True,
                "drift_type": "LARGE",
                "confidence": 0.85,
                "reason": f"Domain mismatch: expected structured/dict result, got {type(actual_value).__name__}"
            }

    elif expected_domain == DOMAIN_TEXT:
        if not actual_is_text and not actual_is_none:
            # Retrieval category: lower sensitivity (results vary)
            conf = 0.6 if expected_category == CATEGORY_RETRIEVAL else 0.75
            return {
                "drift_detected": True,
                "drift_type": "LARGE",
                "confidence": conf,
                "reason": f"Domain mismatch: expected text result, got {type(actual_value).__name__}"
            }

    elif expected_domain == DOMAIN_VOID:
        if actual_value is not None:
            return {
                "drift_detected": True,
                "drift_type": "SMALL",
                "confidence": 0.7,
                "reason": f"Domain mismatch: expected void/no output, got {type(actual_value).__name__}"
            }

    # RULE 5: domain matched — NONE drift
    return {
        "drift_detected": False,
        "drift_type": "NONE",
        "confidence": 1.0,
        "reason": f"Execution result domain ({type(actual_value).__name__}) conforms to expected semantic domain '{expected_domain}'"
    }


def _actual_is_numeric(value: Any) -> bool:
    """Return True if value is a numeric type (int or float, NOT bool)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False
    return False


def _to_float(value: Any) -> Optional[float]:
    """Convert value to float for numeric comparison, returns None on failure."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


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

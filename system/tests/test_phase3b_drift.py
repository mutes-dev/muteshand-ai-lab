"""
PHASE 3B — DRIFT DETECTION SYSTEM TESTS

Verifies:
1. NO DRIFT: add 2 and 3 → drift_detected = false
2. SMALL DRIFT: format difference → drift_type = SMALL
3. LARGE DRIFT: value deviation → drift_type = LARGE
4. FAILURE: divide 10 by 0 → drift_type = LARGE
5. CONTROL FLOW: execution_result unchanged by drift

Architecture validation:
- execution_result unchanged
- drift is advisory only
- no control flow modification
- trace is observational only
"""

import pytest
from system.orchestrator.drift_detector import compare, _normalize_for_comparison, _is_semantic_equivalent


# ─── TEST 1: NO DRIFT ────────────────────────────────────────────────────────

def test_no_drift_success():
    """
    "add 2 and 3" → expected=5, actual=5 (same type, same value)
    EXPECTED: drift_detected = False, drift_type = NONE
    """
    result = compare(
        expected_outcome=5,  # int
        execution_result={"status": "success", "result": 5}  # int - same type and value
    )

    assert result["drift_detected"] is False, f"Expected no drift, got {result}"
    assert result["drift_type"] == "NONE", f"Expected NONE, got {result['drift_type']}"
    assert result["confidence"] == 1.0, "Perfect match should have confidence 1.0"

    print("TEST 1 (NO DRIFT):", result)


# ─── TEST 2: SMALL DRIFT ───────────────────────────────────────────────────────

def test_small_drift_format_difference():
    """
    expected_outcome = 5, actual_result = "5" (int vs string semantic equivalence)
    EXPECTED: drift_type = SMALL
    """
    result = compare(
        expected_outcome=5,  # numeric
        execution_result={"status": "success", "result": "5"}  # String format
    )

    assert result["drift_detected"] is True, f"Expected drift detected, got {result}"
    assert result["drift_type"] == "SMALL", f"Expected SMALL drift, got {result['drift_type']}"
    assert 0.5 <= result["confidence"] <= 1.0, f"Confidence should be moderate-high, got {result['confidence']}"

    print("TEST 2 (SMALL DRIFT):", result)


def test_small_drift_numeric_deviation():
    """
    expected = 5, actual = 5.1 (within 10% deviation)
    EXPECTED: drift_type = SMALL
    """
    result = compare(
        expected_outcome="5",
        execution_result={"status": "success", "result": 5.1}
    )

    assert result["drift_detected"] is True
    assert result["drift_type"] == "SMALL", f"Small numeric deviation should be SMALL, got {result}"

    print("TEST 2b (SMALL NUMERIC DRIFT):", result)


# ─── TEST 3: LARGE DRIFT ──────────────────────────────────────────────────────

def test_large_drift_value_mismatch():
    """
    expected_outcome = 5, actual_result = 20
    EXPECTED: drift_type = LARGE
    """
    result = compare(
        expected_outcome="5",
        execution_result={"status": "success", "result": 20}
    )

    assert result["drift_detected"] is True, f"Expected drift detected, got {result}"
    assert result["drift_type"] == "LARGE", f"Expected LARGE drift, got {result['drift_type']}"

    print("TEST 3 (LARGE DRIFT):", result)


def test_large_drift_type_mismatch():
    """
    expected file path, got number
    EXPECTED: drift_type = LARGE (type/domain mismatch)
    """
    result = compare(
        expected_outcome="/path/to/file.txt",
        execution_result={"status": "success", "result": 42}
    )

    assert result["drift_detected"] is True
    assert result["drift_type"] == "LARGE", f"Type mismatch should be LARGE, got {result}"

    print("TEST 3b (LARGE TYPE MISMATCH):", result)


# ─── TEST 4: FAILURE ──────────────────────────────────────────────────────────

def test_failure_drift_large():
    """
    "divide 10 by 0" → execution_result.status = "failure"
    EXPECTED: drift_type = LARGE per CONTROL_MODEL
    """
    result = compare(
        expected_outcome="some result",
        execution_result={"status": "failure", "reason": "division_by_zero"}
    )

    assert result["drift_detected"] is True, f"Failure should trigger drift, got {result}"
    assert result["drift_type"] == "LARGE", f"Failure should be LARGE drift, got {result['drift_type']}"
    assert result["confidence"] == 1.0, "Failure should have max confidence"

    print("TEST 4 (FAILURE DRIFT):", result)


# ─── TEST 5: CONTROL FLOW ─────────────────────────────────────────────────────

def test_drift_does_not_modify_execution_result():
    """
    VERIFY: execution_result is passed by reference but never modified
    """
    original_execution = {"status": "success", "result": 42}
    original_copy = original_execution.copy()

    result = compare(
        expected_outcome="5",
        execution_result=original_execution
    )

    # execution_result must be unchanged
    assert original_execution == original_copy, "execution_result was modified by drift detection"
    assert result["drift_detected"] is True  # 42 != 5

    print("TEST 5 (CONTROL FLOW): execution_result unchanged =", original_execution == original_copy)


def test_drift_advisory_no_control_impact():
    """
    VERIFY: Same execution_result produces same governance decision regardless of drift
    Note: This verifies the architectural principle, not runtime behavior
    """
    # Execution result is sole truth
    execution_result = {"status": "success", "result": 100}

    # Drift detection (advisory only)
    drift_signal = compare(expected_outcome="5", execution_result=execution_result)

    # The execution_result should be the same before and after drift detection
    assert execution_result["status"] == "success"
    assert execution_result["result"] == 100

    # Drift signal should be advisory metadata, not modifying execution
    assert "drift_type" in drift_signal
    assert drift_signal["drift_type"] == "LARGE"  # 100 vs 5 is large deviation

    print("TEST 5b (ADVISORY ONLY): drift signal =", drift_signal)


# ─── TEST 6: EDGE CASES ─────────────────────────────────────────────────────

def test_missing_execution_result():
    """
    Missing execution_result → LARGE drift (contract violation)
    """
    result = compare(
        expected_outcome="5",
        execution_result=None
    )

    assert result["drift_detected"] is True
    assert result["drift_type"] == "LARGE"
    assert "contract violation" in result["reason"].lower()

    print("TEST 6 (MISSING EXECUTION):", result)


def test_missing_expected_outcome():
    """
    No expected_outcome → NONE (no basis for comparison)
    """
    result = compare(
        expected_outcome=None,
        execution_result={"status": "success", "result": 42}
    )

    assert result["drift_detected"] is False
    assert result["drift_type"] == "NONE"

    print("TEST 6b (MISSING EXPECTED):", result)


def test_semantic_equivalence_boolean():
    """
    "true" vs True → semantic equivalence → SMALL drift (format difference)
    """
    result = compare(
        expected_outcome="true",  # string
        execution_result={"status": "success", "result": True}  # boolean
    )

    # Should be detected as semantic equivalence with format difference
    assert result["drift_detected"] is True  # Format difference
    assert result["drift_type"] == "SMALL"

    print("TEST 6c (BOOLEAN EQUIVALENCE):", result)


# ─── TEST 7: HELPER FUNCTIONS ────────────────────────────────────────────────

def test_normalize_for_comparison():
    """
    Verify normalization handles various types
    """
    assert _normalize_for_comparison(5) == "5"
    assert _normalize_for_comparison(5.0) == "5.0"
    assert _normalize_for_comparison(True) == "true"
    assert _normalize_for_comparison(None) == ""
    assert _normalize_for_comparison("  test  ") == "test"

    print("TEST 7 (NORMALIZE): all passed")


def test_is_semantic_equivalent():
    """
    Verify semantic equivalence detection
    """
    assert _is_semantic_equivalent("5", "5.0") is True  # Numeric
    assert _is_semantic_equivalent("true", "True") is True  # Boolean case
    assert _is_semantic_equivalent("yes", "1") is True  # Boolean mapping
    assert _is_semantic_equivalent("5", "10") is False  # Different values

    print("TEST 7b (SEMANTIC EQUIV): all passed")


# ─── TEST 8: INTEGRATION ──────────────────────────────────────────────────────

def test_drift_signal_structure():
    """
    Verify drift signal has all required fields
    """
    result = compare(
        expected_outcome="5",
        execution_result={"status": "success", "result": 10}
    )

    assert "drift_detected" in result
    assert "drift_type" in result
    assert "confidence" in result
    assert "reason" in result

    assert isinstance(result["drift_detected"], bool)
    assert result["drift_type"] in ("NONE", "SMALL", "LARGE")
    assert isinstance(result["confidence"], float)
    assert 0.0 <= result["confidence"] <= 1.0
    assert isinstance(result["reason"], str)

    print("TEST 8 (SIGNAL STRUCTURE):", result)

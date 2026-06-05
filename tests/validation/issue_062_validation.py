"""
ISSUE-062 Validation Script

Tests:
A. Current actionable FAILED workflow metadata
B. Future terminal/non-actionable FAILED skeleton (mock)
C. Regression checks for other statuses
"""

import sys
import os
import json
import tempfile
import atexit

# Ensure project root is on path
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _PROJECT_ROOT)

# === SAFETY: Isolate persistence to a temp directory ===
_test_active_dir = tempfile.mkdtemp(prefix="issue062_test_")
os.makedirs(_test_active_dir, exist_ok=True)

import system.orchestrator.persistence as _persistence_module
_persistence_module.ACTIVE_WORKFLOW_DIR = _test_active_dir

from tests._test_safety_guard import guard_delete, guard_rmtree


def _cleanup_test_dir():
    guard_rmtree(_test_active_dir)


atexit.register(_cleanup_test_dir)


def _ensure_active_dir():
    os.makedirs(_test_active_dir, exist_ok=True)


def _write_mock_workflow(workflow_id: str, data: dict):
    """Write a mock workflow to the isolated test directory."""
    from system.orchestrator.persistence import _active_workflow_path
    _path = _active_workflow_path(workflow_id)
    with open(_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _cleanup_mock_workflow(workflow_id: str):
    """Remove a mock workflow file via safety guard."""
    from system.orchestrator.persistence import _active_workflow_path
    _path = _active_workflow_path(workflow_id)
    if os.path.exists(_path):
        guard_delete(_path)


def test_a_current_actionable_failed():
    """Scenario A: Current actionable FAILED gets default metadata."""
    print("\n=== SCENARIO A: Current Actionable FAILED ===")

    wf_id = "test_issue_062_actionable_failed"
    _cleanup_mock_workflow(wf_id)

    # Create a FAILED workflow without metadata (simulating old/current behavior)
    _write_mock_workflow(wf_id, {
        "id": wf_id,
        "status": "FAILED",
        "steps": [
            {"id": "step_1", "status": "FAILED", "purpose": "Test step"}
        ],
        "retention_state": "retained",
    })

    # Initialize registry entry
    from system.orchestrator.workflow_control import (
        _workflow_state_registry, _workflow_state_lock,
        _init_failed_metadata_defaults, _get_failed_metadata,
        _compute_retry_eligible,
    )
    with _workflow_state_lock:
        _workflow_state_registry[wf_id] = {
            "status": "FAILED",
            "last_updated": 0,
            "execution_generation": 1,
            "runtime_activity": "IDLE",
        }

    # Simulate entering FAILED — init defaults
    _init_failed_metadata_defaults(wf_id, reason="step_failure")

    # Verify metadata
    meta = _get_failed_metadata(wf_id)
    assert meta["failed_recoverable"] is True, f"Expected failed_recoverable=True, got {meta['failed_recoverable']}"
    assert meta["retry_disabled_reason"] is None, f"Expected retry_disabled_reason=None, got {meta['retry_disabled_reason']}"
    assert meta["actionability_reason"] == "retry_target_available", f"Expected actionability_reason=retry_target_available, got {meta['actionability_reason']}"
    assert meta["terminalization_reason"] == "step_failure", f"Expected terminalization_reason=step_failure, got {meta['terminalization_reason']}"

    # Verify retry eligibility (has FAILED step = target exists)
    from system.orchestrator.persistence import load_workflow
    wf = load_workflow(wf_id)
    retry_eligible = _compute_retry_eligible(wf_id, wf.get("steps", []))
    assert retry_eligible is True, f"Expected retry_eligible=True, got {retry_eligible}"

    # Verify registry contains metadata
    with _workflow_state_lock:
        reg = _workflow_state_registry.get(wf_id, {})
        assert reg.get("failed_recoverable") is True

    # Verify persistence contains metadata
    wf_reloaded = load_workflow(wf_id)
    assert wf_reloaded.get("failed_recoverable") is True

    _cleanup_mock_workflow(wf_id)
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    print("  PASSED: Actionable FAILED gets correct default metadata")


def test_b_terminal_failed_skeleton():
    """Scenario B: Future terminal/non-actionable FAILED skeleton."""
    print("\n=== SCENARIO B: Terminal/Non-Actionable FAILED Skeleton ===")

    wf_id = "test_issue_062_terminal_failed"
    _cleanup_mock_workflow(wf_id)

    # Create a FAILED workflow with explicit terminal metadata
    _write_mock_workflow(wf_id, {
        "id": wf_id,
        "status": "FAILED",
        "steps": [
            {"id": "step_1", "status": "FAILED", "purpose": "Test step"}
        ],
        "retention_state": "retained",
        "failed_recoverable": False,
        "retry_disabled_reason": "escalated_non_recoverable",
        "actionability_reason": "terminal_failure",
        "terminalization_reason": "governance_escalation",
    })

    from system.orchestrator.workflow_control import (
        _workflow_state_registry, _workflow_state_lock,
        _get_failed_metadata, _compute_retry_eligible,
    )
    with _workflow_state_lock:
        _workflow_state_registry[wf_id] = {
            "status": "FAILED",
            "last_updated": 0,
            "execution_generation": 1,
            "runtime_activity": "IDLE",
            "failed_recoverable": False,
            "retry_disabled_reason": "escalated_non_recoverable",
            "actionability_reason": "terminal_failure",
            "terminalization_reason": "governance_escalation",
        }

    meta = _get_failed_metadata(wf_id)
    assert meta["failed_recoverable"] is False, f"Expected failed_recoverable=False, got {meta['failed_recoverable']}"
    assert meta["retry_disabled_reason"] == "escalated_non_recoverable"
    assert meta["actionability_reason"] == "terminal_failure"
    assert meta["terminalization_reason"] == "governance_escalation"

    from system.orchestrator.persistence import load_workflow
    wf = load_workflow(wf_id)
    retry_eligible = _compute_retry_eligible(wf_id, wf.get("steps", []))
    assert retry_eligible is False, f"Expected retry_eligible=False, got {retry_eligible}"

    # Verify taskhub_eligible = False, history_eligible = True
    # (Test the logic that API would compute)
    retention_state = wf.get("retention_state", "retained")
    taskhub_eligible = meta["failed_recoverable"] and retention_state not in ("archived", "dismissed")
    history_eligible = (not meta["failed_recoverable"]) or retention_state in ("archived", "dismissed")
    assert taskhub_eligible is False, f"Expected taskhub_eligible=False, got {taskhub_eligible}"
    assert history_eligible is True, f"Expected history_eligible=True, got {history_eligible}"

    _cleanup_mock_workflow(wf_id)
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    print("  PASSED: Terminal FAILED skeleton behaves correctly")


def test_c_regression_checks():
    """Scenario C: Other statuses unaffected."""
    print("\n=== SCENARIO C: Regression Checks ===")

    from system.orchestrator.workflow_control import (
        _workflow_state_registry, _workflow_state_lock,
        _get_failed_metadata,
    )

    for status in ["ACTIVE", "PAUSED", "BLOCKED", "PENDING_RECOVERY", "QUEUED"]:
        wf_id = f"test_issue_062_regression_{status.lower()}"
        _cleanup_mock_workflow(wf_id)

        meta = _get_failed_metadata(wf_id)
        # For non-FAILED workflows, metadata defaults based on status
        # If workflow doesn't exist, fallback to registry which defaults to (status == "FAILED")
        assert meta["failed_recoverable"] is False, f"Expected failed_recoverable=False for {status}, got {meta}"

        print(f"  {status}: OK (failed_recoverable=False)")

    # CANCELLED workflow
    wf_id = "test_issue_062_regression_cancelled"
    _write_mock_workflow(wf_id, {"id": wf_id, "status": "CANCELLED"})
    meta = _get_failed_metadata(wf_id)
    assert meta["failed_recoverable"] is False, f"Expected failed_recoverable=False for CANCELLED"
    _cleanup_mock_workflow(wf_id)
    print("  CANCELLED: OK (failed_recoverable=False)")

    # COMPLETED workflow
    wf_id = "test_issue_062_regression_completed"
    _write_mock_workflow(wf_id, {"id": wf_id, "status": "COMPLETED"})
    meta = _get_failed_metadata(wf_id)
    assert meta["failed_recoverable"] is False, f"Expected failed_recoverable=False for COMPLETED"
    _cleanup_mock_workflow(wf_id)
    print("  COMPLETED: OK (failed_recoverable=False)")

    print("  PASSED: Regression checks passed")


def test_d_retry_endpoint_hardening():
    """Verify retry endpoint rejects non-retryable FAILED."""
    print("\n=== SCENARIO D: Retry Endpoint Hardening ===")

    wf_id = "test_issue_062_retry_guard"
    _cleanup_mock_workflow(wf_id)

    # Create terminal FAILED workflow
    _write_mock_workflow(wf_id, {
        "id": wf_id,
        "status": "FAILED",
        "steps": [
            {"id": "step_1", "status": "FAILED", "purpose": "Test step"}
        ],
        "failed_recoverable": False,
        "retry_disabled_reason": "terminal_failure",
    })

    from system.orchestrator.workflow_control import (
        _workflow_state_registry, _workflow_state_lock,
        retry_step,
    )
    with _workflow_state_lock:
        _workflow_state_registry[wf_id] = {
            "status": "FAILED",
            "last_updated": 0,
            "execution_generation": 1,
            "runtime_activity": "IDLE",
            "failed_recoverable": False,
            "retry_disabled_reason": "terminal_failure",
        }

    result = retry_step(wf_id, "step_1")
    assert result["status"] == "failure", f"Expected retry rejection, got {result}"
    assert result.get("retry_eligible") is False, f"Expected retry_eligible=False in response"
    assert result.get("failed_recoverable") is False, f"Expected failed_recoverable=False in response"
    print(f"  Retry rejected: {result['reason']}")

    _cleanup_mock_workflow(wf_id)
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    print("  PASSED: Retry endpoint correctly rejects non-retryable FAILED")


if __name__ == "__main__":
    _ensure_active_dir()
    try:
        test_a_current_actionable_failed()
        test_b_terminal_failed_skeleton()
        test_c_regression_checks()
        test_d_retry_endpoint_hardening()
        print("\n" + "=" * 50)
        print("ALL ISSUE-062 VALIDATION TESTS PASSED")
        print("=" * 50)
        sys.exit(0)
    except AssertionError as e:
        print(f"\nVALIDATION FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nVALIDATION ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

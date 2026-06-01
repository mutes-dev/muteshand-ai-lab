"""
Smoke test for ISSUE-061 Bug 2 registry fallback in _list_all_persisted_workflows.

Verifies that workflows present in the runtime registry but missing from disk
are still surfaced by the historical endpoint.
"""
import json
import os
import tempfile
import sys

# Ensure project root is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from system.orchestrator.workflow_control import (
    _workflow_state_registry,
    _workflow_state_lock,
)
from api import _list_all_persisted_workflows


def test_registry_fallback_workflow():
    """
    Inject a synthetic registry entry for a workflow that has no disk presence.
    Confirm _list_all_persisted_workflows includes it with correct metadata.
    """
    test_id = "__test_registry_fallback_workflow__"

    # Pre-clean: remove any stale file
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    active_path = os.path.join(root, "memory", "active_workflows", f"{test_id}.json")
    completed_path = os.path.join(root, "memory", "workflows.json")

    for p in (active_path, completed_path):
        if os.path.exists(p):
            os.remove(p)

    # Inject synthetic registry entry
    with _workflow_state_lock:
        _workflow_state_registry[test_id] = {
            "status": "COMPLETED",
            "last_updated": 1234567890.0,
            "reason": "test_cleanup",
            "execution_generation": 1,
            "runtime_activity": "IDLE",
        }

    try:
        results = _list_all_persisted_workflows()
        ids = {r["workflow_id"] for r in results}
        assert test_id in ids, f"Registry fallback workflow {test_id} missing from historical results"

        record = next(r for r in results if r["workflow_id"] == test_id)
        assert record["status"] == "COMPLETED"
        assert record["inspection_only"] is True
        assert record["source"] == "registry"
        assert record["updated_at"] == 1234567890.0
        print("PASS: registry fallback workflow surfaced correctly")
    finally:
        with _workflow_state_lock:
            _workflow_state_registry.pop(test_id, None)


def test_active_workflow_not_overwritten():
    """
    Confirm that a workflow present on disk is NOT overwritten by registry fallback.
    """
    test_id = "__test_active_not_overwritten__"
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    active_dir = os.path.join(root, "memory", "active_workflows")
    active_path = os.path.join(active_dir, f"{test_id}.json")

    os.makedirs(active_dir, exist_ok=True)
    disk_wf = {
        "id": test_id,
        "status": "FAILED",
        "goal": "Disk goal",
        "updated_at": 9999999999.0,
    }
    with open(active_path, "w", encoding="utf-8") as f:
        json.dump(disk_wf, f)

    # Inject conflicting registry entry
    with _workflow_state_lock:
        _workflow_state_registry[test_id] = {
            "status": "COMPLETED",
            "last_updated": 1111111111.0,
        }

    try:
        results = _list_all_persisted_workflows()
        record = next(r for r in results if r["workflow_id"] == test_id)
        # inject_authoritative_lifecycle_into_workflow overrides disk status with
        # registry status, so the exposed status is COMPLETED (from registry).
        assert record["status"] == "COMPLETED", f"Expected COMPLETED (registry authority), got {record['status']}"
        # Disk fields like goal are still preserved
        assert record["goal"] == "Disk goal"
        # Source is active_workflows because the file was found on disk
        assert record["source"] == "active_workflows"
        print("PASS: disk workflow preserved; registry status injected correctly")
    finally:
        with _workflow_state_lock:
            _workflow_state_registry.pop(test_id, None)
        if os.path.exists(active_path):
            os.remove(active_path)


if __name__ == "__main__":
    test_registry_fallback_workflow()
    test_active_workflow_not_overwritten()
    print("\nAll historical registry fallback tests passed.")

"""
Phase 3F-XA — Durable Lifecycle Authority Stabilization Tests

Tests:
- Crash Recovery (ACTIVE/PAUSED/BLOCKED/FAILED/COMPLETED restart simulation)
- Authority Restoration (registry warm restore, ACTIVE normalization, stale rejection)
- Projection Continuity (bg_id persistence, projection_version monotonicity)
- Persistence Integrity (workflows.json atomicity, checkpoint consistency, active-dir cleanup)
"""

import json
import os
import sys
import tempfile
import threading
import time

# Resolve project root
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.chdir(_ROOT)

# ==============================================================================
# HELPERS
# ==============================================================================

def _make_workflow(wf_id, status="ACTIVE", steps=None):
    return {
        "id": wf_id,
        "name": f"test_{wf_id}",
        "status": status,
        "steps": steps or [
            {"id": "step_1", "status": "COMPLETED", "purpose": "test step",
             "execution_result": {"status": "success", "result": 42}},
        ],
        "output": None,
    }


def _reset_registry():
    from system.orchestrator.workflow_control import _workflow_state_registry, _workflow_state_lock
    with _workflow_state_lock:
        _workflow_state_registry.clear()


# ==============================================================================
# TEST 1 — COMPLETED WRITE ATOMICITY
# ==============================================================================

def test_completed_write_atomicity():
    """
    Verify persistence.save_workflow COMPLETED path uses atomic tempfile→os.replace,
    not a direct open("w") write that can corrupt workflows.json on crash.
    """
    import inspect
    from system.orchestrator import persistence

    src = inspect.getsource(persistence.save_workflow)
    # Must contain tempfile.mkstemp (atomic pattern)
    assert "mkstemp" in src, "FAIL: save_workflow COMPLETED path does not use mkstemp"
    # Must NOT contain direct open(FILE_PATH, "w") in COMPLETED block
    # We check that the only open() call is via os.fdopen (the fd from mkstemp)
    # Simple heuristic: direct open(FILE_PATH, "w") must not appear after "COMPLETED"
    completed_idx = src.find("COMPLETED workflows")
    direct_write_idx = src.find('open(FILE_PATH, "w")')
    assert direct_write_idx == -1 or direct_write_idx < completed_idx, \
        "FAIL: direct open(FILE_PATH, 'w') still present in COMPLETED block"
    print("PASS test_completed_write_atomicity")


# ==============================================================================
# TEST 2 — FAILED ACTIVE-DIR CLEANUP
# ==============================================================================

def test_failed_active_dir_cleanup():
    """
    Verify FAILED workflows are deleted from ACTIVE_WORKFLOW_DIR on terminal confirmation.
    """
    from system.orchestrator.persistence import (
        save_workflow, delete_workflow, load_active_workflows,
        _active_workflow_path, _ensure_active_dir
    )
    wf_id = "test_failed_cleanup_001"
    wf = _make_workflow(wf_id, status="ACTIVE")
    _ensure_active_dir()
    # Write ACTIVE to disk first
    save_workflow(wf)
    path = _active_workflow_path(wf_id)
    assert os.path.exists(path), "FAIL: active workflow file not created"

    # Simulate terminal FAILED: delete from active dir
    delete_workflow(wf_id)
    assert not os.path.exists(path), "FAIL: FAILED workflow file still exists after delete_workflow"
    print("PASS test_failed_active_dir_cleanup")


# ==============================================================================
# TEST 3 — COLD-START AUTHORITY INVERSION ELIMINATED
# ==============================================================================

def test_cold_start_no_direct_dict_write():
    """
    Verify orchestrator_runtime.py no longer directly writes to _workflow_state_registry dict.
    Instead it calls _update_runtime_registry_only or _get_workflow_state.
    """
    import inspect
    from system.orchestrator import orchestrator_runtime
    src = inspect.getsource(orchestrator_runtime.run_workflow)
    # The old pattern was: _workflow_state_registry[...] = {
    # New pattern calls _update_runtime_registry_only or _get_workflow_state
    assert "_update_runtime_registry_only" in src or "_get_workflow_state" in src, \
        "FAIL: run_workflow still uses direct dict write instead of authority helper"
    assert '_workflow_state_registry[workflow.get("id' not in src and \
           '_workflow_state_registry[workflow.get(' not in src, \
        "FAIL: direct _workflow_state_registry dict assignment still in run_workflow cold-start block"
    print("PASS test_cold_start_no_direct_dict_write")


# ==============================================================================
# TEST 4 — REGISTRY WARM RESTORATION
# ==============================================================================

def test_warm_registry_from_disk_basic():
    """
    Verify warm_registry_from_disk populates registry from disk and normalizes
    ACTIVE → PENDING_RECOVERY.
    """
    from system.orchestrator.persistence import save_workflow, delete_workflow, _ensure_active_dir
    from system.orchestrator.workflow_control import (
        warm_registry_from_disk, _workflow_state_registry, _workflow_state_lock
    )

    wf_id_active = "test_warm_active_001"
    wf_id_paused = "test_warm_paused_001"

    # Write ACTIVE workflow to disk
    _ensure_active_dir()
    wf_active = _make_workflow(wf_id_active, status="ACTIVE")
    save_workflow(wf_active)

    # Write PAUSED workflow to disk
    wf_paused = _make_workflow(wf_id_paused, status="PAUSED")
    save_workflow(wf_paused)

    # Clear registry to simulate cold start
    _reset_registry()

    result = warm_registry_from_disk()

    with _workflow_state_lock:
        active_entry = _workflow_state_registry.get(wf_id_active)
        paused_entry = _workflow_state_registry.get(wf_id_paused)

    # ACTIVE must be normalized to PENDING_RECOVERY
    assert active_entry is not None, "FAIL: ACTIVE workflow not found in registry after warm restore"
    assert active_entry["status"] == "PENDING_RECOVERY", \
        f"FAIL: ACTIVE should become PENDING_RECOVERY, got {active_entry['status']}"

    # PAUSED must remain PAUSED
    assert paused_entry is not None, "FAIL: PAUSED workflow not found in registry after warm restore"
    assert paused_entry["status"] == "PAUSED", \
        f"FAIL: PAUSED should remain PAUSED, got {paused_entry['status']}"

    assert result["normalized_active"] >= 1, "FAIL: normalized_active count incorrect"

    # Cleanup
    delete_workflow(wf_id_active)
    delete_workflow(wf_id_paused)
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id_active, None)
        _workflow_state_registry.pop(wf_id_paused, None)

    print(f"PASS test_warm_registry_from_disk_basic — {result}")


def test_warm_registry_does_not_overwrite_existing():
    """
    Verify warm_registry_from_disk skips workflows already in registry
    (e.g. resume_workflow wrote ACTIVE before warm restore runs).
    """
    from system.orchestrator.persistence import save_workflow, delete_workflow, _ensure_active_dir
    from system.orchestrator.workflow_control import (
        warm_registry_from_disk, _workflow_state_registry, _workflow_state_lock,
        _update_runtime_registry_only
    )

    wf_id = "test_warm_no_overwrite_001"
    _ensure_active_dir()

    # Write ACTIVE to disk (stale mirror)
    wf = _make_workflow(wf_id, status="ACTIVE")
    save_workflow(wf)

    # Pre-populate registry with PAUSED (as if resume wrote it)
    _update_runtime_registry_only(wf_id, "PAUSED", "test_pre_populated")

    result = warm_registry_from_disk()

    with _workflow_state_lock:
        entry = _workflow_state_registry.get(wf_id)

    # Must remain PAUSED — warm restore MUST NOT overwrite
    assert entry is not None, "FAIL: entry missing after warm restore"
    assert entry["status"] == "PAUSED", \
        f"FAIL: existing PAUSED entry was overwritten by warm restore; got {entry['status']}"
    assert result["skipped"] >= 1, "FAIL: skipped count should be >= 1"

    # Cleanup
    delete_workflow(wf_id)
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    print(f"PASS test_warm_registry_does_not_overwrite_existing — {result}")


# ==============================================================================
# TEST 5 — CHECKPOINT AUTHORITY ALIGNMENT
# ==============================================================================

def test_checkpoint_uses_authoritative_status():
    """
    Verify checkpoint captures authoritative registry status, not compatibility mirror.
    """
    from system.orchestrator.checkpoint_manager import _extract_checkpoint_data
    from system.orchestrator.workflow_control import (
        _workflow_state_registry, _workflow_state_lock
    )

    wf_id = "test_checkpoint_auth_001"

    # Set up registry with PAUSED (authoritative)
    with _workflow_state_lock:
        _workflow_state_registry[wf_id] = {
            "status": "PAUSED",
            "last_updated": time.time(),
            "reason": "test"
        }

    # Compatibility mirror says ACTIVE (stale)
    wf = _make_workflow(wf_id, status="ACTIVE")

    data = _extract_checkpoint_data(wf)

    # Checkpoint must reflect authoritative PAUSED, not mirror ACTIVE
    assert data["workflow_status"] == "PAUSED", \
        f"FAIL: checkpoint captured mirror status '{data['workflow_status']}' instead of authoritative 'PAUSED'"

    # Cleanup
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    print("PASS test_checkpoint_uses_authoritative_status")


def test_checkpoint_fallback_to_mirror_when_registry_empty():
    """
    Verify checkpoint falls back to workflow["status"] when registry has no entry.
    """
    from system.orchestrator.checkpoint_manager import _extract_checkpoint_data
    from system.orchestrator.workflow_control import (
        _workflow_state_registry, _workflow_state_lock
    )

    wf_id = "test_checkpoint_fallback_001"

    # Ensure no registry entry
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    wf = _make_workflow(wf_id, status="BLOCKED")
    data = _extract_checkpoint_data(wf)

    assert data["workflow_status"] == "BLOCKED", \
        f"FAIL: fallback should return mirror 'BLOCKED', got '{data['workflow_status']}'"

    print("PASS test_checkpoint_fallback_to_mirror_when_registry_empty")


# ==============================================================================
# TEST 6 — bg_id CONTINUITY PERSISTENCE
# ==============================================================================

def test_bg_id_map_register_resolve_deregister():
    """
    Verify bg_id_map correctly persists, resolves, and removes bg_id mappings.
    """
    from system.orchestrator.bg_id_map import register_bg_id, resolve_bg_id, deregister_bg_id

    bg_id = "test-bg-id-00000000"
    wf_id = "test-workflow-id-00000000"

    # Register
    ok = register_bg_id(bg_id, wf_id)
    assert ok, "FAIL: register_bg_id returned False"

    # Resolve
    resolved = resolve_bg_id(bg_id)
    assert resolved == wf_id, f"FAIL: resolve_bg_id returned '{resolved}', expected '{wf_id}'"

    # Deregister
    ok = deregister_bg_id(bg_id)
    assert ok, "FAIL: deregister_bg_id returned False"

    # Must no longer be resolvable
    resolved_after = resolve_bg_id(bg_id)
    assert resolved_after is None, \
        f"FAIL: bg_id still resolvable after deregister: '{resolved_after}'"

    print("PASS test_bg_id_map_register_resolve_deregister")


def test_bg_id_map_survives_reload():
    """
    Verify bg_id_map persists to disk and survives a module-level reload (simulates restart).
    """
    from system.orchestrator.bg_id_map import register_bg_id, load_all, deregister_bg_id

    bg_id = "test-bg-persist-00000001"
    wf_id = "test-wf-persist-00000001"

    register_bg_id(bg_id, wf_id)

    # Reload: simulate restart by re-calling load_all (reads from disk)
    all_mappings = load_all()
    assert bg_id in all_mappings, f"FAIL: bg_id not found in persisted map after reload"
    assert all_mappings[bg_id] == wf_id, \
        f"FAIL: workflow_id mismatch after reload: '{all_mappings[bg_id]}'"

    # Cleanup
    deregister_bg_id(bg_id)
    print("PASS test_bg_id_map_survives_reload")


# ==============================================================================
# TEST 7 — PROJECTION VERSION MONOTONICITY ACROSS RESTART
# ==============================================================================

def test_projection_version_monotonicity():
    """
    Verify projection version counter resumes above last persisted value after simulated restart.
    """
    from system.orchestrator.projection_manager import _WorkflowProjectionStore, _persist_version, _load_persisted_versions

    wf_id = "test-proj-version-mono-001"

    # Get a store and advance the version
    store = _WorkflowProjectionStore(wf_id)
    v1 = store.next_version()
    v2 = store.next_version()
    v3 = store.next_version()
    assert v1 < v2 < v3, f"FAIL: versions not monotonically increasing: {v1}, {v2}, {v3}"

    # Simulate restart: create new store for same workflow_id
    store2 = _WorkflowProjectionStore(wf_id)
    v4 = store2.next_version()
    assert v4 > v3, \
        f"FAIL: post-restart version {v4} not above pre-restart version {v3} — monotonicity broken"

    # Cleanup: remove from persisted map
    versions = _load_persisted_versions()
    versions.pop(wf_id, None)
    from system.orchestrator.projection_manager import _VERSION_PATH, _ROOT as _PM_ROOT
    import json, tempfile, os
    dir_name = os.path.dirname(_VERSION_PATH)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(versions, f)
    os.replace(tmp, _VERSION_PATH)

    print(f"PASS test_projection_version_monotonicity — v1={v1} v2={v2} v3={v3} v4(restart)={v4}")


# ==============================================================================
# TEST 8 — CRASH RECOVERY SIMULATION (ACTIVE → RESTART)
# ==============================================================================

def test_crash_recovery_active_normalizes_to_pending_recovery():
    """
    Simulate: workflow was ACTIVE on disk (process crashed) → restart → warm restore →
    registry must show PENDING_RECOVERY (not ACTIVE zombie).
    """
    from system.orchestrator.persistence import save_workflow, delete_workflow, _ensure_active_dir
    from system.orchestrator.workflow_control import (
        warm_registry_from_disk, _workflow_state_registry, _workflow_state_lock
    )

    wf_id = "test_crash_active_001"
    _ensure_active_dir()

    # Simulate crash: ACTIVE workflow written to disk, process died
    wf = _make_workflow(wf_id, status="ACTIVE")
    save_workflow(wf)

    # Simulate restart: registry is empty
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    # Warm restore
    warm_registry_from_disk()

    with _workflow_state_lock:
        entry = _workflow_state_registry.get(wf_id)

    assert entry is not None, "FAIL: crashed ACTIVE workflow not found in registry after warm restore"
    assert entry["status"] == "PENDING_RECOVERY", \
        f"FAIL: crashed ACTIVE workflow must become PENDING_RECOVERY, got '{entry['status']}'"

    # Cleanup
    delete_workflow(wf_id)
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    print("PASS test_crash_recovery_active_normalizes_to_pending_recovery")


def test_crash_recovery_paused_preserved():
    """
    Simulate: workflow was PAUSED on disk (correctly saved before crash) → restart →
    warm restore → registry must show PAUSED (not corrupted).
    """
    from system.orchestrator.persistence import save_workflow, delete_workflow, _ensure_active_dir
    from system.orchestrator.workflow_control import (
        warm_registry_from_disk, _workflow_state_registry, _workflow_state_lock
    )

    wf_id = "test_crash_paused_001"
    _ensure_active_dir()
    wf = _make_workflow(wf_id, status="PAUSED")
    save_workflow(wf)

    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    warm_registry_from_disk()

    with _workflow_state_lock:
        entry = _workflow_state_registry.get(wf_id)

    assert entry is not None, "FAIL: PAUSED workflow not found in registry"
    assert entry["status"] == "PAUSED", \
        f"FAIL: PAUSED should remain PAUSED after warm restore, got '{entry['status']}'"

    delete_workflow(wf_id)
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    print("PASS test_crash_recovery_paused_preserved")


def test_failed_workflows_not_in_active_dir():
    """
    Verify FAILED workflows are removed from active dir (do not accumulate as stale state).
    FAILED is terminal — should not persist in ACTIVE_WORKFLOW_DIR.
    Uses delete_workflow directly (what runtime now calls on FAILED terminal).
    """
    from system.orchestrator.persistence import (
        save_workflow, delete_workflow, _ensure_active_dir, _active_workflow_path
    )

    wf_id = "test_failed_no_active_001"
    _ensure_active_dir()

    # Write ACTIVE first (simulate workflow was running)
    wf = _make_workflow(wf_id, status="ACTIVE")
    save_workflow(wf)
    path = _active_workflow_path(wf_id)
    assert os.path.exists(path), "FAIL: active file not created"

    # Transition to FAILED and clean up (as orchestrator_runtime now does)
    wf["status"] = "FAILED"
    delete_workflow(wf_id)

    assert not os.path.exists(path), \
        f"FAIL: FAILED workflow still in active dir at {path}"

    print("PASS test_failed_workflows_not_in_active_dir")


# ==============================================================================
# RUNNER
# ==============================================================================

if __name__ == "__main__":
    tests = [
        test_completed_write_atomicity,
        test_failed_active_dir_cleanup,
        test_cold_start_no_direct_dict_write,
        test_warm_registry_from_disk_basic,
        test_warm_registry_does_not_overwrite_existing,
        test_checkpoint_uses_authoritative_status,
        test_checkpoint_fallback_to_mirror_when_registry_empty,
        test_bg_id_map_register_resolve_deregister,
        test_bg_id_map_survives_reload,
        test_projection_version_monotonicity,
        test_crash_recovery_active_normalizes_to_pending_recovery,
        test_crash_recovery_paused_preserved,
        test_failed_workflows_not_in_active_dir,
    ]

    passed = 0
    failed = 0
    errors = []

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            failed += 1
            errors.append((test_fn.__name__, str(e)))
            print(f"FAIL {test_fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            errors.append((test_fn.__name__, f"EXCEPTION: {e}"))
            print(f"ERROR {test_fn.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    if errors:
        print("\nFAILURES:")
        for name, msg in errors:
            print(f"  {name}: {msg}")
    else:
        print("ALL TESTS PASSED")
    sys.exit(0 if failed == 0 else 1)

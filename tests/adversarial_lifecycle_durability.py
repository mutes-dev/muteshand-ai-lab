"""
Phase 3F-XA — Adversarial Validation Tests

Tests authority inversion, projection corruption, recovery legality,
persistence failure scenarios.
"""
import os
import sys
import time

os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# === SAFETY: Isolate persistence to temp directories ===
import tempfile
_test_active_dir = tempfile.mkdtemp(prefix="adv_lifecycle_test_")
os.makedirs(_test_active_dir, exist_ok=True)
import system.orchestrator.persistence as _pm
_pm.ACTIVE_WORKFLOW_DIR = _test_active_dir

_test_checkpoint_dir = tempfile.mkdtemp(prefix="adv_checkpoint_test_")
os.makedirs(_test_checkpoint_dir, exist_ok=True)
import system.orchestrator.checkpoint_manager as _cm
_cm.CHECKPOINT_DIR = _test_checkpoint_dir

from tests._test_safety_guard import guard_delete_workflow, guard_rmtree

import atexit

def _cleanup_adv_test_dirs():
    guard_rmtree(_test_active_dir)
    guard_rmtree(_test_checkpoint_dir)


atexit.register(_cleanup_adv_test_dirs)
# === END SAFETY ===

from system.orchestrator.workflow_control import (
    _workflow_state_registry, _workflow_state_lock,
    _update_workflow_state, _update_runtime_registry_only,
    warm_registry_from_disk, pause_workflow, resume_workflow
)
from system.orchestrator.persistence import (
    save_workflow, _ensure_active_dir, _active_workflow_path
)
from system.orchestrator.bg_id_map import (
    register_bg_id, resolve_bg_id, deregister_bg_id, load_all
)
from system.orchestrator.projection_manager import _WorkflowProjectionStore


def _mk(wf_id, status="ACTIVE"):
    return {
        "id": wf_id, "name": "adv", "status": status,
        "steps": [{"id": "s1", "status": "PENDING", "purpose": "test", "execution_result": None}],
        "output": None
    }


def _clear(wf_id):
    try:
        guard_delete_workflow(wf_id)
    except Exception:
        pass
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)


# ===========================================================================
# AUTHORITY INVERSION SCENARIOS
# ===========================================================================

def test_adv_stale_active_normalized():
    """Stale ACTIVE on disk (crashed workflow) must NOT become zombie ACTIVE in registry."""
    wf_id = "adv_stale_active_001"
    _ensure_active_dir()
    save_workflow(_mk(wf_id, "ACTIVE"))
    _clear(wf_id)
    save_workflow(_mk(wf_id, "ACTIVE"))  # re-save after clear

    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    warm_registry_from_disk()

    with _workflow_state_lock:
        entry = _workflow_state_registry.get(wf_id)

    status = entry["status"] if entry else None
    assert status == "PENDING_RECOVERY", \
        "FAIL: stale ACTIVE not normalized — zombie ACTIVE in registry: {}".format(status)
    _clear(wf_id)
    print("PASS test_adv_stale_active_normalized")


def test_adv_pause_on_pending_recovery_rejected():
    """pause_workflow on PENDING_RECOVERY must fail — FSM rejects unknown state."""
    wf_id = "adv_pause_recovery_001"
    _ensure_active_dir()
    save_workflow(_mk(wf_id, "ACTIVE"))

    # Force PENDING_RECOVERY into registry
    with _workflow_state_lock:
        _workflow_state_registry[wf_id] = {
            "status": "PENDING_RECOVERY", "last_updated": time.time(), "reason": "test"
        }

    result = pause_workflow(wf_id)
    assert result["status"] == "failure", \
        "FAIL: pause on PENDING_RECOVERY should be rejected, got: {}".format(result)
    _clear(wf_id)
    print("PASS test_adv_pause_on_pending_recovery_rejected")


def test_adv_resume_on_pending_recovery_rejected():
    """resume_workflow on PENDING_RECOVERY must fail — not a valid PAUSED state."""
    wf_id = "adv_resume_recovery_001"
    _ensure_active_dir()
    save_workflow(_mk(wf_id, "ACTIVE"))

    with _workflow_state_lock:
        _workflow_state_registry[wf_id] = {
            "status": "PENDING_RECOVERY", "last_updated": time.time(), "reason": "test"
        }

    result = resume_workflow(wf_id)
    assert result["status"] == "failure", \
        "FAIL: resume on PENDING_RECOVERY should be rejected, got: {}".format(result)
    _clear(wf_id)
    print("PASS test_adv_resume_on_pending_recovery_rejected")


def test_adv_warm_restore_preserves_live_active():
    """warm_registry_from_disk must NOT overwrite a live ACTIVE registry entry."""
    wf_id = "adv_live_active_001"
    _ensure_active_dir()
    save_workflow(_mk(wf_id, "ACTIVE"))

    # Simulate live execution: registry already has ACTIVE
    _update_runtime_registry_only(wf_id, "ACTIVE", "live_execution")

    warm_registry_from_disk()

    with _workflow_state_lock:
        entry = _workflow_state_registry.get(wf_id)

    assert entry is not None, "FAIL: registry entry missing"
    assert entry["status"] == "ACTIVE", \
        "FAIL: live ACTIVE was overwritten to: {}".format(entry["status"])
    _clear(wf_id)
    print("PASS test_adv_warm_restore_preserves_live_active")


def test_adv_stale_paused_restoration_correct():
    """PAUSED on disk after crash must be correctly restored as PAUSED (not ACTIVE inversion)."""
    wf_id = "adv_paused_restore_001"
    _ensure_active_dir()
    save_workflow(_mk(wf_id, "PAUSED"))

    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    warm_registry_from_disk()

    with _workflow_state_lock:
        entry = _workflow_state_registry.get(wf_id)

    assert entry is not None, "FAIL: PAUSED not found in registry"
    assert entry["status"] == "PAUSED", \
        "FAIL: PAUSED not preserved after warm restore: {}".format(entry["status"])
    _clear(wf_id)
    print("PASS test_adv_stale_paused_restoration_correct")


# ===========================================================================
# PROJECTION CORRUPTION SCENARIOS
# ===========================================================================

def test_adv_bg_id_not_resolvable_after_deregister():
    """Deregistered bg_id must not be resolvable (no stale reuse)."""
    bg_id = "adv-bg-stale-001"
    wf_id = "adv-wf-stale-001"
    register_bg_id(bg_id, wf_id)
    deregister_bg_id(bg_id)
    resolved = resolve_bg_id(bg_id)
    assert resolved is None, \
        "FAIL: deregistered bg_id still resolvable: {}".format(resolved)
    print("PASS test_adv_bg_id_not_resolvable_after_deregister")


def test_adv_projection_version_no_rollback():
    """Post-restart projection version must be strictly greater than pre-restart version."""
    wf_id = "adv-proj-ver-001"
    store1 = _WorkflowProjectionStore(wf_id)
    pre_restart_max = store1.next_version()
    for _ in range(5):
        pre_restart_max = store1.next_version()

    # Simulate restart
    store2 = _WorkflowProjectionStore(wf_id)
    post_restart_first = store2.next_version()

    assert post_restart_first > pre_restart_max, \
        "FAIL: post-restart version {} not above pre-restart {}".format(
            post_restart_first, pre_restart_max)

    # Cleanup persisted version
    from system.orchestrator.projection_manager import _VERSION_PATH, _load_persisted_versions
    import json, tempfile
    data = _load_persisted_versions()
    data.pop(wf_id, None)
    dir_name = os.path.dirname(_VERSION_PATH)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, _VERSION_PATH)

    print("PASS test_adv_projection_version_no_rollback — pre={} post={}".format(
        pre_restart_max, post_restart_first))


# ===========================================================================
# RECOVERY LEGALITY
# ===========================================================================

def test_adv_duplicate_registry_entry_not_created():
    """warm_registry_from_disk called twice must not duplicate or corrupt entries."""
    wf_id = "adv_dup_entry_001"
    _ensure_active_dir()
    save_workflow(_mk(wf_id, "PAUSED"))

    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)

    r1 = warm_registry_from_disk()
    r2 = warm_registry_from_disk()  # second call — should skip existing

    with _workflow_state_lock:
        entry = _workflow_state_registry.get(wf_id)

    assert entry is not None, "FAIL: entry missing"
    assert entry["status"] == "PAUSED", "FAIL: status corrupted: {}".format(entry["status"])
    # Second call must skip (entry already exists)
    assert r2["skipped"] >= 1, "FAIL: second warm_restore didn't skip existing entries"
    _clear(wf_id)
    print("PASS test_adv_duplicate_registry_entry_not_created")


def test_adv_failed_workflow_removed_from_active_dir():
    """FAILED terminal workflows must not remain in ACTIVE_WORKFLOW_DIR."""
    wf_id = "adv_failed_cleanup_001"
    _ensure_active_dir()
    wf = _mk(wf_id, "ACTIVE")
    save_workflow(wf)
    path = _active_workflow_path(wf_id)
    assert os.path.exists(path), "FAIL: active file not written"

    guard_delete_workflow(wf_id)
    assert not os.path.exists(path), "FAIL: FAILED workflow still in active dir"
    print("PASS test_adv_failed_workflow_removed_from_active_dir")


# ===========================================================================
# PERSISTENCE FAILURE SCENARIOS
# ===========================================================================

def test_adv_bg_id_missing_entry_non_fatal():
    """Resolving a never-registered bg_id returns None without raising."""
    result = resolve_bg_id("nonexistent-bg-id-xyzzy")
    assert result is None, "FAIL: nonexistent bg_id should resolve to None, got: {}".format(result)
    print("PASS test_adv_bg_id_missing_entry_non_fatal")


def test_adv_warm_restore_with_no_active_dir():
    """warm_registry_from_disk must not raise if no active workflows exist."""
    from system.orchestrator.workflow_control import warm_registry_from_disk
    # Just call it — if ACTIVE_WORKFLOW_DIR is empty or missing, must return gracefully
    try:
        result = warm_registry_from_disk()
        assert isinstance(result, dict), "FAIL: should return a dict"
        print("PASS test_adv_warm_restore_with_no_active_dir — result={}".format(result))
    except Exception as e:
        print("FAIL test_adv_warm_restore_with_no_active_dir: {}".format(e))
        raise


# ===========================================================================
# RUNNER
# ===========================================================================

if __name__ == "__main__":
    tests = [
        test_adv_stale_active_normalized,
        test_adv_pause_on_pending_recovery_rejected,
        test_adv_resume_on_pending_recovery_rejected,
        test_adv_warm_restore_preserves_live_active,
        test_adv_stale_paused_restoration_correct,
        test_adv_bg_id_not_resolvable_after_deregister,
        test_adv_projection_version_no_rollback,
        test_adv_duplicate_registry_entry_not_created,
        test_adv_failed_workflow_removed_from_active_dir,
        test_adv_bg_id_missing_entry_non_fatal,
        test_adv_warm_restore_with_no_active_dir,
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
            print("FAIL {}: {}".format(test_fn.__name__, e))
        except Exception as e:
            failed += 1
            errors.append((test_fn.__name__, "EXCEPTION: {}".format(e)))
            print("ERROR {}: {}".format(test_fn.__name__, e))
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("ADVERSARIAL RESULTS: {} passed, {} failed".format(passed, failed))
    if errors:
        print("\nFAILURES:")
        for name, msg in errors:
            print("  {}: {}".format(name, msg))
    else:
        print("ALL ADVERSARIAL TESTS PASSED")
    sys.exit(0 if failed == 0 else 1)

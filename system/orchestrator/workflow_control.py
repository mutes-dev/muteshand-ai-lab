"""
WORKFLOW CONTROL — Pause/Resume, Plan Control, and Control Actions

Per STATE_TRANSITIONS_CONTRACT_V1:
- ACTIVE → PAUSED (user action)
- PAUSED → ACTIVE (resume)

Per GUI_FUNCTIONALITY_CONTRACT_V1:
- ALL actions require workflow_id
- ALL actions require step_id when applicable

Per PLAN_CONTROL_CONTRACT_V1:
- COMPLETED steps = locked
- ACTIVE steps = editable with restart
- FUTURE steps = fully editable
- Validate dependencies after any edit
"""

from typing import Dict, Any, List, Optional
import threading
import time

from system.orchestrator.persistence import load_active_workflows, save_workflow, workflow_persistence_exists
from system.orchestrator.workflow_validator import validate_workflow
from system.interface import event_emitter
import os


# =============================================================================
# S9D STRUCTURED INVALIDATION TRACE — PHASE S9D IMPLEMENTATION
# =============================================================================

def _emit_invalidation_trace(
    workflow_id: str,
    invalidation_type: str,
    step_id: str = None,
    invalidated_targets: list = None,
    execution_generation: int = None,
    reason: str = None,
    details: dict = None,
    actor: str = None,
) -> None:
    """
    Emit structured invalidation trace event.

    Per PHASE S9D: Structured invalidation diagnostics for execution invalidation,
    dependency propagation, and execution generation changes.

    Trace is observational only — does NOT affect execution.
    FAILURE-ISOLATED: trace failure MUST NOT block invalidation.

    Args:
        workflow_id: Target workflow ID
        invalidation_type: Category (step_outputs, dependents, execution_generation, etc.)
        step_id: Step triggering invalidation
        invalidated_targets: List of affected step IDs
        execution_generation: Current generation counter
        reason: Human-readable explanation
        details: Additional metadata dict
        actor: Who triggered the invalidation
    """
    import time
    import sys

    trace_event = {
        "event_type": "invalidation_trace",
        "workflow_id": workflow_id,
        "invalidation_type": invalidation_type,
        "step_id": step_id,
        "invalidated_targets": invalidated_targets or [],
        "execution_generation": execution_generation,
        "reason": reason,
        "details": details,
        "actor": actor,
        "timestamp": time.time(),
    }

    # Publish to event bus if available — FAILURE-ISOLATED
    try:
        from system.interface.event_bus import publish_event
        publish_event(
            workflow_id=workflow_id,
            event_type="invalidation_trace",
            data=trace_event,
        )
    except Exception:
        pass

    # Console trace — FAILURE-ISOLATED
    try:
        targets_str = ",".join(invalidated_targets) if invalidated_targets else "none"
        gen_str = f" gen={execution_generation}" if execution_generation else ""
        details_str = ""
        if details and "previous_generation" in details and "new_generation" in details:
            details_str = f" prev_gen={details['previous_generation']} new_gen={details['new_generation']}"
        print(
            f"[INVALIDATION_TRACE] wf={workflow_id} type={invalidation_type} "
            f"step={step_id} targets={targets_str}{gen_str}{details_str}",
            file=sys.stderr,
        )
    except Exception:
        pass


# In-memory workflow state registry (per-workflow state transitions)
# workflow_id -> {"status": str, "last_updated": float, "execution_generation": int}
# execution_generation is a NON-authoritative coordination metadata counter for
# single-execution-ownership enforcement. It is monotonically increasing, stored
# ONLY in Runtime Registry (volatile), NOT persisted, and does NOT gate lifecycle
# transitions. Per PHASE-IVA EXECUTION LEASE COORDINATION DESIGN AUDIT.
_workflow_state_registry: Dict[str, Dict[str, Any]] = {}
_workflow_state_lock = threading.RLock()


# =============================================================================
# ISSUE-062 — FAILED ACTIONABILITY METADATA
# =============================================================================

# Per LIFECYCLE_AUTHORITY_CONTRACT_V1: lifecycle state ≠ actionability.
# FAILED remains the sole lifecycle FAILED state.
# Actionability/retryability is backend-authored metadata, NOT derived from status.
#
# Metadata fields (workflow-level, persisted):
#   failed_recoverable       — bool, default True for FAILED (backward compat)
#   retry_disabled_reason    — str|null, why retry is not allowed
#   actionability_reason     — str|null, why actionability classification
#   terminalization_reason   — str|null, why workflow became terminal

_FAILED_METADATA_DEFAULTS = {
    "failed_recoverable": True,
    "retry_disabled_reason": None,
    "actionability_reason": "retry_target_available",
    "terminalization_reason": None,
}


def _get_failed_metadata(workflow_id: str) -> Dict[str, Any]:
    """
    Retrieve FAILED actionability metadata for a workflow.

    Per ISSUE-062:
    - Reads from persisted workflow first (authoritative for metadata).
    - Falls back to registry entry.
    - Returns defaults for backward compatibility when metadata is absent.
    """
    # Try persisted workflow first
    try:
        _wf = load_workflow(workflow_id)
        if _wf and isinstance(_wf, dict):
            _meta = {
                "failed_recoverable": _wf.get("failed_recoverable"),
                "retry_disabled_reason": _wf.get("retry_disabled_reason"),
                "actionability_reason": _wf.get("actionability_reason"),
                "terminalization_reason": _wf.get("terminalization_reason"),
            }
            # Backward compatibility: default True for FAILED or BLOCKED workflows
            if _meta["failed_recoverable"] is None:
                _status = _wf.get("status", "UNKNOWN")
                _meta["failed_recoverable"] = (_status in ("FAILED", "BLOCKED"))
            return _meta
    except Exception:
        pass

    # Fallback: registry (transient, may not have metadata)
    with _workflow_state_lock:
        _reg = _workflow_state_registry.get(workflow_id, {})
        _meta = {
            "failed_recoverable": _reg.get("failed_recoverable"),
            "retry_disabled_reason": _reg.get("retry_disabled_reason"),
            "actionability_reason": _reg.get("actionability_reason"),
            "terminalization_reason": _reg.get("terminalization_reason"),
        }
        if _meta["failed_recoverable"] is None:
            _meta["failed_recoverable"] = (_reg.get("status") in ("FAILED", "BLOCKED"))
        return _meta


def _compute_retry_eligible(workflow_id: str, steps: list) -> bool:
    """
    Compute whether normal retry is legally available for this workflow.

    Per ISSUE-062 + ISSUE-098A:
    - retry_eligible = failed_recoverable AND a valid retry target exists
      AND the target step has not exhausted normal retries.
    - Backend-authored truth; frontend MUST NOT synthesize.
    """
    _meta = _get_failed_metadata(workflow_id)
    if not _meta.get("failed_recoverable"):
        return False

    # Compute retry target inline (covers FAILED and BLOCKED workflows)
    _target_id = None
    for step in steps:
        if step.get("status") == "FAILED":
            _target_id = step.get("id")
            break
    if _target_id is None:
        for step in steps:
            if step.get("status") == "BLOCKED":
                _target_id = step.get("id")
                break

    if _target_id is None:
        return False

    # Normal retry boundedness: target step must have retries < max_retries
    for step in steps:
        if step.get("id") == _target_id:
            _retries = step.get("retries", 0)
            _max_retries = step.get("max_retries", 3)
            if _retries >= _max_retries:
                return False
            break

    return True


def _set_failed_metadata(workflow_id: str, **kwargs) -> None:
    """
    Write FAILED actionability metadata into both registry and persistence.

    Per ISSUE-062:
    - Metadata is persisted in the workflow JSON so it survives restarts.
    - Registry is updated for fast in-memory access.
    """
    # Update registry
    with _workflow_state_lock:
        if workflow_id in _workflow_state_registry:
            for _key, _val in kwargs.items():
                _workflow_state_registry[workflow_id][_key] = _val

    # Update persistence
    try:
        _wf = load_workflow(workflow_id)
        if _wf and isinstance(_wf, dict):
            for _key, _val in kwargs.items():
                _wf[_key] = _val
            save_workflow(_wf)
    except Exception:
        pass


def _init_failed_metadata_defaults(workflow_id: str, reason: str = None) -> None:
    """
    Initialize default FAILED metadata when a workflow first enters FAILED.

    Per ISSUE-062 backward compatibility:
    - Default failed_recoverable = True (all current FAILED are actionable).
    - terminalization_reason captures why FAILED occurred.
    """
    _defaults = dict(_FAILED_METADATA_DEFAULTS)
    if reason:
        _defaults["terminalization_reason"] = reason
    _set_failed_metadata(workflow_id, **_defaults)


# ============================================================================
# LIFECYCLE TRANSITION AUTHORITY (Phase 4 — Enforcement)
# ============================================================================

# Step states that are internal-transition only (not user-facing transitions)
# BLOCKED → PENDING is an internal dependency-release transition performed by the
# scheduler pre-flight. It is NOT defined in STATE_TRANSITIONS_CONTRACT_V1 §STEP TRANSITIONS
# but is a documented internal transition. See FSM gap findings in audit.
_INTERNAL_TRANSITIONS = {
    ("BLOCKED", "PENDING"),   # dependency_wait release — scheduler-internal; NOT in public FSM (contract gap, see audit)
    ("FAILED", "PENDING"),    # retry recovery — authority-controlled; NOT in public FSM (strict by design)
    # NOTE: ACTIVE→PENDING (plan edit restart) is now in the public FSM per PLAN_CONTROL_CONTRACT_V1.
    # NOTE: PENDING→BLOCKED is now in the public FSM; removed from internal-only set.
    # NOTE: RETRY is NOT a valid lifecycle state per STATE_TRANSITIONS_CONTRACT_V1.
    #       Retry is an execution regeneration operation; step status remains PENDING.
}


def request_step_transition(
    step: dict,
    new_status: str,
    reason: str = None,
    validate: bool = True,
    _internal: bool = False,
) -> bool:
    """
    Request a lifecycle transition for a step via Lifecycle Authority.

    Per LIFECYCLE_AUTHORITY_CONTRACT_V1 §2+8:
    - ONLY Lifecycle Authority may commit lifecycle transitions
    - All transitions MUST pass through here and obey STATE_TRANSITIONS_CONTRACT_V1
    - Invalid transitions MUST be rejected

    Per AUTHORITY_MODEL §ORCHESTRATOR:
    - Schedulers and executors REQUEST transitions — they do not define them.

    Args:
        step:       The step dict (mutated in place on success).
        new_status: Target lifecycle status.
        reason:     Optional audit reason string (stored in blocked_reason or _transition_reason).
        validate:   If True, enforce FSM check. Set False ONLY for initialization paths
                    (e.g. fresh step construction) where there is no prior state.
        _internal:  If True, also allow internal-only transitions not in public FSM.

    Returns:
        True  — transition committed.
        False — transition rejected (invalid per FSM; step unchanged).
    """
    current_status = step.get("status", "PENDING")

    if validate:
        fsm_valid = _is_valid_state_transition(current_status, new_status)
        internal_valid = _internal and (current_status, new_status) in _INTERNAL_TRANSITIONS

        if not fsm_valid and not internal_valid:
            # Rejected — do NOT mutate step
            import sys
            print(
                f"[LIFECYCLE_AUTHORITY] REJECTED transition {current_status}\u2192{new_status} "
                f"for step {step.get('id','?')} reason={reason}",
                file=sys.stderr
            )
            return False

    # Commit transition
    step["status"] = new_status

    # Audit annotation
    if new_status == "BLOCKED":
        # Only BLOCKED steps may carry blocked_reason
        if reason:
            step["blocked_reason"] = reason
    else:
        # === FIX B: STATE INVARIANT — non-BLOCKED steps MUST NOT carry blocked_reason ===
        # Per DEPENDENCY_MODEL_CONTRACT_V1: blocked_reason is only valid on BLOCKED steps.
        # Clear unconditionally — do NOT gate this on whether reason was supplied.
        # Previous code had this inside 'if reason:' which left stale blocked_reason
        # on ACTIVE/PENDING/COMPLETED steps when no reason arg was passed.
        step.pop("blocked_reason", None)
        if reason:
            step["_transition_reason"] = reason

    return True


# ============================================================================
# WORKFLOW STATE MANAGEMENT (Internal)
# ============================================================================

def _get_workflow_state(workflow_id: str) -> Optional[Dict[str, Any]]:
    """Get current state for workflow from registry, then fast single-file fallback."""
    with _workflow_state_lock:
        if workflow_id in _workflow_state_registry:
            return _workflow_state_registry[workflow_id].copy()

    # Fast single-file fallback — do NOT call load_active_workflows() (full scan).
    try:
        import json as _json_gws
        from system.orchestrator.persistence import _active_workflow_path as _awp_gws
        import os as _os_gws
        _path_gws = _awp_gws(workflow_id)
        if _os_gws.path.exists(_path_gws):
            with open(_path_gws, "r", encoding="utf-8") as _f_gws:
                _wf_gws = _json_gws.load(_f_gws)
            if isinstance(_wf_gws, dict) and _wf_gws.get("id") == workflow_id:
                # === LIFECYCLE FALLBACK CONTINUITY FIX ===
                # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1 §RECOVERY SEMANTICS:
                # Fallback MUST NOT silently regress ACTIVE/BLOCKED workflows to QUEUED.
                # QUEUED implies "not yet started" which violates continuity for workflows
                # that have execution history but lack explicit status in persistence.
                #
                # PENDING_RECOVERY is the correct continuity-preserving fallback:
                # - Indicates workflow exists in persistence (has history)
                # - Requires explicit lifecycle transition to resume
                # - Prevents illegal operations (pause from PENDING_RECOVERY is invalid)
                # - Aligns with warm_registry_from_disk() ACTIVE/ACTIVATING normalization
                _disk_status = _wf_gws.get("status")
                if _disk_status is None:
                    # Workflow exists but lacks status field — treat as recovery candidate
                    _fallback_status = "PENDING_RECOVERY"
                    print(f"[LIFECYCLE_FALLBACK] {workflow_id}: status field missing, using PENDING_RECOVERY (continuity preserved)")
                else:
                    _fallback_status = _disk_status
                return {
                    "status": _fallback_status,
                    "last_updated": time.time(),
                    "failed_recoverable": _wf_gws.get("failed_recoverable"),
                    "retry_disabled_reason": _wf_gws.get("retry_disabled_reason"),
                    "actionability_reason": _wf_gws.get("actionability_reason"),
                    "terminalization_reason": _wf_gws.get("terminalization_reason"),
                }
    except Exception:
        pass
    return None


def _set_runtime_activity(workflow_id: str, activity: str) -> None:
    """
    Set runtime_activity in the authoritative runtime registry.

    Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    - Runtime Registry is the authoritative execution visibility source
    - runtime_activity is coordination-only observability metadata
    - NOT lifecycle authority, NOT projection truth, NOT frontend-derived

    Allowed values:
        BOOTSTRAPPING, PLANNING, REGISTERING, EXECUTING, RESOLVING,
        PAUSING, PAUSED, RESUMING, IDLE

    Failure-isolated: registry write failure MUST NOT affect execution.
    """
    _ALLOWED = {
        "BOOTSTRAPPING", "PLANNING", "REGISTERING", "EXECUTING",
        "RESOLVING", "PAUSING", "PAUSED", "RESUMING", "IDLE",
    }
    if activity not in _ALLOWED:
        return
    try:
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                _old = _workflow_state_registry[workflow_id].get("runtime_activity", "UNKNOWN")
                _workflow_state_registry[workflow_id]["runtime_activity"] = activity
                print(f"[RUNTIME_ACTIVITY] {workflow_id}: {_old} -> {activity}")
            else:
                print(f"[RUNTIME_ACTIVITY:WARN] {workflow_id} not in registry, cannot set {activity}")
    except Exception as _e:
        print(f"[RUNTIME_ACTIVITY:ERROR] {workflow_id}: {activity} failed: {_e}")


def _update_workflow_state(workflow_id: str, new_status: str, reason: str = None, workflow_dict: dict = None) -> bool:
    """
    Update BOTH the authoritative runtime registry AND the disk persistence.
    Optionally synchronize the authoritative lifecycle state into an in-memory
    workflow dict (execution snapshot) — this is a SYNC BRIDGE, NOT authority
    movement. Runtime registry remains sole lifecycle authority.

    Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
    - Runtime registry is sole lifecycle authority
    - Disk persistence is a COMPATIBILITY MIRROR
    - This function writes to both to keep them in sync
    - workflow_dict synchronization is additive projection-layer convergence ONLY

    Per PHASE 1 REMEDIATION:
    - Hard guard for ACTIVE transitions: persistence must exist
    """
    if not workflow_id:
        return False

    # === HARD GUARD: Persistence file must exist before ACTIVATING or ACTIVE transition ===
    # Uses fast O(1) file-existence check — NOT load_active_workflows() scan.
    # Full structural validation only happens at startup (validate_runtime_activation).
    if new_status in ("ACTIVATING", "ACTIVE", "PENDING_RECOVERY"):
        if not workflow_persistence_exists(workflow_id):
            print(f"[INVARIANT:FAIL] _update_workflow_state rejected {workflow_id}→{new_status}: no persistence file")
            return False

    # === TERMINAL LIFECYCLE TRANSITION GUARD ===
    # Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
    # CANCELLED is immutable terminal - must never be downgraded.
    # Check current authoritative state before allowing any transition.
    with _workflow_state_lock:
        _current_state = _workflow_state_registry.get(workflow_id)
        if _current_state:
            _current_status = _current_state.get("status")
            if _current_status == "CANCELLED" and new_status != "CANCELLED":
                print("[CANCELLED_TERMINAL_LOCK]", {
                    "workflow_id": workflow_id,
                    "current": _current_status,
                    "attempted": new_status,
                    "reason": reason,
                    "action": "ignored"
                })
                return False  # Reject downgrade from CANCELLED

    with _workflow_state_lock:
        # Update in-memory registry (authoritative)
        # Preserve execution_generation and runtime_activity (coordination metadata)
        # Preserve ISSUE-062 FAILED actionability metadata
        _existing_entry = _workflow_state_registry.get(workflow_id, {})
        _existing_gen = _existing_entry.get("execution_generation", 1)
        _existing_activity = _existing_entry.get("runtime_activity", "IDLE")
        _failed_recoverable = _existing_entry.get("failed_recoverable")
        _retry_disabled_reason = _existing_entry.get("retry_disabled_reason")
        _actionability_reason = _existing_entry.get("actionability_reason")
        _terminalization_reason = _existing_entry.get("terminalization_reason")
        _workflow_state_registry[workflow_id] = {
            "status": new_status,
            "last_updated": time.time(),
            "reason": reason,
            "execution_generation": _existing_gen,
            "runtime_activity": _existing_activity,
            "failed_recoverable": _failed_recoverable,
            "retry_disabled_reason": _retry_disabled_reason,
            "actionability_reason": _actionability_reason,
            "terminalization_reason": _terminalization_reason,
        }

    # Persist to disk (compatibility mirror) — atomic single-file update.
    # Do NOT call load_active_workflows() (full scan + race). Read only the one file.
    try:
        import json as _json_upd
        from system.orchestrator.persistence import _active_workflow_path as _awp_upd
        import tempfile as _tmp_upd
        import os as _os_upd
        import time as _time_upd
        _path_upd = _awp_upd(workflow_id)
        if _os_upd.path.exists(_path_upd):
            with open(_path_upd, "r", encoding="utf-8") as _rf:
                _wf_upd = _json_upd.load(_rf)
            _wf_upd["status"] = new_status
            # TASK_HUB_TIMESTAMP_PERSISTENCE: Bridge registry timestamps to persisted workflow
            _now_upd = _time_upd.time()
            if not _wf_upd.get("created_at"):
                _wf_upd["created_at"] = _now_upd
            _wf_upd["updated_at"] = _now_upd
            _wf_upd["last_updated"] = _now_upd
            _dir_upd = _os_upd.path.dirname(_path_upd)
            _fd_upd, _tmp_path_upd = _tmp_upd.mkstemp(dir=_dir_upd, suffix=".tmp")
            try:
                with _os_upd.fdopen(_fd_upd, "w", encoding="utf-8") as _wf_out:
                    _json_upd.dump(_wf_upd, _wf_out, ensure_ascii=False, indent=2)
                _os_upd.replace(_tmp_path_upd, _path_upd)
            except Exception:
                try:
                    _os_upd.remove(_tmp_path_upd)
                except OSError:
                    pass
    except Exception:
        # Persistence failure is non-fatal — registry remains authoritative
        pass

    # === LIFECYCLE SYNCHRONIZATION BRIDGE (Phase 4G-A.9) ===
    # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
    # Runtime registry is sole lifecycle authority.
    # workflow_dict is an execution-state snapshot that MAY be lifecycle-synchronized
    # for projection-layer convergence. This does NOT move authority.
    if workflow_dict is not None and isinstance(workflow_dict, dict):
        # Sanitize transitional bootstrap states for external exposure
        _sync_status = new_status
        if _sync_status not in _EXTERNAL_LIFECYCLE_STATES:
            _sync_status = "ACTIVE"
        workflow_dict["status"] = _sync_status

    return True


def _update_runtime_registry_only(workflow_id: str, new_status: str, reason: str = None) -> bool:
    """
    Update ONLY the authoritative runtime registry.
    
    Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
    - Runtime registry is sole lifecycle authority
    - This function does NOT mutate workflow object
    - This function does NOT update persistence
    - Used for authoritative lifecycle updates without side effects
    
    Returns:
        True if update succeeded, False if workflow_id not found in registry
    """
    with _workflow_state_lock:
        if workflow_id in _workflow_state_registry:
            # Preserve execution_generation and runtime_activity (coordination metadata)
            # Preserve ISSUE-062 FAILED actionability metadata
            _existing_entry = _workflow_state_registry[workflow_id]
            _existing_gen = _existing_entry.get("execution_generation", 1)
            _existing_activity = _existing_entry.get("runtime_activity", "IDLE")
            _failed_recoverable = _existing_entry.get("failed_recoverable")
            _retry_disabled_reason = _existing_entry.get("retry_disabled_reason")
            _actionability_reason = _existing_entry.get("actionability_reason")
            _terminalization_reason = _existing_entry.get("terminalization_reason")
            _workflow_state_registry[workflow_id] = {
                "status": new_status,
                "last_updated": time.time(),
                "reason": reason,
                "execution_generation": _existing_gen,
                "runtime_activity": _existing_activity,
                "failed_recoverable": _failed_recoverable,
                "retry_disabled_reason": _retry_disabled_reason,
                "actionability_reason": _actionability_reason,
                "terminalization_reason": _terminalization_reason,
            }
            return True
        # Initialize if not exists (for new workflows) - start generation at 1
        _workflow_state_registry[workflow_id] = {
            "status": new_status,
            "last_updated": time.time(),
            "reason": reason,
            "execution_generation": 1,
            "runtime_activity": "IDLE",
        }
        return True


def finalize_workflow_from_execution(workflow_id: str, steps: list) -> str:
    """
    Authoritative lifecycle reconciliation: derive workflow terminal state from step truth.

    Per PHASE VI AUTHORITY CONSOLIDATION:
    - ONLY this function may inspect step statuses and derive workflow lifecycle.
    - Execution runtime, retry, and escalation MUST call this instead of direct mutation.
    - Commits derived state directly to registry (no mirror mutation).

    Returns:
        The committed workflow status (COMPLETED, FAILED, BLOCKED).
    """
    # === RUNTIME ACTIVITY: RESOLVING ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # Terminal reconciliation is an observable orchestration phase.
    _set_runtime_activity(workflow_id, "RESOLVING")

    if not steps:
        _update_workflow_state(workflow_id, "FAILED", "no_steps")
        _init_failed_metadata_defaults(workflow_id, reason="no_steps")
        _set_runtime_activity(workflow_id, "IDLE")
        return "FAILED"

    if all(s.get("status") == "COMPLETED" for s in steps):
        _update_workflow_state(workflow_id, "COMPLETED", "all_steps_completed")
        _set_runtime_activity(workflow_id, "IDLE")
        return "COMPLETED"

    non_terminal = [s for s in steps if s.get("status") not in ("COMPLETED", "FAILED")]
    if not non_terminal:
        if any(s.get("status") == "FAILED" for s in steps):
            _update_workflow_state(workflow_id, "FAILED", "step_failure")
            _init_failed_metadata_defaults(workflow_id, reason="step_failure")
            _set_runtime_activity(workflow_id, "IDLE")
            return "FAILED"
        _update_workflow_state(workflow_id, "COMPLETED", "all_terminal_success")
        _set_runtime_activity(workflow_id, "IDLE")
        return "COMPLETED"

    if any(s.get("status") == "FAILED" for s in steps):
        _update_workflow_state(workflow_id, "FAILED", "step_failure")
        _init_failed_metadata_defaults(workflow_id, reason="step_failure")
        _set_runtime_activity(workflow_id, "IDLE")
        return "FAILED"

    # Still has non-terminal steps (BLOCKED, PENDING, ACTIVE)
    _auth = _get_workflow_state(workflow_id)
    _current = _auth.get("status") if _auth else "ACTIVE"
    return _current


def reconcile_workflow_lifecycle_from_steps(workflow_id: str, steps: list) -> str:
    """
    Recompute workflow lifecycle after retry/repair and commit authoritatively.

    Per PHASE VI AUTHORITY CONSOLIDATION:
    - retry_step MUST NOT derive workflow status locally.
    - This authority function computes the correct post-retry status.
    """
    _any_hard_failed = any(s.get("status") == "FAILED" for s in steps)
    if _any_hard_failed:
        _new_status = "FAILED"
    else:
        _new_status = "ACTIVE"
    _update_workflow_state(workflow_id, _new_status, "user_retry_reconcile")
    return _new_status


_EXTERNAL_LIFECYCLE_STATES = frozenset([
    "ACTIVE", "PAUSED", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED", "PENDING", "QUEUED"
])


def inject_authoritative_lifecycle_into_workflow(workflow: dict) -> dict:
    """
    Read authoritative registry status and inject it into the workflow dict.
    Per PHASE VII: workflow['status'] is a SERIALIZATION MIRROR ONLY.
    Transitional bootstrap states (ACTIVATING, PENDING_RECOVERY) are
    sanitized to ACTIVE before external exposure.

    Per ISSUE-062: Also inject FAILED actionability metadata from registry
    so historical inspection surfaces backend-authored truth.
    """
    workflow_id = workflow.get("id")
    if not workflow_id:
        return workflow
    _auth = _get_workflow_state(workflow_id)
    if _auth:
        _raw_status = _auth.get("status", workflow.get("status", "ACTIVE"))
        # Sanitize transitional bootstrap states — they are internal-only
        if _raw_status not in _EXTERNAL_LIFECYCLE_STATES:
            _raw_status = "ACTIVE"
        workflow["status"] = _raw_status
        # Inject ISSUE-062 metadata if present in registry
        for _meta_key in ("failed_recoverable", "retry_disabled_reason",
                            "actionability_reason", "terminalization_reason"):
            if _meta_key in _auth and _auth[_meta_key] is not None:
                workflow[_meta_key] = _auth[_meta_key]
    return workflow


def validate_workflow_recovery(wf: dict) -> dict:
    """
    Validate a persisted workflow object for resurrection eligibility.

    Per Phase 3F-XE (Recovery Quarantine):
    - Called BEFORE any startup resurrection attempt.
    - A workflow that fails validation is QUARANTINED, not resurrected.
    - QUARANTINED workflows are persisted with quarantine_reason and excluded from
      all active hydration APIs and frontend recovery selection.
    - This function MUST NOT mutate the workflow.

    Recoverable disk states (eligible for resurrection):
        ACTIVE        — crashed mid-execution (normal recovery path)
        PAUSED        — explicitly paused; execution thread dead but state valid
        BLOCKED       — waiting on dependency/approval; may be resumable
        PENDING_RECOVERY — already normalised on a prior restart

    Non-recoverable (skip, not quarantine):
        COMPLETED — terminal; no resurrection needed
        FAILED    — terminal; resurrection would be invalid_transition:FAILED→ACTIVE
        QUEUED    — planning shell; steps not yet generated, not eligible for resurrection

    Quarantine triggers (structural corruption):
        - No steps list or empty steps list
        - Step missing required id field
        - Duplicate step IDs
        - depends_on references a step_id that does not exist in the workflow
        - Cyclic dependency detected
        - Step has status ACTIVE (only valid inside a live execution thread — on disk
          it means the process died; ACTIVE on disk is normalised to PENDING_RECOVERY
          by warm_registry_from_disk, so by the time validate_workflow_recovery runs
          ACTIVE should already be gone; if it is still present the normalization
          was bypassed and the workflow is suspect)
        - recovery_failure_count >= QUARANTINE_AFTER_FAILURES (repeated resurrection
          failures on previous starts)

    Returns:
        {
            "eligible":  bool,
            "skip":      bool,   # True if terminal/non-resurrectable but not corrupt
            "quarantine": bool,  # True if corrupt / structurally invalid
            "reason":    str,
        }
    """
    QUARANTINE_AFTER_FAILURES = 3

    wf_id = wf.get("id", "<no-id>")
    steps = wf.get("steps")
    disk_status = wf.get("status", "ACTIVE")

    # ── 1. Non-recoverable terminal states ──────────────────────────────────
    if disk_status in ("COMPLETED", "FAILED", "CANCELLED"):
        return {"eligible": False, "skip": True, "quarantine": False,
                "reason": f"terminal_state:{disk_status}"}

    # ── 2. Already quarantined on a previous boot ────────────────────────────
    if disk_status == "QUARANTINED":
        return {"eligible": False, "skip": False, "quarantine": True,
                "reason": wf.get("quarantine_reason", "previously_quarantined")}

    # ── 3. Repeated resurrection failure threshold ───────────────────────────
    failure_count = wf.get("recovery_failure_count", 0)
    if failure_count >= QUARANTINE_AFTER_FAILURES:
        return {"eligible": False, "skip": False, "quarantine": True,
                "reason": f"recovery_failure_threshold:{failure_count}"}

    # ── 4. Steps list must exist and be non-empty ────────────────────────────
    # Exception: QUEUED planning shells are intentionally created with empty
    # steps during pre-registration (ISSUE-055). Incomplete persistence is
    # legal per PERSISTENCE_AND_DURABILITY_CONTRACT_V1. Do NOT quarantine.
    if disk_status == "QUEUED":
        if not isinstance(steps, list) or len(steps) == 0:
            return {"eligible": False, "skip": True, "quarantine": False,
                    "reason": "queued_planning_shell"}
    if not isinstance(steps, list) or len(steps) == 0:
        return {"eligible": False, "skip": False, "quarantine": True,
                "reason": "no_steps_or_empty_steps"}

    # ── 5. Each step must have a non-empty id ───────────────────────────────
    step_ids = []
    for i, step in enumerate(steps):
        sid = step.get("id")
        if not sid or not isinstance(sid, str) or not sid.strip():
            return {"eligible": False, "skip": False, "quarantine": True,
                    "reason": f"step_missing_id:index_{i}"}
        step_ids.append(sid)

    # ── 6. Duplicate step IDs ────────────────────────────────────────────────
    step_id_set = set(step_ids)
    if len(step_ids) != len(step_id_set):
        seen = set()
        dup = next(s for s in step_ids if s in seen or seen.add(s))
        return {"eligible": False, "skip": False, "quarantine": True,
                "reason": f"duplicate_step_id:{dup}"}

    # ── 7. depends_on references must resolve to known step IDs ─────────────
    for step in steps:
        dep_list = step.get("depends_on", [])
        if not isinstance(dep_list, list):
            return {"eligible": False, "skip": False, "quarantine": True,
                    "reason": f"invalid_depends_on_type:step_{step.get('id')}"}
        for dep_id in dep_list:
            if dep_id not in step_id_set:
                return {"eligible": False, "skip": False, "quarantine": True,
                        "reason": f"dangling_dependency:{step.get('id')}→{dep_id}"}

    # ── 8. Acyclicity check (DFS) ────────────────────────────────────────────
    adjacency: dict = {step.get("id"): step.get("depends_on", []) for step in steps}

    def _has_cycle(node: str, visited: set, in_stack: set) -> bool:
        visited.add(node)
        in_stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                if _has_cycle(neighbor, visited, in_stack):
                    return True
            elif neighbor in in_stack:
                return True
        in_stack.discard(node)
        return False

    _visited: set = set()
    for sid in step_id_set:
        if sid not in _visited:
            if _has_cycle(sid, _visited, set()):
                return {"eligible": False, "skip": False, "quarantine": True,
                        "reason": f"cyclic_dependency_detected:involves_{sid}"}

    # ── 9. ACTIVE step statuses on disk are suspicious ──────────────────────
    # warm_registry_from_disk normalises workflow status ACTIVE→PENDING_RECOVERY
    # but does NOT touch step-level statuses. An ACTIVE step on a persisted file
    # that survived warm_registry without being in a live thread indicates the
    # normalize path was bypassed. Flag but do not quarantine — the PERSISTENCE
    # RESTORE block handles ACTIVE→FAILED at step level, so this is recoverable.
    # (This is informational only — not a quarantine trigger.)

    # ── All checks passed ────────────────────────────────────────────────────
    return {"eligible": True, "skip": False, "quarantine": False, "reason": "ok"}


def quarantine_workflow(wf: dict, reason: str) -> bool:
    """
    Mark a workflow as QUARANTINED and persist the quarantine record.

    Per Phase 3F-XE:
    - Writes status=QUARANTINED and quarantine_reason to the persisted file.
    - Also updates the in-memory registry so all code reading authoritative state
      sees QUARANTINED immediately.
    - Does NOT delete the file — quarantined workflows remain inspectable.
    - Returns True if persisted successfully.
    """
    wf_id = wf.get("id")
    if not wf_id:
        return False

    wf["status"] = "QUARANTINED"
    wf["quarantine_reason"] = reason
    wf.pop("recovery_failure_count", None)  # no longer relevant once quarantined

    # Update authoritative registry
    with _workflow_state_lock:
        _workflow_state_registry[wf_id] = {
            "status": "QUARANTINED",
            "last_updated": time.time(),
            "reason": reason,
        }

    # Persist the quarantine mark — use a direct JSON write since save_workflow
    # only persists ACTIVE/BLOCKED/PAUSED/COMPLETED.
    try:
        import os as _os
        import json as _json
        import tempfile as _tempfile
        from system.orchestrator.persistence import _active_workflow_path, _ensure_active_dir
        _ensure_active_dir()
        _path = _active_workflow_path(wf_id)
        _dir = _os.path.dirname(_path)
        _fd, _tmp = _tempfile.mkstemp(dir=_dir, suffix=".tmp")
        try:
            with _os.fdopen(_fd, "w", encoding="utf-8") as _f:
                _json.dump(wf, _f, ensure_ascii=False, indent=2)
            _os.replace(_tmp, _path)
            return True
        except Exception:
            try:
                _os.remove(_tmp)
            except OSError:
                pass
            return False
    except Exception:
        return False


def increment_recovery_failure(wf: dict) -> int:
    """
    Increment recovery_failure_count on a persisted workflow.

    Per Phase 3F-XE: workflows that repeatedly fail resurrection are quarantined
    after QUARANTINE_AFTER_FAILURES attempts. Called when _maybe_resurrect_execution
    returns None (no persistence found) or throws during startup resurrection.

    Returns the new failure count.
    """
    count = wf.get("recovery_failure_count", 0) + 1
    wf["recovery_failure_count"] = count
    # Persist the updated count so next restart sees it
    try:
        import os as _os
        import json as _json
        import tempfile as _tempfile
        from system.orchestrator.persistence import _active_workflow_path, _ensure_active_dir
        _ensure_active_dir()
        _path = _active_workflow_path(wf.get("id", "unknown"))
        _dir = _os.path.dirname(_path)
        _fd, _tmp = _tempfile.mkstemp(dir=_dir, suffix=".tmp")
        try:
            with _os.fdopen(_fd, "w", encoding="utf-8") as _f:
                _json.dump(wf, _f, ensure_ascii=False, indent=2)
            _os.replace(_tmp, _path)
        except Exception:
            try:
                _os.remove(_tmp)
            except OSError:
                pass
    except Exception:
        pass
    return count


# ============================================================================
# PHASE 1 REMEDIATION — CENTRAL INVARIANT VALIDATION
# ============================================================================

def validate_runtime_activation(workflow_id: str) -> Dict[str, Any]:
    """
    Central invariant gate: persistence-backed integrity check.

    Per PHASE 1A ACTIVATION LIFECYCLE REPAIR:
    This function checks ONLY persistence-backed integrity.
    It does NOT require runtime infrastructure to exist yet —
    runtime infrastructure is created DURING the ACTIVATING phase.

    Checks:
    - workflow_id is valid (not placeholder)
    - persistence file exists
    - workflow is structurally valid
    - no placeholder workflow_id

    Does NOT check:
    - bg_id existence        (created during ACTIVATING)
    - stream registry entry  (created during ACTIVATING)
    - projection store       (created during ACTIVATING)
    - running thread         (created at ACTIVE transition)
    - projection data        (post-ACTIVE concern)

    Returns:
        {"valid": True, "workflow": dict}  if persistence check passes
        {"valid": False, "reason": str}    if any check fails
    """
    # ASSERT: workflow_id valid and not placeholder
    if not workflow_id or not isinstance(workflow_id, str):
        return {"valid": False, "reason": "invalid_workflow_id:missing_or_null"}

    if workflow_id in ("pending", "None", "null", ""):
        return {"valid": False, "reason": f"invalid_workflow_id:placeholder_{workflow_id}"}

    # ASSERT: persistence file exists on disk
    try:
        from system.orchestrator.persistence import _active_workflow_path
        workflow_path = _active_workflow_path(workflow_id)
        if not os.path.exists(workflow_path):
            return {"valid": False, "reason": "persistence_not_found"}
    except Exception as e:
        return {"valid": False, "reason": f"persistence_check_failed:{str(e)}"}

    # ASSERT: workflow loads and is structurally valid
    try:
        workflows = load_active_workflows()
        workflow = None
        for wf in workflows:
            if wf.get("id") == workflow_id:
                workflow = wf
                break

        if workflow is None:
            return {"valid": False, "reason": "workflow_not_in_persistence"}

        if workflow.get("id") != workflow_id:
            return {"valid": False, "reason": "workflow_id_mismatch"}

        # Validate structure
        validation = validate_workflow(workflow)
        if validation.get("status") == "failure":
            return {"valid": False, "reason": f"workflow_invalid:{validation.get('reason')}"}

        print(f"[INVARIANT:PASS] validate_runtime_activation for {workflow_id}")
        return {"valid": True, "workflow": workflow}

    except Exception as e:
        return {"valid": False, "reason": f"validation_exception:{str(e)}"}


def warm_registry_from_disk() -> dict:
    """
    Proactively populate _workflow_state_registry from disk on startup.

    Per Phase 3F-XA (Registry Warm Restoration):
    - Replaces lazy-fallback-only restoration with deterministic eager population.
    - Normalizes ACTIVE disk state to PENDING_RECOVERY — an ACTIVE workflow on disk
      means the process died mid-execution; there is no execution thread, so marking
      it ACTIVE in the registry would create a zombie-ACTIVE state that accepts
      pause/resume commands without a live executor.
    - PAUSED, BLOCKED, FAILED are restored as-is (PAUSED/BLOCKED are valid without
      an execution thread; FAILED is terminal and informational only).

    Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
    - Disk persistence is a COMPATIBILITY MIRROR, not authoritative truth.
    - This function uses disk state as a starting point ONLY.
    - The registry remains sole lifecycle authority once populated.
    - PENDING_RECOVERY is a transient registry-only state — it signals that the
      workflow needs run_workflow() to re-enter a legal execution path.
    - This function MUST NOT influence governance, scheduler, or execution logic.

    Returns:
        dict with keys:
            restored (int): number of workflows populated into registry
            normalized_active (int): ACTIVE→PENDING_RECOVERY normalizations performed
            skipped (int): entries skipped (registry already had an entry)
    """
    from system.orchestrator.persistence import load_active_workflows

    restored = 0
    normalized_active = 0
    skipped = 0

    try:
        disk_workflows = load_active_workflows()
    except Exception:
        return {"restored": 0, "normalized_active": 0, "skipped": 0}

    with _workflow_state_lock:
        for wf in disk_workflows:
            wf_id = wf.get("id")
            if not wf_id:
                continue

            # Never overwrite an already-authoritative registry entry.
            # If an entry exists (e.g. resume_workflow wrote ACTIVE), preserve it.
            if wf_id in _workflow_state_registry:
                skipped += 1
                continue

            disk_status = wf.get("status", "ACTIVE")

            # Normalize ACTIVE (crashed/interrupted) → PENDING_RECOVERY.
            # An ACTIVE disk status means the process died while this workflow was
            # running — there is no execution thread. Restore as PENDING_RECOVERY
            # so it cannot be paused/resumed as if live, but can be re-launched.
            if disk_status in ("ACTIVE", "ACTIVATING"):
                registry_status = "PENDING_RECOVERY"
                normalized_active += 1
            else:
                registry_status = disk_status

            _workflow_state_registry[wf_id] = {
                "status": registry_status,
                "last_updated": time.time(),
                "reason": "warm_restore_from_disk",
                "execution_generation": 1,  # Default to 1 on restart (volatile coordination)
            }
            restored += 1

    return {
        "restored": restored,
        "normalized_active": normalized_active,
        "skipped": skipped,
    }


def _is_valid_state_transition(current: str, new: str) -> bool:
    """Check if state transition is valid per STATE_TRANSITIONS_CONTRACT_V1.

    Lifecycle path:
    QUEUED → ACTIVATING → ACTIVE (new execution bootstrap)
    PENDING_RECOVERY → ACTIVATING → ACTIVE (startup resurrection)
    ACTIVATING → FAILED (bootstrap failure)
    ACTIVE → PAUSED | BLOCKED | COMPLETED | FAILED | CANCELLED | PENDING (execution)
    """
    valid_transitions = {
        "QUEUED":           ["ACTIVATING"],
        "PENDING":          ["ACTIVE", "ACTIVATING", "BLOCKED"],
        "PENDING_RECOVERY": ["ACTIVATING", "ACTIVE", "FAILED"],
        "ACTIVATING":       ["ACTIVE", "FAILED"],
        "ACTIVE":           ["PAUSED", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED", "PENDING"],
        "PAUSED":           ["ACTIVE", "FAILED", "CANCELLED"],
        "BLOCKED":          ["ACTIVE", "FAILED", "CANCELLED"],
        "COMPLETED":        [],
        "FAILED":           [],
        # NOTE: RETRY is NOT a valid lifecycle state per STATE_TRANSITIONS_CONTRACT_V1.
        # Retry is execution regeneration within ACTIVE lifecycle continuity.
        # Step status during retry is PENDING (awaiting scheduler dispatch).
        "QUARANTINED":      [],
    }
    return new in valid_transitions.get(current, [])


def _invalidate_dependents(workflow: dict, changed_step_id: str, visited: set = None) -> List[str]:
    """
    Invalidate all dependent steps after a plan edit.
    Per DEPENDENCY_MODEL_CONTRACT_V1 Section 10:
    - Dependent steps MUST be re-evaluated when dependency changes
    - NO stale execution: clear execution_result and output

    Args:
        workflow: The workflow dict
        changed_step_id: The step ID that was modified
        visited: Set of already visited step IDs (for recursion tracking)

    Returns:
        List of step IDs that were invalidated
    """
    if visited is None:
        visited = set()

    if changed_step_id in visited:
        return []
    visited.add(changed_step_id)

    invalidated = []
    steps = workflow.get("steps", [])

    # Find all steps that depend on changed_step_id
    for step in steps:
        step_id = step.get("id")
        if step_id in visited:
            continue

        depends_on = step.get("depends_on", [])
        if changed_step_id in depends_on:
            # This step depends on the changed step
            # Reset to PENDING (will be re-evaluated by scheduler)
            # Preserve FAILED terminality - do not reset FAILED steps
            # Reset RETRY steps to PENDING for re-evaluation
            if step.get("status") not in ("COMPLETED", "FAILED"):
                request_step_transition(step, "PENDING", "dependency_invalidation", _internal=True)
                step.pop("execution_result", None)
                step.pop("output", None)
                # === FIX B: clear stale blocked_reason on invalidated downstream steps ===
                # Per DEPENDENCY_MODEL_CONTRACT_V1: blocked_reason is only valid on BLOCKED
                # steps.  After invalidation the step is PENDING — the reason referencing
                # the now-retried dependency is stale and must not survive.
                step.pop("blocked_reason", None)
                invalidated.append(step_id)

                # Recursively invalidate dependents of this step
                invalidated.extend(_invalidate_dependents(workflow, step_id, visited))

    return invalidated


# ============================================================================
# SUB-PHASE 3B — PAUSE/RESUME
# ============================================================================

def pause_workflow(workflow_id: str) -> Dict[str, Any]:
    """
    Pause a workflow using state transition.
    Per STATE_TRANSITIONS_CONTRACT_V1: ACTIVE → PAUSED

    Args:
        workflow_id: The workflow to pause

    Returns:
        {"status": "success", "previous_state": str, "new_state": "PAUSED"}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    current_state = _get_workflow_state(workflow_id)
    if current_state is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    current = current_state.get("status", "QUEUED")

    # Per STATE_TRANSITIONS_CONTRACT_V1: Only ACTIVE can → PAUSED
    if current != "ACTIVE":
        return {
            "status": "failure",
            "reason": f"invalid_transition:{current}_to_PAUSED"
        }

    if not _is_valid_state_transition(current, "PAUSED"):
        return {"status": "failure", "reason": f"invalid_state_transition:{current}→PAUSED"}

    # === RUNTIME ACTIVITY: PAUSING (pre-commit observability) ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # Signal pause coordination is in progress before lifecycle commit.
    _set_runtime_activity(workflow_id, "PAUSING")

    # Perform transition
    if not _update_workflow_state(workflow_id, "PAUSED", "user_pause"):
        _set_runtime_activity(workflow_id, "EXECUTING")  # rollback on failure
        return {"status": "failure", "reason": "update_failed"}

    # === RUNTIME ACTIVITY: PAUSED (post-commit) ===
    _set_runtime_activity(workflow_id, "PAUSED")

    # Emit event per TRACE_LOGGING_CONTRACT_V1
    try:
        event_emitter.emit_state_transition(
            workflow_id=workflow_id,
            step_id=None,
            previous_state=current,
            new_state="PAUSED",
            reason="user_pause"
        )
        event_emitter.emit_event(
            event_type="PROJECT_PAUSED",
            workflow_id=workflow_id,
            data={"timestamp": time.time(), "reason": "user_pause"}
        )
    except Exception:
        pass  # Event emission failure must not affect execution

    return {
        "status": "success",
        "previous_state": current,
        "new_state": "PAUSED",
        "workflow_id": workflow_id
    }


def resume_workflow(workflow_id: str) -> Dict[str, Any]:
    """
    Resume a workflow using state transition.
    Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED/BLOCKED/PENDING_RECOVERY → ACTIVE

    Per PHASE 1 REMEDIATION:
    - PERSISTENCE BEFORE ACTIVE
    - Hard guard: persistence must exist before ACTIVE transition
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    # === HARD GUARD: Persistence file must exist before ACTIVE transition ===
    if not workflow_persistence_exists(workflow_id):
        print(f"[INVARIANT:FAIL] resume_workflow rejected {workflow_id}: no persistence file")
        return {"status": "failure", "reason": "invariant_failed:persistence_not_found"}

    current_state = _get_workflow_state(workflow_id)
    if current_state is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    current = current_state.get("status", "QUEUED")

    # Per STATE_TRANSITIONS_CONTRACT_V1 §81-84:
    # PAUSED → ACTIVE (resume) and BLOCKED → ACTIVE (user resolves / approval granted)
    # are BOTH valid resume transitions.
    if current not in ("PAUSED", "BLOCKED", "PENDING_RECOVERY"):
        return {
            "status": "failure",
            "reason": f"invalid_transition:{current}_to_ACTIVE"
        }

    # Per LIFECYCLE_AUTHORITY_CONTRACT_V1 §8: validate through FSM before commit
    if not _is_valid_state_transition(current, "ACTIVE"):
        return {"status": "failure", "reason": f"invalid_state_transition:{current}→ACTIVE"}

    # === RESUMABLE BLOCKED GUARD ===
    # Not all BLOCKED states are user-resumable.
    # Terminal escalation blocks must not be auto-resumed via /resume endpoint.
    # blocked_reason is an implementation-level hint; contract does not enumerate sub-types.
    # If blocked_reason is absent, allow resume (dependency_wait has no explicit reason set).
    if current == "BLOCKED":
        _TERMINAL_BLOCK_REASONS = {
            "max_steps_exceeded",
            "max_iterations_exceeded",
            "invalidated",
            "escalated",
        }
        block_reason = current_state.get("reason", "")
        if block_reason in _TERMINAL_BLOCK_REASONS:
            return {
                "status": "failure",
                "reason": f"blocked_state_not_resumable:{block_reason}"
            }

    # === RUNTIME ACTIVITY: RESUMING (pre-commit observability) ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # Signal resume coordination is in progress before lifecycle commit.
    _set_runtime_activity(workflow_id, "RESUMING")

    # Perform transition
    if not _update_workflow_state(workflow_id, "ACTIVE", "user_resume"):
        _set_runtime_activity(workflow_id, "PAUSED")  # rollback on failure
        return {"status": "failure", "reason": "update_failed"}

    # === RUNTIME ACTIVITY: EXECUTING (post-resume commit) ===
    _set_runtime_activity(workflow_id, "EXECUTING")

    # Emit event per TRACE_LOGGING_CONTRACT_V1
    try:
        event_emitter.emit_state_transition(
            workflow_id=workflow_id,
            step_id=None,
            previous_state=current,
            new_state="ACTIVE",
            reason="user_resume"
        )
        event_emitter.emit_event(
            event_type="PROJECT_RESUMED",
            workflow_id=workflow_id,
            data={"timestamp": time.time(), "reason": "user_resume"}
        )
    except Exception:
        pass

    return {
        "status": "success",
        "previous_state": current,
        "new_state": "ACTIVE",
        "workflow_id": workflow_id
    }


# ============================================================================
# SUB-PHASE 3C — PLAN CONTROL
# ============================================================================

def get_plan(workflow_id: str) -> Dict[str, Any]:
    """
    Get the execution plan for a workflow.

    Args:
        workflow_id: The workflow ID

    Returns:
        {"status": "success", "steps": [...], "workflow_status": str}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    workflows = load_active_workflows()
    for wf in workflows:
        if wf.get("id") == workflow_id:
            return {
                "status": "success",
                "workflow_id": workflow_id,
                "workflow_status": wf.get("status", "QUEUED"),
                "steps": wf.get("steps", [])
            }

    return {"status": "failure", "reason": "workflow_not_found"}


def edit_step(workflow_id: str, step_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Edit a step in the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1:
    - COMPLETED steps = locked (reject)
    - ACTIVE steps = editable with restart
    - FUTURE steps = fully editable
    - Validate dependencies after edit

    Args:
        workflow_id: The workflow ID
        step_id: The step ID to edit
        updates: Dictionary of fields to update

    Returns:
        {"status": "success", "step": updated_step}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}
    if not step_id:
        return {"status": "failure", "reason": "missing_step_id"}

    # Load workflow
    workflows = load_active_workflows()
    workflow = None
    for wf in workflows:
        if wf.get("id") == workflow_id:
            workflow = wf
            break

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    # Find step
    step = None
    for s in workflow.get("steps", []):
        if s.get("id") == step_id:
            step = s
            break

    if step is None:
        return {"status": "failure", "reason": "step_not_found"}

    # Check step state per PLAN_CONTROL_CONTRACT_V1
    step_status = step.get("status", "PENDING")

    if step_status == "COMPLETED":
        return {"status": "failure", "reason": "step_completed_locked"}

    # Apply updates
    allowed_fields = [
        "purpose", "tool_call", "expected_outcome", "risk",
        "importance", "resource_targets", "depends_on"
    ]

    for field, value in updates.items():
        if field in allowed_fields:
            step[field] = value

    # === CANONICAL EXECUTION INTENT SYNCHRONIZATION ===
    # step["purpose"] is the user-editable intent (projection/UI).
    # step["input"] is the runtime execution base (escalation/retry).
    # These MUST be identical after mutation or retry/escalation logic
    # will snapshot and inject stale input from the pre-edit era.
    if "purpose" in updates:
        step["input"] = updates["purpose"]
        # === SEMANTIC EXPECTATION REGENERATION ===
        # Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §11:
        # Semantic expectations MUST be regenerated when planner signals change.
        # Deterministic, advisory-only, no LLM.
        from system.orchestrator.semantic_expectation import derive_semantic_expectation
        step["semantic_expectation"] = derive_semantic_expectation(
            agent=step.get("agent"),
            purpose=updates["purpose"],
        )

    # === DERIVED EXECUTION ARTIFACT INVALIDATION ===
    # tool_call is COMPILED EXECUTION STATE derived from purpose/input.
    # When semantic execution intent changes, tool_call MUST be invalidated
    # to force regeneration from updated canonical state.
    # Without this, stale compiled artifacts survive mutation → execution divergence.
    semantic_fields_changed = any(field in updates for field in ["purpose", "input", "tool_call"])
    if semantic_fields_changed:
        old_tool_call = step.pop("tool_call", None)
        if old_tool_call:
            print(f"[MUTATION_INVALIDATION] tool_call cleared for step {step_id}: was '{old_tool_call}'")

    # If ACTIVE step edited, mark for restart per PLAN_CONTROL_CONTRACT_V1
    restart_required = False
    if step_status == "ACTIVE":
        request_step_transition(step, "PENDING", "plan_edit_restart", _internal=True)
        step["retries"] = 0
        step.pop("execution_result", None)
        step.pop("output", None)
        restart_required = True

    step.pop("_original_input", None)
    step.pop("_extracted_constraints", None)
    step.pop("_validator_signals", None)
    step.pop("_validator_advisory", None)
    step.pop("_validator_decision", None)
    step.pop("_drift_signal", None)
    step.pop("_signal_analysis", None)

    # Validate dependency graph after edit
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        # Reject edit if validation fails
        return {"status": "failure", "reason": f"validation_failed:{validation.get('reason')}"}

    # === DEPENDENCY RE-EVALUATION (Phase 4A.1) ===
    # Per DEPENDENCY_MODEL_CONTRACT_V1 Section 10:
    # Invalidate all dependent steps when a step is edited
    invalidated_steps = _invalidate_dependents(workflow, step_id)

    # Save updated workflow
    save_workflow(workflow)

    return {
        "status": "success",
        "step": step,
        "restart_required": restart_required,
        "invalidated_steps": invalidated_steps,
        "workflow_id": workflow_id
    }


def add_step(workflow_id: str, step_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add a new step to the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1: Validates and appends step.

    Args:
        workflow_id: The workflow ID
        step_data: The step definition (must include id, purpose, etc.)

    Returns:
        {"status": "success", "step": new_step}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    # Load workflow
    workflows = load_active_workflows()
    workflow = None
    for wf in workflows:
        if wf.get("id") == workflow_id:
            workflow = wf
            break

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    # Check workflow state - can only add to ACTIVE or PAUSED
    wf_status = workflow.get("status", "QUEUED")
    if wf_status not in ["ACTIVE", "PAUSED", "QUEUED", "BLOCKED"]:
        return {"status": "failure", "reason": f"cannot_add_to_{wf_status}_workflow"}

    # Ensure required fields
    if "id" not in step_data:
        return {"status": "failure", "reason": "missing_step_id"}

    # Set defaults for contract-required fields
    new_step = dict(step_data)
    new_step["type"] = new_step.get("type", "EXECUTE_API")
    new_step["purpose"] = new_step.get("purpose", "New step")
    new_step["tool_call"] = new_step.get("tool_call", "")
    new_step["expected_outcome"] = new_step.get("expected_outcome", "Execution completed")
    new_step["risk"] = new_step.get("risk", "LOW")
    new_step["importance"] = new_step.get("importance", "MEDIUM")
    new_step["resource_targets"] = new_step.get("resource_targets", [])
    # Initialize lifecycle through authority API (validate=False: no prior state)
    request_step_transition(new_step, "PENDING", "step_initialization", validate=False)
    new_step["retries"] = 0
    new_step["max_retries"] = new_step.get("max_retries", 3)
    # === SEMANTIC EXPECTATION DERIVATION ===
    # Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §5:
    # Planner-derived semantic expectations are deterministic advisory metadata.
    from system.orchestrator.semantic_expectation import derive_semantic_expectation
    new_step["semantic_expectation"] = derive_semantic_expectation(
        agent=new_step.get("agent"),
        purpose=new_step.get("purpose"),
    )

    # Add to workflow
    if "steps" not in workflow:
        workflow["steps"] = []
    workflow["steps"].append(new_step)

    # Validate dependency graph
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        # Remove the step we just added
        workflow["steps"].pop()
        return {"status": "failure", "reason": f"validation_failed:{validation.get('reason')}"}

    # Save updated workflow
    save_workflow(workflow)

    return {
        "status": "success",
        "step": new_step,
        "workflow_id": workflow_id
    }


def remove_step(workflow_id: str, step_id: str) -> Dict[str, Any]:
    """
    Remove a step from the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1:
    - Reject if step is COMPLETED
    - Reject if step has dependents (other steps depend on it)

    Args:
        workflow_id: The workflow ID
        step_id: The step ID to remove

    Returns:
        {"status": "success", "removed_step_id": str}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}
    if not step_id:
        return {"status": "failure", "reason": "missing_step_id"}

    # Load workflow
    workflows = load_active_workflows()
    workflow = None
    for wf in workflows:
        if wf.get("id") == workflow_id:
            workflow = wf
            break

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    # Find step
    steps = workflow.get("steps", [])
    step_index = None
    step = None
    for i, s in enumerate(steps):
        if s.get("id") == step_id:
            step_index = i
            step = s
            break

    if step is None:
        return {"status": "failure", "reason": "step_not_found"}

    # Check step state - COMPLETED steps are locked
    if step.get("status") == "COMPLETED":
        return {"status": "failure", "reason": "completed_step_locked"}

    # Check for dependents
    for s in steps:
        depends_on = s.get("depends_on", [])
        if step_id in depends_on:
            return {
                "status": "failure",
                "reason": "step_has_dependents",
                "dependent_step_id": s.get("id")
            }

    # Remove step
    steps.pop(step_index)

    # Validate workflow still valid
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        # Re-add the step (this shouldn't happen, but safety first)
        steps.insert(step_index, step)
        return {"status": "failure", "reason": f"validation_failed:{validation.get('reason')}"}

    # Save updated workflow
    save_workflow(workflow)

    return {
        "status": "success",
        "removed_step_id": step_id,
        "workflow_id": workflow_id
    }


def reorder_steps(workflow_id: str, new_order: List[str]) -> Dict[str, Any]:
    """
    Reorder steps in the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1: Validates dependency constraints.

    Args:
        workflow_id: The workflow ID
        new_order: List of step IDs in new order

    Returns:
        {"status": "success", "new_order": [...]}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}
    if not new_order:
        return {"status": "failure", "reason": "empty_new_order"}

    # Load workflow
    workflows = load_active_workflows()
    workflow = None
    for wf in workflows:
        if wf.get("id") == workflow_id:
            workflow = wf
            break

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    steps = workflow.get("steps", [])
    current_ids = {s.get("id") for s in steps}

    # Validate new_order contains all current steps
    new_ids = set(new_order)
    if new_ids != current_ids:
        return {"status": "failure", "reason": "order_must_include_all_steps"}

    # Create new step list in specified order
    step_map = {s.get("id"): s for s in steps}
    new_steps = [step_map[sid] for sid in new_order if sid in step_map]

    # Temporarily update workflow
    original_steps = steps.copy()
    workflow["steps"] = new_steps

    # Validate dependency constraints
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        # Restore original order
        workflow["steps"] = original_steps
        return {"status": "failure", "reason": f"dependency_violation:{validation.get('reason')}"}

    # Save updated workflow
    save_workflow(workflow)

    return {
        "status": "success",
        "new_order": new_order,
        "workflow_id": workflow_id
    }


# ============================================================================
# SUB-PHASE 3D — CONTROL ACTIONS
# ============================================================================

def retry_step(workflow_id: str, step_id: str, _force_retry: bool = False) -> Dict[str, Any]:
    """
    Retry a failed or blocked step.
    Per HAND_ARCHITECTURE_V2: User has absolute authority to retry FAILED steps.
    Per stabilization plan: Use RETRY state for explicit lifecycle tracking.
    Per ISSUE-098A: Separate bounded force retry budget for exhausted normal retries.

    Args:
        workflow_id: The workflow ID
        step_id: The step ID to retry
        _force_retry: If True, bypass normal retry exhaustion check and enforce
                      separate force retry budget (limit = 1 per step).

    Returns:
        {"status": "success", "step": updated_step}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}
    if not step_id:
        return {"status": "failure", "reason": "missing_step_id"}

    # Load workflow
    workflows = load_active_workflows()
    workflow = None
    for wf in workflows:
        if wf.get("id") == workflow_id:
            workflow = wf
            break

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    # Find step first so we can do step-specific validation
    step = None
    for s in workflow.get("steps", []):
        if s.get("id") == step_id:
            step = s
            break

    if step is None:
        return {"status": "failure", "reason": "step_not_found"}

    # Check current status
    current_status = step.get("status", "PENDING")
    if current_status not in ["FAILED", "BLOCKED"]:
        return {"status": "failure", "reason": f"cannot_retry_{current_status}_step"}

    # === ISSUE-062 + ISSUE-098A: RETRY ELIGIBILITY GUARD ===
    # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: backend authors retry legality.
    # Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1: retry creates new execution instance.
    # Frontend hiding the button is NOT sufficient — backend must enforce.
    _steps = workflow.get("steps", [])
    _meta = _get_failed_metadata(workflow_id)
    if not _meta.get("failed_recoverable", True):
        _reason = _meta.get("retry_disabled_reason") or "retry_not_eligible"
        print(f"[ISSUE-062] retry_step REJECTED: workflow_id={workflow_id} retry_eligible=False reason={_reason}")
        return {
            "status": "failure",
            "reason": _reason,
            "retry_eligible": False,
            "failed_recoverable": _meta.get("failed_recoverable", False),
        }

    if not _force_retry:
        # Normal retry boundedness check
        _retries = step.get("retries", 0)
        _max_retries = step.get("max_retries", 3)
        if _retries >= _max_retries:
            print(f"[ISSUE-098A] retry_step REJECTED: workflow_id={workflow_id} step_id={step_id} normal_retries_exhausted")
            return {
                "status": "failure",
                "reason": "normal_retries_exhausted",
                "retry_eligible": False,
            }
    else:
        # Force retry budget check (limit = 1 per step)
        _force_count = step.get("_force_retry_count", 0)
        if _force_count >= 1:
            print(f"[ISSUE-098A] retry_step REJECTED: workflow_id={workflow_id} step_id={step_id} force_retry_exhausted")
            return {
                "status": "failure",
                "reason": "force_retry_exhausted",
            }

    # Per STATE_TRANSITIONS_CONTRACT_V1 §RETRY BEHAVIOR: RETRY does NOT change step state.
    # Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1 §9: retry is a new execution attempt
    # within the existing ACTIVE lifecycle window — NOT a separate lifecycle state.
    # Step is set to PENDING so the scheduler can dispatch it cleanly.
    # _retry_generation is a non-authoritative execution coordination counter only;
    # it is NOT a lifecycle state and MUST NOT be used for lifecycle decisions.
    _transition_reason = "force_retry" if _force_retry else "user_retry"
    _transition_ok = request_step_transition(step, "PENDING", _transition_reason, _internal=True)
    if not _transition_ok:
        print(f"[LIFECYCLE_AUTHORITY] retry_step ABORTED: transition rejected for step {step_id}")
        return {
            "status": "failure",
            "reason": "lifecycle_transition_rejected",
            "step_id": step_id,
            "current_status": step.get("status")
        }
    step["_retry_generation"] = step.get("_retry_generation", 0) + 1
    step["retries"] = 0
    if _force_retry:
        step["_force_retry_count"] = step.get("_force_retry_count", 0) + 1
        # Store execution_generation for audit scoping (pre-increment value)
        with _workflow_state_lock:
            _current_gen = _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
        step["_force_retry_at_generation"] = _current_gen
    step.pop("execution_result", None)
    step.pop("output", None)
    step.pop("blocked_reason", None)
    step.pop("_original_input", None)
    step.pop("_extracted_constraints", None)
    step.pop("_validator_signals", None)
    step.pop("_validator_advisory", None)
    step.pop("_validator_decision", None)
    step.pop("_drift_signal", None)
    step.pop("_signal_analysis", None)

    # === FIX 1: CONTEXT STEP_OUTPUTS INVALIDATION (STEP_IO_CONTRACT_V1 §6) ===
    # retry_step clears step["execution_result"] and step["output"] above, but
    # workflow["context"]["step_outputs"] is a separate store used by the executor
    # to pass dependency outputs between steps.  Without this call, the stale
    # pre-retry output survives save_workflow serialization, is loaded by the
    # resurrection thread, and is passed to dependent steps via
    # get_dependency_outputs() — causing executor behavior to diverge from the
    # projection (executor still runs as if "Divide by 0" was the input).
    # invalidate_step_outputs deletes step_id's output AND all dependent outputs.
    from system.orchestrator.memory_controller import invalidate_step_outputs
    invalidate_step_outputs(workflow, step_id)

    # === PHASE S9D: STRUCTURED INVALIDATION TRACE — STEP OUTPUTS ===
    _emit_invalidation_trace(
        workflow_id=workflow_id,
        invalidation_type="step_outputs",
        step_id=step_id,
        details={"invalidated_step": step_id, "trigger": "retry"},
        actor="retry_step"
    )

    # === FIX A: DOWNSTREAM DEPENDENT INVALIDATION (Phase 1B — RETRY NORMALIZATION) ===
    # Per DEPENDENCY_MODEL_CONTRACT_V1 §10: dependent steps MUST be re-evaluated when
    # a dependency is retried.  Without this, downstream steps retain stale BLOCKED/PENDING
    # state with a blocked_reason referencing the now-retried step, causing mixed
    # ACTIVE/BLOCKED/PENDING persistence and projection divergence.
    _invalidated_dependents = _invalidate_dependents(workflow, step_id)

    # === PHASE S9D: STRUCTURED INVALIDATION TRACE — DEPENDENTS ===
    if _invalidated_dependents:
        _emit_invalidation_trace(
            workflow_id=workflow_id,
            invalidation_type="dependents",
            step_id=step_id,
            details={"invalidated_dependents": _invalidated_dependents, "trigger": "retry"},
            actor="retry_step"
        )

    # === FIX C: WORKFLOW AGGREGATE STATE RECOMPUTATION (Phase 1B — RETRY NORMALIZATION) ===
    # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: workflow aggregate state MUST be recomputed
    # from canonical step states after any lifecycle mutation.
    # Retry clears the failure that caused the workflow to be BLOCKED/FAILED; recompute:
    #   - If any step is still terminal-failed → workflow remains FAILED.
    #   - Otherwise workflow returns to ACTIVE so the orchestrator loop can continue.
    # workflow["output"] is cleared — it was built from the now-invalidated execution.
    # workflow["error"] is cleared — it reflected the retried failure.
    # _update_workflow_state writes authoritative ACTIVE to the registry so the
    # orchestrator loop condition (reads registry) does NOT immediately exit.
    _steps = workflow.get("steps", [])
    _new_wf_status = reconcile_workflow_lifecycle_from_steps(workflow_id, _steps)
    workflow["status"] = _new_wf_status  # Sync serialization mirror to computed status
    workflow.pop("error", None)          # Stale failure reason — no longer valid
    workflow["output"] = None            # Stale output — invalidated by retry

    # === PHASE 3B: TERMINAL INVALIDATION CHOREOGRAPHY ===
    # Canonical ordering per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1 §8:
    # 1. Terminal projection invalidation (authority-first, before lifecycle write)
    # 2. Lifecycle authority write
    # 3. Persistence commit
    # 4. Checkpoint cleanup
    # 5. Projection regeneration
    # 6. Stream event emission
    #
    # Per PROJECTION_CONTINUITY_CONTRACT_V1 §9:
    # Terminal projections MUST NOT revert unless Lifecycle Authority explicitly invalidates.
    # This invalidation call is the explicit invalidation authority action.
    # It MUST precede the lifecycle write so that the terminal projection is marked INVALIDATED
    # before any new projection can be generated from the updated state.
    try:
        from system.orchestrator.projection_manager import get_projection_manager as _get_pm_retry
        _pm_retry = _get_pm_retry()
        _pm_retry.invalidate_workflow(workflow_id)  # Step 1: invalidate terminal projection
    except Exception:
        pass

    _update_workflow_state(workflow_id, _new_wf_status, "user_retry")  # Step 2: Authoritative registry

    # === PHASE-IVB: EXECUTION GENERATION COORDINATION ===
    # Increment workflow_execution_generation to invalidate stale execution owners.
    # This is NON-authoritative coordination metadata only. It does NOT gate lifecycle
    # transitions. Per PHASE-IVA EXECUTION LEASE COORDINATION DESIGN AUDIT.
    with _workflow_state_lock:
        _current_gen = _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
        _workflow_state_registry[workflow_id]["execution_generation"] = _current_gen + 1
        _new_gen = _current_gen + 1
        print(f"[EXECUTION_GENERATION] Incremented workflow={workflow_id} generation={_new_gen}")

    # === PHASE S9D: STRUCTURED INVALIDATION TRACE — GENERATION ===
    _emit_invalidation_trace(
        workflow_id=workflow_id,
        invalidation_type="execution_generation",
        step_id=step_id,
        details={"previous_generation": _current_gen, "new_generation": _new_gen, "trigger": "retry"},
        actor="retry_step"
    )

    # Step 3: Persistence commit
    save_workflow(workflow)

    # Step 4: Delete stale checkpoint
    # The checkpoint was saved when step was FAILED with old execution_result.
    # If not deleted, restore_workflow_from_checkpoint will overwrite PENDING
    # status with FAILED and restore the stale execution_result, causing
    # immediate re-block with the old error despite mutation.
    from system.orchestrator.checkpoint_manager import delete_checkpoint
    delete_checkpoint(workflow_id)

    # Step 5: Projection regeneration — emit after authoritative state is committed.
    # Per CANONICAL_PROJECTION_MODEL_V1 §6: projections MUST be emitted when lifecycle changes.
    # Per PROJECTION_CONTINUITY_CONTRACT_V1 §10: invalid projections MUST refresh from authority.
    # The projection was INVALIDATED in Step 1; now regenerate from authoritative post-retry state.
    try:
        from system.orchestrator.projection_manager import get_projection_manager as _get_pm_retry2
        _pm_retry2 = _get_pm_retry2()
        _pm_retry2.emit_plan_mutated(workflow, _new_wf_status)  # Step 5: Regenerate projection
    except Exception:
        pass

    # Step 6: Stream event emission
    # Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
    # Emit truthful retry_generation so telemetry reflects actual user retry count.
    try:
        event_emitter.emit_step_retry(
            workflow_id=workflow_id,
            step_id=step_id,
            retry_count=step.get("_retry_generation", 0),
            max_retries=step.get("max_retries", 3),
            reason="user_retry"
        )
    except Exception:
        pass

    return {
        "status": "success",
        "step": step,
        "workflow_id": workflow_id
    }


def stop_workflow(workflow_id: str) -> Dict[str, Any]:
    """
    Stop a running workflow — FULL AUTHORITATIVE TERMINAL CONVERGENCE CHOREOGRAPHY.

    Per STATE_TRANSITIONS_CONTRACT_V1: ACTIVE|PAUSED|BLOCKED → FAILED
    Per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1 §8:
    Canonical convergence ordering:
      1. Lifecycle authority transition (FAILED)
      2. Projection invalidation (authority-first)
      3. Terminal projection regeneration
      4. Persistence synchronization
      5. Checkpoint cleanup
      6. Stream event emission

    Per PROJECTION_CONTINUITY_CONTRACT_V1 §9:
    Terminal projections MUST NOT revert unless Lifecycle Authority explicitly invalidates.
    Invalidation MUST precede terminal projection generation.

    Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1:
    Terminalization MUST terminate execution and retry workers.
    Execution loops cooperatively check authoritative registry state — setting FAILED
    in the registry causes running loops to exit at the next boundary check.

    Args:
        workflow_id: The workflow ID

    Returns:
        {"status": "success", "previous_state": str, "new_state": "FAILED"}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    current_state = _get_workflow_state(workflow_id)
    if current_state is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    current = current_state.get("status", "QUEUED")

    # Per STATE_TRANSITIONS_CONTRACT_V1: Can stop from ACTIVE, PAUSED, or BLOCKED
    if current not in ["ACTIVE", "PAUSED", "BLOCKED"]:
        return {"status": "failure", "reason": f"cannot_stop_{current}_workflow"}

    # === STEP 1: LIFECYCLE AUTHORITY TRANSITION ===
    # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: Lifecycle Authority is sole lifecycle writer.
    # This is the authoritative terminal transition. All downstream layers observe this.
    # Execution loops cooperatively exit when they read FAILED from the registry.
    if not _update_workflow_state(workflow_id, "FAILED", "user_stop"):
        return {"status": "failure", "reason": "update_failed"}

    # === STEP 2: PROJECTION INVALIDATION (authority-first) ===
    # Per PROJECTION_CONTINUITY_CONTRACT_V1 §9: Invalidation MUST precede terminal
    # projection generation so stale non-terminal projections are cleared first.
    # Per CANONICAL_PROJECTION_MODEL_V1 §10: Invalidation on lifecycle authority change.
    try:
        from system.orchestrator.projection_manager import get_projection_manager as _get_pm_stop
        _pm_stop = _get_pm_stop()
        _pm_stop.invalidate_workflow(workflow_id)
    except Exception:
        pass  # Projection failure MUST NOT affect lifecycle convergence

    # === STEP 3: TERMINAL PROJECTION REGENERATION ===
    # Per CANONICAL_PROJECTION_MODEL_V1 §5: Emit projection on lifecycle change.
    # Build a terminal FAILED projection from persisted workflow state.
    try:
        from system.orchestrator.projection_manager import get_projection_manager as _get_pm_stop2
        _pm_stop2 = _get_pm_stop2()
        # Load workflow from persistence for projection generation
        import json as _json_stop
        from system.orchestrator.persistence import _active_workflow_path as _awp_stop
        _stop_wf = None
        try:
            _stop_path = _awp_stop(workflow_id)
            if os.path.exists(_stop_path):
                with open(_stop_path, "r", encoding="utf-8") as _sf:
                    _stop_wf = _json_stop.load(_sf)
        except Exception:
            pass
        if _stop_wf and isinstance(_stop_wf, dict):
            inject_authoritative_lifecycle_into_workflow(_stop_wf)
            _pm_stop2.emit_lifecycle_changed(_stop_wf, "FAILED")
    except Exception:
        pass  # Projection failure MUST NOT affect lifecycle convergence

    # === STEP 4: PERSISTENCE SYNCHRONIZATION ===
    # Per INCIDENT-098A: Preserve FAILED active files per ISSUE-057 recoverable
    # semantics. Only delete active file for non-FAILED terminal workflows.
    try:
        from system.orchestrator.persistence import delete_workflow as _del_wf_stop
        _current_after_stop = _get_workflow_state(workflow_id)
        if _current_after_stop and _current_after_stop.get("status") != "FAILED":
            _del_wf_stop(workflow_id)
    except Exception:
        pass  # Persistence failure MUST NOT affect lifecycle convergence

    # === STEP 5: CHECKPOINT CLEANUP ===
    # Per Phase 2C: Delete checkpoint after terminal state.
    try:
        from system.orchestrator.checkpoint_manager import delete_checkpoint as _del_cp_stop
        _del_cp_stop(workflow_id)
    except Exception:
        pass  # Checkpoint failure MUST NOT affect lifecycle convergence

    # === STEP 5b: PROJECTION STORE CLEANUP (PHASE XII §3) ===
    # Per PHASE XII: remove in-memory projection store after terminal convergence.
    # Terminal projection was already emitted in STEP 3. This cleans up process-lifetime state.
    try:
        from system.orchestrator.projection_manager import get_projection_manager as _get_pm_stop3
        _get_pm_stop3().remove_workflow(workflow_id)
    except Exception:
        pass  # Projection cleanup failure MUST NOT affect lifecycle convergence

    # === STEP 5c: BG_ID CLEANUP (PHASE XII §2) ===
    # Per PHASE XII: deregister bg_id after terminal convergence.
    # bg_id may not be available here (stop_workflow is a control-plane operation),
    # but if we can resolve it from the map, clean it up.
    try:
        from system.orchestrator.bg_id_map import load_all as _load_all_stop, deregister_bg_id as _dereg_stop
        _all_mappings = _load_all_stop()
        for _bg_id_stop, _mapped_wf_id in list(_all_mappings.items()):
            if _mapped_wf_id == workflow_id:
                _dereg_stop(_bg_id_stop)
                break
    except Exception:
        pass  # bg_id cleanup failure MUST NOT affect lifecycle convergence

    # === STEP 6: STREAM EVENT EMISSION ===
    # Per CONTROL_MODEL: Events are advisory, non-authoritative.
    try:
        event_emitter.emit_state_transition(
            workflow_id=workflow_id,
            step_id=None,
            previous_state=current,
            new_state="FAILED",
            reason="user_stop"
        )
        event_emitter.emit_event(
            event_type="PROJECT_FAILED",
            workflow_id=workflow_id,
            data={"timestamp": time.time(), "reason": "user_stop"}
        )
    except Exception:
        pass

    return {
        "status": "success",
        "previous_state": current,
        "new_state": "FAILED",
        "workflow_id": workflow_id
    }


def cancel_workflow(workflow_id: str, reason: str = "user_cancel") -> Dict[str, Any]:
    """
    Cancel a running workflow — AUTHORITATIVE IMMUTABLE TERMINAL CONVERGENCE.

    Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
      ACTIVE|PAUSED|BLOCKED → CANCELLED

    Cancellation is:
      - intentional operator/system termination
      - immutable terminal (non-retryable, non-continuable)
      - governance-authorized stop

    Canonical convergence ordering (mirrors stop_workflow choreography):
      1. Lifecycle authority transition (CANCELLED)
      2. Projection invalidation (authority-first)
      3. Terminal projection regeneration
      4. Persistence synchronization
      5. Checkpoint cleanup
      6. Stream event emission

    Args:
        workflow_id: The workflow ID
        reason: Cancellation reason (default "user_cancel")

    Returns:
        {"status": "success", "previous_state": str, "new_state": "CANCELLED"}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    current_state = _get_workflow_state(workflow_id)
    if current_state is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    current = current_state.get("status", "QUEUED")

    # Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
    # Can cancel from ACTIVE, PAUSED, or BLOCKED
    if current not in ["ACTIVE", "PAUSED", "BLOCKED"]:
        return {"status": "failure", "reason": f"cannot_cancel_{current}_workflow"}

    # === STEP 1: LIFECYCLE AUTHORITY TRANSITION ===
    # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: Lifecycle Authority is sole lifecycle writer.
    # This is the authoritative immutable terminal transition.
    if not _update_workflow_state(workflow_id, "CANCELLED", reason):
        return {"status": "failure", "reason": "update_failed"}

    # === STEP 2: PROJECTION INVALIDATION (authority-first) ===
    try:
        from system.orchestrator.projection_manager import get_projection_manager as _get_pm_cancel
        _pm_cancel = _get_pm_cancel()
        _pm_cancel.invalidate_workflow(workflow_id)
    except Exception:
        pass  # Projection failure MUST NOT affect lifecycle convergence

    # === STEP 3: TERMINAL PROJECTION REGENERATION ===
    try:
        from system.orchestrator.projection_manager import get_projection_manager as _get_pm_cancel2
        _pm_cancel2 = _get_pm_cancel2()
        import json as _json_cancel
        from system.orchestrator.persistence import _active_workflow_path as _awp_cancel
        _cancel_wf = None
        try:
            _cancel_path = _awp_cancel(workflow_id)
            if os.path.exists(_cancel_path):
                with open(_cancel_path, "r", encoding="utf-8") as _cf:
                    _cancel_wf = _json_cancel.load(_cf)
        except Exception:
            pass
        if _cancel_wf and isinstance(_cancel_wf, dict):
            inject_authoritative_lifecycle_into_workflow(_cancel_wf)
            _pm_cancel2.emit_lifecycle_changed(_cancel_wf, "CANCELLED")
    except Exception:
        pass  # Projection failure MUST NOT affect lifecycle convergence

    # === STEP 4: PERSISTENCE PRESERVATION FOR INSPECTION ===
    # Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
    # CANCELLED workflows MAY support observability and inspection.
    # Preserve workflow persistence with CANCELLED status for terminal inspection.
    # Do NOT delete workflow file - this prevents inspection after refresh.
    try:
        from system.orchestrator.persistence import save_workflow as _save_wf_cancel
        # Use authoritative workflow state from registry, not stale disk file
        _cancel_wf = None
        _status_before = None
        
        # First try to get current workflow state from registry (authoritative)
        try:
            _current_state = _get_workflow_state(workflow_id)
            if _current_state:
                _status_before = _current_state.get("status")
        except Exception:
            pass
        
        # Load existing workflow file to preserve structure, but override status
        try:
            from system.orchestrator.persistence import _active_workflow_path as _awp_cancel
            _cancel_path = _awp_cancel(workflow_id)
            if os.path.exists(_cancel_path):
                import json as _json_cancel
                with open(_cancel_path, "r", encoding="utf-8") as _cf:
                    _cancel_wf = _json_cancel.load(_cf)
        except Exception:
            pass
        
        # Ensure we have a workflow object to save
        if not _cancel_wf:
            _cancel_wf = {"id": workflow_id, "status": "CANCELLED"}
        
        # Set authoritative CANCELLED status
        _cancel_wf["status"] = "CANCELLED"
        _cancel_wf["cancelled_at"] = time.time()
        _cancel_wf["cancellation_reason"] = reason
        
        # Persist with CANCELLED status
        _save_result = _save_wf_cancel(workflow_id, _cancel_wf)
        
        # Log persistence operation
        print("[CANCEL_PERSIST]", {
            "workflow_id": workflow_id,
            "status_before": _status_before,
            "status_after": "CANCELLED",
            "persisted": True,
            "path": _awp_cancel(workflow_id) if '_awp_cancel' in locals() else "unknown",
            "timestamp": time.time()
        })
        
    except Exception as e:
        # Log failure but don't affect lifecycle convergence
        print("[CANCEL_PERSIST_ERROR]", {
            "workflow_id": workflow_id,
            "error": str(e),
            "persisted": False,
            "timestamp": time.time()
        })
        pass  # Persistence failure MUST NOT affect lifecycle convergence

    # === STEP 5: CHECKPOINT CLEANUP ===
    try:
        from system.orchestrator.checkpoint_manager import delete_checkpoint as _del_cp_cancel
        _del_cp_cancel(workflow_id)
    except Exception:
        pass  # Checkpoint failure MUST NOT affect lifecycle convergence

    # === STEP 5b: PROJECTION STORE CLEANUP ===
    try:
        from system.orchestrator.projection_manager import get_projection_manager as _get_pm_cancel3
        _get_pm_cancel3().remove_workflow(workflow_id)
    except Exception:
        pass  # Projection cleanup failure MUST NOT affect lifecycle convergence

    # === STEP 5c: BG_ID CLEANUP ===
    try:
        from system.orchestrator.bg_id_map import load_all as _load_all_cancel, deregister_bg_id as _dereg_cancel
        _all_mappings = _load_all_cancel()
        for _bg_id_cancel, _mapped_wf_id in list(_all_mappings.items()):
            if _mapped_wf_id == workflow_id:
                _dereg_cancel(_bg_id_cancel)
                break
    except Exception:
        pass  # bg_id cleanup failure MUST NOT affect lifecycle convergence

    # === STEP 6: STREAM EVENT EMISSION ===
    try:
        event_emitter.emit_state_transition(
            workflow_id=workflow_id,
            step_id=None,
            previous_state=current,
            new_state="CANCELLED",
            reason=reason,
        )
        event_emitter.emit_event(
            event_type="PROJECT_CANCELLED",
            workflow_id=workflow_id,
            data={"timestamp": time.time(), "reason": reason},
        )
    except Exception:
        pass

    return {
        "status": "success",
        "previous_state": current,
        "new_state": "CANCELLED",
        "workflow_id": workflow_id,
    }

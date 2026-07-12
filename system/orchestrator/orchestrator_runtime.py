import json
import os
import shlex
import threading
import time
from datetime import datetime, timezone

DEBUG_VERBOSE = False

from system.entry.system_entry import system_entry
from system.orchestrator.workflow_validator import validate_workflow
from system.orchestrator.agent_executor import execute_agent
from system.orchestrator.agent_output_interpreter import interpret_agent_output
from system.orchestrator.decision_hook import evaluate_interpretation
from system.orchestrator.persistence import save_workflow
from system.orchestrator.orchestrator_planner import plan_workflow
from system.orchestrator.planner_output_validator import validate_planner_output
from system.orchestrator.planner_soft_guard import enforce_atomic_steps
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm
from system.orchestrator.workflow_control import _update_workflow_state, _get_workflow_state, _update_runtime_registry_only, finalize_workflow_from_execution


def _rollback_partial_state(workflow_id: str, bg_id: str, stream_registry, stream_registry_lock, reason: str) -> None:
    """
    Orchestrator-layer-only cleanup for execution bootstrap failures.

    Does NOT import from api.py — eliminates circular dependency.
    Cleans: stream registry entry, bg_id map, projection store, runtime registry.
    All steps are idempotent and failure-isolated.
    """
    print(f"[ROLLBACK] workflow={workflow_id} bg={bg_id} reason={reason}")

    if bg_id and stream_registry is not None and stream_registry_lock is not None:
        try:
            with stream_registry_lock:
                stream_registry.pop(bg_id, None)
        except Exception:
            pass

    if bg_id:
        try:
            from system.orchestrator.bg_id_map import deregister_bg_id as _dereg
            _dereg(bg_id)
        except Exception:
            pass

    if workflow_id:
        try:
            from system.orchestrator.projection_manager import get_projection_manager as _gpm
            _pm = _gpm()
            _pm.remove_workflow(workflow_id)
        except Exception:
            pass

    if workflow_id:
        try:
            _update_runtime_registry_only(workflow_id, "FAILED", f"rollback:{reason}")
        except Exception:
            pass


# === SAFETY CONSTRAINTS ===
MAX_STEPS_PER_WORKFLOW = 20
MAX_STEPS_PER_CYCLE = 1
from system.orchestrator.intent_validator import evaluate_intent
import system.orchestrator.governance as governance
from system.orchestrator import trace_collector
from system.orchestrator import escalation_controller

# === LIVE STATE STREAMING (Phase 3) — OBSERVATIONAL ONLY ===
# Per HAND_ARCHITECTURE_V2: Streaming reflects state, never influences it
# Per CONTROL_MODEL: Events are advisory, non-authoritative
try:
    from system.interface import event_emitter as _event_emitter
except Exception:
    _event_emitter = None
from system.orchestrator.conflict_detector import get_detector
from system.orchestrator.execution_scheduler import create_execution_group
from system.orchestrator.parallel_executor import execute_parallel_group, execute_sequential_group

# === CANONICAL PROJECTION MANAGER (Phase 4A.0) ===
# Per CANONICAL_PROJECTION_MODEL_V1: Orchestrator Runtime owns canonical projections
# Per ORCHESTRATOR_CONTRACT_V2: Runtime MUST generate synchronized canonical projections
# FAILURE-ISOLATED: Import failure must not affect execution
try:
    from system.orchestrator.projection_manager import get_projection_manager as _get_projection_manager
except Exception:
    _get_projection_manager = None

# === F4-A1/F4-B/F4-C CONTINUATION PIPELINE (Phase 4C.0) ===
# Per PLANNING_CONTINUATION_CONTRACT_V1: observation/resolution/application are
# advisory planning control only; they do not own lifecycle, governance, or execution.
# FAILURE-ISOLATED: Import failure or continuation failure must not affect execution.
try:
    from system.orchestrator.planning_continuation import (
        apply_resolved_continuations,
        observe_step_after_completion,
        resolve_continuation_candidates,
    )
except Exception:
    observe_step_after_completion = None
    resolve_continuation_candidates = None
    apply_resolved_continuations = None

# === STREAM REGISTRY ACCESS ===
# Stream registry and lock are injected by api.py as parameters to execute_from_input().
# These module-level names are kept as None; all actual access goes through the
# function parameters (stream_registry, stream_registry_lock). The existing
# 'if bg_id and stream_registry and stream_registry_lock:' guards throughout
# execute_from_input() handle the None case (non-API/test context).
_stream_registry = None
_stream_registry_lock = None

# === EARLY WORKFLOW_ID REGISTRY (Phase 3 — Streaming) ===
# Maps thread_id → workflow_id as soon as planning completes.
# Written by execute_from_input after plan_workflow; read by API streaming wrapper.
# Observational only — never influences execution.
_thread_workflow_registry: dict = {}
_thread_workflow_registry_lock = threading.Lock()


def _register_workflow_id(workflow_id: str) -> None:
    """Publish workflow_id for the current thread — called after planning, before execution."""
    tid = threading.current_thread().ident
    with _thread_workflow_registry_lock:
        _thread_workflow_registry[tid] = workflow_id


def get_workflow_id_for_thread(thread_ident: int) -> str | None:
    """Retrieve workflow_id for a given thread — called by API streaming wrapper."""
    with _thread_workflow_registry_lock:
        return _thread_workflow_registry.get(thread_ident)


def _unregister_workflow_id() -> None:
    """Clean up registry entry for current thread after execution completes."""
    tid = threading.current_thread().ident
    with _thread_workflow_registry_lock:
        _thread_workflow_registry.pop(tid, None)


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TOOL_INDEX_PATH = os.path.join(_ROOT, "system", "tool_index", "tools.json")
with open(_TOOL_INDEX_PATH, "r", encoding="utf-8") as _f:
    _tool_index = json.load(_f)




def _ensure_step_metadata(step: dict) -> None:
    """
    Ensure step has required metadata fields for dynamic workflow support.
    Adds defaults if fields are missing (modifies step in-place).
    """
    if "created_at_runtime" not in step:
        step["created_at_runtime"] = False
    if "created_during_step" not in step:
        step["created_during_step"] = None


def observe_tool_call(tool_call: str) -> dict:
    issues = []

    if not isinstance(tool_call, str):
        issues.append("not_string")
        return {
            "tool_call": tool_call,
            "issues": issues,
            "issue_count": len(issues)
        }

    if not tool_call.startswith("USE_TOOL:"):
        issues.append("missing_prefix")

    if "|" in tool_call:
        issues.append("pipe_operator")

    if len(tool_call.strip()) == 0:
        issues.append("empty_call")

    return {
        "tool_call": tool_call,
        "issues": issues,
        "issue_count": len(issues)
    }



def add_step(workflow: dict, step_data: dict, parent_step_id: str = None) -> dict:
    """
    Add a new step to workflow at runtime.
    
    STRUCTURAL ONLY — Does NOT trigger execution or enforce runtime constraints.
    
    Args:
        workflow: The workflow dict to append step to
        step_data: Step definition (must include id, name, agent, input, etc.)
        parent_step_id: ID of step that triggered this step creation (optional)
        
    Returns:
        dict: Updated workflow with new step appended
        
    Rules:
    - Appends to workflow["steps"] list
    - Sets created_at_runtime = True
    - Sets created_during_step = parent_step_id
    - Does NOT modify existing steps
    - Does NOT reorder steps
    - Does NOT trigger execution
    - Does NOT enforce runtime constraints (enforced in runtime loop)
    """
    # Copy step_data to avoid modifying input
    new_step = dict(step_data)
    
    # Set runtime metadata
    new_step["created_at_runtime"] = True
    new_step["created_during_step"] = parent_step_id
    
    # Enforce STEP_SCHEMA_CONTRACT_V1 required fields with safe defaults
    new_step["type"] = new_step.get("type", "EXECUTE_API")
    # tool_call set by agent at execution time — runtime does NOT construct/modify it
    new_step["expected_outcome"] = new_step.get("expected_outcome", "Execution completed")
    new_step["risk"] = new_step.get("risk", "LOW")
    new_step["importance"] = new_step.get("importance", "MEDIUM")
    new_step["resource_targets"] = new_step.get("resource_targets", [])
    
    # Set runtime state fields
    # Phase VII: route step initialization through authority API
    from system.orchestrator.workflow_control import request_step_transition as _rst_init
    _rst_init(new_step, new_step.get("status", "PENDING"), "runtime_step_added", validate=False)
    new_step["retries"] = new_step.get("retries", 0)
    new_step["max_retries"] = new_step.get("max_retries", 2)
    
    # Ensure attempt_history exists
    if "attempt_history" not in new_step:
        new_step["attempt_history"] = []
    
    # Append to workflow steps
    if "steps" not in workflow:
        workflow["steps"] = []
    workflow["steps"].append(new_step)
    
    return workflow


def run_workflow(workflow: dict, bg_id: str = None, return_trace: bool = False, stream_registry: dict = None, stream_registry_lock = None) -> dict:
    # === PERF036: run_workflow entry ===
    try:
        import time as _rw_time, json as _rw_json
        from datetime import datetime as _rw_dt, timezone as _rw_tz
        _p036_rw_start = _rw_time.monotonic()
        print("PERF036_BACKEND " + _rw_json.dumps({
            "label": "run_workflow_entry",
            "source_layer": "orchestrator_runtime_run_workflow",
            "timestamp_iso": _rw_dt.now(_rw_tz.utc).isoformat(),
            "bg_id": bg_id,
            "workflow_id": workflow.get("id", "unknown"),
            "step_count": len(workflow.get("steps", [])),
            "workflow_status": workflow.get("status"),
        }))
    except Exception:
        _p036_rw_start = None

    _wf_id = workflow.get("id", "unknown_workflow")
    _reg_state = _get_workflow_state(_wf_id)

    # Ensure workflow["steps"] exists
    if "steps" not in workflow:
        workflow["steps"] = []

    # Store workflow reference in registry at execution start (for progressive streaming)
    if bg_id and stream_registry and stream_registry_lock:
        try:
            with stream_registry_lock:
                if bg_id in stream_registry:
                    stream_registry[bg_id]["workflow"] = workflow
        except Exception:
            # Registry write failure must not affect execution
            pass

    # Ensure all existing steps have STEP_SCHEMA_CONTRACT_V1 fields
    for step in workflow.get("steps", []):
        _ensure_step_metadata(step)
        # Initialize schema fields with safe defaults
        if "type" not in step:
            step["type"] = "EXECUTE_API"
        # tool_call set by agent at execution time — runtime does NOT modify
        if "expected_outcome" not in step:
            step["expected_outcome"] = "Execution completed"
        if "risk" not in step:
            step["risk"] = "LOW"
        if "importance" not in step:
            step["importance"] = "MEDIUM"
        if "resource_targets" not in step:
            step["resource_targets"] = []
        # Initialize runtime state fields
        if "status" not in step:
            from system.orchestrator.workflow_control import request_step_transition
            request_step_transition(step, "PENDING", "schema_initialization", validate=False)
        if "retries" not in step:
            step["retries"] = 0
        if "max_retries" not in step:
            step["max_retries"] = 3
        # === F1: Step-result metadata defaults (non-authoritative, internal-only) ===
        step.setdefault("evidence_refs", [])
        step.setdefault("unresolved_refs", [])
        step.setdefault("dependency_refs_used", [])
        step.setdefault("validator_results", [])

    # === F1: Plan IR metadata defaults for hydrated/restored workflows ===
    workflow.setdefault("plan_id", workflow.get("id", "unknown"))
    workflow.setdefault("plan_version", 1)
    workflow.setdefault("continuation_metadata", {})

    # Initialize workflow status if not set
    # Per PHASE VI AUTHORITY CONSOLIDATION: workflow["status"] is SERIALIZATION MIRROR ONLY.
    # Registry is initialized from execute_from_input bootstrap, NOT from mutable mirror.
    workflow_id = workflow.get("id", "unknown_workflow")
    _existing = _get_workflow_state(workflow_id)
    if _existing is None:
        _update_workflow_state(workflow_id, "ACTIVE", "initialization", workflow_dict=workflow)  # Authoritative registry only
    elif _existing.get("status") == "ACTIVATING":
        # Per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1 §7:
        # ACTIVATING is transitional — MUST converge to ACTIVE before execution proceeds.
        # This handles resurrection path where startup set ACTIVATING but convergence
        # to ACTIVE is the execution thread's responsibility.
        _update_workflow_state(workflow_id, "ACTIVE", "resurrection_convergence", workflow_dict=workflow)

    # === CONTROL REGISTRY INITIALIZATION (LIFECYCLE STABILIZATION) ===
    # Populate workflow_control._workflow_state_registry for control-plane authority.
    # Per architectural audit: runtime memory owns active orchestration control.
    # This ensures pause/resume/override commands can locate active workflows.
    # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
    # MUST NOT overwrite an existing registry entry — resume_workflow() already
    # wrote ACTIVE to the registry before run_workflow() was called. Clobbering
    # that entry with workflow["status"] (stale persistence dict, may still say
    # PAUSED) would re-introduce the PAUSED entry guard firing on valid resume.
    #
    # Per Phase 3F-XA (Cold-Start Authority Fix):
    # Route through _update_runtime_registry_only() — the designated authority helper —
    # instead of a direct dict write. _update_runtime_registry_only initializes new
    # entries and is a no-op if the entry already exists AND was set by a prior
    # authoritative write (e.g. resume_workflow → _update_workflow_state).
    # Direct dict mutations outside lifecycle authority helpers are prohibited.
    try:
        from system.orchestrator.workflow_control import _update_runtime_registry_only
        _wf_id_init = workflow.get("id", "unknown_workflow")
        _existing = _get_workflow_state(_wf_id_init)
        if _existing is None:
            # No registry entry exists — initialize authoritatively.
            _update_runtime_registry_only(_wf_id_init, "ACTIVE", "run_workflow_init")
        # If entry already exists (resume path wrote ACTIVE), do NOT overwrite.
    except Exception:
        # Registry initialization failure must not affect execution
        pass

    # === WORKFLOW CONTEXT INITIALIZATION (via Memory Controller) ===
    from system.orchestrator.memory_controller import get_context
    get_context(workflow)  # Ensures context exists
    
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        workflow["output"] = {"status": "failure", "reason": validation["reason"]}
        workflow_id = workflow.get("id", "unknown_workflow")
        _update_workflow_state(workflow_id, "FAILED", validation["reason"], workflow_dict=workflow)  # Authoritative registry ONLY
        return {"status": "failure", "reason": validation["reason"]}

    trace = []

    # === TRACE COLLECTOR INITIALIZATION (READ-ONLY OBSERVABILITY) ===
    trace_collector.create_collector(workflow.get("id", "unknown_workflow"))

    # === CONFLICT DETECTOR REGISTRATION (Phase 1A) ===
    conflict_detector = get_detector()
    conflict_detector.register_workflow(workflow.get("id", "unknown_workflow"))

    # === LIVE STREAMING: WORKFLOW STARTED (OBSERVATIONAL ONLY) ===
    # Per HAND_ARCHITECTURE_V2 Section 15: LIVE mode shows workflow progress
    # CALL AFTER: workflow setup complete
    # FAILURE-ISOLATED: Event emission failure must not affect execution
    if _event_emitter is not None:
        try:
            _wf_id = workflow.get("id", "unknown_workflow")
            _wf_name = workflow.get("name", "unnamed")
            _step_count = len(workflow.get("steps", []))
            _event_emitter.emit_workflow_started(
                workflow_id=_wf_id,
                workflow_name=_wf_name,
                step_count=_step_count
            )
        except Exception:
            pass

    # === CANONICAL PROJECTION: WORKFLOW INITIALIZED (Phase 4A.0) ===
    # Per CANONICAL_PROJECTION_MODEL_V1 §5: Emit projection on workflow initialization
    # Per ORCHESTRATOR_CONTRACT_V2: Orchestrator Runtime owns projection generation
    # FAILURE-ISOLATED: Projection failure must not affect execution
    if _get_projection_manager is not None:
        try:
            _proj_mgr = _get_projection_manager()
            _init_lifecycle = (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("status", workflow.get("status", "ACTIVE"))
            _proj_mgr.emit_workflow_initialized(workflow, _init_lifecycle)
        except Exception:
            pass

    # === PAUSE ENTRY GUARD (Phase 6 Correction) ===
    # Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED is a blocking state
    # PAUSED → ACTIVE requires explicit user action via /resume endpoint
    # Runtime MUST NOT auto-resume paused workflows.
    # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: read authoritative registry,
    # NOT stale workflow dict — on resume re-entry the dict may still say "PAUSED"
    # if the persistence write lagged slightly behind the registry update.
    _pause_guard_state = (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get(
        "status", workflow.get("status")
    )
    if _pause_guard_state == "PAUSED":
        return {
            "status": "control",
            "action": "paused"
        }

    # === CHECKPOINT RESTORE (Phase 2C) — OBSERVATIONAL ONLY ===
    # Attempt to restore state from checkpoint BEFORE execution loop.
    # If checkpoint exists: restore step states (COMPLETED→skip, ACTIVE→FAILED, etc.)
    # If checkpoint missing or corrupt: start fresh (no effect on execution).
    # MUST NOT influence governance, scheduler, or execution logic.
    try:
        from system.orchestrator.checkpoint_manager import (
            load_checkpoint,
            restore_workflow_from_checkpoint,
        )
        _checkpoint = load_checkpoint(workflow.get("id", "unknown_workflow"))
        if _checkpoint is not None:
            restore_workflow_from_checkpoint(workflow, _checkpoint)
            print(f"[CHECKPOINT] Restored from checkpoint: {_checkpoint.get('last_completed_step_index', -1) + 1} step(s) recovered")
    except Exception:
        pass  # Checkpoint failure MUST NOT affect execution

    # === PERSISTENCE RESTORE (Phase 2D) — OBSERVATIONAL ONLY ===
    # Attempt to restore workflow state from persisted active workflow file.
    # If persisted state exists for this workflow: restore step states.
    # Normalize: ACTIVE (interrupted) → BLOCKED for resumption.
    # MUST NOT influence governance, scheduler, or execution logic.
    try:
        import json as _json_pr
        from system.orchestrator.persistence import _active_workflow_path as _awp_pr
        _wf_id = workflow.get("id", "unknown_workflow")
        _persisted = None
        try:
            with open(_awp_pr(_wf_id), "r", encoding="utf-8") as _pf:
                _persisted = _json_pr.load(_pf)
            if not isinstance(_persisted, dict) or _persisted.get("id") != _wf_id:
                _persisted = None
        except Exception:
            _persisted = None
        if _persisted is not None:
            # === PERSISTENCE GUARD (Identity Collision Fix) ===
            # Skip restore if persisted workflow has mismatched step IDs
            _persisted_step_ids = {s.get("id") for s in _persisted.get("steps", [])}
            _incoming_step_ids = {s.get("id") for s in workflow.get("steps", [])}
            if _persisted_step_ids != _incoming_step_ids:
                print(f"[PERSISTENCE] Skipped restore — step ID mismatch for {_wf_id}")
            else:
                _persisted_steps = {s.get("id"): s for s in _persisted.get("steps", [])}
                for step in workflow.get("steps", []):
                    _sid = step.get("id")
                    if _sid not in _persisted_steps:
                        continue
                    _ps = _persisted_steps[_sid]
                    _ps_status = _ps.get("status")
                    from system.orchestrator.workflow_control import request_step_transition as _rst
                    if _ps_status == "COMPLETED":
                        _rst(step, "COMPLETED", "persistence_restore", validate=False)
                        step["execution_result"] = _ps.get("execution_result")
                        step["retries"] = _ps.get("retries", 0)
                    elif _ps_status == "FAILED":
                        _rst(step, "FAILED", "persistence_restore", validate=False)
                        step["retries"] = _ps.get("retries", 0)
                    elif _ps_status == "BLOCKED":
                        _blocked_reason = _ps.get("blocked_reason", "")
                        # === EXECUTION RECOVERY NORMALIZATION (Phase 1B) ===
                        _DEP_BLOCK_PREFIX = "dependency_not_completed"
                        _ESCALATION_REASONS = {
                            "max_retries_exceeded", "escalated", "system_error"
                        }
                        if _blocked_reason.startswith(_DEP_BLOCK_PREFIX):
                            _rst(step, "PENDING", "persistence_restore_dep_block", validate=False)
                            step.pop("blocked_reason", None)
                            step["retries"] = _ps.get("retries", 0)
                            print(f"[PERSISTENCE] Step {_sid}: dep-BLOCKED → PENDING (dep re-eval on resume)")
                        elif _blocked_reason in _ESCALATION_REASONS:
                            _rst(step, "BLOCKED", "persistence_restore_escalation", validate=False)
                            step["blocked_reason"] = _blocked_reason
                            step["retries"] = 0
                            print(f"[PERSISTENCE] Step {_sid}: escalation-BLOCKED restored, retries reset to 0")
                        else:
                            _rst(step, "BLOCKED", "persistence_restore", validate=False)
                            step["retries"] = _ps.get("retries", 0)
                            if _blocked_reason:
                                step["blocked_reason"] = _blocked_reason
                    elif _ps_status == "ACTIVE":
                        # ACTIVE (interrupted) → BLOCKED for resumption
                        _rst(step, "BLOCKED", "persistence_restore_interrupted", validate=False)
                        step["retries"] = _ps.get("retries", 0)
                        step.pop("_retry_pending", None)
                    elif _ps_status == "RETRY":
                        # Legacy RETRY → PENDING normalization
                        _rst(step, "PENDING", "persistence_restore_legacy", validate=False)
                        step["retries"] = _ps.get("retries", 0)
                print(f"[PERSISTENCE] Restored workflow {_wf_id} from persisted state")
                # === STEP_OUTPUTS REBUILD (Phase 3F-XD) ===
                # Per STEP_IO_CONTRACT_V1 §3: dependency_outputs are read from
                # workflow["context"]["step_outputs"] at execution time.
                # step_outputs is written by set_step_output() only when a step
                # completes inside a live execution thread — it is NOT written
                # during persistence restore above.
                # After restart, step_outputs is empty even though COMPLETED steps
                # have their execution_result correctly restored. This causes
                # get_dependency_outputs to return {} for all deps, leaving the
                # agent with no concrete output values. The agent then re-resolves
                # the purpose string via LLM inference, which may produce a different
                # semantic interpretation (e.g. "result of step_4" instead of
                # "result of step_5"), corrupting the workflow DAG.
                # Fix: after persistence restore, repopulate step_outputs from
                # the restored execution_result of every COMPLETED step.
                # This is the same value that set_step_output() would have written
                # during the original execution — no semantic reinterpretation.
                try:
                    from system.orchestrator.memory_controller import set_step_output
                    _rebuilt = 0
                    for _rs in workflow.get("steps", []):
                        if _rs.get("status") == "COMPLETED" and _rs.get("execution_result") is not None:
                            set_step_output(workflow, _rs["id"], _rs["execution_result"])
                            _rebuilt += 1
                    if _rebuilt:
                        print(f"[PERSISTENCE] Rebuilt step_outputs for {_rebuilt} COMPLETED step(s) in {_wf_id}")
                except Exception:
                    pass  # Rebuild failure MUST NOT affect execution
        else:
            print(f"[PERSISTENCE] No persisted state for {_wf_id} — fresh start")
    except Exception:
        pass  # Persistence restore failure MUST NOT affect execution

    # === CONTEXT TRACKING FOR STEP-TO-STEP PASSING ===
    last_result = None

    # === SAFETY TRACKING VARIABLES ===
    # Track step creation per cycle (resets each iteration)
    steps_created_this_cycle = 0
    # Track recent outputs for loop detection
    _recent_outputs = []
    # Track hybrid (output, result) pairs for enhanced loop detection
    _recent_pairs = []

    loop_iteration = 0
    # === LOOP CONDITION (Phase 6 Fix) ===
    # Per AUTHORITY MODEL: runtime MUST NOT influence decisions
    # Loop continues while workflow not in terminal state (COMPLETED/FAILED/CANCELLED)
    from system.orchestrator.step_executor import execute_step
    from system.orchestrator.step_chainer import propagate_result

    # === PHASE-IVB: OPTIONAL LOOP-TOP GENERATION VALIDATION (DEFENSE-IN-DEPTH) ===
    # Capture execution generation at loop entry for stale owner suppression.
    # This is NON-authoritative coordination metadata only. It does NOT gate lifecycle
    # transitions. Entry-point validation (generation increment at resurrection/retry) is
    # the PRIMARY defense. Loop-top validation is OPTIONAL defense-in-depth only.
    # Per PHASE-IVA EXECUTION LEASE COORDINATION DESIGN AUDIT.
    try:
        _loop_start_gen = None
        from system.orchestrator.workflow_control import _workflow_state_registry
        _loop_start_gen = _workflow_state_registry.get(workflow.get("id", "unknown_workflow"), {}).get("execution_generation", 1)
    except Exception:
        _loop_start_gen = 1

    _stale_owner_exit = False

    # === RUNTIME ACTIVITY: EXECUTING ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # Execution loop is now active — set EXECUTING authoritatively in registry.
    # Failure-isolated: must not affect execution.
    try:
        from system.orchestrator.workflow_control import _set_runtime_activity as _sra_exec
        _wf_id_exec = workflow.get("id", "unknown_workflow")
        _sra_exec(_wf_id_exec, "EXECUTING")
        # Mirror to stream registry for global frontend observability
        if bg_id and stream_registry and stream_registry_lock:
            with stream_registry_lock:
                if bg_id in stream_registry:
                    stream_registry[bg_id]["runtime_activity"] = "EXECUTING"
    except Exception:
        pass

    # === LOOP CONDITION (Phase 4A.1) ===
    # Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED is an exit condition
    # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1 §EXECUTOR RULES:
    # Executors MUST check authoritative runtime state only.
    # workflow["status"] is stale in-memory object; authoritative truth is _workflow_state_registry.
    while (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("status", workflow["status"]) not in ("COMPLETED", "BLOCKED", "FAILED", "CANCELLED", "PAUSED"):
        loop_iteration += 1
        
        # === PHASE-IVB: OPTIONAL LOOP-TOP GENERATION VALIDATION (DEFENSE-IN-DEPTH) ===
        # Check if execution generation has changed (ownership transfer occurred).
        # If generation changed, this is a stale owner — suppress execution.
        # This is NON-authoritative coordination metadata only. Entry-point validation
        # (generation increment at resurrection/retry) is the PRIMARY defense.
        # Per PHASE-IVA EXECUTION LEASE COORDINATION DESIGN AUDIT.
        try:
            from system.orchestrator.workflow_control import _workflow_state_registry
            _current_gen = _workflow_state_registry.get(workflow.get("id", "unknown_workflow"), {}).get("execution_generation", 1)
            if _loop_start_gen is not None and _current_gen != _loop_start_gen:
                _stale_owner_exit = True
                break
        except Exception:
            pass
        if len(workflow.get("steps", [])) > MAX_STEPS_PER_WORKFLOW:
            # Per PHASE VI AUTHORITY CONSOLIDATION: direct mirror mutation prohibited
            workflow_id = workflow.get("id", "unknown_workflow")
            workflow["error"] = "max_steps_exceeded"
            _update_workflow_state(workflow_id, "BLOCKED", "max_steps_exceeded", workflow_dict=workflow)  # Authoritative registry ONLY
            trace.append({
                "step_id": "workflow",
                "event": "workflow_blocked",
                "status": workflow["status"],
                "reason": "max_steps_exceeded",
                "retries": 0
            })
            break

        # === USER CONTROL: PAUSE CHECK (Phase 4A.1) ===
        # Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED is a controlled state transition
        # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1 §EXECUTOR RULES:
        # Executors MUST check authoritative runtime state only — not stale workflow object.
        _authoritative_status = (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("status", workflow.get("status"))
        if _authoritative_status == "PAUSED":
            save_workflow(workflow)
            trace.append({
                "step_id": "workflow",
                "event": "workflow_paused",
                "status": "PAUSED",
                "retries": 0
            })
            return {
                "status": "success",
                "result": {
                    "status": "paused",
                    "reason": "Execution paused by user"
                }
            }

        # === APPROVAL RESUME FLOW (Phase 1D — STATE_TRANSITIONS_CONTRACT_V1) ===
        # Before scheduling, check for approval-blocked steps.
        # Governance is the SOLE authority that decided BLOCK.
        # Runtime ONLY handles the approval interaction.
        # BLOCKED → ACTIVE transition per STATE_TRANSITIONS_CONTRACT_V1.
        for step in workflow.get("steps", []):
            if step.get("status") == "BLOCKED" and step.get("blocked_reason") == "approval_required":
                from system.orchestrator.user_approval import (
                    create_approval_request,
                    resolve_approval,
                    ApprovalStatus,
                )
                from system.interface.notification_manager import notify_approval_required
                step_id = step.get("id", "unknown")
                workflow_id = workflow.get("id", "unknown")

                # Create backend-owned approval request
                approval_req = create_approval_request(
                    workflow_id=workflow_id,
                    step_id=step_id,
                    reason="approval_required",
                    risk_level=step.get("risk", "MEDIUM"),
                    requested_action="execute_step",
                    source="governance",
                    details={
                        "purpose": step.get("purpose"),
                        "type": step.get("type"),
                        "tool_call": step.get("tool_call"),
                    },
                )

                # Emit contract-safe notification with approval_id action link
                try:
                    notify_approval_required(
                        step_id=step_id,
                        project_id=workflow_id,
                        risk_level=step.get("risk", "MEDIUM"),
                        approval_id=approval_req.approval_id,
                    )
                except Exception:
                    pass

                # TRACE: APPROVAL_REQUESTED (legacy compatibility)
                try:
                    trace_collector.record_transition(
                        step_id=step_id,
                        previous_status="BLOCKED",
                        new_status="BLOCKED",
                        reason="APPROVAL_REQUESTED"
                    )
                except Exception:
                    pass

                # Block runtime thread until operator resolves via API.
                # concurrent.futures.Future is thread-safe and compatible
                # with ThreadPoolExecutor contexts.
                try:
                    approved = approval_req.wait_for_decision(timeout=None)
                except Exception:
                    approved = False

                if approved:
                    # Validate the approval is still legal before applying
                    if approval_req.status == ApprovalStatus.APPROVED:
                        # BLOCKED → ACTIVE (per STATE_TRANSITIONS_CONTRACT_V1)
                        from system.orchestrator.workflow_control import request_step_transition as _rst_approval
                        _rst_approval(step, "ACTIVE", "approval_granted", _internal=True)
                        step.pop("blocked_reason", None)
                        step["_approval_resumed"] = True

                        # TRACE: approval_applied
                        try:
                            _tc = trace_collector.get_collector(workflow_id)
                            if _tc:
                                _tc._safe(
                                    "approval_applied",
                                    lambda: _tc.steps.append({
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                        "project_id": workflow_id,
                                        "step_id": step_id,
                                        "level": "NORMAL",
                                        "event": "approval_applied",
                                        "data": {
                                            "approval_id": approval_req.approval_id,
                                            "workflow_id": workflow_id,
                                            "step_id": step_id,
                                            "reason": "approval_granted",
                                        }
                                    })
                                )
                        except Exception:
                            pass

                        # TRACE: APPROVAL_GRANTED (legacy compatibility)
                        try:
                            trace_collector.record_transition(
                                step_id=step_id,
                                previous_status="BLOCKED",
                                new_status="ACTIVE",
                                reason="APPROVAL_GRANTED"
                            )
                        except Exception:
                            pass
                    else:
                        # Approval status drifted after wait (should not happen)
                        approved = False

                if not approved:
                    # TRACE: APPROVAL_DENIED — step remains BLOCKED
                    try:
                        trace_collector.record_transition(
                            step_id=step_id,
                            previous_status="BLOCKED",
                            new_status="BLOCKED",
                            reason="APPROVAL_DENIED"
                        )
                    except Exception:
                        pass

        # === EXTERNAL-CALL RISK RESUME / BLOCK FLOW (ISSUE-098I) ===
        # Pre-execution deterministic check for external-call tools.
        # Backend-owned metadata decides whether a step may proceed.
        # Does NOT bypass system_entry, governance, approval, or plan mode.
        # Failure-isolated: any exception in this block skips to next step.
        for _ec_step in workflow.get("steps", []):
            _ec_step_id = _ec_step.get("id", "unknown")
            _ec_wf_id = workflow.get("id", "unknown")
            _ec_status = _ec_step.get("status")

            # Determine the tool for external-call gating.
            # Prefer explicit tool_call; otherwise infer from deterministic
            # capability/profile metadata so web steps that are not prepopulated
            # are still gated before scheduling.
            _ec_tool_call = _ec_step.get("tool_call")
            _ec_tool_inferred = not _ec_tool_call
            _ec_tool_name = None
            _ec_tool_args = None
            if _ec_tool_call:
                try:
                    _ec_parts = shlex.split(str(_ec_tool_call).strip(), posix=False)
                except ValueError:
                    continue
                if not _ec_parts:
                    continue
                _ec_tool_name = _ec_parts[0]
                if _ec_tool_name == "read_webpage" and len(_ec_parts) > 1:
                    _ec_tool_args = {"url": " ".join(_ec_parts[1:])}
                elif _ec_tool_name == "web_search" and len(_ec_parts) > 1:
                    _ec_tool_args = {"query": " ".join(_ec_parts[1:])}
            else:
                # === FIX2/FIX3.1: deterministic inference for empty tool_call ===
                # Explicit step-owned allowed_tool is the most specific signal and must
                # short-circuit agent/profile fallbacks. If it is a non-web tool, the
                # step is NOT an external-call gate target.
                _cap_meta = _ec_step.get("capability_metadata") or {}
                _allowed_tool = _cap_meta.get("allowed_tool") or _ec_step.get("allowed_tool")
                if _allowed_tool in ("read_webpage", "web_search"):
                    _ec_tool_name = _allowed_tool
                elif _allowed_tool:
                    # Explicit non-web allowed_tool means this step is not an external-call step.
                    continue
                else:
                    # Exact agent -> default external-call tool mapping only.
                    _agent_to_tool = {
                        "web_read": "read_webpage",
                        "web_executor": "web_search",
                    }
                    _ec_tool_name = _agent_to_tool.get(_ec_step.get("agent"))
                    if not _ec_tool_name:
                        # Step-owned profile -> default external-call tool mapping.
                        # Workflow-level profile alone must NOT cause a non-web
                        # finalize/present step to be gated.
                        _step_profile = _ec_step.get("_step_profile")
                        if _step_profile == "WebReadProfile":
                            _ec_tool_name = "read_webpage"
                        elif _step_profile == "WebSearchProfile":
                            _ec_tool_name = "web_search"
                if not _ec_tool_name:
                    continue

            # Query deterministic external-call risk metadata
            try:
                from system.security.tool_policy import get_external_call_risk_metadata
                _ec_risk = get_external_call_risk_metadata(_ec_tool_name, _ec_tool_args)
            except Exception:
                continue

            # Not an external-call tool — nothing to do
            if not _ec_risk.get("external_call"):
                continue

            # RESUME: Already blocked for external_call_risk
            if _ec_status == "BLOCKED" and _ec_step.get("blocked_reason") == "external_call_risk":
                try:
                    from system.orchestrator.user_control import get_accepted_external_call_risk_for_step
                    _ec_accepted = get_accepted_external_call_risk_for_step(
                        _ec_wf_id,
                        _ec_step_id,
                        execution_generation=_ec_step.get("execution_generation"),
                        retry_generation=_ec_step.get("_retry_generation"),
                    )
                except Exception:
                    _ec_accepted = None

                if _ec_accepted and (
                    _ec_risk.get("overrideable_with_user_control") or _ec_tool_inferred
                ):
                    # === ISSUE-098KM FIX: Transition BLOCKED → PENDING (not ACTIVE) ===
                    # Per execution_scheduler.py active_steps guard (lines 496-505):
                    # ACTIVE steps without _approval_resumed or _retry_pending cause
                    # scheduler to return None, preventing execution.
                    # PENDING steps are naturally included in the execution group.
                    try:
                        from system.orchestrator.workflow_control import request_step_transition as _rst_ec_resume
                        _rst_ec_resume(_ec_step, "PENDING", "external_call_risk_accepted", _internal=True)
                    except Exception:
                        pass

                    # Do NOT mark request APPLIED here.
                    # Per ISSUE-098KM: APPLIED before execution causes BLOCK path
                    # to fail the accepted lookup on the next loop iteration,
                    # creating a new pending request and blocking the step again.
                    # The request remains ACCEPTED; BLOCK path will honor it.
                    continue

                # === ISSUE-098KL: Check for REJECTED request ===
                # If operator previously rejected, update blocked_reason so the
                # step state clearly indicates rejection rather than pending.
                try:
                    from system.orchestrator.user_control import get_rejected_external_call_risk_for_step
                    _ec_rejected = get_rejected_external_call_risk_for_step(
                        _ec_wf_id,
                        _ec_step_id,
                        tool_name=_ec_tool_name,
                        destination=_ec_risk.get("destination"),
                    )
                except Exception:
                    _ec_rejected = None

                if _ec_rejected:
                    _ec_step["blocked_reason"] = "external_call_risk_rejected"

                    # Trace: external_call_risk_rejected
                    try:
                        trace_collector.record_transition(
                            step_id=_ec_step_id,
                            previous_status="BLOCKED",
                            new_status="BLOCKED",
                            reason="EXTERNAL_CALL_RISK_REJECTED",
                        )
                    except Exception:
                        pass

                    # Structured trace
                    try:
                        _ec_tc = trace_collector.get_collector(_ec_wf_id)
                        if _ec_tc:
                            _ec_tc._safe(
                                "external_call_risk_rejected",
                                lambda: _ec_tc.steps.append({
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "project_id": _ec_wf_id,
                                    "step_id": _ec_step_id,
                                    "level": "NORMAL",
                                    "event": "external_call_risk_rejected",
                                    "data": {
                                        "tool_name": _ec_tool_name,
                                        "provider": _ec_risk.get("provider"),
                                        "destination": _ec_risk.get("destination"),
                                        "control_id": _ec_rejected.control_id,
                                        "reason": "operator_rejected",
                                    },
                                })
                            )
                    except Exception:
                        pass
                continue

            # BLOCK: PENDING or ACTIVE steps that use external-call tools
            if _ec_status not in ("PENDING", "ACTIVE"):
                continue

            # Fail-closed: non-overrideable tools must not be allowed through user-control.
            # Exception: when the tool was inferred from capability/profile metadata
            # because tool_call is not yet prepopulated, runtime metadata may be
            # incomplete (e.g. read_webpage without a URL). The tool is still known
            # to be an external-call approval tool, so gate it rather than skipping.
            if not _ec_risk.get("overrideable_with_user_control") and not _ec_tool_inferred:
                continue

            # Check for accepted request
            try:
                from system.orchestrator.user_control import get_accepted_external_call_risk_for_step
                _ec_accepted = get_accepted_external_call_risk_for_step(
                    _ec_wf_id,
                    _ec_step_id,
                    execution_generation=_ec_step.get("execution_generation"),
                    retry_generation=_ec_step.get("_retry_generation"),
                )
            except Exception:
                _ec_accepted = None

            if _ec_accepted:
                # Accepted request exists — step proceeds normally.
                # No status change needed; scheduler will pick it up as PENDING/ACTIVE.
                continue

            # === ISSUE-098KM: Safety-net — check for APPLIED request ===
            # If an accepted request was already consumed (marked APPLIED) for
            # this generation, the step should still proceed. Do not create a new
            # pending request that would cause an accept loop.
            try:
                from system.orchestrator.user_control import get_latest_external_call_risk_for_step
                _ec_latest = get_latest_external_call_risk_for_step(_ec_wf_id, _ec_step_id)
                if _ec_latest and _ec_latest.status.value == "APPLIED":
                    from system.orchestrator.user_control import _validate_stale_generations
                    _stale_check = _validate_stale_generations(
                        _ec_latest,
                        current_execution_generation=_ec_step.get("execution_generation"),
                        current_retry_generation=_ec_step.get("_retry_generation"),
                    )
                    if _stale_check["valid"]:
                        continue
            except Exception:
                pass

            # === ISSUE-098KL: Check for REJECTED request before creating new pending ===
            # If operator previously rejected, do not spam-create a new pending request.
            # Block with rejected reason and require explicit operator action to retry.
            try:
                from system.orchestrator.user_control import get_rejected_external_call_risk_for_step
                _ec_rejected = get_rejected_external_call_risk_for_step(
                    _ec_wf_id,
                    _ec_step_id,
                    tool_name=_ec_tool_name,
                    destination=_ec_risk.get("destination"),
                )
            except Exception:
                _ec_rejected = None

            if _ec_rejected:
                # Block with rejected reason — no new request, no execution
                try:
                    from system.orchestrator.workflow_control import request_step_transition as _rst_ec_reject
                    _rst_ec_reject(_ec_step, "BLOCKED", "external_call_risk_rejected", _internal=True)
                    _ec_step["blocked_reason"] = "external_call_risk_rejected"
                except Exception:
                    continue

                # Trace: external_call_risk_rejected
                try:
                    trace_collector.record_transition(
                        step_id=_ec_step_id,
                        previous_status=_ec_status,
                        new_status="BLOCKED",
                        reason="EXTERNAL_CALL_RISK_REJECTED",
                    )
                except Exception:
                    pass

                # Structured trace
                try:
                    _ec_tc = trace_collector.get_collector(_ec_wf_id)
                    if _ec_tc:
                        _ec_tc._safe(
                            "external_call_risk_rejected",
                            lambda: _ec_tc.steps.append({
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "project_id": _ec_wf_id,
                                "step_id": _ec_step_id,
                                "level": "NORMAL",
                                "event": "external_call_risk_rejected",
                                "data": {
                                    "tool_name": _ec_tool_name,
                                    "provider": _ec_risk.get("provider"),
                                    "destination": _ec_risk.get("destination"),
                                    "control_id": _ec_rejected.control_id,
                                    "reason": "operator_rejected",
                                },
                            })
                        )
                except Exception:
                    pass
                continue

            # === ISSUE-098J: Get or create pending user-control request ===
            _ec_control_id = None
            _ec_request_created = False
            try:
                from system.orchestrator.user_control import get_or_create_external_call_risk_request
                _ec_req_result = get_or_create_external_call_risk_request(
                    workflow_id=_ec_wf_id,
                    step_id=_ec_step_id,
                    tool_name=_ec_tool_name,
                    provider=_ec_risk.get("provider"),
                    destination=_ec_risk.get("destination"),
                    data_leaving_system=_ec_risk.get("data_leaving_system"),
                    privacy_classification=_ec_risk.get("privacy_classification"),
                    risk_level=_ec_risk.get("risk_level", "MEDIUM"),
                    read_only=_ec_risk.get("read_only", True),
                    mutating=_ec_risk.get("mutating", False),
                    external_call=_ec_risk.get("external_call", True),
                    confirmation_text=_ec_risk.get("confirmation_text"),
                    execution_generation=_ec_step.get("execution_generation"),
                    retry_generation=_ec_step.get("_retry_generation"),
                )
                if _ec_req_result.get("success"):
                    _ec_control_id = _ec_req_result.get("control_id")
                    _ec_request_created = _ec_req_result.get("created", False)
            except Exception:
                _ec_control_id = None
                _ec_request_created = False

            # === ISSUE-098KLM-FIX1: RACE — accept arrived before BLOCKED commit ===
            # Re-check for an accepted request before committing the step/workflow
            # to BLOCKED. If the user resolved during this loop iteration, the
            # pending request created above is immediately superseded by the
            # accepted one; we must not write BLOCKED or exit the loop.
            _ec_accepted_race = None
            try:
                from system.orchestrator.user_control import get_accepted_external_call_risk_for_step
                _ec_accepted_race = get_accepted_external_call_risk_for_step(
                    _ec_wf_id,
                    _ec_step_id,
                    execution_generation=_ec_step.get("execution_generation"),
                    retry_generation=_ec_step.get("_retry_generation"),
                )
            except Exception:
                _ec_accepted_race = None

            if _ec_accepted_race is not None:
                # Accepted request already exists — allow execution to proceed.
                # The existing external-call gate will continue to honor it on
                # subsequent iterations, and the scheduler will pick the step up.
                continue

            # No accepted request — block step before execution
            try:
                from system.orchestrator.workflow_control import request_step_transition as _rst_ec_block
                _rst_ec_block(_ec_step, "BLOCKED", "external_call_risk", _internal=True)
                _ec_step["blocked_reason"] = "external_call_risk"
                # ISSUE-098N: persist control_id in execution_result for orphan reconstruction
                _ec_step["execution_result"] = {
                    "status": "blocked",
                    "reason": "external_call_risk",
                    "control_id": _ec_control_id,
                    "request_status": "PENDING" if _ec_control_id else None,
                }
            except Exception:
                continue

            # === ISSUE-098KN FIX: Update workflow status to BLOCKED ===
            # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: runtime loop must exit when
            # no executable steps remain. Without this, workflow stays ACTIVE while
            # step is BLOCKED, causing accept-triggered resume to fail because
            # resume_workflow rejects ACTIVE→ACTIVE and the old thread exits as
            # stale after generation increment.
            try:
                from system.orchestrator.workflow_control import _update_workflow_state as _uws_ec_block
                _uws_ec_block(_ec_wf_id, "BLOCKED", "external_call_risk", workflow_dict=workflow)
            except Exception:
                pass

            # Trace: external_call_risk_blocked
            try:
                trace_collector.record_transition(
                    step_id=_ec_step_id,
                    previous_status=_ec_status,
                    new_status="BLOCKED",
                    reason="EXTERNAL_CALL_RISK_BLOCKED",
                )
            except Exception:
                pass

            # Structured trace with full metadata
            try:
                _ec_tc = trace_collector.get_collector(_ec_wf_id)
                if _ec_tc:
                    _ec_tc._safe(
                        "external_call_risk_blocked",
                        lambda: _ec_tc.steps.append({
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "project_id": _ec_wf_id,
                            "step_id": _ec_step_id,
                            "level": "NORMAL",
                            "event": "external_call_risk_blocked",
                            "data": {
                                "tool_name": _ec_tool_name,
                                "provider": _ec_risk.get("provider"),
                                "destination": _ec_risk.get("destination"),
                                "data_leaving_system": _ec_risk.get("data_leaving_system"),
                                "privacy_classification": _ec_risk.get("privacy_classification"),
                                "risk_level": _ec_risk.get("risk_level"),
                                "confirmation_text": _ec_risk.get("confirmation_text"),
                                "blocked_reason": "external_call_risk",
                                "control_id": _ec_control_id,
                                "request_created": _ec_request_created,
                            },
                        })
                    )
            except Exception:
                pass

            # Notification (only if request was newly created to avoid spam)
            if _ec_request_created and _ec_control_id:
                try:
                    from system.interface.notification_manager import notify_user_control_required
                    notify_user_control_required(
                        step_id=_ec_step_id,
                        project_id=_ec_wf_id,
                        risk_level=_ec_risk.get("risk_level", "MEDIUM"),
                        control_id=_ec_control_id,
                        requested_action="accept_external_call_risk",
                    )
                except Exception:
                    pass

        # === EXECUTION SCHEDULING (EXECUTION_SCHEDULING_CONTRACT_V1) ===
        # Build step_states map for scheduler
        step_states = {s.get("id"): s.get("status", "PENDING") for s in workflow.get("steps", [])}

        # Form NEXT execution group (scheduler derives groups dynamically)
        group = create_execution_group(
            workflow=workflow,
            step_states=step_states,
            conflict_detector=conflict_detector,
            workflow_id=workflow.get("id", "unknown_workflow")
        )

        if group is None:
            print("[SCHEDULER] No execution group formed - no pending steps or previous group incomplete")
            # === FIX: Check terminalization before breaking (retry repair gap) ===
            # When no execution group is formed (all steps terminal), we must still
            # check if workflow should be COMPLETED. Without this check, repaired workflows
            # remain ACTIVE forever after successful retry completion.
            workflow_id = workflow.get("id", "unknown_workflow")
            if all(s["status"] == "COMPLETED" for s in workflow["steps"]):
                print(f"[CHECK] All steps completed (group=None path), exiting loop")
                _final_status = finalize_workflow_from_execution(workflow_id, workflow["steps"])
                try:
                    if _get_projection_manager is not None:
                        _proj_mgr = _get_projection_manager()
                        if _final_status == "COMPLETED":
                            _proj_mgr.emit_lifecycle_changed(workflow, "COMPLETED")
                except Exception:
                    pass
                break
            # If not all COMPLETED, check for terminal failure state
            non_terminal = [s for s in workflow["steps"] if s["status"] not in ("COMPLETED", "FAILED")]
            if not non_terminal:
                _final_status = finalize_workflow_from_execution(workflow_id, workflow["steps"])
                try:
                    if _get_projection_manager is not None:
                        _proj_mgr = _get_projection_manager()
                        if _final_status in ("COMPLETED", "FAILED", "CANCELLED"):
                            _proj_mgr.emit_lifecycle_changed(workflow, _final_status)
                except Exception:
                    pass
                break
            # If there are non-terminal steps (BLOCKED), continue loop for re-evaluation
            print("[CHECK] BLOCKED steps exist, continuing for dependency re-evaluation")

        if group is None:
            # No pending steps available for scheduling; skip group execution
            # Post-group termination checks below will handle exit/continue
            print("[SCHEDULER] No group formed - skipping execution")
            group_results = []
        else:
            print(f"[SCHEDULER] Group formed: {group['group_id']} type={group['group_type']} steps={group['steps']}")

            # === GROUP-BASED EXECUTION ===
            group_type = group.get("group_type", "SEQUENTIAL")

            if group_type == "PARALLEL" and len(group.get("steps", [])) > 1:
                # === PARALLEL GROUP EXECUTION ===
                group_results = execute_parallel_group(
                    group=group,
                    workflow=workflow,
                    execute_step_fn=execute_step,
                    governance_fn=governance.decide_next_action,
                    propagate_fn=propagate_result,
                    escalation_handler=escalation_controller,
                    debug_verbose=DEBUG_VERBOSE
                )
            else:
                # === SEQUENTIAL GROUP EXECUTION ===
                group_results = execute_sequential_group(
                    group=group,
                    workflow=workflow,
                    execute_step_fn=execute_step,
                    governance_fn=governance.decide_next_action,
                    propagate_fn=propagate_result,
                    escalation_handler=escalation_controller,
                    debug_verbose=DEBUG_VERBOSE,
                    post_step_callback=None
                )

            # === POST-GROUP STATE UPDATE ===
            # CRITICAL FIX: Process EACH result individually, not just the last one
            # Previous bug: loop only extracted values, then used LAST result after loop
            for result in group_results:
                step_id = result.get("step_id")
                step_status = result.get("status")
                exec_res = result.get("execution_result")

                # Trace EACH step completion
                trace.append({
                    "step_id": step_id,
                    "event": f"step_{step_status.lower()}" if step_status else "step_unknown",
                    "status": step_status,
                    "retries": step.get("retries", 0)
                })

                # === OUTPUT CONTRACT: Update workflow output on EACH completion ===
                if step_status == "COMPLETED" and exec_res:
                    last_step = None
                    for s in reversed(workflow.get("steps", [])):
                        if s.get("execution_result") is not None:
                            last_step = s
                            break
                    workflow["output"] = governance.resolve_decision(
                        validator_output={},
                        execution_result=exec_res,
                        context={"last_step": last_step}
                    )
                    # Progressive registry update after each step completion
                    if bg_id and _stream_registry is not None:
                        with _stream_registry_lock:
                            if bg_id in _stream_registry:
                                _stream_registry[bg_id]["result"] = workflow

                    # === CANONICAL PROJECTION: OUTPUT UPDATED (Phase 4A.0) ===
                    # Per CANONICAL_PROJECTION_MODEL_V1 §5: Emit projection on output update
                    # FAILURE-ISOLATED: Projection failure must not affect execution
                    #
                    # === TERMINAL GUARD (PHASE-IIIA) ===
                    # Per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1: stale emissions
                    # MUST NOT overwrite terminal projections. Check authoritative state
                    # before emitting — if stop_workflow already terminalized, skip.
                    if _get_projection_manager is not None:
                        try:
                            _proj_mgr = _get_projection_manager()
                            _cur_lifecycle = (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("status", workflow.get("status", "ACTIVE"))
                            if _cur_lifecycle not in ("COMPLETED", "FAILED", "CANCELLED"):
                                _proj_mgr.emit_output_updated(workflow, step_id, _cur_lifecycle)
                        except Exception:
                            pass

                    # === F4-A1: OBSERVE-ONLY CONTINUATION CANDIDATE DETECTION ===
                    # Per PLANNING_CONTINUATION_CONTRACT_V1 §3: observe evidence and
                    # detect unresolved downstream references. This is advisory-only;
                    # it does not mutate the plan, execute tools, or change lifecycle.
                    # FAILURE-ISOLATED: Observation failure is absorbed and logged only.
                    if observe_step_after_completion is not None:
                        try:
                            completed_step = next(
                                (s for s in workflow.get("steps", []) if s.get("id") == step_id),
                                None,
                            )
                            if completed_step is not None:
                                observation = observe_step_after_completion(
                                    workflow,
                                    completed_step,
                                )
                                workflow.setdefault("_continuation_observations", []).append(observation)
                                trace.append({
                                    "step_id": step_id,
                                    "event": "continuation_observation",
                                    "observation_type": observation.get("observation_type"),
                                    "continue_candidates": [
                                        c.get("step_id")
                                        for c in observation.get("continue_candidates", [])
                                    ],
                                })
                                if resolve_continuation_candidates is not None:
                                    try:
                                        resolutions = resolve_continuation_candidates(
                                            workflow,
                                            completed_step,
                                            observation,
                                        )
                                        workflow.setdefault("_continuation_resolutions", []).extend(resolutions)
                                        trace.append({
                                            "step_id": step_id,
                                            "event": "continuation_resolutions",
                                            "resolution_count": len(resolutions),
                                            "resolved_step_ids": [
                                                r.get("target_step_id")
                                                for r in resolutions
                                                if r.get("status") == "resolved"
                                            ],
                                        })
                                    except Exception as _res_err:
                                        print(f"[F4-B:RESOLVE:WARN] {_res_err}")
                                if apply_resolved_continuations is not None:
                                    try:
                                        applications = apply_resolved_continuations(
                                            workflow,
                                            completed_step,
                                            resolutions,
                                        )
                                        workflow.setdefault("_continuation_applications", []).extend(applications)
                                        trace.append({
                                            "step_id": step_id,
                                            "event": "continuation_applications",
                                            "application_count": len(applications),
                                            "applied_step_ids": [
                                                a.get("target_step_id")
                                                for a in applications
                                                if a.get("status") == "applied"
                                            ],
                                        })
                                    except Exception as _app_err:
                                        print(f"[F4-C:APPLY:WARN] {_app_err}")
                        except Exception as _obs_err:
                            print(f"[F4-A1:OBSERVE:WARN] {_obs_err}")

        # === WORKFLOW STATE UPDATE (post-group boundary) ===
        step_statuses = [(s.get('id'), s.get('status')) for s in workflow["steps"]]
        print(f"[POST-GROUP CHECK] Step statuses: {step_statuses}")
        print(f"[POST-GROUP CHECK] Any BLOCKED: {any(s['status'] == 'BLOCKED' for s in workflow['steps'])}")
        print(f"[POST-GROUP CHECK] All COMPLETED: {all(s['status'] == 'COMPLETED' for s in workflow['steps'])}")

        # === CORRECT TERMINATION CONDITIONS (Phase 4B.2.6) ===
        # Per DEPENDENCY_MODEL_CONTRACT_V1: BLOCKED steps may become runnable
        # DO NOT terminate loop just because BLOCKED steps exist
        
        # Only exit when ALL steps are COMPLETED
        if all(s["status"] == "COMPLETED" for s in workflow["steps"]):
            print(f"[CHECK] All steps completed, exiting loop")
            # Per PHASE VI AUTHORITY CONSOLIDATION: execution NEVER commits lifecycle directly
            workflow_id = workflow.get("id", "unknown_workflow")
            finalize_workflow_from_execution(workflow_id, workflow["steps"])
            trace.append({
                "step_id": "workflow",
                "event": "workflow_completed"
            })
            # === CANONICAL PROJECTION: LIFECYCLE CHANGED → COMPLETED (Phase 4A.0) ===
            # === TERMINAL GUARD (PHASE-IIIA) ===
            # Verify authoritative state is still COMPLETED (not overridden by stop_workflow)
            # before emitting terminal projection.
            if _get_projection_manager is not None:
                try:
                    _proj_mgr = _get_projection_manager()
                    _auth_status_cp = (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("status")
                    if _auth_status_cp == "COMPLETED":
                        _proj_mgr.emit_lifecycle_changed(workflow, "COMPLETED")
                except Exception:
                    pass
            break
        
        # If no executable steps remain (no pending, no active), check if stuck
        # Per STATE_TRANSITIONS_CONTRACT_V1: RETRY is not a valid lifecycle state.
        # Retry candidates are in PENDING state after retry_step() (PHASE-IA).
        pending_steps = [s for s in workflow["steps"] if s["status"] == "PENDING"]
        active_steps = [s for s in workflow["steps"] if s["status"] == "ACTIVE"]
        
        if not pending_steps and not active_steps:
            # No steps can run - check if workflow is terminal or stuck
            non_terminal = [s for s in workflow["steps"] if s["status"] not in ("COMPLETED", "FAILED")]
            if not non_terminal:
                # All terminal - exit
                # Per PHASE VI AUTHORITY CONSOLIDATION: execution NEVER commits lifecycle directly
                workflow_id = workflow.get("id", "unknown_workflow")
                finalize_workflow_from_execution(workflow_id, workflow["steps"])
                trace.append({
                    "step_id": "workflow",
                    "event": f"workflow_{workflow['status'].lower()}"
                })
                # === CANONICAL PROJECTION: LIFECYCLE CHANGED → TERMINAL (Phase 4A.0) ===
                # === TERMINAL GUARD (PHASE-IIIA) ===
                # Verify authoritative state matches before emitting terminal projection.
                # If stop_workflow already wrote FAILED, do not overwrite with stale status.
                if _get_projection_manager is not None:
                    try:
                        _proj_mgr = _get_projection_manager()
                        _auth_status_t = (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("status")
                        if _auth_status_t == workflow["status"]:
                            _proj_mgr.emit_lifecycle_changed(workflow, workflow["status"])
                    except Exception:
                        pass
                break

            # Check if BLOCKED steps are permanently blocked
            blocked_steps = [s for s in workflow["steps"] if s["status"] == "BLOCKED"]

            permanently_blocked = []
            # Stale dependency guard: build steps map for actual status lookup
            _steps_map = {s.get("id"): s for s in workflow.get("steps", []) if s.get("id")}

            for step in blocked_steps:
                blocked_reason = step.get("blocked_reason", "")

                # Permanently blocked due to failed dependency
                if blocked_reason.startswith("dependency_failed"):
                    permanently_blocked.append(step)
                    continue

                # ISSUE-057: dependency_not_completed with terminal dependency state
                # (e.g. dependency_not_completed:step_3:FAILED) is also permanently blocked.
                # STALE GUARD: verify actual dependency status matches claimed status.
                if blocked_reason.startswith("dependency_not_completed"):
                    _parts = blocked_reason.split(":")
                    _dep_state = _parts[-1] if _parts else ""
                    if _dep_state in ("FAILED", "BLOCKED"):
                        _is_stale = False
                        if len(_parts) >= 3:
                            _dep_id = _parts[1]
                            _dep_step = _steps_map.get(_dep_id)
                            _actual_status = _dep_step.get("status") if _dep_step else None
                            if _actual_status != _dep_state:
                                _is_stale = True
                                print(f"[CHECK] Step {step.get('id')}: stale blocked_reason ({blocked_reason}), actual dep {_dep_id} status={_actual_status}")
                        if not _is_stale:
                            permanently_blocked.append(step)
                        continue

                # Permanently blocked due to exhausted retry/escalation
                if blocked_reason in (
                    "max_retries_exceeded",
                    "escalated",
                    "system_error"
                ):
                    permanently_blocked.append(step)

            if blocked_steps and len(permanently_blocked) == len(blocked_steps):
                print(
                    f"[CHECK] All BLOCKED steps permanently blocked "
                    f"({len(permanently_blocked)}), workflow remains BLOCKED"
                )

                workflow_id = workflow.get("id", "unknown_workflow")

                # BLOCKED is non-terminal per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1 §3.
                # Do NOT call finalize_workflow_from_execution — that would auto-FAILED.
                _update_workflow_state(workflow_id, "BLOCKED", "permanently_blocked", workflow_dict=workflow)

                try:
                    from system.orchestrator.workflow_control import _set_runtime_activity as _sra_perm_block
                    _sra_perm_block(workflow_id, "IDLE")
                except Exception:
                    pass

                # Emit non-terminal BLOCKED projection update.
                # BLOCKED is not in TERMINAL_WORKFLOW_STATES → projection_state = ACTIVE.
                if _get_projection_manager is not None:
                    try:
                        _proj_mgr = _get_projection_manager()
                        _proj_mgr.emit_lifecycle_changed(workflow, "BLOCKED")
                        print(
                            f"[PROJECTION] BLOCKED lifecycle emitted "
                            f"for workflow {workflow_id}"
                        )
                    except Exception as _proj_err:
                        print(
                            f"[PROJECTION:ERROR] BLOCKED lifecycle emission failed "
                            f"for workflow {workflow_id}: {_proj_err}"
                        )

                break

            else:
                print(
                    f"[CHECK] "
                    f"{len(blocked_steps) - len(permanently_blocked)} "
                    f"recoverable BLOCKED steps exist, continuing"
                )
        
        # === SAFETY: MAX ITERATIONS ===
        max_iterations = len(workflow["steps"]) * 5
        if loop_iteration >= max_iterations:
            print(f"[CHECK] Max iterations ({max_iterations}) reached")
            # Per PHASE VI AUTHORITY CONSOLIDATION: direct mirror mutation prohibited
            workflow_id = workflow.get("id", "unknown_workflow")
            workflow["error"] = "max_iterations_exceeded"
            _update_workflow_state(workflow_id, "BLOCKED", "max_iterations_exceeded", workflow_dict=workflow)  # Authoritative registry ONLY
            # Set runtime_activity to IDLE for BLOCKED convergence.
            try:
                from system.orchestrator.workflow_control import _set_runtime_activity as _sra_max_iter
                _sra_max_iter(workflow_id, "IDLE")
            except Exception:
                pass
            # Emit non-terminal BLOCKED projection for max-iterations exit.
            if _get_projection_manager is not None:
                try:
                    _proj_mgr = _get_projection_manager()
                    _proj_mgr.emit_lifecycle_changed(workflow, "BLOCKED")
                    print(f"[PROJECTION] BLOCKED lifecycle emitted for workflow {workflow_id} (max_iterations)")
                except Exception as _proj_err:
                    print(f"[PROJECTION:ERROR] BLOCKED lifecycle emission failed for workflow {workflow_id}: {_proj_err}")
            trace.append({
                "step_id": "workflow",
                "event": "workflow_blocked",
                "reason": "max_iterations_exceeded"
            })
            break
        
        # Continue loop for next iteration
        # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1 §EXECUTOR RULES:
        # Executors MUST NOT override runtime authority.
        # Removed: workflow["status"] = "ACTIVE" overwrite — executor MUST NOT overwrite externally-authoritative PAUSED state.
        # Removed: _update_workflow_state(... "ACTIVE" ...) overwrite — executor MUST NOT mutate registry back to ACTIVE.
        # Workflow remains ACTIVE in registry unless externally transitioned (e.g. pause_workflow).
        # === TERMINAL GUARD (PHASE-IIIA) ===
        # Per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1: stale persistence writes
        # MUST NOT overwrite terminal truth. If stop_workflow already terminalized
        # and cleaned persistence, do NOT re-create the file.
        _loop_wf_id = workflow.get("id", "unknown_workflow")
        _loop_auth = (_get_workflow_state(_loop_wf_id) or {}).get("status")
        if _loop_auth not in ("COMPLETED", "FAILED", "CANCELLED"):
            try:
                save_workflow(workflow)
            except Exception:
                pass

    # === LOOP EXIT DEBUG ===
    print(f"[LOOP EXIT] Loop ended at iteration {loop_iteration}")
    print(f"[LOOP EXIT] workflow_status: {workflow['status']}")
    print(f"[LOOP EXIT] step statuses: {[(s.get('id'), s.get('status')) for s in workflow.get('steps', [])]}")
    
    # === STALE OWNER EARLY RETURN ===
    # If this thread exited due to stale owner detection, do NOT make terminal
    # decisions or set registry BLOCKED. The current owner thread is responsible.
    if _stale_owner_exit:
        conflict_detector.unregister_workflow(workflow["id"])
        return {"status": "failure", "reason": "stale_owner_suppressed"}

    # === TERMINAL PERSISTENCE (PHASE-IIIA) ===
    # Per INCIDENT-098A: Terminal workflows MUST be persisted to their
    # appropriate terminal store before cleanup. Stale owner guard already
    # returned above if execution_generation changed. Do NOT save if
    # stop_workflow() already handled cleanup (reason == "user_stop").
    _postloop_auth = (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("status")
    _postloop_reason = (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("reason")
    if _postloop_auth in ("COMPLETED", "FAILED", "CANCELLED"):
        if _postloop_reason != "user_stop":
            save_workflow(workflow)
    # Guarantee output field exists
    if "output" not in workflow:
        workflow["output"] = None

    # === PAUSED EXIT GUARD ===
    # If the loop exited because the workflow was PAUSED, this thread MUST NOT
    # make terminal decisions. Non-COMPLETED steps are expected in a PAUSED workflow.
    # Terminal decisions (BLOCKED/FAILED registry writes, persistence deletion) are
    # only valid when the loop exits due to actual terminal convergence.
    # Without this guard, a PAUSED-exit thread deletes the persistence file, causing
    # the subsequent /resume to fail with invariant_failed:persistence_not_found.
    if _postloop_auth == "PAUSED":
        conflict_detector.unregister_workflow(workflow["id"])
        return {"status": "paused", "reason": "cooperative_pause"}

    # === POST-LOOP STALE OWNER RE-CHECK ===
    # Narrow race defense: if resume/mutation happened between loop exit and here,
    # generation will have changed. This thread must not make terminal decisions.
    try:
        from system.orchestrator.workflow_control import _workflow_state_registry
        _postloop_gen = _workflow_state_registry.get(workflow.get("id", "unknown_workflow"), {}).get("execution_generation", 1)
        if _loop_start_gen is not None and _postloop_gen != _loop_start_gen:
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": "stale_owner_suppressed"}
    except Exception:
        pass

    # === ISSUE-PDIAG-004: WORKFLOW OUTPUT AGGREGATION ===
    # Compute structured output aggregation from existing step truth.
    # Pure deterministic helper: no LLM calls, no tool execution, no lifecycle mutation.
    # Called before failure detection gates so failed workflows still preserve
    # partial successful outputs as inspection data.
    try:
        from system.orchestrator.workflow_output_aggregator import aggregate_workflow_output
        workflow["output_aggregation"] = aggregate_workflow_output(workflow)
    except Exception as _agg_err:
        print(f"[PDIAG-004:ERROR] Output aggregation failed for workflow {workflow.get('id', 'unknown')}: {_agg_err}")
        workflow["output_aggregation"] = None

    # FAILURE DETECTION GATE: Check for BLOCKED/FAILED steps BEFORE fallback
    # Prevents successful step result from masking later step failures
    # Per STATE_TRANSITIONS_CONTRACT_V1: only COMPLETED is the valid terminal-success step state.
    for step in workflow.get("steps", []):
        exec_res = step.get("execution_result")
        
        if step.get("status") == "BLOCKED":
            blocked_reason = step.get("blocked_reason", "")

            # Derive reason from step's execution_result, then step's blocked_reason,
            # then workflow-level error, then the FSM state name itself.
            # Per Phase 1B audit: hardcoded "escalated" fallback wrote a terminal block
            # reason into the registry even for recoverable dep-blocked or retry-exhausted
            # states. This caused valid BLOCKED workflows to be treated as terminal failures
            # on the next resume attempt. Reason must reflect the actual block cause.
            reason = (
                (exec_res.get("reason") if exec_res else None)
                or step.get("blocked_reason")
                or workflow.get("error")
                or "blocked"
            )
            print(f"[POST_LOOP_BLOCK] Step {step.get('id')} is BLOCKED with reason={reason}. Setting registry BLOCKED.")
            _update_workflow_state(workflow_id, "BLOCKED", reason, workflow_dict=workflow)  # Authoritative registry ONLY
            # ISSUE-057: set runtime_activity to IDLE for terminal convergence
            try:
                from system.orchestrator.workflow_control import _set_runtime_activity as _sra_post_loop_b
                _sra_post_loop_b(workflow_id, "IDLE")
            except Exception:
                pass
            # ISSUE-057: emit terminal projection for post-loop BLOCKED convergence
            if _get_projection_manager is not None:
                try:
                    _proj_mgr = _get_projection_manager()
                    _proj_mgr.emit_lifecycle_changed(workflow, "BLOCKED")
                    print(f"[PROJECTION] BLOCKED lifecycle emitted for workflow {workflow_id} (post_loop_blocked)")
                except Exception as _proj_err:
                    print(f"[PROJECTION:ERROR] BLOCKED lifecycle emission failed for workflow {workflow_id}: {_proj_err}")
            # Unregister workflow on blocked exit
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": reason}
        if step.get("status") not in ("COMPLETED",):
            # Only COMPLETED is the valid non-failure terminal step state.
            # FAILED, BLOCKED, PENDING, ACTIVE all indicate the workflow did not complete cleanly.
            workflow_id = workflow.get("id", "unknown_workflow")
            _update_workflow_state(workflow_id, "FAILED", "step_not_completed", workflow_dict=workflow)  # Authoritative registry ONLY
            # ISSUE-057: set runtime_activity to IDLE for terminal convergence
            try:
                from system.orchestrator.workflow_control import _set_runtime_activity as _sra_post_loop_s
                _sra_post_loop_s(workflow_id, "IDLE")
            except Exception:
                pass
            # ISSUE-057: emit terminal projection for post-loop FAILED convergence
            if _get_projection_manager is not None:
                try:
                    _proj_mgr = _get_projection_manager()
                    _proj_mgr.emit_lifecycle_changed(workflow, "FAILED")
                    print(f"[PROJECTION] FAILED lifecycle emitted for workflow {workflow_id} (post_loop_step_not_completed)")
                except Exception as _proj_err:
                    print(f"[PROJECTION:ERROR] FAILED lifecycle emission failed for workflow {workflow_id}: {_proj_err}")
            conflict_detector.unregister_workflow(workflow["id"])
            # Cleanup terminal from active dir — prevents stale resurrection on cold start.
            # ISSUE-057: Preserve FAILED persistence so projection endpoint can serve
            # the terminal FAILED projection to the focused UI.
            if workflow.get("status") != "FAILED":
                try:
                    from system.orchestrator.persistence import delete_workflow as _del_wf
                    _del_wf(workflow_id)
                except Exception:
                    pass
            return {"status": "failure", "reason": "step_failed"}
        # CRITICAL: Check execution_result even for COMPLETED steps
        # A step can complete but have a failed execution_result
        if exec_res and exec_res.get("status") == "failure":
            reason = exec_res.get("reason", "execution_failed")
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": reason}

    # FALLBACK: Only use SUCCESSFUL execution results from completed steps
    if workflow.get("output") is None:
        exec_res_fallback = None
        for s in reversed(workflow.get("steps", [])):
            # Only consider COMPLETED steps with successful execution
            if s.get("status") == "COMPLETED" and s.get("execution_result") is not None:
                exec_res = s.get("execution_result")
                if exec_res.get("status") == "success":
                    exec_res_fallback = exec_res
                    break
        if exec_res_fallback is not None:
            workflow["output"] = exec_res_fallback

    # FINAL VALIDATION GATE: Ensure all steps completed
    # Per STATE_TRANSITIONS_CONTRACT_V1: COMPLETED is the only valid terminal-success step state.
    for step in workflow.get("steps", []):
        if step.get("status") == "BLOCKED":
            # Same derivation as FAILURE DETECTION GATE above — reason must reflect
            # actual block cause, not hardcoded "escalated".
            _fvg_exec_res = step.get("execution_result")
            _fvg_reason = (
                (_fvg_exec_res.get("reason") if _fvg_exec_res else None)
                or step.get("blocked_reason")
                or workflow.get("error")
                or "blocked"
            )
            workflow_id = workflow.get("id", "unknown_workflow")
            _update_workflow_state(workflow_id, "BLOCKED", _fvg_reason, workflow_dict=workflow)  # Authoritative registry ONLY
            # Set runtime_activity to IDLE for BLOCKED convergence.
            try:
                from system.orchestrator.workflow_control import _set_runtime_activity as _sra_fvg_b
                _sra_fvg_b(workflow_id, "IDLE")
            except Exception:
                pass
            # Emit non-terminal BLOCKED projection for final validation gate.
            if _get_projection_manager is not None:
                try:
                    _proj_mgr = _get_projection_manager()
                    _proj_mgr.emit_lifecycle_changed(workflow, "BLOCKED")
                    print(f"[PROJECTION] BLOCKED lifecycle emitted for workflow {workflow_id} (final_validation_gate)")
                except Exception as _proj_err:
                    print(f"[PROJECTION:ERROR] BLOCKED lifecycle emission failed for workflow {workflow_id}: {_proj_err}")
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": _fvg_reason}
        if step.get("status") not in ("COMPLETED",):
            # Only COMPLETED is the valid terminal-success step state.
            workflow_id = workflow.get("id", "unknown_workflow")
            _update_workflow_state(workflow_id, "FAILED", "step_not_completed", workflow_dict=workflow)  # Authoritative registry ONLY
            # ISSUE-057: set runtime_activity to IDLE for terminal convergence
            try:
                from system.orchestrator.workflow_control import _set_runtime_activity as _sra_fvg_f
                _sra_fvg_f(workflow_id, "IDLE")
            except Exception:
                pass
            # ISSUE-057: emit terminal projection for final validation FAILED convergence
            if _get_projection_manager is not None:
                try:
                    _proj_mgr = _get_projection_manager()
                    _proj_mgr.emit_lifecycle_changed(workflow, "FAILED")
                    print(f"[PROJECTION] FAILED lifecycle emitted for workflow {workflow_id} (final_validation_gate)")
                except Exception as _proj_err:
                    print(f"[PROJECTION:ERROR] FAILED lifecycle emission failed for workflow {workflow_id}: {_proj_err}")
            conflict_detector.unregister_workflow(workflow["id"])
            # Cleanup terminal from active dir — prevents stale resurrection on cold start.
            # ISSUE-057: Preserve FAILED persistence so projection endpoint can serve
            # the terminal FAILED projection to the focused UI.
            if workflow.get("status") != "FAILED":
                try:
                    from system.orchestrator.persistence import delete_workflow as _del_wf
                    _del_wf(workflow_id)
                except Exception:
                    pass
            return {"status": "failure", "reason": "step_failed"}

    execution_result = workflow.get("output")

    # === CONFLICT DETECTOR UNREGISTRATION (Phase 1A) ===
    # Clean up workflow from active registry on completion
    conflict_detector.unregister_workflow(workflow["id"])

    # === CHECKPOINT CLEANUP (Phase 2C) ===
    # Delete checkpoint after workflow reaches terminal state.
    # Failure is silently ignored — MUST NOT affect execution.
    try:
        from system.orchestrator.checkpoint_manager import delete_checkpoint
        delete_checkpoint(workflow.get("id", "unknown_workflow"))
    except Exception:
        pass

    # === TRACE PERSISTENCE (Phase 2) ===
    # Save trace to disk for later retrieval via API
    # Failure is silently ignored — MUST NOT affect execution
    workflow_id = workflow.get("id", "unknown_workflow")
    try:
        import os
        import json
        trace_data = trace_collector.get_trace(workflow_id)
        if trace_data:
            # Create traces directory if it doesn't exist
            traces_dir = "traces"
            if not os.path.exists(traces_dir):
                os.makedirs(traces_dir)
            # Save trace to file
            trace_file = os.path.join(traces_dir, f"{workflow_id}.json")
            with open(trace_file, "w") as f:
                json.dump(trace_data, f, indent=2)
    except Exception:
        # Trace persistence failure must not affect execution
        pass

    # === PERSISTENCE CLEANUP (Phase 2D) ===
    # Per INCIDENT-098A: Only delete active file for COMPLETED (which is
    # persisted to workflows.json). FAILED and CANCELLED remain in active
    # persistence for recovery and projection serving.
    # ISSUE-057: Preserve FAILED persistence so projection endpoint can serve
    # the terminal FAILED projection to the focused UI.
    # Failure is silently ignored — MUST NOT affect execution.
    _terminal_status = workflow.get("status")
    if _terminal_status == "COMPLETED":
        try:
            from system.orchestrator.persistence import delete_workflow
            delete_workflow(workflow_id)
        except Exception:
            pass

    # === PHASE XII §3: PROJECTION STORE CLEANUP ===
    # Per PHASE XII: call remove_workflow() ONLY AFTER terminal convergence finalized.
    # Removes in-memory projection store for terminal workflows to prevent process-lifetime
    # accumulation. Terminal projection was already emitted and persisted store was already
    # cleaned by emit_lifecycle_changed(). This cleans the in-memory _stores dict only.
    # ISSUE-057: Preserve FAILED projection store so /projection/{workflow_id} can
    # continue serving the terminal FAILED projection.
    # Failure is silently ignored — MUST NOT affect execution.
    if _terminal_status in ("COMPLETED", "CANCELLED"):
        try:
            if _get_projection_manager is not None:
                _proj_mgr_cleanup = _get_projection_manager()
                _proj_mgr_cleanup.remove_workflow(workflow_id)
        except Exception:
            pass

    if execution_result is not None:
        if execution_result.get("status") == "failure":
            return {"status": "failure", "reason": execution_result.get("reason")}
        for step in workflow.get("steps", []):
            # Per STATE_TRANSITIONS_CONTRACT_V1: COMPLETED is the only valid terminal-success state.
            if step.get("status") not in ("COMPLETED",):
                return {"status": "failure", "reason": "step_failed"}
        # Return full workflow object with steps for projection layer
        return workflow
    else:
        return {"status": "failure", "reason": "No execution_result"}


def execute_from_input(user_input: str, bg_id: str = None, stream_registry: dict = None, stream_registry_lock = None, pre_generated_workflow_id: str = None) -> dict:
    """
    Entry point: user_input → planner → workflow → runtime execution.

    Per PHASE 1 REMEDIATION:
    - PERSISTENCE BEFORE RUNTIME
    - Stream registry entry created ONLY AFTER persistence exists
    - bg_id registration ONLY AFTER workflow_id is known and persistence exists

    Per ISSUE-055 PRE-REGISTRATION:
    - workflow_id may be pre-generated by caller (e.g., /execute/stream)
    - Pre-generated shell is persisted as QUEUED before planner runs
    - Planner preserves pre-generated workflow_id in returned workflow
    - On planner failure: shell transitions to FAILED (not deleted)
    - Lifecycle transitions: QUEUED → ACTIVATING → ACTIVE

    Args:
        user_input: The user's input string
        bg_id: Background task ID for streaming registry updates (optional)
        stream_registry: Registry for progressive streaming updates (optional)
        stream_registry_lock: Lock for thread-safe registry access (optional)
        pre_generated_workflow_id: Pre-generated workflow_id from pre-registration (optional)
    """
    # === PERF036: execute_from_input entry ===
    try:
        import time as _p036_rt_time, json as _p036_rt_json
        from datetime import datetime as _p036_rt_dt, timezone as _p036_rt_tz
        _p036_efi_start = _p036_rt_time.monotonic()
        print("PERF036_BACKEND " + _p036_rt_json.dumps({
            "label": "execute_from_input_entry",
            "source_layer": "orchestrator_runtime",
            "timestamp_iso": _p036_rt_dt.now(_p036_rt_tz.utc).isoformat(),
            "bg_id": bg_id,
            "pre_generated_workflow_id": pre_generated_workflow_id,
        }))
    except Exception:
        _p036_efi_start = None

    # === RUNTIME ACTIVITY: BOOTSTRAPPING ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # Immediately signal bootstrap entry. workflow_id unknown yet — set after registry entry.
    # This activity is set retroactively after registry entry in Step 6.5.
    _bootstrap_activity_pending = True

    # Step 0: Task classification (ADVISORY ONLY - does not influence execution)
    # === PERF036: classify_task in background (call #2) ===
    _p036_classify2_start = None
    try:
        _p036_classify2_start = _p036_rt_time.monotonic()
    except Exception:
        pass
    from system.orchestrator.task_classifier import classify_task
    classification = classify_task(user_input)
    try:
        if _p036_classify2_start is not None:
            print("PERF036_BACKEND " + _p036_rt_json.dumps({
                "label": "classify_task_background",
                "source_layer": "orchestrator_runtime",
                "timestamp_iso": _p036_rt_dt.now(_p036_rt_tz.utc).isoformat(),
                "bg_id": bg_id,
                "workflow_id": pre_generated_workflow_id,
                "duration_ms": round((_p036_rt_time.monotonic() - _p036_classify2_start) * 1000, 2),
                "call_site": "execute_from_input_background",
            }))
    except Exception:
        pass

    # Normalize classification to safe structure (ADVISORY ONLY - fail-safe)
    if not isinstance(classification, dict):
        classification = {}

    classification = {
        "classification": classification.get("classification"),
        "autonomy_level": classification.get("autonomy_level"),
        "approval_required": bool(classification.get("approval_required", False)),
        "reasoning": classification.get("reasoning"),
        "confidence": classification.get("confidence"),
    }

    # === CAPABILITY ROUTER (AGENT_CAPABILITY_ROUTING_CONTRACT_V1) ===
    # Pre-runtime deterministic capability routing. Advisory only.
    # Falls back to plan_workflow for unsupported, low-confidence, or mixed-domain prompts.
    _route_result = None
    try:
        from system.orchestrator.capability_router import route_capability
        _route_result = route_capability(user_input, classification)
    except Exception as _route_err:
        print(f"[CAPABILITY_ROUTE_ERROR] {str(_route_err)} — falling back to planner")
        # === AGENT-001C: Emit route error event ===
        try:
            from system.interface import event_emitter as _cap_err_emitter
            if _cap_err_emitter is not None and pre_generated_workflow_id:
                _cap_err_emitter.emit_capability_route_error(
                    workflow_id=pre_generated_workflow_id,
                    error=str(_route_err),
                    fallback_reason=f"route_exception:{str(_route_err)}",
                )
        except Exception:
            pass

    # === TOOL_PROFILE_GATING_CONTRACT_V1 §4: Profile selection ===
    # Capability router may RECOMMEND a profile; planner/compiler may CONFIRM or OVERRIDE.
    _selected_profile = None
    _recommended_profile = None
    _profile_reason_code = None
    try:
        from system.orchestrator.profile_selector import select_profile_with_reason, capability_to_profile
        if _route_result and _route_result.get("recommended_profile"):
            _recommended_profile = _route_result["recommended_profile"]
            _selected_profile = _recommended_profile
            _profile_reason_code = f"capability_recommended:{_route_result.get('capability_id', 'unknown')}"
        else:
            _profile_sel = select_profile_with_reason(user_input)
            _selected_profile = _profile_sel["profile_name"]
            _profile_reason_code = _profile_sel["profile_reason_code"]
    except Exception:
        _selected_profile = "GeneralFallbackProfile"
        _profile_reason_code = "profile_selection_error"

    # === AGENT-001C: Emit route attempted event ===
    if _route_result and pre_generated_workflow_id:
        try:
            from system.interface import event_emitter as _cap_attempt_emitter
            if _cap_attempt_emitter is not None:
                _cap_attempt_emitter.emit_capability_route_attempted(
                    workflow_id=pre_generated_workflow_id,
                    capability_id=_route_result.get("capability_id"),
                    route_confidence=_route_result.get("route_confidence", 0.0),
                    route_reason_code=_route_result.get("route_reason_code"),
                    user_input_preview=user_input,
                )
        except Exception:
            pass

    if _route_result and _route_result.get("route_decision") == "ROUTE_ACCEPTED":
        candidate_workflow = _route_result.get("candidate_workflow")
        if candidate_workflow:
            try:
                # Preserve pre-generated workflow identity for live attach / streaming continuity
                if pre_generated_workflow_id:
                    candidate_workflow["id"] = pre_generated_workflow_id
                # === AGENT-001B: Minimal planning events for capability route ===
                # Event emission belongs in orchestrator_runtime, not in planning_compiler.
                try:
                    from system.interface import event_emitter as _cap_event_emitter
                    if _cap_event_emitter is not None:
                        try:
                            _cap_event_emitter.emit_planning_started(
                                workflow_id=pre_generated_workflow_id,
                                attempt=0,
                                prompt_version="capability_v1",
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
                # Mandatory compiler handoff (PLANNING_COMPILER_CONTRACT_V1 Section 7)
                from system.orchestrator.planning_compiler import compile_candidate_workflow
                compiled_workflow = compile_candidate_workflow(
                    candidate_workflow,
                    user_input=user_input,
                )
                workflow_result = {"status": "success", "workflow": compiled_workflow}
                # === AGENT-001B: Planning completed event for capability route ===
                try:
                    from system.interface import event_emitter as _cap_event_emitter
                    if _cap_event_emitter is not None:
                        try:
                            _cap_event_emitter.emit_planning_completed(
                                workflow_id=pre_generated_workflow_id,
                                step_count=len(compiled_workflow.get("steps", [])),
                                prompt_version="capability_v1",
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
                # === AGENT-001C: Attach non-authoritative route metadata for debug/audit ===
                compiled_workflow["_capability_route_metadata"] = _route_result.get("route_metadata", {})
                compiled_workflow["_capability_route_metadata"]["route_decision"] = "ROUTE_ACCEPTED"
                compiled_workflow["_capability_route_metadata"]["capability_id"] = _route_result.get("capability_id")
                compiled_workflow["_capability_route_metadata"]["route_confidence"] = _route_result.get("route_confidence")
                compiled_workflow["_capability_route_metadata"]["route_reason_code"] = _route_result.get("route_reason_code")
                compiled_workflow["_capability_route_metadata"]["compiler_handoff_status"] = "completed"
                compiled_workflow["_capability_route_metadata"]["compiler_repairs_applied"] = "not_recorded"
                # === TOOL_PROFILE_GATING_CONTRACT_V1: Attach profile metadata ===
                compiled_workflow["profile_name"] = _selected_profile or "GeneralFallbackProfile"
                compiled_workflow["_profile_metadata"] = {
                    "selected_profile": _selected_profile,
                    "recommended_profile": _recommended_profile,
                    "profile_reason_code": _profile_reason_code,
                }
                # === F1: Plan IR metadata defaults (non-authoritative, internal-only) ===
                _cap_wf_id = compiled_workflow.get("id", pre_generated_workflow_id or "")
                compiled_workflow.setdefault("plan_id", _cap_wf_id)
                compiled_workflow.setdefault("plan_version", 1)
                compiled_workflow.setdefault("continuation_metadata", {})
                # === AGENT-001C: Emit route accepted event ===
                try:
                    from system.interface import event_emitter as _cap_accept_emitter
                    if _cap_accept_emitter is not None:
                        _cap_accept_emitter.emit_capability_route_accepted(
                            workflow_id=pre_generated_workflow_id,
                            capability_id=_route_result.get("capability_id"),
                            route_confidence=_route_result.get("route_confidence", 1.0),
                            route_reason_code=_route_result.get("route_reason_code"),
                            candidate_workflow_emitted=True,
                            compiler_handoff_status="completed",
                            compiler_repairs_applied="not_recorded",
                        )
                except Exception:
                    pass
            except Exception as _cap_compile_err:
                print(f"[CAPABILITY_COMPILE_ERROR] {str(_cap_compile_err)} — falling back to planner")
                # === AGENT-001C: Emit route error for compiler failure ===
                try:
                    from system.interface import event_emitter as _cap_compile_err_emitter
                    if _cap_compile_err_emitter is not None and pre_generated_workflow_id:
                        _cap_compile_err_emitter.emit_capability_route_error(
                            workflow_id=pre_generated_workflow_id,
                            capability_id=_route_result.get("capability_id"),
                            error=str(_cap_compile_err),
                            fallback_reason="compiler_handoff_failed",
                        )
                except Exception:
                    pass
                _route_result = None
        else:
            # Safety: accepted route without candidate workflow is an error — fall back
            _route_result = None

    # === RUNTIME ACTIVITY: PLANNING ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # Planning phase begins — no workflow_id yet, activity set retroactively in Step 6.5.
    _planning_activity_pending = True

    # Step 1: Create workflow via planner (classification is advisory signal only)
    # Fallback to planner when capability routing is not accepted or not available.
    # === AGENT-001C: Emit route fallback event before planner handoff ===
    if not (_route_result and _route_result.get("route_decision") == "ROUTE_ACCEPTED"):
        if _route_result and pre_generated_workflow_id:
            try:
                from system.interface import event_emitter as _cap_fallback_emitter
                if _cap_fallback_emitter is not None:
                    _cap_fallback_emitter.emit_capability_route_fallback(
                        workflow_id=pre_generated_workflow_id,
                        capability_id=_route_result.get("capability_id"),
                        route_confidence=_route_result.get("route_confidence", 0.0),
                        route_reason_code=_route_result.get("route_reason_code"),
                        fallback_reason=_route_result.get("fallback_reason"),
                    )
            except Exception:
                pass
        # === PERF036: plan_workflow bracket ===
        _p036_plan_call_start = None
        try:
            _p036_plan_call_start = _p036_rt_time.monotonic()
        except Exception:
            pass
        workflow_result = plan_workflow(user_input, classification=classification, pre_generated_workflow_id=pre_generated_workflow_id, profile_name=_selected_profile)
    try:
        if _p036_plan_call_start is not None:
            print("PERF036_BACKEND " + _p036_rt_json.dumps({
                "label": "plan_workflow_runtime_end",
                "source_layer": "orchestrator_runtime",
                "timestamp_iso": _p036_rt_dt.now(_p036_rt_tz.utc).isoformat(),
                "bg_id": bg_id,
                "workflow_id": pre_generated_workflow_id,
                "duration_ms": round((_p036_rt_time.monotonic() - _p036_plan_call_start) * 1000, 2),
                "plan_status": workflow_result.get("status"),
            }))
    except Exception:
        pass

    # === ISSUE-092B: Planner failure display messages ===
    _PLANNER_FAILURE_DISPLAY_MESSAGES = {
        "planner_empty_steps": "Planning failed because no executable workflow steps were produced.",
        "planner_parse_failure": "Planning failed because the planner response could not be parsed into a valid workflow.",
        "planner_invalid_format": "Planning failed because the planner returned an invalid workflow format.",
        "dependency_resolver_exception": "Planning failed while resolving workflow dependencies.",
        "planner_failed": "Planning failed before executable workflow steps could be created.",
    }

    # Step 2: Validate workflow creation
    if workflow_result.get("status") != "success":
        # === ISSUE-092B: Preserve specific planner failure reason ===
        # planner returns reasons like "planner_empty_steps", "planner_parse_failure", etc.
        _planner_reason = workflow_result.get("reason", "planner_failed")
        if pre_generated_workflow_id:
            # Pre-registered shell exists: transition to FAILED, do NOT delete
            _update_workflow_state(pre_generated_workflow_id, "FAILED", _planner_reason)
            # === ISSUE-055B Phase 1B: Update planning_request on planner failure ===
            try:
                from system.orchestrator.persistence import load_workflow as _load_wf_fail
                _fail_shell = _load_wf_fail(pre_generated_workflow_id)
                if _fail_shell and isinstance(_fail_shell.get("planning_request"), dict):
                    _fail_shell["planning_request"]["planning_status"] = "FAILED"
                    _fail_shell["planning_request"]["last_interruption_reason"] = _planner_reason
                    from system.orchestrator.persistence import save_workflow as _save_wf_fail
                    _save_wf_fail(_fail_shell)
                    print(f"[PLANNING_REQUEST:FAIL] Updated planning_status=FAILED for {pre_generated_workflow_id}")
            except Exception:
                pass
            # === ISSUE-092B: Enriched FAILED result for pre-step planner failure ===
            _fail_result = {
                "status": "FAILED",
                "reason": _planner_reason,
                "failure_reason": _planner_reason,
                "failure_display_message": _PLANNER_FAILURE_DISPLAY_MESSAGES.get(_planner_reason, _PLANNER_FAILURE_DISPLAY_MESSAGES["planner_failed"]),
                "workflow_id": pre_generated_workflow_id,
                "steps": [],
                "outputs": [],
                "workflow_output": None,
                "failed_step_id": None,
                "retry_target_step_id": None,
                "last_successful_step_id": None,
                "last_successful_output": None,
                "retry_eligible": False,
                "failed_recoverable": False,
                "retry_disabled_reason": "No failed step to retry — planning produced no valid steps",
            }
            if bg_id and stream_registry and stream_registry_lock:
                with stream_registry_lock:
                    if bg_id in stream_registry:
                        stream_registry[bg_id]["status"] = "FAILED"
                        stream_registry[bg_id]["error"] = _planner_reason
                        stream_registry[bg_id]["result"] = _fail_result
            try:
                from system.orchestrator.bg_id_map import deregister_bg_id as _dereg
                _dereg(bg_id)
            except Exception:
                pass
            return _fail_result
        else:
            _unregister_workflow_id()
            _rollback_partial_state("unknown", bg_id, stream_registry, stream_registry_lock, _planner_reason)
            return {"status": "failure", "reason": _planner_reason}

    # Step 3: Extract workflow
    workflow = workflow_result.get("workflow", {})
    workflow_id = workflow.get("id", "unknown_workflow")

    # Planner ID preservation guard: ensure pre-generated ID is respected
    if pre_generated_workflow_id and workflow_id != pre_generated_workflow_id:
        print(f"[WARN] Planner returned mismatched workflow_id: {workflow_id} vs {pre_generated_workflow_id}")
        workflow["id"] = pre_generated_workflow_id
        workflow_id = pre_generated_workflow_id

    # === AGENT-001C: Attach fallback route metadata to planner workflows (debug-only) ===
    if workflow and not workflow.get("_capability_route_metadata"):
        if _route_result:
            workflow["_capability_route_metadata"] = _route_result.get("route_metadata", {})
            workflow["_capability_route_metadata"]["route_decision"] = _route_result.get("route_decision", "ROUTE_FALLBACK_TO_PLANNER")
            workflow["_capability_route_metadata"]["fallback_reason"] = _route_result.get("fallback_reason")
        else:
            workflow["_capability_route_metadata"] = {
                "route_attempted": True,
                "route_decision": "ROUTE_FALLBACK_TO_PLANNER",
                "route_reason_code": "route_unavailable",
                "fallback_reason": "route_unavailable_or_error",
            }
    # === TOOL_PROFILE_GATING_CONTRACT_V1: Attach profile metadata to planner workflows ===
    if workflow and not workflow.get("_profile_metadata"):
        workflow["_profile_metadata"] = {
            "selected_profile": _selected_profile,
            "recommended_profile": _recommended_profile,
            "profile_reason_code": _profile_reason_code,
        }

    # === F1: Plan IR metadata defaults for planner-routed workflows (non-authoritative, internal-only) ===
    if workflow:
        workflow.setdefault("plan_id", workflow.get("id", workflow_id or ""))
        workflow.setdefault("plan_version", 1)
        workflow.setdefault("continuation_metadata", {})

    # === D1b: Step-scoped profile resolver for mixed-domain workflows ===
    # Deterministically assigns per-step profile metadata (_step_profile) to
    # individual steps in mixed-domain GeneralFallbackProfile workflows so AG1
    # receives a narrowed tool view per step. Does not modify depends_on,
    # purpose, expected_outcome, or any lifecycle/contract field.
    try:
        from system.orchestrator.step_profile_resolver import resolve_step_profiles_for_workflow
        workflow = resolve_step_profiles_for_workflow(workflow, user_input=user_input)
    except Exception as _d1b_err:
        print(f"[D1b_STEP_PROFILE_RESOLVER] Non-fatal error: {_d1b_err}")

    # Step 4: Validate workflow structure
    from system.orchestrator.workflow_validator import validate_workflow
    validation = validate_workflow(workflow)
    # === AGENT-001C: Record validator result in route metadata ===
    if workflow and workflow.get("_capability_route_metadata"):
        if validation.get("status") == "success":
            workflow["_capability_route_metadata"]["validator_result"] = "passed"
            workflow["_capability_route_metadata"]["validator_handoff_status"] = "completed"
        else:
            workflow["_capability_route_metadata"]["validator_result"] = f"failed:{validation.get('reason', 'unknown')}"
            workflow["_capability_route_metadata"]["validator_handoff_status"] = "failed"
    if validation.get("status") == "failure":
        if pre_generated_workflow_id:
            _update_workflow_state(pre_generated_workflow_id, "FAILED", f"validation_failed:{validation.get('reason')}")
            # === ISSUE-055B Phase 1B: Update planning_request on validation failure ===
            try:
                from system.orchestrator.persistence import load_workflow as _load_wf_val_fail
                _val_fail_shell = _load_wf_val_fail(pre_generated_workflow_id)
                if _val_fail_shell and isinstance(_val_fail_shell.get("planning_request"), dict):
                    _val_fail_shell["planning_request"]["planning_status"] = "FAILED"
                    _val_fail_shell["planning_request"]["last_interruption_reason"] = f"validation_failed:{validation.get('reason')}"
                    from system.orchestrator.persistence import save_workflow as _save_wf_val_fail
                    _save_wf_val_fail(_val_fail_shell)
                    print(f"[PLANNING_REQUEST:FAIL] Updated planning_status=FAILED for {pre_generated_workflow_id} (validation)")
            except Exception:
                pass
            if bg_id and stream_registry and stream_registry_lock:
                with stream_registry_lock:
                    if bg_id in stream_registry:
                        stream_registry[bg_id]["status"] = "FAILED"
                        stream_registry[bg_id]["error"] = f"validation_failed:{validation.get('reason')}"
            try:
                from system.orchestrator.bg_id_map import deregister_bg_id as _dereg
                _dereg(bg_id)
            except Exception:
                pass
            return {"status": "failure", "reason": f"workflow_validation_failed:{validation.get('reason')}", "workflow_id": pre_generated_workflow_id}
        else:
            _unregister_workflow_id()
            _rollback_partial_state(workflow_id, bg_id, stream_registry, stream_registry_lock, f"validation_failed:{validation.get('reason')}")
            return {"status": "failure", "reason": f"workflow_validation_failed:{validation.get('reason')}"}

    # === Sprint 9D-3: planning validation passed telemetry ===
    if _event_emitter is not None:
        try:
            _event_emitter.emit_planning_validation_passed(
                workflow_id=workflow_id,
                warning_count=validation.get("warning_count") if isinstance(validation, dict) else None,
            )
        except Exception:
            pass

    print(f"[LIFECYCLE] PLANNED workflow {workflow_id}")

    # === ISSUE-055B Phase 1B: Preserve planning_request across planner success overwrite ===
    # Per PLANNING_RECOVERY_AND_REPLAN_CONTRACT_V1:
    #   Planning Request ≠ Workflow Identity ≠ Planning Execution
    # save_workflow() serializes the entire workflow dict, which would drop planning_request
    # if the planner output does not include it. Load the pre-registered shell and merge.
    if pre_generated_workflow_id and "planning_request" not in workflow:
        try:
            from system.orchestrator.persistence import load_workflow as _load_wf_merge
            _old_shell = _load_wf_merge(pre_generated_workflow_id)
            if _old_shell and isinstance(_old_shell.get("planning_request"), dict):
                workflow["planning_request"] = _old_shell["planning_request"]
                print(f"[PLANNING_REQUEST:PRESERVE] Merged planning_request into planned workflow {workflow_id}")
        except Exception:
            pass

    # === AGENT-001C: Record runtime handoff status in route metadata ===
    if workflow and workflow.get("_capability_route_metadata"):
        workflow["_capability_route_metadata"]["runtime_handoff_status"] = "completed"

    # Step 5: Save workflow to persistence — overwrites pre-registered shell with real workflow.
    from system.orchestrator.persistence import save_workflow
    # === PERF036: save_workflow timing ===
    _p036_save_start = None
    try:
        _p036_save_start = _p036_rt_time.monotonic()
    except Exception:
        pass
    try:
        save_workflow(workflow)
        print(f"[LIFECYCLE] PERSISTED workflow {workflow_id}")
        try:
            if _p036_save_start is not None:
                print("PERF036_BACKEND " + _p036_rt_json.dumps({
                    "label": "save_workflow_end",
                    "source_layer": "orchestrator_runtime",
                    "timestamp_iso": _p036_rt_dt.now(_p036_rt_tz.utc).isoformat(),
                    "bg_id": bg_id,
                    "workflow_id": workflow_id,
                    "duration_ms": round((_p036_rt_time.monotonic() - _p036_save_start) * 1000, 2),
                }))
        except Exception:
            pass
    except Exception as e:
        _unregister_workflow_id()
        print(f"[PERSISTENCE:FAIL] Failed to persist workflow {workflow_id}: {e}")
        _rollback_partial_state(workflow_id, bg_id, stream_registry, stream_registry_lock, f"persistence_failed:{str(e)}")
        return {"status": "failure", "reason": f"persistence_failed:{str(e)}"}

    # Step 6: Verify persistence file exists (HARD GUARD before any runtime state)
    from system.orchestrator.persistence import workflow_persistence_exists as _wpe
    if not _wpe(workflow_id):
        _unregister_workflow_id()
        print(f"[INVARIANT:FAIL] Persistence check failed for {workflow_id}: file not found after save")
        return {"status": "failure", "reason": "invariant_failed:persistence_not_found"}

    # Step 6.4: PROMOTE AUTHORITATIVE LIFECYCLE TO ACTIVATING
    # Per ISSUE-055: two-step transition QUEUED → ACTIVATING → ACTIVE
    _update_workflow_state(
        workflow_id,
        "ACTIVATING",
        "execution_bootstrap",
        workflow_dict=workflow,
    )
    print(f"[LIFECYCLE] PROMOTED workflow {workflow_id} to ACTIVATING")

    # Step 6.5: PROMOTE AUTHORITATIVE LIFECYCLE TO ACTIVE
    _update_workflow_state(
        workflow_id,
        "ACTIVE",
        "execution_bootstrap",
        workflow_dict=workflow,
    )
    print(f"[LIFECYCLE] PROMOTED workflow {workflow_id} to ACTIVE")

    # === RUNTIME ACTIVITY: BOOTSTRAPPING (retroactive — registry entry now exists) ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # workflow_id now known and registry entry exists — set BOOTSTRAPPING now.
    from system.orchestrator.workflow_control import _set_runtime_activity as _sra_boot
    try:
        _sra_boot(workflow_id, "BOOTSTRAPPING")
        # Mirror to stream registry for global frontend observability (projection cache)
        if bg_id and stream_registry and stream_registry_lock:
            with stream_registry_lock:
                if bg_id in stream_registry:
                    stream_registry[bg_id]["runtime_activity"] = "BOOTSTRAPPING"
    except Exception:
        pass

    # Step 7: INTERNAL BOOTSTRAP (no external lifecycle state change)
    # Per PHASE VI: ACTIVATING MUST NOT enter public registry or API responses.
    # Registry is now ACTIVE from Step 6.5 throughout bootstrap.
    print(f"[LIFECYCLE] BOOTSTRAP workflow {workflow_id}")

    # === RUNTIME ACTIVITY: PLANNING (retroactive — bootstrap complete, planning occurred) ===
    try:
        _sra_boot(workflow_id, "PLANNING")
        if bg_id and stream_registry and stream_registry_lock:
            with stream_registry_lock:
                if bg_id in stream_registry:
                    stream_registry[bg_id]["runtime_activity"] = "PLANNING"
    except Exception:
        pass

    # Step 8: Register bg_id mapping
    if bg_id and stream_registry and stream_registry_lock:
        try:
            from system.orchestrator.bg_id_map import register_bg_id as _register_bg_id_ext
            _register_bg_id_ext(bg_id, workflow_id)
            print(f"[ACTIVATION:VALIDATED] bg_id {bg_id} mapped to workflow {workflow_id}")
        except Exception as e:
            print(f"[ACTIVATION:FAILED] bg_id registration failed for {bg_id}: {e}")
            _rollback_partial_state(workflow_id, bg_id, stream_registry, stream_registry_lock, f"bg_id_failed:{str(e)}")
            return {"status": "failure", "reason": f"bg_id_registration_failed:{str(e)}"}

    # === RUNTIME ACTIVITY: REGISTERING ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # Workflow is being registered into stream/projection infrastructure.
    try:
        _sra_boot(workflow_id, "REGISTERING")
        if bg_id and stream_registry and stream_registry_lock:
            with stream_registry_lock:
                if bg_id in stream_registry:
                    stream_registry[bg_id]["runtime_activity"] = "REGISTERING"
    except Exception:
        pass

    # Step 9: Update stream entry from authoritative registry ONLY.
    # Per PHASE VI §5: Stream registry may ONLY consume _get_workflow_state().
    if bg_id and stream_registry and stream_registry_lock:
        try:
            _stream_auth_status = (_get_workflow_state(workflow_id) or {}).get("status", "UNKNOWN")
            with stream_registry_lock:
                if bg_id in stream_registry:
                    stream_registry[bg_id]["orchestrator_workflow_id"] = workflow_id
                    stream_registry[bg_id]["workflow"] = workflow
                    stream_registry[bg_id]["status"] = _stream_auth_status
                    stream_registry[bg_id]["error"] = None
                else:
                    stream_registry[bg_id] = {
                        "orchestrator_workflow_id": workflow_id,
                        "workflow": workflow,
                        "result": None,
                        "status": _stream_auth_status,
                        "error": None,
                    }
            print(f"[ACTIVATION:VALIDATED] Stream entry updated: bg_id={bg_id} workflow={workflow_id} status={_stream_auth_status}")
        except Exception as e:
            print(f"[ACTIVATION:FAILED] Stream registry update failed: {e}")
            _rollback_partial_state(workflow_id, bg_id, stream_registry, stream_registry_lock, f"stream_registry_failed:{str(e)}")
            return {"status": "failure", "reason": f"stream_registry_failed:{str(e)}"}

    from system.orchestrator.persistence import workflow_persistence_exists as _wpe_trace

    # Step 11: Bootstrap complete — registry remains ACTIVE.
    print(f"[LIFECYCLE] ACTIVE workflow {workflow_id}")

    # Publish workflow_id to thread registry after persistence exists
    _register_workflow_id(workflow_id)

    # Store classification in workflow for observability (advisory only, no control impact)
    workflow["classification"] = classification

    # Step 3.0: Observational validation of planner output (read-only, no control flow)
    planner_steps = workflow.get("steps", [])
    planner_validation = validate_planner_output(planner_steps)
    if not planner_validation.get("valid", True):
        print("[PLANNER_VALIDATOR_OBSERVATION] issues detected:", planner_validation.get("issues", []))

    # Step 3.1: Constraint extraction REMOVED (Phase B)
    # Runtime does NOT use LLM for constraint extraction
    # Constraints must be explicitly provided in workflow or step
    constraints = workflow.get("constraints", [])

    # Step 3.2: Soft structural guard — detect and split collapsed multi-objective steps
    # Advisory structural correction only — does not affect governance or system_entry
    workflow = enforce_atomic_steps(workflow)

    # Step 3.5: Normalize planner output to executable format
    # Planner creates advisory workflows; runtime needs executable workflows
    if "name" not in workflow:
        workflow["name"] = workflow.get("goal", "auto_workflow")[:50]
    # Per PHASE VI: workflow['status'] is serialization mirror ONLY.
    # Do NOT initialize mirror here — save_workflow injects from registry.

    # Normalize steps to have STEP_SCHEMA_CONTRACT_V1 required fields
    for step in workflow.get("steps", []):
        if "type" not in step:
            step["type"] = "EXECUTE_API"
        # tool_call set by agent at execution time — runtime does NOT modify
        if "expected_outcome" not in step:
            step["expected_outcome"] = "Execution completed"
        if "risk" not in step:
            step["risk"] = "LOW"
        if "importance" not in step:
            step["importance"] = "MEDIUM"
        if "resource_targets" not in step:
            step["resource_targets"] = []
        if "status" not in step:
            from system.orchestrator.workflow_control import request_step_transition as _rst_rt
            _rst_rt(step, "PENDING", "schema_initialization", validate=False)
        if "retries" not in step:
            step["retries"] = 0
        if "max_retries" not in step:
            step["max_retries"] = 2
        if "input" not in step:
            step["input"] = step.get("purpose", user_input)

    # Step 4: Execute via runtime (preserves all existing logic)
    # === PHASE XII §4: THREAD OWNERSHIP HARDENING ===
    # Wrap execution in try/finally to ensure _unregister_workflow_id() always executes,
    # even if run_workflow() or downstream code raises an unhandled exception.
    # This prevents _thread_workflow_registry leak on exception paths.
    # === PERF036: run_workflow call start ===
    _p036_run_start = None
    try:
        _p036_run_start = _p036_rt_time.monotonic()
        print("PERF036_BACKEND " + _p036_rt_json.dumps({
            "label": "run_workflow_call_start",
            "source_layer": "orchestrator_runtime",
            "timestamp_iso": _p036_rt_dt.now(_p036_rt_tz.utc).isoformat(),
            "bg_id": bg_id,
            "workflow_id": workflow_id,
            "step_count": len(workflow.get("steps", [])),
            "efi_total_so_far_ms": round((_p036_rt_time.monotonic() - _p036_efi_start) * 1000, 2) if _p036_efi_start else None,
        }))
    except Exception:
        pass
    try:
        result = run_workflow(workflow, bg_id, stream_registry=stream_registry, stream_registry_lock=stream_registry_lock)

        # === PERF036: run_workflow call end ===
        try:
            if _p036_run_start is not None:
                print("PERF036_BACKEND " + _p036_rt_json.dumps({
                    "label": "run_workflow_call_end",
                    "source_layer": "orchestrator_runtime",
                    "timestamp_iso": _p036_rt_dt.now(_p036_rt_tz.utc).isoformat(),
                    "bg_id": bg_id,
                    "workflow_id": workflow_id,
                    "duration_ms": round((_p036_rt_time.monotonic() - _p036_run_start) * 1000, 2),
                    "result_status": result.get("status") if isinstance(result, dict) else "unknown",
                    "efi_total_ms": round((_p036_rt_time.monotonic() - _p036_efi_start) * 1000, 2) if _p036_efi_start else None,
                }))
        except Exception:
            pass

        if result and result.get("status") == "failure":
            # run_workflow detected a failure - preserve it, include workflow_id
            return {"status": "failure", "reason": result.get("reason", "workflow_failed"), "workflow_id": workflow.get("id", "unknown_workflow")}

        governance_output = governance.resolve_decision(
            validator_output={},
            execution_result=result.get("output"),
            context={"last_step": None}
        )

        # Preserve original result if governance returns None
        if governance_output is not None:
            result["output"] = governance_output

        # Return full workflow object with steps for projection layer
        return result
    finally:
        _unregister_workflow_id()

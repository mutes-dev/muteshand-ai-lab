import json
import os
import shlex
import threading
import time

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
    # === RESURRECTION INSTRUMENTATION (Point 3) ===
    print(f"[RESURRECTION_INSTRUMENTATION] run_workflow entry:")
    print(f"  workflow.status: {workflow.get('status')}")
    print(f"  all step statuses: {[(s.get('id'), s.get('status')) for s in workflow.get('steps', [])]}")
    _wf_id = workflow.get("id", "unknown_workflow")
    _reg_state = _get_workflow_state(_wf_id)
    print(f"  registry state: {_reg_state}")

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
        # === RESURRECTION INSTRUMENTATION (Point 7a) ===
        print("[RESURRECTION_INSTRUMENTATION] Early return: PAUSED guard triggered")
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
    # Normalize: ACTIVE (interrupted) → PENDING for re-evaluation.
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
                        # ACTIVE (interrupted) → FAILED for safety
                        _rst(step, "FAILED", "persistence_restore_interrupted", validate=False)
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
            # === RESURRECTION INSTRUMENTATION (Point 7b) ===
            print("[RESURRECTION_INSTRUMENTATION] Loop break: max_steps_exceeded")
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
            # === RESURRECTION INSTRUMENTATION (Point 7c) ===
            print("[RESURRECTION_INSTRUMENTATION] Early return: PAUSED user control check")
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
                from system.orchestrator.user_approval import request_approval
                step_id = step.get("id", "unknown")

                # TRACE: APPROVAL_REQUIRED
                try:
                    trace_collector.record_transition(
                        step_id=step_id,
                        previous_status="BLOCKED",
                        new_status="BLOCKED",
                        reason="APPROVAL_REQUIRED"
                    )
                except Exception:
                    pass

                approved = request_approval(step)

                if approved:
                    # BLOCKED → ACTIVE (per STATE_TRANSITIONS_CONTRACT_V1)
                    from system.orchestrator.workflow_control import request_step_transition as _rst_approval
                    _rst_approval(step, "ACTIVE", "approval_granted", _internal=True)
                    step.pop("blocked_reason", None)
                    step["_approval_resumed"] = True
                    # TRACE: APPROVAL_GRANTED
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

        # === EXECUTION SCHEDULING (EXECUTION_SCHEDULING_CONTRACT_V1) ===
        # Build step_states map for scheduler
        step_states = {s.get("id"): s.get("status", "PENDING") for s in workflow.get("steps", [])}

        # === RESURRECTION INSTRUMENTATION (Point 4) ===
        print(f"[RESURRECTION_INSTRUMENTATION] Before create_execution_group:")
        print(f"  candidate step ids: {list(step_states.keys())}")
        print(f"  candidate statuses: {step_states}")

        # Form NEXT execution group (scheduler derives groups dynamically)
        group = create_execution_group(
            workflow=workflow,
            step_states=step_states,
            conflict_detector=conflict_detector,
            workflow_id=workflow.get("id", "unknown_workflow")
        )

        if group is None:
            print("[SCHEDULER] No execution group formed - no pending steps or previous group incomplete")
            # === RESURRECTION INSTRUMENTATION (Point 7) ===
            print("[RESURRECTION_INSTRUMENTATION] Early return: group is None")
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

        # === RESURRECTION INSTRUMENTATION (Point 6) ===
        print(f"[RESURRECTION_INSTRUMENTATION] After create_execution_group:")
        print(f"  execution_group contents: {group}")

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

            for step in blocked_steps:
                blocked_reason = step.get("blocked_reason", "")

                # Permanently blocked due to failed dependency
                if blocked_reason.startswith("dependency_failed"):
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
                    f"({len(permanently_blocked)}), terminalizing to FAILED"
                )

                workflow_id = workflow.get("id", "unknown_workflow")

                _final_status = finalize_workflow_from_execution(
                    workflow_id,
                    workflow["steps"]
                )

                # CRITICAL: FAILED lifecycle convergence requires projection emission visibility.
                # Silent suppression creates permanent ACTIVE projection divergence.
                if _get_projection_manager is not None:
                    try:
                        _proj_mgr = _get_projection_manager()

                        if _final_status == "FAILED":
                            _proj_mgr.emit_lifecycle_changed(
                                workflow,
                                "FAILED"
                            )

                            print(
                                f"[PROJECTION] FAILED lifecycle emitted "
                                f"for workflow {workflow_id}"
                            )

                    except Exception as _proj_err:
                        print(
                            f"[PROJECTION:ERROR] FAILED lifecycle emission failed "
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

    # === TERMINAL GUARD (PHASE-IIIA) ===
    # Post-loop save: only persist if this thread still owns terminal authority.
    # If stop_workflow already terminalized, it handled persistence cleanup.
    _postloop_auth = (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("status")
    if _postloop_auth not in ("COMPLETED", "FAILED", "CANCELLED"):
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

    # FAILURE DETECTION GATE: Check for BLOCKED/FAILED steps BEFORE fallback
    # Prevents successful step result from masking later step failures
    # Per STATE_TRANSITIONS_CONTRACT_V1: only COMPLETED is the valid terminal-success step state.
    for step in workflow.get("steps", []):
        exec_res = step.get("execution_result")
        
        if step.get("status") == "BLOCKED":
            blocked_reason = step.get("blocked_reason", "")

            # Permanent BLOCKED states must converge to FAILED
            if (
                blocked_reason.startswith("dependency_failed")
                or blocked_reason in (
                    "max_retries_exceeded",
                    "escalated"
                )
            ):
                _update_workflow_state(
                    workflow_id,
                    "FAILED",
                    blocked_reason,
                    workflow_dict=workflow
                )

                conflict_detector.unregister_workflow(workflow["id"])

                return {
                    "status": "failure",
                    "reason": blocked_reason
                }

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
            # Unregister workflow on blocked exit
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": reason}
        if step.get("status") not in ("COMPLETED",):
            # Only COMPLETED is the valid non-failure terminal step state.
            # FAILED, BLOCKED, PENDING, ACTIVE all indicate the workflow did not complete cleanly.
            workflow_id = workflow.get("id", "unknown_workflow")
            _update_workflow_state(workflow_id, "FAILED", "step_not_completed", workflow_dict=workflow)  # Authoritative registry ONLY
            conflict_detector.unregister_workflow(workflow["id"])
            # Cleanup FAILED from active dir — prevents stale resurrection on cold start
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
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": _fvg_reason}
        if step.get("status") not in ("COMPLETED",):
            # Only COMPLETED is the valid terminal-success step state.
            workflow_id = workflow.get("id", "unknown_workflow")
            _update_workflow_state(workflow_id, "FAILED", "step_not_completed", workflow_dict=workflow)  # Authoritative registry ONLY
            conflict_detector.unregister_workflow(workflow["id"])
            # Cleanup FAILED from active dir — prevents stale resurrection on cold start
            try:
                from system.orchestrator.persistence import delete_workflow as _del_wf
                _del_wf(workflow_id)
            except Exception:
                pass
            return {"status": "failure", "reason": "step_failed"}

    execution_result = workflow.get("output")
    print("[TRACE] final workflow output before return:", workflow.get("output"))

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
    # Delete active workflow file after workflow reaches terminal state.
    # Covers COMPLETED, FAILED, and CANCELLED — all terminal and must not persist in
    # ACTIVE_WORKFLOW_DIR, which would cause stale resurrection on cold start.
    # Failure is silently ignored — MUST NOT affect execution.
    _terminal_status = workflow.get("status")
    if _terminal_status in ("COMPLETED", "FAILED", "CANCELLED"):
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
    # Failure is silently ignored — MUST NOT affect execution.
    if _terminal_status in ("COMPLETED", "FAILED", "CANCELLED"):
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


def execute_from_input(user_input: str, bg_id: str = None, stream_registry: dict = None, stream_registry_lock = None) -> dict:
    """
    Entry point: user_input → planner → workflow → runtime execution.

    Per PHASE 1 REMEDIATION:
    - PERSISTENCE BEFORE RUNTIME
    - NO placeholder workflow IDs
    - NO placeholder stream registry entries
    - Stream registry entry created ONLY AFTER persistence exists
    - bg_id registration ONLY AFTER workflow_id is known and persistence exists

    New required ordering:
    1. plan_workflow()
    2. validate_workflow_structure()
    3. save_workflow()
    4. verify persistence exists
    5. update authoritative registry ACTIVE
    6. register bg_id
    7. create stream registry entry
    8. create projection store
    9. spawn execution thread
    10. expose to frontend

    Args:
        user_input: The user's input string
        bg_id: Background task ID for streaming registry updates (optional)
        stream_registry: Registry for progressive streaming updates (optional)
        stream_registry_lock: Lock for thread-safe registry access (optional)
    """
    # === RUNTIME ACTIVITY: BOOTSTRAPPING ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # Immediately signal bootstrap entry. workflow_id unknown yet — set after registry entry.
    # This activity is set retroactively after registry entry in Step 6.5.
    _bootstrap_activity_pending = True

    # Step 0: Task classification (ADVISORY ONLY - does not influence execution)
    from system.orchestrator.task_classifier import classify_task
    classification = classify_task(user_input)

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

    # === RUNTIME ACTIVITY: PLANNING ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # Planning phase begins — no workflow_id yet, activity set retroactively in Step 6.5.
    _planning_activity_pending = True

    # Step 1: Create workflow via planner (classification is advisory signal only)
    workflow_result = plan_workflow(user_input, classification=classification)

    # Step 2: Validate workflow creation
    if workflow_result.get("status") != "success":
        _unregister_workflow_id()
        _rollback_partial_state("unknown", bg_id, stream_registry, stream_registry_lock, "planner_failed")
        return {"status": "failure", "reason": "planner_failed"}

    # Step 3: Extract workflow
    workflow = workflow_result.get("workflow", {})
    workflow_id = workflow.get("id", "unknown_workflow")

    # Step 4: Validate workflow structure
    from system.orchestrator.workflow_validator import validate_workflow
    validation = validate_workflow(workflow)
    if validation.get("status") == "failure":
        _unregister_workflow_id()
        _rollback_partial_state(workflow_id, bg_id, stream_registry, stream_registry_lock, f"validation_failed:{validation.get('reason')}")
        return {"status": "failure", "reason": f"workflow_validation_failed:{validation.get('reason')}"}

    print(f"[LIFECYCLE] PLANNED workflow {workflow_id}")

    # Step 5: Save workflow to persistence — file is written before any runtime state exists.
    # Per PHASE VI: save_workflow injects authoritative lifecycle from registry.
    # Registry ACTIVE was already set at Step 7 below (reordered bootstrap).
    from system.orchestrator.persistence import save_workflow
    try:
        save_workflow(workflow)
        print(f"[LIFECYCLE] PERSISTED workflow {workflow_id}")
    except Exception as e:
        _unregister_workflow_id()
        print(f"[PERSISTENCE:FAIL] Failed to persist workflow {workflow_id}: {e}")
        _rollback_partial_state(workflow_id, bg_id, stream_registry, stream_registry_lock, f"persistence_failed:{str(e)}")
        return {"status": "failure", "reason": f"persistence_failed:{str(e)}"}

    # Step 6: Verify persistence file exists (HARD GUARD before any runtime state)
    # Fast O(1) check — full structural validation only happens at startup.
    from system.orchestrator.persistence import workflow_persistence_exists as _wpe
    if not _wpe(workflow_id):
        _unregister_workflow_id()
        print(f"[INVARIANT:FAIL] Persistence check failed for {workflow_id}: file not found after save")
        return {"status": "failure", "reason": "invariant_failed:persistence_not_found"}

    # Step 6.5: PROMOTE AUTHORITATIVE LIFECYCLE TO ACTIVE
    # Per LIFECYCLE_AUTHORITY_CONTRACT_V1 §2:
    # Workflow lifecycle MUST be committed before execution begins.
    #
    # Per lifecycle continuity invariants:
    # ACTIVE step execution REQUIRES authoritative workflow ACTIVE state.
    #
    # This promotion was previously missing, causing:
    # - ACTIVE execution
    # - ACTIVE projections
    # - QUEUED authoritative registry
    # - invalid QUEUED→PAUSED transitions
    #
    # This is a lifecycle continuity correction, NOT a redesign.
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

    # === PHASE XV-B TRACE LOGGING ===
    from system.orchestrator.persistence import _active_workflow_path, workflow_persistence_exists as _wpe_trace
    print("[WF_CREATE]")
    print(f"  workflow_id={workflow_id}")
    print(f"  bg_id={bg_id}")
    print(f"  persisted=true")
    print(f"  path={_active_workflow_path(workflow_id)}")
    print("[WF_ACTIVE]")
    print(f"  workflow_id={workflow_id}")
    print(f"  registry_status={(_get_workflow_state(workflow_id) or {}).get('status', 'UNKNOWN')}")
    print(f"  persistence_exists={_wpe_trace(workflow_id)}")

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
    try:
        result = run_workflow(workflow, bg_id, stream_registry=stream_registry, stream_registry_lock=stream_registry_lock)

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

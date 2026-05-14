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
from system.orchestrator.workflow_control import _update_workflow_state, _get_workflow_state, _update_runtime_registry_only


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
            if hasattr(_pm, "evict_workflow"):
                _pm.evict_workflow(workflow_id)
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
    new_step["status"] = new_step.get("status", "PENDING")
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
            step["status"] = "PENDING"
        if "retries" not in step:
            step["retries"] = 0
        if "max_retries" not in step:
            step["max_retries"] = 3

    # Initialize workflow status if not set
    # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Runtime registry is sole authority
    # Per DUAL-READ STRATEGY: workflow["status"] becomes compatibility mirror
    if "status" not in workflow:
        workflow_id = workflow.get("id", "unknown_workflow")
        workflow["status"] = "ACTIVE"  # Compatibility mirror
        _update_workflow_state(workflow_id, "ACTIVE", "initialization")  # Authoritative registry

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
            # No registry entry exists — initialize from the current workflow status.
            # workflow["status"] at this point has been set by the ACTIVE initialization
            # path above (line ~247), so it reflects the intended start state.
            _update_runtime_registry_only(_wf_id_init, workflow["status"], "run_workflow_init")
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
        workflow["status"] = "FAILED"  # Compatibility mirror
        _update_workflow_state(workflow_id, "FAILED", validation["reason"])  # Authoritative registry
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
                    if _ps_status == "COMPLETED":
                        step["status"] = "COMPLETED"
                        step["execution_result"] = _ps.get("execution_result")
                        step["retries"] = _ps.get("retries", 0)
                    elif _ps_status == "FAILED":
                        step["status"] = "FAILED"
                        step["retries"] = _ps.get("retries", 0)
                    elif _ps_status == "BLOCKED":
                        _blocked_reason = _ps.get("blocked_reason", "")
                        # === EXECUTION RECOVERY NORMALIZATION (Phase 1B) ===
                        # Per STATE_TRANSITIONS_CONTRACT_V1 §RECOVERY RULES:
                        # "execution continues from last step" — stale BLOCKED state
                        # must not prevent re-evaluation on resume re-entry.
                        #
                        # Sub-case 1: dependency-blocked step.
                        # Restore as PENDING so the scheduler pre-flight re-evaluates
                        # deps against the CURRENT live step states (not a stale
                        # blocked_reason snapshot). The dependency may now be satisfied.
                        #
                        # Sub-case 2: escalation/retry-exhausted step.
                        # Restore as BLOCKED but reset retries to 0 so the step gets
                        # a fresh retry budget. Without this, governance immediately
                        # re-escalates (retries >= max_retries) on the first attempt,
                        # re-blocking the workflow before execution can recover.
                        _DEP_BLOCK_PREFIX = "dependency_not_completed"
                        _ESCALATION_REASONS = {
                            "max_retries_exceeded", "escalated", "system_error"
                        }
                        if _blocked_reason.startswith(_DEP_BLOCK_PREFIX):
                            # Dep-blocked: restore as PENDING for fresh dep evaluation
                            step["status"] = "PENDING"
                            step.pop("blocked_reason", None)
                            step["retries"] = _ps.get("retries", 0)
                            print(f"[PERSISTENCE] Step {_sid}: dep-BLOCKED → PENDING (dep re-eval on resume)")
                        elif _blocked_reason in _ESCALATION_REASONS:
                            # Escalation-blocked: restore as BLOCKED but reset retry budget
                            step["status"] = "BLOCKED"
                            step["blocked_reason"] = _blocked_reason
                            step["retries"] = 0  # Fresh budget — avoids immediate re-escalation
                            print(f"[PERSISTENCE] Step {_sid}: escalation-BLOCKED restored, retries reset to 0")
                        else:
                            # Unknown/approval-blocked: restore as-is
                            step["status"] = "BLOCKED"
                            step["retries"] = _ps.get("retries", 0)
                            if _blocked_reason:
                                step["blocked_reason"] = _blocked_reason
                    elif _ps_status == "ACTIVE":
                        # ACTIVE (interrupted) → FAILED for safety (was interrupted mid-execution)
                        step["status"] = "FAILED"
                        step["retries"] = _ps.get("retries", 0)
                        step.pop("_retry_pending", None)  # Clear transient retry flag — must not survive restore
                    elif _ps_status == "RETRY":
                        # RETRY → PENDING for resurrection restore path.
                        # In resurrection (new run_workflow thread, no prior executor ownership),
                        # ACTIVE is a zombie state: scheduler ACTIVE-exclusion correctly rejects
                        # it, downstream dep checks correctly fail on ACTIVE dependency, no group
                        # forms, workflow deadlocks ACTIVE/BLOCKED.
                        # PENDING allows scheduler to reclaim and dispatch normally:
                        #   PENDING → ACTIVE (scheduler dispatch) → COMPLETED
                        # The escalation in-thread retry path (parallel_executor →
                        # escalation_controller.handle_retry) sets ACTIVE directly on the live
                        # step dict and never reaches PERSISTENCE RESTORE, so it is unaffected.
                        step["status"] = "PENDING"
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
    # Override is passed to governance via governance_fn parameter
    # Loop continues while workflow not in terminal state (COMPLETED/FAILED)
    from system.orchestrator.user_control import get_override
    from system.orchestrator.step_executor import execute_step
    from system.orchestrator.step_chainer import propagate_result

    # Capture override state for governance decisions
    override_state = get_override()

    # Governance wrapper to inject override_state into decisions
    def governance_with_override(validator_output, execution_result, step, context, memory_confidence=None):
        return governance.decide_next_action(
            validator_output=validator_output,
            execution_result=execution_result,
            step=step,
            context=context,
            memory_confidence=memory_confidence,
            override_state=override_state
        )

    # === LOOP CONDITION (Phase 4A.1) ===
    # Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED is an exit condition
    # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1 §EXECUTOR RULES:
    # Executors MUST check authoritative runtime state only.
    # workflow["status"] is stale in-memory object; authoritative truth is _workflow_state_registry.
    while (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("status", workflow["status"]) not in ("COMPLETED", "BLOCKED", "FAILED", "PAUSED"):
        loop_iteration += 1
        print(f"[LOOP TOP] Iteration {loop_iteration}, workflow_status: {workflow['status']}")
        if len(workflow.get("steps", [])) > MAX_STEPS_PER_WORKFLOW:
            # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Runtime registry is sole authority
            workflow_id = workflow.get("id", "unknown_workflow")
            workflow["status"] = "BLOCKED"  # Compatibility mirror
            workflow["error"] = "max_steps_exceeded"
            _update_workflow_state(workflow_id, "BLOCKED", "max_steps_exceeded")  # Authoritative registry
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
                    step["status"] = "ACTIVE"
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
            break

        # === RESURRECTION INSTRUMENTATION (Point 6) ===
        print(f"[RESURRECTION_INSTRUMENTATION] After create_execution_group:")
        print(f"  execution_group contents: {group}")

        print(f"[SCHEDULER] Group formed: {group['group_id']} type={group['group_type']} steps={group['steps']}")

        # === GROUP-BASED EXECUTION ===
        group_type = group.get("group_type", "SEQUENTIAL")

        if group_type == "PARALLEL" and len(group.get("steps", [])) > 1:
            # === PARALLEL GROUP EXECUTION ===
            group_results = execute_parallel_group(
                group=group,
                workflow=workflow,
                execute_step_fn=execute_step,
                governance_fn=governance_with_override,
                propagate_fn=propagate_result,
                escalation_handler=escalation_controller,
                debug_verbose=DEBUG_VERBOSE,
                override_state=override_state
            )
        else:
            # === SEQUENTIAL GROUP EXECUTION ===
            group_results = execute_sequential_group(
                group=group,
                workflow=workflow,
                execute_step_fn=execute_step,
                governance_fn=governance_with_override,
                propagate_fn=propagate_result,
                escalation_handler=escalation_controller,
                debug_verbose=DEBUG_VERBOSE,
                override_state=override_state,
                post_step_callback=None
            )

            # === POST-GROUP STATE UPDATE ===
            for result in group_results:
                step_id = result.get("step_id")
                step_status = result.get("status")
                exec_res = result.get("execution_result")

            trace.append({
                "step_id": step_id,
                "event": f"step_{step_status.lower()}" if step_status else "step_unknown",
                "status": step_status,
                "retries": step.get("retries", 0)
            })

            # === OUTPUT CONTRACT: Update workflow output on completion ===
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
                if _get_projection_manager is not None:
                    try:
                        _proj_mgr = _get_projection_manager()
                        _cur_lifecycle = (_get_workflow_state(workflow.get("id", "unknown_workflow")) or {}).get("status", workflow.get("status", "ACTIVE"))
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
            # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Runtime registry is sole authority
            workflow_id = workflow.get("id", "unknown_workflow")
            workflow["status"] = "COMPLETED"  # Compatibility mirror
            _update_workflow_state(workflow_id, "COMPLETED", "all_steps_completed")  # Authoritative registry
            trace.append({
                "step_id": "workflow",
                "event": "workflow_completed"
            })
            # === CANONICAL PROJECTION: LIFECYCLE CHANGED → COMPLETED (Phase 4A.0) ===
            if _get_projection_manager is not None:
                try:
                    _proj_mgr = _get_projection_manager()
                    _proj_mgr.emit_lifecycle_changed(workflow, "COMPLETED")
                except Exception:
                    pass
            break
        
        # If no executable steps remain (no pending, no retry, no active), check if stuck
        pending_steps = [s for s in workflow["steps"] if s["status"] == "PENDING"]
        retry_steps = [s for s in workflow["steps"] if s["status"] == "RETRY"]
        active_steps = [s for s in workflow["steps"] if s["status"] == "ACTIVE"]
        
        if not pending_steps and not retry_steps and not active_steps:
            # No steps can run - check if workflow is terminal or stuck
            non_terminal = [s for s in workflow["steps"] if s["status"] not in ("COMPLETED", "FAILED")]
            if not non_terminal:
                # All terminal - exit
                # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Runtime registry is sole authority
                workflow_id = workflow.get("id", "unknown_workflow")
                if any(s["status"] == "FAILED" for s in workflow["steps"]):
                    workflow["status"] = "FAILED"  # Compatibility mirror
                    _update_workflow_state(workflow_id, "FAILED", "step_failure")  # Authoritative registry
                else:
                    workflow["status"] = "COMPLETED"  # Compatibility mirror
                    _update_workflow_state(workflow_id, "COMPLETED", "all_terminal_success")  # Authoritative registry
                trace.append({
                    "step_id": "workflow",
                    "event": f"workflow_{workflow['status'].lower()}"
                })
                # === CANONICAL PROJECTION: LIFECYCLE CHANGED → TERMINAL (Phase 4A.0) ===
                if _get_projection_manager is not None:
                    try:
                        _proj_mgr = _get_projection_manager()
                        _proj_mgr.emit_lifecycle_changed(workflow, workflow["status"])
                    except Exception:
                        pass
                break
            # BLOCKED steps exist - continue for re-evaluation
            print(f"[CHECK] BLOCKED steps exist, continuing for dependency re-evaluation")
        
        # === SAFETY: MAX ITERATIONS ===
        max_iterations = len(workflow["steps"]) * 5
        if loop_iteration >= max_iterations:
            print(f"[CHECK] Max iterations ({max_iterations}) reached")
            # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Runtime registry is sole authority
            workflow_id = workflow.get("id", "unknown_workflow")
            workflow["status"] = "BLOCKED"  # Compatibility mirror
            workflow["error"] = "max_iterations_exceeded"
            _update_workflow_state(workflow_id, "BLOCKED", "max_iterations_exceeded")  # Authoritative registry
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
        try:
            save_workflow(workflow)
        except Exception:
            pass

    # === LOOP EXIT DEBUG ===
    print(f"[LOOP EXIT] Loop ended at iteration {loop_iteration}")
    print(f"[LOOP EXIT] workflow_status: {workflow['status']}")
    print(f"[LOOP EXIT] step statuses: {[(s.get('id'), s.get('status')) for s in workflow.get('steps', [])]}")
    
    save_workflow(workflow)
    # Guarantee output field exists
    if "output" not in workflow:
        workflow["output"] = None

    # FAILURE DETECTION GATE: Check for BLOCKED/FAILED steps BEFORE fallback
    # Prevents successful step result from masking later step failures
    # RETRY is a valid non-terminal state - do not treat as failure
    for step in workflow.get("steps", []):
        exec_res = step.get("execution_result")
        
        if step.get("status") == "BLOCKED":
            # Derive reason from step's execution_result, then step's blocked_reason,
            # then workflow-level error, then the FSM state name itself.
            # Per Phase 1B audit: hardcoded "escalated" fallback wrote a terminal block
            # reason into the registry even for recoverable dep-blocked or retry-exhausted
            # steps, causing resume_workflow()'s _TERMINAL_BLOCK_REASONS guard to fire
            # on the next resume attempt. Reason must reflect the actual block cause.
            reason = (
                (exec_res.get("reason") if exec_res else None)
                or step.get("blocked_reason")
                or workflow.get("error")
                or "blocked"
            )
            workflow_id = workflow.get("id", "unknown_workflow")
            workflow["status"] = "BLOCKED"  # Compatibility mirror
            _update_workflow_state(workflow_id, "BLOCKED", reason)  # Authoritative registry
            # Unregister workflow on blocked exit
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": reason}
        if step.get("status") not in ("COMPLETED", "RETRY"):
            # Only COMPLETED and RETRY are non-terminal states that don't cause workflow failure
            # FAILED, BLOCKED, PENDING, ACTIVE are terminal or require further processing
            workflow_id = workflow.get("id", "unknown_workflow")
            workflow["status"] = "FAILED"  # Compatibility mirror
            _update_workflow_state(workflow_id, "FAILED", "step_not_completed")  # Authoritative registry
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

    # FINAL VALIDATION GATE: Ensure all steps completed or escalated
    # RETRY is a valid non-terminal state - do not treat as failure
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
            workflow["status"] = "BLOCKED"  # Compatibility mirror
            _update_workflow_state(workflow_id, "BLOCKED", _fvg_reason)  # Authoritative registry
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": _fvg_reason}
        if step.get("status") not in ("COMPLETED", "RETRY"):
            # Only COMPLETED and RETRY are non-terminal states that don't cause workflow failure
            workflow_id = workflow.get("id", "unknown_workflow")
            workflow["status"] = "FAILED"  # Compatibility mirror
            _update_workflow_state(workflow_id, "FAILED", "step_not_completed")  # Authoritative registry
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
    # Covers COMPLETED and FAILED — both are terminal and must not persist in
    # ACTIVE_WORKFLOW_DIR, which would cause stale resurrection on cold start.
    # Failure is silently ignored — MUST NOT affect execution.
    _terminal_status = workflow.get("status")
    if _terminal_status in ("COMPLETED", "FAILED"):
        try:
            from system.orchestrator.persistence import delete_workflow
            delete_workflow(workflow_id)
        except Exception:
            pass

    if execution_result is not None:
        if execution_result.get("status") == "failure":
            return {"status": "failure", "reason": execution_result.get("reason")}
        for step in workflow.get("steps", []):
            # RETRY is a valid non-terminal state - do not treat as failure
            if step.get("status") not in ("COMPLETED", "RETRY"):
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
    # Workflow status is pre-set to ACTIVE so persistence layer writes to active_workflows/.
    # Runtime registry is NOT yet ACTIVE — that happens at Step 11 after bootstrap.
    workflow["status"] = "ACTIVE"
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

    # Step 7: LIFECYCLE: QUEUED → ACTIVATING
    # Runtime infrastructure (bg_id, stream registry, projection) created during ACTIVATING.
    # ACTIVATING is a legal transient bootstrap state. Bootstrap failure → ACTIVATING → FAILED.
    print(f"[LIFECYCLE] ACTIVATING workflow {workflow_id}")
    _update_workflow_state(workflow_id, "ACTIVATING", "bootstrap_start")

    # Step 8: Register bg_id mapping (ACTIVATING phase — partial materialization allowed)
    if bg_id and stream_registry and stream_registry_lock:
        try:
            from system.orchestrator.bg_id_map import register_bg_id as _register_bg_id_ext
            _register_bg_id_ext(bg_id, workflow_id)
            print(f"[ACTIVATION:VALIDATED] bg_id {bg_id} mapped to workflow {workflow_id}")
        except Exception as e:
            print(f"[ACTIVATION:FAILED] bg_id registration failed for {bg_id}: {e}")
            _rollback_partial_state(workflow_id, bg_id, stream_registry, stream_registry_lock, f"bg_id_failed:{str(e)}")
            return {"status": "failure", "reason": f"bg_id_registration_failed:{str(e)}"}

    # Step 9: Update PENDING stream entry in-place with workflow_id + ACTIVE status.
    # The PENDING entry was created in execute_stream() before thread spawn.
    # Update it — do NOT replace the dict (dict replacement loses the PENDING entry reference).
    # Stream schema: {orchestrator_workflow_id, workflow, result, status, error}
    # Frontend-visible statuses only: PENDING, ACTIVE, COMPLETED, FAILED.
    if bg_id and stream_registry and stream_registry_lock:
        try:
            with stream_registry_lock:
                if bg_id in stream_registry:
                    stream_registry[bg_id]["orchestrator_workflow_id"] = workflow_id
                    stream_registry[bg_id]["workflow"] = workflow
                    stream_registry[bg_id]["status"] = "ACTIVE"
                    stream_registry[bg_id]["error"] = None
                else:
                    stream_registry[bg_id] = {
                        "orchestrator_workflow_id": workflow_id,
                        "workflow": workflow,
                        "result": None,
                        "status": "ACTIVE",
                        "error": None,
                    }
            print(f"[ACTIVATION:VALIDATED] Stream entry updated: bg_id={bg_id} workflow={workflow_id} status=ACTIVE")
        except Exception as e:
            print(f"[ACTIVATION:FAILED] Stream registry update failed: {e}")
            _rollback_partial_state(workflow_id, bg_id, stream_registry, stream_registry_lock, f"stream_registry_failed:{str(e)}")
            return {"status": "failure", "reason": f"stream_registry_failed:{str(e)}"}

    # Step 11: LIFECYCLE: ACTIVATING → ACTIVE (bootstrap complete)
    # All runtime infrastructure exists. Execution thread may now spawn.
    print(f"[LIFECYCLE] ACTIVE workflow {workflow_id}")
    _update_workflow_state(workflow_id, "ACTIVE", "bootstrap_complete")

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
    if "status" not in workflow:
        # Per PHASE 1 REMEDIATION: status already set to ACTIVE in authoritative registry at Step 7
        # This is only the compatibility mirror in the workflow dict
        workflow["status"] = "ACTIVE"

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
            step["status"] = "PENDING"
        if "retries" not in step:
            step["retries"] = 0
        if "max_retries" not in step:
            step["max_retries"] = 2
        if "input" not in step:
            step["input"] = step.get("purpose", user_input)

    # Step 4: Execute via runtime (preserves all existing logic)
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

    _unregister_workflow_id()
    # Return full workflow object with steps for projection layer
    return result

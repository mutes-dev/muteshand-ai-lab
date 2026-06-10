"""
AI LAB GUI — FastAPI Backend

Architecture contract:
- Thin API layer ONLY — zero decision logic
- All execution flows through orchestrator_runtime.execute_from_input
- All control flows through user_control and background_manager
- All approval flows through user_approval
- MUST NOT call main.py
- MUST NOT modify orchestrator or alter workflow
"""

import os
import sys

# Resolve project root (2 levels up from backend/)
# ROOT = directory that contains the "system/" folder
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Set working directory so all relative paths inside the system resolve correctly
os.chdir(ROOT)

# Ensure package imports work from any launch location
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, Optional
import asyncio
import json
import threading
import time as _perf_time
import uuid as _uuid_mod
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

# === ISSUE-063: Backend Identity Guard ===
# Generate backend instance identity at module load (startup time)
_BACKEND_INSTANCE_ID = _uuid_mod.uuid4().hex
_BACKEND_STARTED_AT = datetime.now(timezone.utc).isoformat()
_BACKEND_PID = os.getpid()
_BACKEND_PROJECT_ROOT = ROOT

# === ADMIN/TEST ENDPOINT GATE (ISSUE-097) ===
# Admin/test endpoints are blocked by default and require explicit env enablement.
# Optionally gated by a local admin token. Does NOT affect normal endpoints.
_ADMIN_TEST_ENABLED = os.getenv("MH_ENABLE_ADMIN_TEST_ENDPOINTS", "").lower() in {"1", "true", "yes", "on"}
_ADMIN_TEST_TOKEN = os.getenv("MH_ADMIN_TEST_TOKEN", "")


def _require_admin_test_enabled(request: Request):
    """
    FastAPI dependency-style guard for /admin/test/* endpoints.

    Blocks by default unless MH_ENABLE_ADMIN_TEST_ENDPOINTS is set to a truthy value.
    If MH_ADMIN_TEST_TOKEN is set, requires X-MH-Admin-Token header to match.
    """
    if not _ADMIN_TEST_ENABLED:
        raise HTTPException(status_code=403, detail="Admin test endpoints are disabled.")
    if _ADMIN_TEST_TOKEN:
        provided = request.headers.get("X-MH-Admin-Token", "")
        if provided != _ADMIN_TEST_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid admin test token.")


# === SYSTEM IMPORTS (verified real contracts) ===
from system.orchestrator.orchestrator_runtime import execute_from_input, get_workflow_id_for_thread, run_workflow
from system.orchestrator.task_classifier import classify_task as _classify_task
from system.orchestrator.user_control import (
    get_control_state,
)
from system.orchestrator.workflow_control import (
    pause_workflow,
    resume_workflow,
    get_plan,
    edit_step,
    add_step as add_plan_step,
    remove_step as remove_plan_step,
    reorder_steps,
    retry_step,
    stop_workflow,
    cancel_workflow,
    _get_workflow_state,
    _update_workflow_state,
    warm_registry_from_disk,
    validate_runtime_activation,
)
from system.orchestrator.persistence import (
    workflow_persistence_exists as _wf_persistence_exists,
    load_active_workflows,
    load_workflow,
    save_workflow as _save_workflow,
    get_retention_state,
    set_retention_state,
)
from system.orchestrator.bootstrap import initialize_system
from system.runtime.background_manager import BackgroundManager

# === ISSUE-094B: LLM Budget / Router Observability ===
try:
    from system.llm import budget as _llm_budget
except Exception:
    _llm_budget = None

# === ISSUE-077: MEMORY STORAGE PRIMITIVES (Sprint 6) ===
# Per MEMORY_STORAGE_CONTRACT_V1: Memory is advisory-only, local-first, non-authoritative.
# FAILURE-ISOLATED: Import failure must not affect other API functionality.
try:
    from system.memory import memory_store as _memory_store
    from system.memory.schema import (
        validate_scope as _validate_memory_scope,
        validate_category as _validate_memory_category,
        validate_confidence as _validate_memory_confidence,
        validate_key as _validate_memory_key,
        validate_source as _validate_memory_source,
        MemoryValidationError as _MemoryValidationError,
        SCOPE_GLOBAL as _MEMORY_SCOPE_GLOBAL,
        SCOPE_PROJECT as _MEMORY_SCOPE_PROJECT,
    )
except Exception:
    _memory_store = None
    _validate_memory_scope = None
    _validate_memory_category = None
    _validate_memory_confidence = None
    _validate_memory_key = None
    _validate_memory_source = None
    _MemoryValidationError = ValueError
    _MEMORY_SCOPE_GLOBAL = "GLOBAL"
    _MEMORY_SCOPE_PROJECT = "PROJECT"

# === ISSUE-078: TRACE COLLECTOR FOR MEMORY OBSERVABILITY ===
# FAILURE-ISOLATED: Import failure must not affect other API functionality.
try:
    from system.orchestrator import trace_collector as _trace_collector
except Exception:
    _trace_collector = None


def _record_memory_trace(event: str, key: Optional[str] = None, data: Optional[dict] = None) -> None:
    """
    Emit a memory trace event if trace_collector is available.
    Trace failure MUST NOT block the caller.
    """
    if _trace_collector is None:
        return
    try:
        _trace_collector.record_memory_event(
            event=event,
            key=key,
            data=data,
        )
    except Exception:
        pass

# === CANONICAL PROJECTION TRANSPORT (Phase 4A.0) ===
# Per CANONICAL_PROJECTION_MODEL_V1: API is transport-only — does NOT own projection truth
# Per ORCHESTRATOR_CONTRACT_V2: API transports projections generated by Orchestrator Runtime
# FAILURE-ISOLATED: Import failure must not affect other API functionality
try:
    from system.orchestrator.projection_manager import get_projection_manager as _get_proj_mgr
    from system.orchestrator.projection_schema import validate_projection_identity
except Exception:
    _get_proj_mgr = None
    validate_projection_identity = None

# === BG_ID CONTINUITY PERSISTENCE (Phase 3F-XA) ===
# Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1 §RESUME RULES:
# Resume MUST reuse same projection identity (bg_id) to maintain continuity.
# bg_id_map persists bg_id → orchestrator_workflow_id mapping across restarts.
# FAILURE-ISOLATED: Import failure must not affect other API functionality.
try:
    from system.orchestrator.bg_id_map import (
        register_bg_id as _register_bg_id,
        deregister_bg_id as _deregister_bg_id,
        load_all as _load_bg_id_map,
    )
except Exception:
    _register_bg_id = None
    _deregister_bg_id = None
    _load_bg_id_map = None

# === PLAN MUTATION MANAGER (Phase 4B.1) ===
# Per CANONICAL_PROJECTION_MODEL_V1 §7: API routes mutation intents only
# API MUST NOT own mutation authority
# FAILURE-ISOLATED: Import failure must not affect other API functionality
try:
    from system.orchestrator.plan_mutation_manager import request_plan_mutation as _request_plan_mutation
    from system.orchestrator.mutation_validation import ALLOWED_MUTATION_TYPES as _ALLOWED_MUTATION_TYPES
except Exception:
    _request_plan_mutation = None
    _ALLOWED_MUTATION_TYPES = frozenset()

# ── module-level singletons ──────────────────────────────────────────────────
_bg_manager = BackgroundManager()
_executor = ThreadPoolExecutor(max_workers=4)

# ── Approval Registry (contract-safe, keyed by approval_id) ──────────────────
# Per USER_APPROVAL_CONTRACT_V1: approval identity is backend-owned.
# Legacy _pending_approvals replaced by user_approval._approval_registry.
from system.orchestrator.user_approval import (
    get_pending_approvals_for_workflow,
    get_approval,
    resolve_approval,
    ApprovalStatus,
    cleanup_stale_approvals,
)

# ── User Control Registry (contract-safe, keyed by control_id) ─────────────────
# Per USER_CONTROL_CONTRACT_V2: user-control identity is backend-owned.
# Distinct from approval; override/force-execution semantics.
from system.orchestrator.user_control import (
    get_pending_user_controls_for_workflow,
    get_user_control_request,
    resolve_user_control_request,
    UserControlStatus,
    cleanup_expired_user_controls,
    create_user_control_request,
)

# ── Notification Manager (contract-safe) ───────────────────────────────────
from system.interface.notification_manager import (
    get_notifications,
    mark_notification_read,
    dismiss_notification,
    get_unread_count,
    NotificationType,
    NotificationSeverity,
    NotificationStatus,
)


# ── PROJECTION LAYER (Contract-Compliant Data Model) ──────────────────────
# Per GUI_ARCHITECTURE.txt: outputs should be separate from steps
# Per PLAN_STEP_CONTRACT_V1: plan steps MUST NOT include tool_call
def project_workflow_for_gui(workflow: dict) -> dict:
    """
    Project workflow data to contract-compliant GUI model.
    
    Transforms internal workflow representation (with execution_result and tool_call
    attached to steps) into external GUI representation (steps without execution fields,
    outputs in separate structure).
    
    Args:
        workflow: Internal workflow dict with steps containing execution_result and tool_call
        
    Returns:
        Contract-compliant dict with:
        - steps: Plan step fields only (no execution_result, no tool_call)
        - outputs: Separate array of execution results
        - workflow_output: Top-level workflow output
    """
    if not workflow or not isinstance(workflow, dict):
        return workflow
    
    # Extract outputs and clean steps
    outputs = []
    cleaned_steps = []
    
    for step in workflow.get("steps", []):
        if not isinstance(step, dict):
            cleaned_steps.append(step)
            continue
        
        # Extract execution_result if present
        execution_result = step.get("execution_result")
        if execution_result:
            outputs.append({
                "step_id": step.get("id"),
                "execution_result": execution_result
            })
        
        # Clean step - remove execution-only fields
        cleaned_step = {
            "id": step.get("id"),
            "type": step.get("type"),
            "purpose": step.get("purpose"),
            "expected_outcome": step.get("expected_outcome"),
            "risk": step.get("risk"),
            "importance": step.get("importance"),
            "depends_on": step.get("depends_on"),
            "resource_targets": step.get("resource_targets"),
            "status": step.get("status"),
            "retries": step.get("retries", 0),
            # === ISSUE-073: AG1 attribution metadata — read-only observability only ===
            "agent_metadata": step.get("_agent_metadata") or None,
        }
        
        # === SEMANTIC GATE (Phase 4G-A.9): blocked_reason is ONLY valid on BLOCKED steps ===
        # Per DEPENDENCY_MODEL_CONTRACT_V1: blocked_reason must not appear on non-BLOCKED steps.
        if step.get("status") == "BLOCKED" and step.get("blocked_reason"):
            cleaned_step["blocked_reason"] = step["blocked_reason"]
        
        cleaned_steps.append(cleaned_step)
    
    # Return contract-compliant structure
    return {
        "steps": cleaned_steps,
        "outputs": outputs,
        "workflow_output": workflow.get("output")
    }


def project_step_for_approval(step: dict) -> dict:
    """
    Project step data for approval panel.
    
    Removes execution-only fields (tool_call, execution_result) while keeping
    plan step fields needed for approval decision.
    
    Args:
        step: Internal step dict
        
    Returns:
        Contract-compliant step dict without execution fields
    """
    if not step or not isinstance(step, dict):
        return step
    
    return {
        "id": step.get("id"),
        "type": step.get("type"),
        "purpose": step.get("purpose"),
        "expected_outcome": step.get("expected_outcome"),
        "risk": step.get("risk"),
        "importance": step.get("importance"),
        "status": step.get("status")
    }

app = FastAPI(title="AI Lab GUI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _evict_workflow_state(workflow_id: str, bg_id: str = None, reason: str = "") -> None:
    """
    Single authoritative cleanup path — replaces _evict_orphaned_runtime_state
    and _cleanup_partial_execution_state.

    Called from:
      - startup eviction (invalid/quarantined workflows)
      - stream_active / stream_workflow_id (no persistence found)
      - execution failure rollback

    Responsibilities (all idempotent):
      1. Remove bg_id entry from _stream_registry
      2. Remove bg_id → workflow_id mapping from bg_id_map persistence
      3. Evict workflow projection from projection store
      4. Mark runtime registry as FAILED

    Failure MUST NOT affect startup or other workflows.
    """
    print(f"[EVICT] workflow={workflow_id} bg={bg_id} reason={reason}")

    # 1. Remove from in-memory stream registry
    if bg_id:
        try:
            with _stream_registry_lock:
                _stream_registry.pop(bg_id, None)
        except Exception:
            pass

    # 2. Deregister from bg_id_map persistence
    if bg_id:
        try:
            if _deregister_bg_id is not None:
                _deregister_bg_id(bg_id)
        except Exception:
            pass

    # 3. Evict projection store entry
    if workflow_id:
        try:
            if _get_proj_mgr is not None:
                _pm = _get_proj_mgr()
                _pm.remove_workflow(workflow_id)
        except Exception:
            pass

    # 4. Mark registry FAILED — do NOT touch persistence
    if workflow_id:
        try:
            from system.orchestrator.workflow_control import _update_runtime_registry_only as _urro_evict
            _urro_evict(workflow_id, "FAILED", f"evicted:{reason}")
        except Exception:
            pass


@app.on_event("startup")
def on_startup():
    """
    Per PHASE 1 REMEDIATION:
    - PERSISTENCE-DRIVEN RECOVERY ONLY
    - Runtime metadata is DERIVED, never authoritative
    - NO resurrection from stream registry or bg_id_map
    - Persistence files are the ONLY resurrection authority

    New startup ordering:
    Phase A: load_active_workflows() — ONLY resurrection authority
    Phase B: validate persisted workflows
    Phase C: resurrect eligible workflows
    Phase D: rebuild runtime metadata (bg_id_map, stream registry, projections)
    """
    initialize_system()

    # === PHASE A: Load persistence files (ONLY resurrection authority) ===
    print("[RECOVERY:PERSISTENCE_LOAD] Loading persisted workflows")
    try:
        _all_disk_wfs = load_active_workflows()
        print(f"[RECOVERY:PERSISTENCE_LOAD] Loaded {len(_all_disk_wfs)} persisted workflows")
    except Exception as _e:
        print(f"[RECOVERY:PERSISTENCE_LOAD] Failed (non-fatal): {_e}")
        _all_disk_wfs = []

    # === Registry warm restoration (normalizes ACTIVE → PENDING_RECOVERY) ===
    try:
        _warm_result = warm_registry_from_disk()
        print(
            f"[STARTUP] Registry warm restore: {_warm_result['restored']} restored, "
            f"{_warm_result['normalized_active']} ACTIVE\u2192PENDING_RECOVERY, "
            f"{_warm_result['skipped']} skipped"
        )
    except Exception as _e:
        print(f"[STARTUP] Registry warm restore failed (non-fatal): {_e}")

    # === PHASE B: Validate persisted workflows ===
    print("[RECOVERY:VALIDATED] Validating persisted workflows")
    from system.orchestrator.workflow_control import (
        validate_workflow_recovery as _vwr,
        quarantine_workflow as _qwf,
        _update_runtime_registry_only as _urro,
    )

    _eligible_workflows = []  # (workflow_id, workflow_dict)
    _cnt = {"eligible": 0, "skip_terminal": 0, "quarantine": 0, "error": 0}

    for _wf in _all_disk_wfs:
        _wf_id = _wf.get("id")
        if not _wf_id:
            continue

        try:
            _vr = _vwr(_wf)

            if _vr["skip"]:
                _cnt["skip_terminal"] += 1
                print(f"[RECOVERY:VALIDATED] SKIP    wf={_wf_id} reason={_vr['reason']}")
                continue

            if _vr["quarantine"]:
                _qwf(_wf, _vr["reason"])
                _cnt["quarantine"] += 1
                print(f"[RECOVERY:VALIDATED] QUARANTINE wf={_wf_id} reason={_vr['reason']}")
                continue

            # ELIGIBLE for resurrection
            _eligible_workflows.append((_wf_id, _wf))
            _cnt["eligible"] += 1
            print(f"[RECOVERY:VALIDATED] ELIGIBLE wf={_wf_id}")

        except Exception as _e:
            _cnt["error"] += 1
            print(f"[RECOVERY:VALIDATED] ERROR   wf={_wf_id} exception={str(_e)}")

    print(f"[RECOVERY:VALIDATED] Summary: {_cnt['eligible']} eligible, {_cnt['skip_terminal']} terminal, {_cnt['quarantine']} quarantined, {_cnt['error']} errors")

    # === PHASE C: Operator-gated recovery (no auto-resurrection) ===
    # Per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1 §10:
    # Recovery continuation is operator-gated. Workflows remain in PENDING_RECOVERY
    # until explicitly resumed by operator via /resume endpoint.
    print(f"[RECOVERY:OPERATOR_GATED] {len(_eligible_workflows)} workflows in PENDING_RECOVERY awaiting operator resume")

    # === PHASE D: Rebuild runtime metadata (DERIVED ONLY) ===
    print("[RECOVERY:RUNTIME_REBUILD] Rebuilding runtime metadata from eligible workflows")

    # Stream registry is NOT cleared here. Phase D rebuilds entries for eligible workflows
    # from bg_id_map. Clearing here would destroy that work.
    # Any genuinely stale entries (no matching eligible workflow) are evicted by the
    # fast _wf_persistence_exists() checks in the /active and /workflow_id endpoints.

    # Reconstruct stream registry from bg_id_map for eligible workflows.
    # bg_id_map persists bg_id → workflow_id across restarts. For each eligible
    # workflow, restore its stream registry entry so the frontend can reconnect using
    # the same bg_id it held before the restart.
    try:
        if _load_bg_id_map is not None:
            _persisted_bg_map = _load_bg_id_map()
            _eligible_ids = {wf_id for wf_id, _ in _eligible_workflows}
            _bg_restored = 0
            for _bg_id_key, _wf_id_val in _persisted_bg_map.items():
                if _wf_id_val not in _eligible_ids:
                    continue
                with _stream_registry_lock:
                    if _bg_id_key not in _stream_registry:
                        _stream_registry[_bg_id_key] = {
                            "orchestrator_workflow_id": _wf_id_val,
                            "workflow": None,
                            "result": None,
                            "status": "PENDING_RECOVERY",
                            "error": None,
                        }
                        _bg_restored += 1
            print(f"[RECOVERY:RUNTIME_REBUILD] Stream registry: {_bg_restored} entries restored from bg_id_map")
    except Exception as _e:
        print(f"[RECOVERY:RUNTIME_REBUILD] bg_id_map stream restore failed (non-fatal): {_e}")

    # Projection stores are DERIVED - restore them with validation
    try:
        if _get_proj_mgr is not None:
            _proj_mgr = _get_proj_mgr()
            _store_result = _proj_mgr.warm_stores_from_disk(_get_workflow_state)
            print(
                f"[RECOVERY:RUNTIME_REBUILD] Projection stores: {_store_result['restored']} restored, "
                f"{_store_result['skipped_stale']} stale skipped, "
                f"{_store_result['errors']} errors"
            )
    except Exception as _e:
        print(f"[RECOVERY:RUNTIME_REBUILD] Projection store restore failed (non-fatal): {_e}")

    print("[STARTUP] Startup recovery complete")


# =============================================================================
# REQUEST MODELS
# =============================================================================

class ExecuteRequest(BaseModel):
    input: str



class ResumeRequest(BaseModel):
    workflow_id: str


class PauseRequest(BaseModel):
    workflow_id: str


class PlanEditRequest(BaseModel):
    workflow_id: str
    step_id: str
    updates: dict


class PlanAddRequest(BaseModel):
    workflow_id: str
    step_data: dict


class PlanRemoveRequest(BaseModel):
    workflow_id: str
    step_id: str


class PlanReorderRequest(BaseModel):
    workflow_id: str
    new_order: list


class RetryStepRequest(BaseModel):
    workflow_id: str
    step_id: str


class StopWorkflowRequest(BaseModel):
    workflow_id: str


class ApprovalRequest(BaseModel):
    workflow_id: str
    step_id: str
    approved: bool


class MutationRequest(BaseModel):
    mutation_type: str
    payload: dict
    actor: Optional[str] = "user"


class BackgroundStartRequest(BaseModel):
    input: str


class ExecuteFailToolRequest(BaseModel):
    """TEST ONLY: Execute a deterministic failing tool through authentic runtime.
    
    This creates REAL runtime failure without synthetic state mutation.
    Routes through normal orchestration execution for authentic semantics.
    """
    workflow_id: str
    step_id: str
    reason: str = "test_deterministic_failure"


# =============================================================================
# ISSUE-077 — MEMORY MANAGEMENT REQUEST MODELS
# =============================================================================

class MemoryWriteRequest(BaseModel):
    scope: str
    key: str
    value: Any
    category: str
    project_id: Optional[str] = None
    source: Optional[str] = "user"
    confidence: Optional[float] = 0.5
    editable: Optional[bool] = True
    deletable: Optional[bool] = True


class MemoryUpdateRequest(BaseModel):
    scope: str
    key: str
    value: Any
    project_id: Optional[str] = None


class MemoryDeleteRequest(BaseModel):
    scope: str
    key: str
    project_id: Optional[str] = None


class MemoryResetRequest(BaseModel):
    scope: str
    project_id: Optional[str] = None
    confirm_all: Optional[bool] = False


# =============================================================================
# PHASE 2.1 — EXECUTION
# =============================================================================

@app.post("/execute")
async def execute(req: ExecuteRequest):
    """
    POST /execute
    Calls orchestrator_runtime.execute_from_input(input).
    Returns contract-compliant projection (steps without execution fields, outputs separate).
    """
    if not req.input or not req.input.strip():
        raise HTTPException(status_code=400, detail="input must not be empty")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, execute_from_input, req.input)
    
    # Apply projection layer for contract compliance
    if result and isinstance(result, dict) and "steps" in result:
        result = project_workflow_for_gui(result)
    
    return result


# =============================================================================
# PHASE 2.1b — STREAMING EXECUTION (non-blocking, returns workflow_id early)
# =============================================================================

# Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
# - Runtime registry is sole lifecycle authority
# - Stream registry is PROJECTION CACHE ONLY
# - Stream registry mirrors runtime authority, never originates lifecycle state
# - All lifecycle state must derive from runtime registry via _get_workflow_state()

# Registry: bg_id → {"orchestrator_workflow_id": str|None, "result": dict|None, "status": str}
# Note: "status" field is projection cache, NOT authoritative lifecycle state
_stream_registry: dict = {}
_stream_registry_lock = threading.Lock()

# ISSUE-055B Phase 3: In-flight replan guard to prevent duplicate planner threads
_replan_in_progress: set = set()
_replan_lock = threading.Lock()


def _run_workflow_wrapper(bg_id: str, workflow_or_input, mode: str = "new", pre_generated_workflow_id: str = None) -> None:
    """
    Single unified execution thread wrapper.

    mode="new"         — calls execute_from_input(user_input, bg_id, ...)
    mode="resurrect"   — calls run_workflow(workflow, bg_id, ...)
    mode="resume"      — calls run_workflow(workflow, bg_id, ...)

    After execution: writes result to stream registry, reads authoritative status
    from runtime registry, deregisters bg_id on terminal state.
    """
    # === PERF036: wrapper entry ===
    _p036_wrapper_start = _perf_time.monotonic()
    try:
        print("PERF036_BACKEND " + json.dumps({
            "label": "run_workflow_wrapper_entry",
            "source_layer": "api_wrapper",
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "bg_id": bg_id,
            "mode": mode,
            "pre_generated_workflow_id": pre_generated_workflow_id,
        }))
    except Exception:
        pass

    try:
        if mode == "new":
            result = execute_from_input(
                workflow_or_input, bg_id, _stream_registry, _stream_registry_lock,
                pre_generated_workflow_id=pre_generated_workflow_id
            )
            orchestrator_wf_id = pre_generated_workflow_id or result.get("workflow_id") or result.get("id")
        else:
            result = run_workflow(
                workflow_or_input, bg_id,
                stream_registry=_stream_registry,
                stream_registry_lock=_stream_registry_lock,
            )
            orchestrator_wf_id = workflow_or_input.get("id") if isinstance(workflow_or_input, dict) else None

        with _stream_registry_lock:
            if bg_id in _stream_registry:
                _stream_registry[bg_id]["result"] = result
                # ISSUE-057: Update stream registry workflow cache with post-execution
                # workflow dict so terminal FAILED stream responses include step details.
                # Only caches projection/step-detail transport; does NOT own lifecycle.
                if isinstance(result, dict) and "steps" in result:
                    _stream_registry[bg_id]["workflow"] = result
                elif isinstance(workflow_or_input, dict) and "steps" in workflow_or_input:
                    _stream_registry[bg_id]["workflow"] = workflow_or_input
                # Per PHASE VI §5: Stream registry consumes ONLY from authority
                runtime_state = _get_workflow_state(orchestrator_wf_id) if orchestrator_wf_id else None
                # Terminal guard: do NOT overwrite CANCELLED or other terminal states
                # that may have been set during planning (e.g., cancel during planning)
                existing_status = _stream_registry[bg_id].get("status")
                if existing_status in ("COMPLETED", "FAILED", "CANCELLED"):
                    # Preserve terminal state — planner completion must not resurrect
                    print(f"[STREAM_TERMINAL_GUARD] bg_id={bg_id} preserving terminal={existing_status}")
                elif runtime_state:
                    _stream_registry[bg_id]["status"] = runtime_state["status"]
                    _stream_registry[bg_id]["runtime_activity"] = runtime_state.get("runtime_activity")
                else:
                    # Phase 4G-A.9: UNKNOWN MUST NOT leak into operator UI.
                    # Use None so frontend renders Pending / no label instead of UNKNOWN.
                    _stream_registry[bg_id]["status"] = None
            else:
                _stream_registry[bg_id] = {
                    "orchestrator_workflow_id": orchestrator_wf_id,
                    "result": result,
                    # Phase 4G-A.9: UNKNOWN MUST NOT leak into operator UI.
                    "status": runtime_state["status"] if runtime_state else None,
                    "runtime_activity": runtime_state.get("runtime_activity") if runtime_state else None,
                    "error": None,
                }

        # === PHASE XII §2: bg_id CLEANUP HARDENING ===
        # Per PHASE XII: deregister bg_id after terminal convergence succeeds.
        # BLOCKED is NOT terminal — user-control workflows must remain
        # attachable/controllable after refresh. The bg_id stays registered
        # so the frontend can poll and discover BLOCKED status.
        # Resurrection (retry/resume) re-registers a fresh bg_id if needed.
        try:
            _final_status = _stream_registry.get(bg_id, {}).get("status", "")
            if _final_status in ("COMPLETED", "FAILED", "CANCELLED") and _deregister_bg_id is not None:
                _deregister_bg_id(bg_id)
        except Exception:
            pass

    except Exception as e:
        with _stream_registry_lock:
            if bg_id in _stream_registry:
                orchestrator_wf_id = _stream_registry[bg_id].get("orchestrator_workflow_id")
                runtime_state = _get_workflow_state(orchestrator_wf_id) if orchestrator_wf_id else None
                _stream_registry[bg_id]["status"] = runtime_state["status"] if runtime_state else "FAILED"
                _stream_registry[bg_id]["error"] = str(e)


def _trigger_execution_resume(workflow_id: str, skip_generation_increment: bool = False) -> dict:
    """
    Resume a BLOCKED/PAUSED/PENDING_RECOVERY workflow and spawn a new execution thread.

    Per ISSUE-098KLM: extracted from /resume endpoint so user-control accept
    can trigger execution re-entry when operator resolves an external-call risk request.

    Per ISSUE-098KN: accept_external_call_risk may skip generation increment
    because no stale running thread exists (runtime loop has exited).

    Args:
        workflow_id: The workflow to resume.
        skip_generation_increment: If True, do not increment execution_generation.
            Use for accept_external_call_risk where the old thread is already dead.

    Returns:
        dict with {"status": "ok", "resumed": True, "workflow_id": ..., "bg_id": ...}
        or {"status": "failure", "reason": ...} on error.
    """
    result = resume_workflow(workflow_id)
    if result.get("status") == "failure":
        return result

    # Fast single-file load — do NOT call load_active_workflows() (full scan).
    from system.orchestrator.persistence import _active_workflow_path as _awp
    import json as _json
    workflow = None
    try:
        with open(_awp(workflow_id), "r", encoding="utf-8") as _f:
            workflow = _json.load(_f)
        if not isinstance(workflow, dict) or workflow.get("id") != workflow_id:
            workflow = None
    except Exception:
        workflow = None

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    # Verify transition occurred — check authoritative runtime registry.
    _authoritative = _get_workflow_state(workflow_id)
    if not _authoritative or _authoritative.get("status") != "ACTIVE":
        return {"status": "failure", "reason": "workflow_not_resumed"}

    # Sync the loaded dict from authoritative registry ONLY.
    from system.orchestrator.workflow_control import inject_authoritative_lifecycle_into_workflow
    inject_authoritative_lifecycle_into_workflow(workflow)

    # Increment execution generation to invalidate stale threads.
    # ISSUE-098KN: accept_external_call_risk may skip because no stale thread.
    if not skip_generation_increment:
        try:
            from system.orchestrator.workflow_control import _workflow_state_registry, _workflow_state_lock
            with _workflow_state_lock:
                _current_gen = _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
                _workflow_state_registry[workflow_id]["execution_generation"] = _current_gen + 1
                print(f"[EXECUTION_GENERATION] Resume incremented workflow={workflow_id} generation={_current_gen + 1}")
        except Exception as e:
            print(f"[EXECUTION_GENERATION] Failed to increment generation for resume workflow={workflow_id}: {e}")

    # Find existing bg_id associated with this workflow_id
    bg_id = None
    with _stream_registry_lock:
        for existing_bg_id, entry in _stream_registry.items():
            if entry.get("orchestrator_workflow_id") == workflow_id:
                bg_id = existing_bg_id
                runtime_state = _get_workflow_state(workflow_id)
                entry["status"] = runtime_state["status"] if runtime_state else "ACTIVE"
                entry["runtime_activity"] = runtime_state.get("runtime_activity") if runtime_state else None
                _cached_wf = entry.get("workflow")
                if _cached_wf is not None and isinstance(_cached_wf, dict):
                    _cached_wf["status"] = runtime_state["status"] if runtime_state else "ACTIVE"
                entry["workflow"] = None
                entry["result"] = None
                entry["error"] = None
                break

    if bg_id is None:
        bg_id = str(_uuid_mod.uuid4())
        with _stream_registry_lock:
            _res_auth_new2 = _get_workflow_state(workflow_id)
            _stream_registry[bg_id] = {
                "orchestrator_workflow_id": workflow_id,
                "workflow": None,
                "result": None,
                "status": _res_auth_new2["status"] if _res_auth_new2 else "ACTIVE",
                "runtime_activity": _res_auth_new2.get("runtime_activity") if _res_auth_new2 else None,
                "error": None,
            }

    # Resume is async: start execution thread and return bg_id immediately.
    t = threading.Thread(
        target=_run_workflow_wrapper,
        args=(bg_id, workflow),
        kwargs={"mode": "resume"},
        daemon=True,
        name=f"resume-{bg_id[:8]}",
    )
    t.start()

    return {"status": "ok", "resumed": True, "workflow_id": workflow_id, "bg_id": bg_id}


def _maybe_resurrect_execution(workflow_id: str) -> Optional[str]:
    """
    Execution resurrection bridge for retry/edit mutations on terminal workflows.

    Per ORCHESTRATOR_EXECUTION_CONTRACT: run_workflow is the sole execution authority.
    Per LIFECYCLE_AUTHORITY_CONTRACT_V1: _update_workflow_state is the sole lifecycle writer.
    Per PROJECTION_CONTINUITY_CONTRACT_V1: reuse existing bg_id to preserve stream identity.

    When a retry/edit mutation resets a BLOCKED/FAILED workflow back to ACTIVE (via
    retry_step → _update_workflow_state(wf_id, "ACTIVE")), the original execution thread
    is already dead — run_workflow exited when the workflow first hit BLOCKED/FAILED.
    The mutation writes correct state into persistence and registry but no thread is
    consuming it.  This function detects that gap and spawns a new run_workflow thread,
    exactly as /resume/{workflow_id} does, but triggered from the mutation pipeline.

    Returns:
        bg_id if resurrection was triggered, None if not needed (workflow not ACTIVE or
        already has a running thread, or workflow not found in persistence).

    Contract compliance:
    - Does NOT call resume_workflow() — that function checks PAUSED/BLOCKED guard which
      would reject because the mutation already wrote ACTIVE directly.
    - Does NOT write lifecycle state — mutation manager already did that correctly.
    - Does NOT mutate projection — projection was already rebuilt by _invalidate_and_reemit.
    - Only spawns execution thread and updates stream registry projection cache.
    """
    # Check authoritative registry — resurrect for ACTIVE, ACTIVATING, or PENDING_RECOVERY.
    # Startup sets ACTIVATING before calling this function, so ACTIVE-only check always
    # rejected all resurrection. PENDING_RECOVERY is the normalized state after warm_registry.
    _auth = _get_workflow_state(workflow_id)
    if not _auth or _auth.get("status") not in ("ACTIVE", "ACTIVATING", "PENDING_RECOVERY"):
        return None

    # === PHASE-IVB: EXECUTION GENERATION COORDINATION ===
    # Increment workflow_execution_generation for resurrection replacement.
    # This is NON-authoritative coordination metadata only. It does NOT gate lifecycle
    # transitions. Per PHASE-IVA EXECUTION LEASE COORDINATION DESIGN AUDIT.
    try:
        from system.orchestrator.workflow_control import _workflow_state_registry, _workflow_state_lock
        with _workflow_state_lock:
            _current_gen = _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
            _workflow_state_registry[workflow_id]["execution_generation"] = _current_gen + 1
            print(f"[EXECUTION_GENERATION] Resurrection incremented workflow={workflow_id} generation={_current_gen + 1}")
    except Exception as e:
        print(f"[EXECUTION_GENERATION] Failed to increment generation for workflow={workflow_id}: {e}")
        # Non-fatal — proceed with resurrection

    # Fast single-file load — do NOT call load_active_workflows() (full scan).
    from system.orchestrator.persistence import _active_workflow_path as _awp
    import json as _json
    try:
        with open(_awp(workflow_id), "r", encoding="utf-8") as _f:
            workflow = _json.load(_f)
    except Exception:
        return None
    if not isinstance(workflow, dict) or workflow.get("id") != workflow_id:
        return None

    # Sync compatibility mirror from authoritative registry ONLY
    from system.orchestrator.workflow_control import inject_authoritative_lifecycle_into_workflow
    inject_authoritative_lifecycle_into_workflow(workflow)

    print(f"[RESURRECTION] workflow={workflow_id} state={_auth.get('status')}")

    # Find or create bg_id — reuse for projection continuity (in-place update)
    bg_id = None
    with _stream_registry_lock:
        for existing_bg_id, entry in _stream_registry.items():
            if entry.get("orchestrator_workflow_id") == workflow_id:
                bg_id = existing_bg_id
                entry["result"] = None
                entry["error"] = None
                _res_auth = _get_workflow_state(workflow_id)
                entry["status"] = _res_auth["status"] if _res_auth else "ACTIVE"
                entry["workflow"] = None
                break

    if bg_id is None:
        bg_id = str(_uuid_mod.uuid4())
        with _stream_registry_lock:
            _res_auth_new = _get_workflow_state(workflow_id)
            _stream_registry[bg_id] = {
                "orchestrator_workflow_id": workflow_id,
                "workflow": None,
                "result": None,
                "status": _res_auth_new["status"] if _res_auth_new else "ACTIVE",
                "error": None,
            }

    t = threading.Thread(
        target=_run_workflow_wrapper,
        args=(bg_id, workflow),
        kwargs={"mode": "resurrect"},
        daemon=True,
        name=f"resurrect-{bg_id[:8]}",
    )
    t.start()
    return bg_id


@app.post("/execute/stream")
def execute_stream(req: ExecuteRequest):
    """
    POST /execute/stream
    Starts execute_from_input in a background thread.
    Returns bg_id immediately — frontend uses this to poll for workflow_id and result.
    Execution path is identical to /execute — no bypass of system_entry.

    Per PHASE 1 REMEDIATION:
    - NO placeholder workflow IDs
    - NO placeholder stream registry entries
    - Stream registry entry created ONLY AFTER persistence exists
    - bg_id registration ONLY AFTER workflow_id is known and persistence exists
    """
    # === PERF036: handler entry ===
    _p036_handler_start = _perf_time.monotonic()
    try:
        print("PERF036_BACKEND " + json.dumps({
            "label": "execute_stream_handler_entry",
            "source_layer": "api",
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "monotonic_ms": round(_p036_handler_start * 1000, 2),
        }))
    except Exception:
        pass

    if not req.input or not req.input.strip():
        raise HTTPException(status_code=400, detail="input must not be empty")

    bg_id = str(_uuid_mod.uuid4())
    workflow_id = f"workflow_{_uuid_mod.uuid4().hex[:8]}"
    # === PERF036: bg_id + workflow_id generated ===
    try:
        print("PERF036_BACKEND " + json.dumps({
            "label": "execute_stream_ids_generated",
            "source_layer": "api",
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "bg_id": bg_id,
            "workflow_id": workflow_id,
            "duration_ms": round((_perf_time.monotonic() - _p036_handler_start) * 1000, 2),
        }))
    except Exception:
        pass

    # === PRE-REGISTRATION (ISSUE-055) ===
    # Create minimal workflow shell BEFORE planner/LLM work begins.
    # This ensures an authoritative workflow identity exists from T+0ms,
    # eliminating the impossible-restore window during planning-phase refresh.
    #
    # === ISSUE-055B Phase 1B: planning_request persistence ===
    # Per PLANNING_RECOVERY_AND_REPLAN_CONTRACT_V1:
    #   Planning Request ≠ Workflow Identity ≠ Planning Execution
    # planning_request must survive planner success/failure and backend restart.
    # === PERF036: classify_task in handler (call #1) ===
    _p036_classify_start = _perf_time.monotonic()
    _classification = _classify_task(req.input.strip())
    try:
        print("PERF036_BACKEND " + json.dumps({
            "label": "classify_task_handler",
            "source_layer": "api",
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "bg_id": bg_id,
            "workflow_id": workflow_id,
            "duration_ms": round((_perf_time.monotonic() - _p036_classify_start) * 1000, 2),
            "call_site": "execute_stream_handler",
        }))
    except Exception:
        pass
    _planning_exec_id = f"plan_{_uuid_mod.uuid4().hex[:12]}"
    shell = {
        "id": workflow_id,
        "name": "dynamic_workflow",
        "status": "QUEUED",
        "steps": [],
        "goal": req.input.strip(),
        "approval_required": False,
        "planning_request": {
            "original_prompt": req.input.strip(),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "planning_status": "IN_PROGRESS",
            "classification": _classification.get("classification") if isinstance(_classification, dict) else None,
            "planning_attempt_count": 1,
            "planning_execution_id": _planning_exec_id,
            "last_interruption_reason": None,
            "last_replanned_at": None,
        },
    }

    # Step 1: Persist shell
    _p036_persist_start = _perf_time.monotonic()
    try:
        _save_workflow(shell)
        print(f"[PRE_REGISTER] Persisted shell {workflow_id}")
        try:
            print("PERF036_BACKEND " + json.dumps({
                "label": "shell_persist_end",
                "source_layer": "api",
                "timestamp_iso": datetime.now(timezone.utc).isoformat(),
                "bg_id": bg_id,
                "workflow_id": workflow_id,
                "duration_ms": round((_perf_time.monotonic() - _p036_persist_start) * 1000, 2),
            }))
        except Exception:
            pass
    except Exception as e:
        print(f"[PRE_REGISTER:FAIL] Persistence failed for {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail="workflow_pre_registration_failed")

    # Step 2: Register lifecycle entry as QUEUED
    try:
        _update_workflow_state(workflow_id, "QUEUED", "pre_registration")
        print(f"[PRE_REGISTER] Registered lifecycle {workflow_id} as QUEUED")
    except Exception as e:
        print(f"[PRE_REGISTER:FAIL] Lifecycle registration failed for {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail="workflow_pre_registration_failed")

    # Step 3: Register bg_id → workflow_id mapping
    if _register_bg_id is not None:
        try:
            _register_bg_id(bg_id, workflow_id)
            print(f"[PRE_REGISTER] Registered bg_id {bg_id} → {workflow_id}")
        except Exception as e:
            print(f"[PRE_REGISTER:WARN] bg_id registration failed for {bg_id}: {e}")

    # Step 4: Create stream registry entry with workflow_id and shell
    with _stream_registry_lock:
        _stream_registry[bg_id] = {
            "orchestrator_workflow_id": workflow_id,
            "workflow": shell,
            "result": None,
            "status": "PENDING",
            "error": None,
        }

    # Step 5: Spawn execution thread with pre-generated workflow_id
    # === PERF036: thread spawn ===
    _p036_spawn_ts = _perf_time.monotonic()
    t = threading.Thread(
        target=_run_workflow_wrapper,
        args=(bg_id, req.input),
        kwargs={"mode": "new", "pre_generated_workflow_id": workflow_id},
        daemon=True,
        name=f"stream-{bg_id[:8]}",
    )
    t.start()
    try:
        print("PERF036_BACKEND " + json.dumps({
            "label": "execute_stream_thread_spawned",
            "source_layer": "api",
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "bg_id": bg_id,
            "workflow_id": workflow_id,
            "handler_total_ms": round((_perf_time.monotonic() - _p036_handler_start) * 1000, 2),
        }))
    except Exception:
        pass
    return {"bg_id": bg_id, "status": "PENDING"}


@app.get("/execute/stream/workflow_id/{bg_id}")
def stream_workflow_id(bg_id: str):
    """
    GET /execute/stream/workflow_id/{bg_id}
    Returns orchestrator workflow_id once planning completes (written by thread).

    Per PHASE 1 REMEDIATION:
    - Frontend may ONLY hydrate from persistence-backed workflows
    - Persistence validation required before returning to frontend
    """
    with _stream_registry_lock:
        entry = _stream_registry.get(bg_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="bg_id not found")

    wf_id = entry.get("orchestrator_workflow_id")
    status = entry.get("status", "")

    # Internal bootstrap states (ACTIVATING, PERSISTED, PENDING_RECOVERY) must NOT
    # appear in stream schema. Return PENDING — frontend treats it as planning-in-progress.
    # CRITICAL: Workflow identity MUST propagate immediately for frontend ownership convergence.
    # Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1: Authoritative workflow_id available
    # as soon as orchestrator assigns it, even while internal lifecycle remains in bootstrap.
    if status in ("ACTIVATING", "PERSISTED", "PENDING_RECOVERY"):
        return {
            "bg_id": bg_id,
            "workflow_id": wf_id,
            "status": "PENDING",
            "result": None,
        }

    # === FRONTEND AUTHORITY ENFORCEMENT ===
    # Fast O(1) existence check — do NOT call validate_runtime_activation() here (full scan).
    if wf_id:
        if not _wf_persistence_exists(wf_id):
            _evict_workflow_state(wf_id, bg_id=bg_id, reason="stream_workflow_id_no_persistence")
            raise HTTPException(status_code=404, detail="workflow not found")

    # === RUNTIME OBSERVABILITY: runtime_activity ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # Stream endpoint exposes runtime_activity for global frontend observability.
    # Stream registry cache preferred; falls back to authoritative runtime registry.
    _runtime_activity = entry.get("runtime_activity")
    if not _runtime_activity and wf_id and _get_workflow_state is not None:
        _runtime_state = _get_workflow_state(wf_id)
        if _runtime_state:
            _runtime_activity = _runtime_state.get("runtime_activity")

    response = {
        "bg_id": bg_id,
        "workflow_id": wf_id,
        "status": status,
        "runtime_activity": _runtime_activity,
    }

    workflow = entry.get("workflow")
    # ISSUE-092B: Must check for substantive steps, not just key presence.
    # Pre-registered shells have steps=[]; empty shells should fall through
    # to enriched FAILED result logic for pre-step planner failures.
    if workflow and isinstance(workflow, dict) and workflow.get("steps"):
        projected = project_workflow_for_gui(workflow)
        projected["workflow_id"] = wf_id
        projected["status"] = entry["status"]
        response["result"] = projected
    elif entry.get("status") == "FAILED":
        # === ISSUE-092B: Use enriched FAILED result from stream registry if available ===
        stored_result = entry.get("result") or {}
        # If backend already provided enriched result (pre-step planner failure), use it
        # Otherwise synthesize minimal FAILED response
        if stored_result.get("status") == "FAILED" and stored_result.get("workflow_id") == wf_id:
            # Use the enriched result with all metadata fields
            response["result"] = stored_result
        else:
            # Synthesize minimal FAILED response for backward compatibility
            response["result"] = {
                "status": "FAILED",
                "reason": stored_result.get("reason") or entry.get("error") or "execution_failed",
                "failure_reason": stored_result.get("failure_reason") or entry.get("error") or "execution_failed",
                "failure_display_message": stored_result.get("failure_display_message"),
                "workflow_id": wf_id,
                "steps": stored_result.get("steps", []),
                "outputs": stored_result.get("outputs", []),
                "workflow_output": stored_result.get("workflow_output"),
                "failed_step_id": stored_result.get("failed_step_id"),
                "retry_target_step_id": stored_result.get("retry_target_step_id"),
                "last_successful_step_id": stored_result.get("last_successful_step_id"),
                "last_successful_output": stored_result.get("last_successful_output"),
                "retry_eligible": stored_result.get("retry_eligible"),
                "failed_recoverable": stored_result.get("failed_recoverable"),
                "retry_disabled_reason": stored_result.get("retry_disabled_reason"),
            }
    else:
        response["result"] = None

    return response



# =============================================================================
# PHASE 2.2 — WORKFLOW CONTROL (Per GUI_FUNCTIONALITY_CONTRACT_V1)
# =============================================================================

@app.post("/pause/{workflow_id}")
def pause_workflow_endpoint(workflow_id: str):
    """
    POST /pause/{workflow_id}
    Pause a specific workflow using state transition.
    Per STATE_TRANSITIONS_CONTRACT_V1: ACTIVE → PAUSED
    Per GUI_FUNCTIONALITY_CONTRACT_V1: ALL actions require workflow_id
    """
    result = pause_workflow(workflow_id)
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    
    # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Stream registry is projection-only
    # Update projection cache to mirror runtime registry (pause_workflow updates runtime registry)
    with _stream_registry_lock:
        for bg_id, entry in _stream_registry.items():
            if entry.get("orchestrator_workflow_id") == workflow_id:
                # Read authoritative lifecycle state from runtime registry and cache for projection
                runtime_state = _get_workflow_state(workflow_id)
                entry["status"] = runtime_state["status"] if runtime_state else "PAUSED"
                entry["runtime_activity"] = runtime_state.get("runtime_activity") if runtime_state else None
                # === LIFECYCLE SYNC BRIDGE (Phase 4G-A.9): sync into cached workflow dict ===
                _cached_wf = entry.get("workflow")
                if _cached_wf is not None and isinstance(_cached_wf, dict):
                    _cached_wf["status"] = runtime_state["status"] if runtime_state else "PAUSED"
                break

    # === CANONICAL PROJECTION EMISSION ON PAUSE ===
    # Per CANONICAL_PROJECTION_MODEL_V1 §5: projection MUST be emitted on lifecycle change.
    # pause_workflow() commits PAUSED to registry but does not emit canonical projection.
    # Emit now so /projection/{workflow_id} immediately reflects PAUSED lifecycle.
    # Failure-isolated: must not affect pause response.
    try:
        if _get_proj_mgr is not None:
            _wf_for_proj = None
            # Prefer in-memory workflow from stream registry (shallow copy to avoid race with execution thread)
            with _stream_registry_lock:
                for _p_bg_id, _p_entry in _stream_registry.items():
                    if _p_entry.get("orchestrator_workflow_id") == workflow_id:
                        _raw_wf = _p_entry.get("workflow")
                        _wf_for_proj = dict(_raw_wf) if isinstance(_raw_wf, dict) else None
                        break
            # Fallback to persistence if not in stream registry
            if _wf_for_proj is None:
                from system.orchestrator.persistence import load_active_workflows as _law_p
                for _wf_p in _law_p():
                    if _wf_p.get("id") == workflow_id:
                        _wf_for_proj = _wf_p
                        break
            if _wf_for_proj is not None and isinstance(_wf_for_proj, dict):
                _get_proj_mgr().emit_lifecycle_changed(_wf_for_proj, "PAUSED")
                print(f"[PROJECTION] Emitted PAUSED projection for {workflow_id}")
            else:
                print(f"[PROJECTION] Could not emit PAUSED projection for {workflow_id}: workflow not found")
    except Exception as _proj_e:
        print(f"[PROJECTION] PAUSED projection emission failed for {workflow_id}: {_proj_e}")

    return {"status": "ok", "paused": True, "workflow_id": workflow_id}


@app.post("/resume/{workflow_id}")
async def resume_workflow_endpoint(workflow_id: str):
    """
    POST /resume/{workflow_id}
    Resume a specific workflow using state transition.
    Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED/BLOCKED/PENDING_RECOVERY → ACTIVE
    Per GUI_FUNCTIONALITY_CONTRACT_V1: ALL actions require workflow_id
    """
    result = _trigger_execution_resume(workflow_id)
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return result


# ISSUE-055B Phase 3: Helper to deregister all stale bg_ids for a workflow_id
def _deregister_stale_bg_ids_for_workflow(workflow_id: str) -> None:
    """Remove all bg_id map entries pointing to this workflow_id."""
    if _deregister_bg_id is None:
        return
    try:
        if _load_bg_id_map:
            _bg_map = _load_bg_id_map()
            stale_bg_ids = [bg_id for bg_id, wf_id in _bg_map.items() if wf_id == workflow_id]
            for bg_id in stale_bg_ids:
                _deregister_bg_id(bg_id)
                print(f"[REPLAN:STALE_CLEANUP] deregistered stale bg_id={bg_id} for workflow={workflow_id}")
    except Exception as e:
        print(f"[REPLAN:STALE_CLEANUP:WARN] {e}")


@app.post("/replan/{workflow_id}")
async def replan_workflow_endpoint(workflow_id: str):
    """
    POST /replan/{workflow_id}
    Operator-initiated replan for QUEUED_REPLAN_REQUIRED workflows.
    Preserves workflow_id, creates new planning execution identity,
    generates new bg_id, and spawns a fresh planner thread.

    Per PLANNING_RECOVERY_AND_REPLAN_CONTRACT_V1:
    - Replan is NOT recovery, retry, replay, or planner resurrection.
    - Replan creates a NEW planning execution from persisted planning request.
    """
    # === VALIDATION 1: Workflow exists in persistence ===
    workflow = load_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="workflow_not_found")

    # === VALIDATION 2: Status must be QUEUED ===
    if workflow.get("status") != "QUEUED":
        raise HTTPException(status_code=400, detail="invalid_status_for_replan")

    # === VALIDATION 3: Must have planning_request or legacy goal ===
    planning_request = workflow.get("planning_request")
    original_prompt = None
    if isinstance(planning_request, dict):
        original_prompt = planning_request.get("original_prompt")
    if not original_prompt:
        original_prompt = workflow.get("goal")
    if not original_prompt:
        raise HTTPException(status_code=400, detail="no_planning_request")

    # === VALIDATION 4: Must not already be live planning ===
    with _stream_registry_lock:
        for entry in _stream_registry.values():
            if entry.get("orchestrator_workflow_id") == workflow_id:
                raise HTTPException(status_code=409, detail="workflow_already_live_or_replanning")

    # === VALIDATION 5: Must not be in-flight replan ===
    with _replan_lock:
        if workflow_id in _replan_in_progress:
            raise HTTPException(status_code=409, detail="workflow_already_live_or_replanning")
        _replan_in_progress.add(workflow_id)

    try:
        # === STALE BG_ID CLEANUP ===
        _deregister_stale_bg_ids_for_workflow(workflow_id)

        # === UPDATE PLANNING REQUEST ===
        _new_planning_exec_id = f"plan_{_uuid_mod.uuid4().hex[:12]}"
        _now = datetime.now(timezone.utc).isoformat()
        if not isinstance(planning_request, dict):
            workflow["planning_request"] = {}
            planning_request = workflow["planning_request"]

        _prev_attempt_count = planning_request.get("planning_attempt_count", 0)
        planning_request["planning_status"] = "IN_PROGRESS"
        planning_request["planning_execution_id"] = _new_planning_exec_id
        planning_request["planning_attempt_count"] = _prev_attempt_count + 1
        planning_request["last_replanned_at"] = _now
        planning_request["last_interruption_reason"] = None
        # Preserve original_prompt, submitted_at, classification

        # === PERSIST UPDATED WORKFLOW ===
        _save_workflow(workflow)
        print(f"[REPLAN:PERSIST] workflow={workflow_id} planning_attempt_count={_prev_attempt_count + 1}")

        # === GENERATE NEW BG_ID ===
        bg_id = str(_uuid_mod.uuid4())

        # === REGISTER BG_ID ===
        if _register_bg_id is not None:
            try:
                _register_bg_id(bg_id, workflow_id)
                print(f"[REPLAN:BG_REGISTER] bg_id={bg_id} → workflow={workflow_id}")
            except Exception as e:
                print(f"[REPLAN:BG_REGISTER:WARN] {e}")

        # === CREATE STREAM REGISTRY ENTRY ===
        with _stream_registry_lock:
            _stream_registry[bg_id] = {
                "orchestrator_workflow_id": workflow_id,
                "workflow": workflow,
                "result": None,
                "status": "PENDING",
                "error": None,
            }

        # === SPAWN PLANNER THREAD ===
        t = threading.Thread(
            target=_run_workflow_wrapper,
            args=(bg_id, original_prompt),
            kwargs={"mode": "new", "pre_generated_workflow_id": workflow_id},
            daemon=True,
            name=f"replan-{bg_id[:8]}",
        )
        t.start()

        print(f"[REPLAN:STARTED] workflow={workflow_id} bg_id={bg_id} planning_execution_id={_new_planning_exec_id}")

        return {
            "workflow_id": workflow_id,
            "bg_id": bg_id,
            "status": "QUEUED",
            "planning_status": "IN_PROGRESS",
            "planning_execution_id": _new_planning_exec_id,
            "planning_attempt_count": _prev_attempt_count + 1,
            "actionability": "LIVE_PLANNING",
            "live_planning": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[REPLAN:ERROR] workflow={workflow_id} error={e}")
        raise HTTPException(status_code=500, detail=f"replan_failed: {e}")
    finally:
        # Clear in-flight guard only after thread has started;
        # the stream registry entry remains as live evidence.
        with _replan_lock:
            _replan_in_progress.discard(workflow_id)


@app.get("/status")
def get_status():
    """GET /status → user_control.get_control_state()"""
    return get_control_state()


@app.get("/identity")
def get_identity():
    """GET /identity → backend instance identity for ISSUE-063 port ownership guard.

    Returns read-only identity metadata so the Tauri app can verify it owns
    the backend process on port 8000 and is not silently attaching to an
    external, stale, or unrelated backend.
    """
    return {
        "pid": _BACKEND_PID,
        "started_at": _BACKEND_STARTED_AT,
        "backend_instance_id": _BACKEND_INSTANCE_ID,
        "project_root": _BACKEND_PROJECT_ROOT,
        "launch_mode": os.environ.get("AI_LAB_LAUNCH_MODE", "unknown"),
        "app_instance_id": os.environ.get("AI_LAB_APP_INSTANCE_ID", None),
        "version": "0.1.0",
    }


# =============================================================================
# PHASE 2.3 — BACKGROUND WORKFLOWS
# =============================================================================

@app.post("/background/start")
def background_start(req: BackgroundStartRequest):
    """POST /background/start → background_manager.start_workflow()"""
    if not req.input or not req.input.strip():
        raise HTTPException(status_code=400, detail="input must not be empty")
    workflow_id = _bg_manager.start_workflow(execute_from_input, req.input)
    return {"status": "ok", "workflow_id": workflow_id}


@app.get("/background/list")
def background_list():
    """GET /background/list → background_manager.list_workflows()"""
    return {"workflows": _bg_manager.list_workflows()}


@app.get("/execute/stream/active")
def stream_active():
    """
    GET /execute/stream/active
    Returns all bg_id entries from _stream_registry that have a known workflow_id.

    Per PHASE 1 REMEDIATION:
    - Frontend may ONLY hydrate from persistence-backed workflows
    - NO placeholder workflow IDs (removed)
    - Persistence validation required before returning to frontend
    """
    # Snapshot candidates without holding the lock during I/O
    _snapshot = []
    with _stream_registry_lock:
        _snapshot = list(_stream_registry.items())

    active = []
    _to_evict = []  # (wf_id, bg_id, reason) — evicted after iteration

    for bg_id, entry in _snapshot:
        wf_id = entry.get("orchestrator_workflow_id")
        # Per PHASE 1: NO placeholder entries
        if not wf_id:
            continue

        status = entry.get("status", "")

        # Frontend may ONLY see ACTIVE workflows.
        # ACTIVATING and PENDING_RECOVERY are pre-bootstrap states — exclude from frontend.
        if status in ("QUARANTINED", "ACTIVATING", "PENDING_RECOVERY"):
            if status == "QUARANTINED":
                _to_evict.append((wf_id, bg_id, "stream_active_quarantined_status"))
            continue

        # === FRONTEND AUTHORITY ENFORCEMENT ===
        # Fast O(1) existence check — do NOT call validate_runtime_activation() here (full scan).
        if not _wf_persistence_exists(wf_id):
            _to_evict.append((wf_id, bg_id, "stream_active_no_persistence"))
            continue

        active.append({
            "bg_id": bg_id,
            "workflow_id": wf_id,
            "status": status,
        })

    # Execute evictions outside the snapshot loop
    for _ev_wfid, _ev_bgid, _ev_reason in _to_evict:
        _evict_workflow_state(_ev_wfid, bg_id=_ev_bgid, reason=_ev_reason)

    return {"active": active}


@app.get("/workflows/authoritative")
def get_authoritative_workflows():
    """
    GET /workflows/authoritative
    Returns authoritative workflow enumeration from Lifecycle Registry.

    Per LIFECYCLE_AUTHORITY_CONTRACT_V1 §WORKFLOW ENUMERATION RULES:
    - Workflow enumeration MUST originate from authoritative workflow identity state.
    - Stream registry MUST NOT act as recovery authority.

    Per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1 §14:
    - Frontend heuristic workflow restoration is PROHIBITED.
    - Stream-derived workflow identity is PROHIBITED.

    SOURCE OF TRUTH:
    - _workflow_state_registry (Lifecycle Authority)
    - persistence-backed workflow identity

    DO NOT:
    - source from stream registry
    - source from projections
    - source from frontend state
    """
    from system.orchestrator.workflow_control import _workflow_state_registry, _workflow_state_lock

    # Build reverse bg_id lookup for transport convenience
    wf_to_bg = {}
    try:
        if _load_bg_id_map:
            _bg_map = _load_bg_id_map()
            for bg_id, wf_id in _bg_map.items():
                wf_to_bg.setdefault(wf_id, []).append(bg_id)
    except Exception:
        pass

    workflows = []
    with _workflow_state_lock:
        for wf_id, state in _workflow_state_registry.items():
            # Hard guard: persistence must exist for any returned workflow
            if not _wf_persistence_exists(wf_id):
                continue
            # Phase 4G-A.9: UNKNOWN MUST NOT leak into operator UI.
            # Use None so frontend renders Pending / no label.
            status = state.get("status")
            # Recoverable = non-terminal, non-quarantined
            # CANCELLED is immutable terminal — must NOT be recoverable
            recoverable = status not in ("COMPLETED", "FAILED", "CANCELLED", "QUARANTINED")
            # Inspection-only = terminal workflows that can be viewed but not acted upon
            inspection_only = status in ("CANCELLED", "COMPLETED")

            # Per ISSUE-060: retention_state is NOT registry authority.
            # Load from persisted workflow JSON. Missing defaults to "retained".
            retention_state = get_retention_state(wf_id)

            # === ISSUE-055B Phase 1A — Backend-authored actionability metadata ===
            # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: lifecycle state does not equal actionability.
            # Per PLANNING_RECOVERY_AND_REPLAN_CONTRACT_V1: QUEUED requires classification.
            # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1:
            #   stream registry is the only live runtime evidence.
            # All fields are additive; existing recoverable/inspection_only preserved unchanged.

            actionability = "INSPECTION_ONLY"
            runtime_recovery_eligible = False
            planning_actionability = None
            replan_eligible = False
            live_planning = False
            stale_bg_id = False
            projection_expected_missing = False
            taskhub_action = "INSPECT"
            action_label = "View"

            if status == "QUEUED":
                # Check for live stream registry entry as the only live evidence.
                # Do NOT use bg_id_map alone. Do NOT use projection presence.
                has_live_stream = False
                try:
                    with _stream_registry_lock:
                        for entry in _stream_registry.values():
                            if entry.get("orchestrator_workflow_id") == wf_id:
                                has_live_stream = True
                                break
                except Exception:
                    has_live_stream = False

                if has_live_stream:
                    # QUEUED_LIVE_PLANNING
                    actionability = "LIVE_PLANNING"
                    runtime_recovery_eligible = False
                    planning_actionability = "LIVE_PLANNING"
                    replan_eligible = False
                    live_planning = True
                    stale_bg_id = False
                    projection_expected_missing = True
                    taskhub_action = None
                    action_label = None
                else:
                    # QUEUED_REPLAN_REQUIRED
                    actionability = "PLANNING_REPLAN"
                    runtime_recovery_eligible = False
                    planning_actionability = "REPLAN_REQUIRED"
                    # Replan eligibility: planning_request.original_prompt OR goal must exist
                    _wf_data = None
                    try:
                        _wf_data = load_workflow(wf_id)
                    except Exception:
                        pass
                    _has_prompt = False
                    if _wf_data and isinstance(_wf_data.get("planning_request"), dict):
                        _has_prompt = bool(_wf_data["planning_request"].get("original_prompt"))
                    _has_goal = bool(_wf_data and _wf_data.get("goal"))
                    replan_eligible = _has_prompt or _has_goal
                    live_planning = False
                    # stale if bg_id_map has entries but no live stream (confirmed by has_live_stream==False)
                    _bg_ids = wf_to_bg.get(wf_id, [])
                    stale_bg_id = len(_bg_ids) > 0
                    projection_expected_missing = True
                    taskhub_action = "RESUME_PLANNING"
                    action_label = "Resume Planning / Replan"

            elif status in ("ACTIVE", "ACTIVATING", "PAUSED", "BLOCKED", "PENDING_RECOVERY"):
                actionability = "RUNTIME_RECOVERABLE"
                runtime_recovery_eligible = True
                planning_actionability = None
                replan_eligible = False
                live_planning = False
                stale_bg_id = False
                projection_expected_missing = False
                taskhub_action = "RESUME"
                action_label = "Resume"

            elif status == "FAILED":
                # === ISSUE-062: Backend-authored FAILED actionability metadata ===
                # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: lifecycle state ≠ actionability.
                # Load persisted metadata; default to actionable for backward compatibility.
                _wf_data = None
                try:
                    _wf_data = load_workflow(wf_id)
                except Exception:
                    pass

                _failed_recoverable = True
                _retry_disabled_reason = None
                _actionability_reason = "retry_target_available"
                _terminalization_reason = None
                if _wf_data and isinstance(_wf_data, dict):
                    _failed_recoverable = _wf_data.get("failed_recoverable")
                    if _failed_recoverable is None:
                        _failed_recoverable = True
                    _retry_disabled_reason = _wf_data.get("retry_disabled_reason")
                    _actionability_reason = _wf_data.get("actionability_reason", "retry_target_available")
                    _terminalization_reason = _wf_data.get("terminalization_reason")

                # Compute retry_eligible: failed_recoverable AND valid retry target exists
                _retry_eligible = False
                if _failed_recoverable:
                    try:
                        from system.orchestrator.projection_schema import _compute_retry_target_step_id
                        _steps = _wf_data.get("steps", []) if _wf_data else []
                        _retry_target = _compute_retry_target_step_id(_steps, lifecycle_status="FAILED")
                        _retry_eligible = _retry_target is not None
                    except Exception:
                        _retry_eligible = True  # backward compat: default permissive

                actionability = "RUNTIME_RECOVERABLE" if _failed_recoverable else "INSPECTION_ONLY"
                runtime_recovery_eligible = _failed_recoverable
                planning_actionability = None
                replan_eligible = False
                live_planning = False
                stale_bg_id = False
                projection_expected_missing = False
                taskhub_action = "RETRY" if _retry_eligible else "INSPECT"
                action_label = "Retry Failed Step" if _retry_eligible else "View"

            elif status in ("COMPLETED", "CANCELLED", "QUARANTINED"):
                actionability = "INSPECTION_ONLY"
                runtime_recovery_eligible = False
                planning_actionability = None
                replan_eligible = False
                live_planning = False
                stale_bg_id = False
                projection_expected_missing = False
                taskhub_action = "INSPECT"
                action_label = "View"

            # === ISSUE-098KX: Compute explicit membership eligibility for all statuses ===
            # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: lifecycle state ≠ actionability.
            # Frontend MUST NOT infer membership from status alone.
            _taskhub_eligible = None
            _history_eligible = None
            if status == "FAILED":
                _taskhub_eligible = (
                    _failed_recoverable and
                    retention_state not in ("archived", "dismissed")
                )
                _history_eligible = (
                    not _failed_recoverable or
                    retention_state in ("archived", "dismissed")
                )
            elif status in ("COMPLETED", "CANCELLED", "QUARANTINED"):
                _taskhub_eligible = False
                _history_eligible = True
            elif status == "QUEUED":
                # QUEUED is actionable if replan is required; not actionable during live planning
                _taskhub_eligible = actionability in ("PLANNING_REPLAN",)
                _history_eligible = False
            else:
                # ACTIVE, ACTIVATING, PAUSED, BLOCKED, PENDING_RECOVERY
                _taskhub_eligible = True
                _history_eligible = False

            _workflow_entry = {
                "workflow_id": wf_id,
                "status": status,
                "recoverable": recoverable,
                "inspection_only": inspection_only,
                "retention_state": retention_state,
                "execution_generation": state.get("execution_generation", 1),
                "bg_ids": wf_to_bg.get(wf_id, []),
                "last_updated": state.get("last_updated"),
                # === ISSUE-055B Phase 1A additive fields ===
                "actionability": actionability,
                "runtime_recovery_eligible": runtime_recovery_eligible,
                "planning_actionability": planning_actionability,
                "replan_eligible": replan_eligible,
                "live_planning": live_planning,
                "stale_bg_id": stale_bg_id,
                "projection_expected_missing": projection_expected_missing,
                "taskhub_action": taskhub_action,
                "action_label": action_label,
                # === ISSUE-098KX: Explicit membership eligibility ===
                "taskhub_eligible": _taskhub_eligible,
                "history_eligible": _history_eligible,
            }
            # === ISSUE-062: Add FAILED actionability metadata for FAILED workflows ===
            if status == "FAILED":
                _workflow_entry["failed_recoverable"] = _failed_recoverable
                _workflow_entry["retry_eligible"] = _retry_eligible
                _workflow_entry["retry_disabled_reason"] = _retry_disabled_reason
                _workflow_entry["actionability_reason"] = _actionability_reason
                _workflow_entry["terminalization_reason"] = _terminalization_reason
            workflows.append(_workflow_entry)

    # === ISSUE-098KZ: Include persisted workflows not in lifecycle registry ===
    # After backend restart, FAILED workflows have no bg_id and are not restored
    # to the registry. They exist in active_workflows/ and must be discoverable
    # via the authoritative endpoint so TaskHubTab can display them.
    _existing_ids = {w["workflow_id"] for w in workflows}
    # Build file-mtime lookup for last_updated fallback
    _active_file_mtims = {}
    try:
        _aw_dir = os.path.join(ROOT, "memory", "active_workflows")
        if os.path.isdir(_aw_dir):
            for _fname in os.listdir(_aw_dir):
                if _fname.endswith(".json"):
                    _fid = _fname[:-5]
                    try:
                        _active_file_mtims[_fid] = os.path.getmtime(os.path.join(_aw_dir, _fname))
                    except OSError:
                        pass
    except Exception:
        pass
    try:
        _persisted_list = load_active_workflows()
        for _pwf in _persisted_list:
            if not isinstance(_pwf, dict):
                continue
            _pwf_id = _pwf.get("id")
            if not _pwf_id or _pwf_id in _existing_ids:
                continue
            _pwf_status = _pwf.get("status", "UNKNOWN")
            _pwf_retention = _pwf.get("retention_state", "retained")

            _pwf_recoverable = _pwf_status not in ("COMPLETED", "FAILED", "CANCELLED", "QUARANTINED")
            _pwf_inspection_only = _pwf_status in ("CANCELLED", "COMPLETED")

            # FAILED actionability metadata
            _pwf_failed_recoverable = None
            _pwf_retry_eligible = None
            _pwf_retry_disabled_reason = None
            _pwf_actionability_reason = None
            _pwf_terminalization_reason = None
            if _pwf_status == "FAILED":
                _pwf_failed_recoverable = _pwf.get("failed_recoverable")
                if _pwf_failed_recoverable is None:
                    _pwf_failed_recoverable = True
                _pwf_retry_disabled_reason = _pwf.get("retry_disabled_reason")
                _pwf_actionability_reason = _pwf.get("actionability_reason", "retry_target_available")
                _pwf_terminalization_reason = _pwf.get("terminalization_reason")
                if _pwf_failed_recoverable:
                    try:
                        from system.orchestrator.projection_schema import _compute_retry_target_step_id
                        _pwf_retry_target = _compute_retry_target_step_id(_pwf.get("steps", []), lifecycle_status="FAILED")
                        _pwf_retry_eligible = _pwf_retry_target is not None
                    except Exception:
                        _pwf_retry_eligible = True
                else:
                    _pwf_retry_eligible = False

            # Membership eligibility
            if _pwf_status == "FAILED":
                _pwf_taskhub = _pwf_failed_recoverable and _pwf_retention not in ("archived", "dismissed")
                _pwf_history = (not _pwf_failed_recoverable) or _pwf_retention in ("archived", "dismissed")
            elif _pwf_status in ("COMPLETED", "CANCELLED", "QUARANTINED"):
                _pwf_taskhub = False
                _pwf_history = True
            elif _pwf_status == "QUEUED":
                _pwf_taskhub = False
                _pwf_history = False
            else:
                _pwf_taskhub = True
                _pwf_history = False

            # Actionability
            if _pwf_status == "QUEUED":
                _pwf_actionability = "PLANNING_REPLAN"
                _pwf_taskhub_action = "RESUME_PLANNING"
                _pwf_action_label = "Resume Planning / Replan"
            elif _pwf_status in ("ACTIVE", "ACTIVATING", "PAUSED", "BLOCKED", "PENDING_RECOVERY"):
                _pwf_actionability = "RUNTIME_RECOVERABLE"
                _pwf_taskhub_action = "RESUME"
                _pwf_action_label = "Resume"
            elif _pwf_status == "FAILED":
                _pwf_actionability = "RUNTIME_RECOVERABLE" if _pwf_failed_recoverable else "INSPECTION_ONLY"
                _pwf_taskhub_action = "RETRY" if _pwf_retry_eligible else "INSPECT"
                _pwf_action_label = "Retry Failed Step" if _pwf_retry_eligible else "View"
            else:
                _pwf_actionability = "INSPECTION_ONLY"
                _pwf_taskhub_action = "INSPECT"
                _pwf_action_label = "View"

            _pwf_entry = {
                "workflow_id": _pwf_id,
                "status": _pwf_status,
                "recoverable": _pwf_recoverable,
                "inspection_only": _pwf_inspection_only,
                "retention_state": _pwf_retention,
                "execution_generation": _pwf.get("execution_generation", 1),
                "bg_ids": wf_to_bg.get(_pwf_id, []),
                "last_updated": _pwf.get("updated_at") or _pwf.get("last_updated") or _active_file_mtims.get(_pwf_id),
                "actionability": _pwf_actionability,
                "runtime_recovery_eligible": _pwf_recoverable,
                "planning_actionability": None,
                "replan_eligible": False,
                "live_planning": False,
                "stale_bg_id": False,
                "projection_expected_missing": False,
                "taskhub_action": _pwf_taskhub_action,
                "action_label": _pwf_action_label,
                "taskhub_eligible": _pwf_taskhub,
                "history_eligible": _pwf_history,
            }
            if _pwf_status == "FAILED":
                _pwf_entry["failed_recoverable"] = _pwf_failed_recoverable
                _pwf_entry["retry_eligible"] = _pwf_retry_eligible
                _pwf_entry["retry_disabled_reason"] = _pwf_retry_disabled_reason
                _pwf_entry["actionability_reason"] = _pwf_actionability_reason
                _pwf_entry["terminalization_reason"] = _pwf_terminalization_reason
            workflows.append(_pwf_entry)
    except Exception:
        pass

    return {"workflows": workflows}


def _list_all_persisted_workflows() -> list:
    """
    Enumerate all persisted workflow records for historical/inspection purposes.

    Per ISSUE-061 Phase 1:
    - Read-only. Does not mutate lifecycle, registry, or projections.
    - Scans active_workflows/ and workflows.json.
    - Deduplicates by workflow_id (active_workflows preferred over workflows.json).
    - Injects authoritative lifecycle when available, but does NOT derive
      Task Hub recoverability/actionability hints.
    - Tolerates malformed files by skipping silently.
    - Marks projection/trace/event availability safely without error emission.

    Returns:
        List of workflow metadata dicts for History/Archive inspection.
    """
    import os
    import json

    _ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    _ACTIVE_DIR = os.path.join(_ROOT, "memory", "active_workflows")
    _WORKFLOWS_JSON = os.path.join(_ROOT, "memory", "workflows.json")
    _PROJECTION_STORES_PATH = os.path.join(_ROOT, "memory", "projection_stores.json")
    _EVENT_DIR = os.path.join(_ROOT, "memory", "events")
    _TRACE_DIR = os.path.join(_ROOT, "traces")

    workflows_by_id: dict = {}
    from_active_workflows: set = set()
    from_registry: set = set()

    # Helpers for history_sort_timestamp derivation
    def _best_timestamp(wf_dict):
        """Return (timestamp_float_or_none, source_label) from best available evidence."""
        # 1. updated_at
        for key in ("updated_at", "last_updated", "retention_updated_at"):
            val = wf_dict.get(key)
            if val is not None:
                ts = _to_timestamp(val)
                if ts is not None:
                    return (ts, "updated_at")
        # 2. terminal timestamps
        for key in ("completed_at", "terminalized_at", "finished_at", "cancelled_at"):
            val = wf_dict.get(key)
            if val is not None:
                ts = _to_timestamp(val)
                if ts is not None:
                    return (ts, key)
        # 3. created_at / submitted_at / started_at
        for key in ("created_at", "submitted_at", "started_at"):
            val = wf_dict.get(key)
            if val is not None:
                ts = _to_timestamp(val)
                if ts is not None:
                    return (ts, key)
        # === ISSUE-098KY: nested timestamps for workflows.json workflows ===
        # 4. planning_request.submitted_at
        pr = wf_dict.get("planning_request")
        if isinstance(pr, dict):
            val = pr.get("submitted_at")
            if val is not None:
                ts = _to_timestamp(val)
                if ts is not None:
                    return (ts, "planning_request.submitted_at")
        # 5. context.step_history[*].timestamp (latest)
        ctx = wf_dict.get("context")
        if isinstance(ctx, dict):
            sh = ctx.get("step_history")
            if isinstance(sh, list) and sh:
                last_sh = sh[-1]
                if isinstance(last_sh, dict):
                    val = last_sh.get("timestamp")
                    if val is not None:
                        ts = _to_timestamp(val)
                        if ts is not None:
                            return (ts, "context.step_history.latest")
        # 6. output timestamp
        out = wf_dict.get("output")
        if isinstance(out, dict):
            val = out.get("timestamp") or out.get("completed_at")
            if val is not None:
                ts = _to_timestamp(val)
                if ts is not None:
                    return (ts, "output.timestamp")
        return (None, None)

    def _to_timestamp(val):
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                pass
        return None

    # 1. Scan active_workflows/ (non-COMPLETED + retention-modified workflows)
    active_file_mtims: dict = {}
    if os.path.isdir(_ACTIVE_DIR):
        for filename in os.listdir(_ACTIVE_DIR):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(_ACTIVE_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict) or "id" not in data:
                    continue
                wf_id = data["id"]
                # Inject authoritative lifecycle if available (read-only lookup)
                try:
                    from system.orchestrator.workflow_control import inject_authoritative_lifecycle_into_workflow
                    inject_authoritative_lifecycle_into_workflow(data)
                except Exception:
                    pass
                workflows_by_id[wf_id] = data
                from_active_workflows.add(wf_id)
                try:
                    active_file_mtims[wf_id] = os.path.getmtime(filepath)
                except OSError:
                    pass
            except (json.JSONDecodeError, OSError):
                # Malformed or unreadable — skip silently per tolerance requirement
                continue

    # 2. Read workflows.json (COMPLETED workflows only)
    workflows_json_mtime = None
    if os.path.isfile(_WORKFLOWS_JSON):
        try:
            workflows_json_mtime = os.path.getmtime(_WORKFLOWS_JSON)
        except OSError:
            pass
        try:
            with open(_WORKFLOWS_JSON, "r", encoding="utf-8") as f:
                completed_list = json.load(f)
            if isinstance(completed_list, list):
                for data in completed_list:
                    if not isinstance(data, dict) or "id" not in data:
                        continue
                    wf_id = data["id"]
                    # Skip if already found in active_workflows/ (more recent source)
                    if wf_id in workflows_by_id:
                        continue
                    try:
                        from system.orchestrator.workflow_control import inject_authoritative_lifecycle_into_workflow
                        inject_authoritative_lifecycle_into_workflow(data)
                    except Exception:
                        pass
                    workflows_by_id[wf_id] = data
        except (json.JSONDecodeError, OSError):
            pass

    # 3. Registry fallback: include workflows in runtime registry not found on disk.
    # Per ISSUE-061 Phase 4 remediation: completed workflows may be cleaned from
    # active_workflows/ before workflows.json append occurs. Registry is read-only
    # here — we only synthesize a minimal record so History remains complete.
    registry_fallback_timestamps: dict = {}
    try:
        from system.orchestrator.workflow_control import _workflow_state_registry, _workflow_state_lock
        with _workflow_state_lock:
            for _reg_id, _reg_state in _workflow_state_registry.items():
                if _reg_id in workflows_by_id:
                    continue
                _reg_status = _reg_state.get("status", "UNKNOWN")
                # Skip transient/bootstrap states that have no historical value
                if _reg_status in ("ACTIVATING", "PENDING_RECOVERY", None):
                    continue
                workflows_by_id[_reg_id] = {
                    "id": _reg_id,
                    "status": _reg_status,
                    "retention_state": "retained",
                    "last_updated": _reg_state.get("last_updated"),
                }
                from_registry.add(_reg_id)
                registry_fallback_timestamps[_reg_id] = _reg_state.get("last_updated")
    except Exception:
        pass

    # 4. Pre-load persisted projection store keys for cheap existence check
    persisted_projection_ids: set = set()
    try:
        if os.path.isfile(_PROJECTION_STORES_PATH):
            with open(_PROJECTION_STORES_PATH, "r", encoding="utf-8") as f:
                proj_data = json.load(f)
            if isinstance(proj_data, dict):
                persisted_projection_ids = set(proj_data.keys())
    except Exception:
        pass

    results = []
    for wf_id, wf in workflows_by_id.items():
        status = wf.get("status", "UNKNOWN")
        retention_state = wf.get("retention_state", "retained")

        # Extract human-readable metadata safely
        goal = wf.get("goal") or wf.get("summary") or wf.get("title")
        original_prompt = None
        planning_request = wf.get("planning_request")
        if isinstance(planning_request, dict):
            original_prompt = planning_request.get("original_prompt")

        # --- Projection availability (safe, read-only) ---
        projection_available = False
        if _get_proj_mgr is not None:
            try:
                if _get_proj_mgr().get_latest_projection(wf_id) is not None:
                    projection_available = True
            except Exception:
                pass
        # Fallback: persisted store on disk (may not be loaded into memory)
        if not projection_available and wf_id in persisted_projection_ids:
            projection_available = True

        # --- Trace availability (safe, read-only) ---
        trace_available = False
        try:
            from system.orchestrator import trace_collector
            if trace_collector.get_trace(wf_id) is not None:
                trace_available = True
        except Exception:
            pass
        if not trace_available:
            trace_file = os.path.join(_TRACE_DIR, f"{wf_id}.json")
            if os.path.isfile(trace_file):
                trace_available = True

        # --- Event availability (safe, read-only) ---
        events_available = False
        event_count = 0
        safe_evt_id = "".join(c for c in wf_id if c.isalnum() or c in ("-", "_"))
        if not safe_evt_id:
            safe_evt_id = "unknown"
        event_file = os.path.join(_EVENT_DIR, f"{safe_evt_id}.jsonl")
        if os.path.isfile(event_file):
            events_available = True
            # Cheap approximate count: non-empty lines in JSONL journal
            try:
                with open(event_file, "r", encoding="utf-8") as f:
                    event_count = sum(1 for line in f if line.strip())
            except Exception:
                pass

        # Derive history_sort_timestamp from best available evidence
        hst, hss = _best_timestamp(wf)
        if hst is None and events_available:
            try:
                hst = os.path.getmtime(event_file)
                hss = "event_file_mtime"
            except OSError:
                pass
        if hst is None and wf_id in from_active_workflows:
            hst = active_file_mtims.get(wf_id)
            if hst is not None:
                hss = "active_file_mtime"
        if hst is None and wf_id not in from_active_workflows and not from_registry:
            hst = workflows_json_mtime
            if hst is not None:
                hss = "workflows_json_file_mtime"
        if hst is None and wf_id in from_registry:
            hst = registry_fallback_timestamps.get(wf_id)
            if hst is not None:
                hss = "registry_fallback"
        if hst is None:
            hst = 0.0
            hss = "none"

        # === ISSUE-098KY: Compute explicit membership eligibility for ALL statuses ===
        # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: lifecycle state ≠ actionability.
        # Frontend MUST NOT infer membership from status alone.
        _failed_recoverable = None
        _retry_eligible = None
        _retry_disabled_reason = None
        _actionability_reason = None
        _terminalization_reason = None
        if status == "FAILED":
            _failed_recoverable = wf.get("failed_recoverable")
            if _failed_recoverable is None:
                _failed_recoverable = True  # backward compat default
            _retry_disabled_reason = wf.get("retry_disabled_reason")
            _actionability_reason = wf.get("actionability_reason", "retry_target_available")
            _terminalization_reason = wf.get("terminalization_reason")
            # retry_eligible: failed_recoverable + valid retry target
            if _failed_recoverable:
                try:
                    from system.orchestrator.projection_schema import _compute_retry_target_step_id
                    _retry_target = _compute_retry_target_step_id(wf.get("steps", []))
                    _retry_eligible = _retry_target is not None
                except Exception:
                    _retry_eligible = True
            else:
                _retry_eligible = False

        # Membership eligibility: explicit for every status
        if status == "FAILED":
            _taskhub_eligible = _failed_recoverable and retention_state not in ("archived", "dismissed")
            _history_eligible = (not _failed_recoverable) or retention_state in ("archived", "dismissed")
        elif status in ("COMPLETED", "CANCELLED", "QUARANTINED"):
            _taskhub_eligible = False
            _history_eligible = True
        elif status == "QUEUED":
            _taskhub_eligible = False  # QUEUED history membership is replan-specific; default false
            _history_eligible = False
        else:
            # ACTIVE, ACTIVATING, PAUSED, BLOCKED, PENDING_RECOVERY
            _taskhub_eligible = True
            _history_eligible = False

        record = {
            "workflow_id": wf_id,
            "status": status,
            "retention_state": retention_state,
            "inspection_only": status in ("CANCELLED", "COMPLETED"),
            "archived": retention_state == "archived",
            "dismissed": retention_state == "dismissed",
            "created_at": wf.get("created_at") or wf.get("submitted_at") or wf.get("started_at"),
            "updated_at": wf.get("updated_at") or wf.get("last_updated") or wf.get("retention_updated_at"),
            "goal": goal,
            "original_prompt": original_prompt,
            "projection_available": projection_available,
            "trace_available": trace_available,
            "events_available": events_available,
            "event_count": event_count if events_available else 0,
            "planning_actionability": planning_request.get("planning_status") if isinstance(planning_request, dict) else None,
            "actionability": wf.get("actionability"),
            "source": (
                "active_workflows" if wf_id in from_active_workflows
                else "registry" if wf_id in from_registry
                else "workflows_json"
            ),
            "history_sort_timestamp": hst,
            "history_sort_source": hss,
            # === ISSUE-062: FAILED actionability metadata ===
            "failed_recoverable": _failed_recoverable,
            "retry_eligible": _retry_eligible,
            "retry_disabled_reason": _retry_disabled_reason,
            "actionability_reason": _actionability_reason,
            "terminalization_reason": _terminalization_reason,
            "taskhub_eligible": _taskhub_eligible,
            "history_eligible": _history_eligible,
        }
        results.append(record)

    # Sort by history_sort_timestamp descending (most recent first)
    def _sort_key(r):
        ts = r.get("history_sort_timestamp")
        if isinstance(ts, (int, float)):
            return (-float(ts), r["workflow_id"])
        return (0, r["workflow_id"])

    results.sort(key=_sort_key)
    return results


@app.get("/workflows/historical")
def get_historical_workflows():
    """
    GET /workflows/historical

    Returns a non-authoritative, inspection-oriented list of all persisted workflows.

    Per WORKFLOW_RETENTION_AND_ARCHIVAL_CONTRACT_V1:
    - History represents previously existing workflows.
    - History is observability-oriented and inspection-oriented.
    - History is NOT recoverability-oriented.

    This endpoint:
    - Enumerates persisted workflow records from active_workflows/ and workflows.json.
    - Does not rely solely on _workflow_state_registry.
    - Includes terminal, archived, dismissed, and retained workflows.
    - Is read-only and does not mutate lifecycle state, runtime registry, or projections.
    - Does NOT derive Task Hub actionability, recoverability, or authority hints.
    - Tolerates old/dirty/malformed workflow files by skipping or returning degraded metadata.
    - Marks projection_available safely without emitting projection_fetch_error.
    """
    workflows = _list_all_persisted_workflows()
    return {"workflows": workflows}


@app.get("/background/status/{workflow_id}")
def background_status(workflow_id: str):
    """GET /background/status/{id} → background_manager.get_status(id)"""
    status = _bg_manager.get_status(workflow_id)
    if status is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    return status


# =============================================================================
# PHASE 2.5 — TRACE RETRIEVAL
# =============================================================================

@app.get("/trace/{workflow_id}")
def get_trace(workflow_id: str):
    """
    GET /trace/{workflow_id}
    Returns trace data for specific workflow.
    Tries memory first, then file fallback.
    Returns 404 if not found.
    Trace data is projected to remove execution fields from steps.
    """
    # Try memory first (current collectors)
    from system.orchestrator import trace_collector
    trace = trace_collector.get_trace(workflow_id)
    
    if trace is None:
        # Fallback to file storage
        try:
            import os
            import json
            trace_file = os.path.join("traces", f"{workflow_id}.json")
            if os.path.exists(trace_file):
                with open(trace_file, "r") as f:
                    trace = json.load(f)
        except Exception:
            # File read error - treat as not found
            pass
    
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    
    # Apply projection to trace steps if present
    if trace and isinstance(trace, dict) and "steps" in trace:
        # Clean trace steps - remove execution_result and tool_call
        cleaned_steps = []
        for step in trace.get("steps", []):
            if not isinstance(step, dict):
                cleaned_steps.append(step)
                continue
            
            cleaned_step = {
                "step_id": step.get("step_id"),
                "status": step.get("status"),
                "purpose": step.get("purpose"),
                "retries": step.get("retries", 0)
            }
            
            # Keep governance_decision if present
            if step.get("governance_decision"):
                cleaned_step["governance_decision"] = step["governance_decision"]
            
            cleaned_steps.append(cleaned_step)
        
        trace["steps"] = cleaned_steps
    
    return trace


# =============================================================================
# PHASE 2.6 — LIVE EVENT STREAMING (STATE-DRIVEN)
# =============================================================================

@app.get("/events/{workflow_id}")
def get_events(
    workflow_id: str,
    since: int = -1,
    since_sequence: int = -1,
    limit: int = 100,
):
    """
    GET /events/{workflow_id}?since={event_id}&since_sequence={seq}&limit={count}
    Returns live events for workflow state streaming.

    Per HAND_ARCHITECTURE_V2 Section 15: LIVE mode provides step-by-step visibility
    Per CONTROL_MODEL: Events are advisory, non-authoritative
    Per TRACE_LOGGING_CONTRACT_V1: UI uses STATE (events), not trace, for live updates

    Per REPLAY_QUERY_PAGINATION:
    - since_sequence (bus_sequence_id) is the authoritative monotonic cursor.
    - since (event_id index) is legacy; preserved for backward compatibility.

    Args:
        since: Return only events after this event index (legacy, optional)
        since_sequence: Return only events with bus_sequence_id > since_sequence (authoritative)
        limit: Maximum events to return (default 100)

    Returns:
        List of events with:
        - event_type: step_started, step_completed, governance_decision, etc.
        - timestamp: ISO8601 timestamp
        - data: Event payload (step_id, status, result, etc.)
    """
    from system.interface.event_bus import get_events as _get_events

    # Prefer authoritative since_sequence cursor; fall back to legacy since_event_id
    since_seq = since_sequence if since_sequence >= 0 else None
    since_event_id = since if since >= 0 and since_seq is None else None
    events = _get_events(
        workflow_id,
        since_event_id=since_event_id,
        since_sequence=since_seq,
        limit=limit,
    )

    # Per PROJECTION_CONTINUITY_CONTRACT_V1 §6 (SUB-PHASE 3D):
    # Sort by bus_sequence_id (monotonic per-workflow counter) when available;
    # fall back to timestamp for backward compatibility.
    # bus_sequence_id is deterministic; timestamp sort can have same-ms ties.
    # Per PROJECTION_CONTINUITY_CONTRACT_V1 §11: detect invalid stream ordering.
    has_seq = any("bus_sequence_id" in e for e in events)
    if has_seq:
        events.sort(key=lambda e: e.get("bus_sequence_id", 0))
    else:
        events.sort(key=lambda e: e.get("timestamp", ""))

    # Add sequential IDs for since-based polling (backward compatibility)
    base = since + 1 if since >= 0 else 0
    for i, event in enumerate(events):
        event["event_id"] = base + i

    # Per PROJECTION_CONTINUITY_CONTRACT_V1 §11 (SUB-PHASE 3D):
    # Expose latest_bus_sequence_id for reconnect continuity gap detection.
    from system.interface.event_bus import get_latest_sequence as _get_latest_seq
    latest_bus_seq = _get_latest_seq(workflow_id)

    return {
        "workflow_id": workflow_id,
        "events": events,
        "count": len(events),
        "latest_event_id": base + len(events) - 1 if events else since,
        "latest_bus_sequence_id": latest_bus_seq,  # authoritative reconnect cursor
    }


# =============================================================================
# ISSUE-074A — SSE Event-Hint Endpoint (Backend Foundation Slice)
# =============================================================================

@app.get("/events/{workflow_id}/sse")
async def get_events_sse(
    workflow_id: str,
    request: Request,
):
    """
    GET /events/{workflow_id}/sse
    Server-Sent Events endpoint for event-hint delivery.

    Per ISSUE-074A SSE AUDIT:
    - Workflow-scoped SSE transport only.
    - Payload is event-hint only: event_type, bus_sequence_id, timestamp, workflow_id.
    - NO projection snapshots. NO execution_result. NO lifecycle authority.
    - Polling fallback preserved: existing /events/{workflow_id} remains unchanged.
    - Disconnect cleanup removes EventBus subscriber to prevent leaks.

    Per PROJECTION_CONTINUITY_CONTRACT_V1 §11:
    - Last-Event-ID header maps to bus_sequence_id for reconnect gap detection.
    - Missed events are replayed from journal on reconnect.
    """
    from system.interface.event_bus import get_event_bus, get_events

    bus = get_event_bus()
    queue = bus.subscribe_async(workflow_id)

    # Per PROJECTION_CONTINUITY_CONTRACT_V1 §11:
    # Last-Event-ID header carries last known bus_sequence_id for gap repair.
    last_event_id = request.headers.get("last-event-id")
    since_sequence = None
    if last_event_id is not None:
        try:
            since_sequence = int(last_event_id)
        except ValueError:
            since_sequence = None

    async def _event_generator():
        try:
            # If reconnecting with Last-Event-ID, replay missed events first
            if since_sequence is not None:
                missed_events = get_events(
                    workflow_id,
                    since_sequence=since_sequence,
                    limit=100,
                )
                # Sort by bus_sequence_id for deterministic delivery
                missed_events.sort(key=lambda e: e.get("bus_sequence_id", 0))
                for event in missed_events:
                    sse_payload = {
                        "event_type": event.get("event_type"),
                        "bus_sequence_id": event.get("bus_sequence_id"),
                        "timestamp": event.get("timestamp"),
                        "workflow_id": event.get("workflow_id"),
                    }
                    sse_id = str(event.get("bus_sequence_id", ""))
                    sse_data = json.dumps(sse_payload)
                    yield f"id: {sse_id}\nevent: workflow_event\ndata: {sse_data}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # SSE comment heartbeat to keep connection alive through proxies
                    yield ":heartbeat\n\n"
                    continue

                # Build event-hint-only payload
                # Per ISSUE-074A: NO projection snapshots, NO execution_result
                sse_payload = {
                    "event_type": event.get("event_type"),
                    "bus_sequence_id": event.get("bus_sequence_id"),
                    "timestamp": event.get("timestamp"),
                    "workflow_id": event.get("workflow_id"),
                }
                sse_id = str(event.get("bus_sequence_id", ""))
                sse_data = json.dumps(sse_payload)

                yield f"id: {sse_id}\nevent: workflow_event\ndata: {sse_data}\n\n"

        finally:
            # Per ISSUE-074A: Disconnect cleanup MUST remove subscriber
            bus.unsubscribe_async(workflow_id, queue)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
    )


# =============================================================================
# PHASE 2.4 — APPROVAL (Contract-Safe, ISSUE-096B)
# =============================================================================
# Per USER_APPROVAL_CONTRACT_V1:
# - Backend owns approval request creation, identity, status, expiry, validation
# - approval_id is the stable identity key
# - Frontend sends intent only; backend validates and resolves
# =============================================================================

class ApprovalResolveRequest(BaseModel):
    approved: bool


@app.get("/approvals/{workflow_id}")
def list_pending_approvals(workflow_id: str):
    """
    GET /approvals/{workflow_id}
    Returns PENDING approval requests for the specified workflow.
    Per USER_APPROVAL_CONTRACT_V1 §12: workflow-scoped lookup only.
    """
    pending = get_pending_approvals_for_workflow(workflow_id)
    return {
        "workflow_id": workflow_id,
        "pending": [req.to_dict() for req in pending],
        "count": len(pending),
    }


@app.post("/approvals/{approval_id}/approve")
def approve_by_id(approval_id: str):
    """
    POST /approvals/{approval_id}/approve
    Resolve a pending approval as APPROVED if still legal.
    Backend validates: not expired, workflow not terminal, step exists, etc.
    """
    # Gather validation context
    request = get_approval(approval_id)
    if request is None:
        raise HTTPException(status_code=404, detail="approval_id not found")

    validate = {"workflow_id": request.workflow_id}

    # Workflow status validation
    try:
        wf_state = _get_workflow_state(request.workflow_id)
        validate["workflow_status"] = wf_state.get("status", "UNKNOWN") if wf_state else "UNKNOWN"
    except Exception:
        pass

    # Execution generation validation (if available on step)
    try:
        plan = get_plan(request.workflow_id)
        if plan and plan.get("steps"):
            for s in plan.get("steps", []):
                if s.get("id") == request.step_id:
                    validate["step_exists"] = True
                    validate["execution_generation"] = s.get("execution_generation")
                    break
            else:
                validate["step_exists"] = False
    except Exception:
        pass

    result = resolve_approval(approval_id, approved=True, actor="operator", validate=validate)

    if not result["success"]:
        status_code = 409
        if result["status"] in ("not_found", "mismatch"):
            status_code = 404
        elif result["status"] in ("EXPIRED", "SUPERSEDED", "CANCELLED"):
            status_code = 410
        raise HTTPException(status_code=status_code, detail=result["error"])

    return {
        "status": "ok",
        "approval_id": approval_id,
        "resolution": "APPROVED",
    }


@app.post("/approvals/{approval_id}/reject")
def reject_by_id(approval_id: str):
    """
    POST /approvals/{approval_id}/reject
    Resolve a pending approval as REJECTED if still legal.
    """
    request = get_approval(approval_id)
    if request is None:
        raise HTTPException(status_code=404, detail="approval_id not found")

    validate = {"workflow_id": request.workflow_id}
    try:
        wf_state = _get_workflow_state(request.workflow_id)
        validate["workflow_status"] = wf_state.get("status", "UNKNOWN") if wf_state else "UNKNOWN"
    except Exception:
        pass

    try:
        plan = get_plan(request.workflow_id)
        if plan and plan.get("steps"):
            for s in plan.get("steps", []):
                if s.get("id") == request.step_id:
                    validate["step_exists"] = True
                    validate["execution_generation"] = s.get("execution_generation")
                    break
            else:
                validate["step_exists"] = False
    except Exception:
        pass

    result = resolve_approval(approval_id, approved=False, actor="operator", validate=validate)

    if not result["success"]:
        status_code = 409
        if result["status"] in ("not_found", "mismatch"):
            status_code = 404
        elif result["status"] in ("EXPIRED", "SUPERSEDED", "CANCELLED"):
            status_code = 410
        raise HTTPException(status_code=status_code, detail=result["error"])

    return {
        "status": "ok",
        "approval_id": approval_id,
        "resolution": "REJECTED",
    }


# ── LEGACY ENDPOINTS (DEPRECATED — 410 Gone) ─────────────────────────────────
# Per USER_APPROVAL_CONTRACT_V1 §12: old step_id-keyed endpoints are not contract-safe.

@app.get("/approval/pending")
def approval_pending_legacy():
    """DEPRECATED. Use GET /approvals/{workflow_id}"""
    raise HTTPException(
        status_code=410,
        detail="DEPRECATED: Use GET /approvals/{workflow_id} instead. Old step_id-keyed approvals are not contract-safe.",
    )


@app.post("/approve")
def approve_step_legacy(req: ApprovalRequest):
    """DEPRECATED. Use POST /approvals/{approval_id}/approve"""
    raise HTTPException(
        status_code=410,
        detail="DEPRECATED: Use POST /approvals/{approval_id}/approve instead. Old step_id-keyed approvals are not contract-safe.",
    )


@app.post("/deny")
def deny_step_legacy(req: ApprovalRequest):
    """DEPRECATED. Use POST /approvals/{approval_id}/reject"""
    raise HTTPException(
        status_code=410,
        detail="DEPRECATED: Use POST /approvals/{approval_id}/reject instead. Old step_id-keyed approvals are not contract-safe.",
    )


# =============================================================================
# PHASE 2.5B — USER CONTROL (Contract-Safe, ISSUE-098C)
# =============================================================================
# Per USER_CONTROL_CONTRACT_V2:
# - Backend owns user-control request creation, identity, status, expiry, validation
# - control_id is the stable identity key
# - Frontend sends intent only; backend validates and resolves
# - ACCEPT/REJECT do NOT apply runtime behavior in 098C (foundation only)
# =============================================================================

@app.get("/user-controls/{workflow_id}")
def list_pending_user_controls(workflow_id: str):
    """
    GET /user-controls/{workflow_id}
    Returns pending and recent user-control requests for the specified workflow.
    Per USER_CONTROL_CONTRACT_V2 §9: workflow-scoped lookup only.
    """
    pending = get_pending_user_controls_for_workflow(workflow_id)
    return {
        "workflow_id": workflow_id,
        "pending": [req.to_dict() for req in pending],
    }


@app.post("/user-controls/{control_id}/accept")
def accept_user_control_by_id(control_id: str):
    """
    POST /user-controls/{control_id}/accept
    Resolve a pending user-control request as ACCEPTED if still legal.
    Backend validates: not expired, not terminal, generation match if supplied.
    Per ISSUE-098C: does NOT apply runtime behavior; only changes request status.
    """
    request = get_user_control_request(control_id)
    if request is None:
        raise HTTPException(status_code=404, detail="control_id not found")

    validate = {"workflow_id": request.workflow_id}

    # Execution generation validation (if available)
    try:
        plan = get_plan(request.workflow_id)
        if plan and plan.get("steps"):
            for s in plan.get("steps", []):
                if s.get("id") == request.step_id:
                    validate["step_exists"] = True
                    validate["execution_generation"] = s.get("execution_generation")
                    validate["retry_generation"] = s.get("_retry_generation")
                    break
            else:
                validate["step_exists"] = False
    except Exception:
        pass

    result = resolve_user_control_request(
        control_id=control_id,
        decision="accept",
        actor="operator",
        validate=validate,
    )

    if not result["success"]:
        status_code = 409
        if result["status"] in ("not_found", "mismatch"):
            status_code = 404
        elif result["status"] in ("EXPIRED", "SUPERSEDED", "CANCELLED"):
            status_code = 410
        raise HTTPException(status_code=status_code, detail=result["error"])

    # === ISSUE-098KLM: Trigger execution resume for accepted external-call risk ===
    # Per ORCHESTRATOR_EXECUTION_CONTRACT: run_workflow is the sole execution authority.
    # The runtime loop has exited for BLOCKED workflows; a new thread must be spawned.
    # ISSUE-098KN: Skip generation increment — no stale thread to invalidate.
    _resume_info = None
    if request.requested_action == "accept_external_call_risk":
        _resume_info = _trigger_execution_resume(
            request.workflow_id,
            skip_generation_increment=True,
        )

    return {
        "status": "ok",
        "control_id": control_id,
        "resolution": "ACCEPTED",
        "note": "request accepted — execution resumed for external_call_risk" if _resume_info and _resume_info.get("status") == "ok" else "request accepted",
        "resume": _resume_info,
    }


@app.post("/user-controls/{control_id}/reject")
def reject_user_control_by_id(control_id: str):
    """
    POST /user-controls/{control_id}/reject
    Resolve a pending user-control request as REJECTED if still legal.
    Per ISSUE-098C: does NOT apply runtime behavior; only changes request status.
    Per ISSUE-098KLM: updates blocked_reason directly because runtime loop may be idle.
    """
    request = get_user_control_request(control_id)
    if request is None:
        raise HTTPException(status_code=404, detail="control_id not found")

    validate = {"workflow_id": request.workflow_id}
    try:
        plan = get_plan(request.workflow_id)
        if plan and plan.get("steps"):
            for s in plan.get("steps", []):
                if s.get("id") == request.step_id:
                    validate["step_exists"] = True
                    validate["execution_generation"] = s.get("execution_generation")
                    validate["retry_generation"] = s.get("_retry_generation")
                    break
            else:
                validate["step_exists"] = False
    except Exception:
        pass

    result = resolve_user_control_request(
        control_id=control_id,
        decision="reject",
        actor="operator",
        validate=validate,
    )

    if not result["success"]:
        status_code = 409
        if result["status"] in ("not_found", "mismatch"):
            status_code = 404
        elif result["status"] in ("EXPIRED", "SUPERSEDED", "CANCELLED"):
            status_code = 410
        raise HTTPException(status_code=status_code, detail=result["error"])

    # === ISSUE-098KLM: Update blocked_reason directly because runtime loop is idle ===
    # The runtime has exited for BLOCKED workflows, so the 098KL runtime guard
    # never executes. We must write the rejected reason into persistence directly.
    try:
        _wf = load_workflow(request.workflow_id)
        if _wf and isinstance(_wf, dict):
            for _step in _wf.get("steps", []):
                if _step.get("id") == request.step_id:
                    _step["blocked_reason"] = "external_call_risk_rejected"
                    break
            _save_workflow(_wf)
    except Exception:
        pass

    return {
        "status": "ok",
        "control_id": control_id,
        "resolution": "REJECTED",
        "note": "request rejected — blocked_reason updated to external_call_risk_rejected",
    }


# ── DEV/TEST ENDPOINT (admin-gated) ───────────────────────────────────────────
# Per ISSUE-098C: optional endpoint for manual validation only.
# Gated under existing admin/test endpoint safety model.

class UserControlCreateRequest(BaseModel):
    workflow_id: str
    step_id: Optional[str] = None
    requested_action: str
    reason: str
    risk_level: str = "MEDIUM"
    actor: str = "user"
    confirmation_text: Optional[str] = None
    execution_generation: Optional[int] = None
    retry_generation: Optional[int] = None


@app.post("/admin/test/create_user_control_request")
def admin_create_user_control_request(
    req: UserControlCreateRequest,
    request: Request,
):
    """
    DEV/TEST ONLY: Create a user-control request for manual validation.
    Gated under /admin/test/ — NOT for production use.
    """
    _require_admin_test_enabled(request)
    result = create_user_control_request(
        workflow_id=req.workflow_id,
        step_id=req.step_id,
        requested_action=req.requested_action,
        reason=req.reason,
        risk_level=req.risk_level,
        actor=req.actor,
        confirmation_text=req.confirmation_text,
        execution_generation=req.execution_generation,
        retry_generation=req.retry_generation,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "invalid_request"))
    return result


# =============================================================================
# PHASE 3C — NOTIFICATIONS (Contract-Safe, ISSUE-096B)
# =============================================================================
# Per NOTIFICATION_CONTRACT_V1:
# - Backend-authored notification identity
# - Read/dismiss are non-mutating to workflow state
# =============================================================================

@app.get("/notifications")
def list_notifications(
    workflow_id: Optional[str] = None,
    limit: int = 100,
    include_dismissed: bool = True,
):
    """
    GET /notifications
    Global notification list. Optionally filter by workflow_id.
    Per NOTIFICATION_CONTRACT_V1 §12: bounded, sorted newest first.
    """
    notifications = get_notifications(
        workflow_id=workflow_id,
        limit=limit,
        include_dismissed=include_dismissed,
    )
    return {
        "notifications": notifications,
        "count": len(notifications),
        "unread": get_unread_count(workflow_id=workflow_id),
    }


@app.get("/notifications/{workflow_id}")
def list_workflow_notifications(workflow_id: str, limit: int = 100):
    """
    GET /notifications/{workflow_id}
    Workflow-scoped notification list.
    """
    notifications = get_notifications(workflow_id=workflow_id, limit=limit)
    return {
        "workflow_id": workflow_id,
        "notifications": notifications,
        "count": len(notifications),
        "unread": get_unread_count(workflow_id=workflow_id),
    }


@app.post("/notifications/{notification_id}/read")
def read_notification(notification_id: str):
    """
    POST /notifications/{notification_id}/read
    Mark notification as READ.
    Per NOTIFICATION_CONTRACT_V1 §7: read does NOT approve/reject/mutate workflow.
    """
    ok = mark_notification_read(notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="notification_id not found")
    return {"status": "ok", "notification_id": notification_id, "new_status": "READ"}


@app.post("/notifications/{notification_id}/dismiss")
def dismiss_notification_endpoint(notification_id: str):
    """
    POST /notifications/{notification_id}/dismiss
    Mark notification as DISMISSED.
    Per NOTIFICATION_CONTRACT_V1 §10: dismissal is not approval.
    """
    ok = dismiss_notification(notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="notification_id not found")
    return {"status": "ok", "notification_id": notification_id, "new_status": "DISMISSED"}


# =============================================================================
# PHASE 5 — DEBUG
# =============================================================================

@app.get("/debug/events")
def debug_events():
    """GET /debug/events — dump all active workflow IDs and event counts in the bus."""
    from system.interface.event_bus import get_event_bus
    bus = get_event_bus()
    workflow_ids = bus.get_workflow_ids()
    summary = {}
    for wid in workflow_ids:
        events = bus.get_events(wid)
        summary[wid] = {
            "count": len(events),
            "types": [e.get("event_type") for e in events],
        }
    return {"active_workflows": workflow_ids, "summary": summary, "failure_count": bus.get_failure_count()}


@app.get("/debug/control_state")
def debug_control_state():
    """GET /debug/control_state — raw control state dump"""
    # Legacy _pending_approvals replaced by approval registry
    try:
        from system.orchestrator.user_approval import _approval_registry
        pending_ids = [
            req.approval_id for req in _approval_registry.values()
            if req.status == ApprovalStatus.PENDING
        ]
    except Exception:
        pending_ids = []
    return {
        "control_state": get_control_state(),
        "pending_approvals": pending_ids,
        "background_count": _bg_manager.active_count(),
    }


# =============================================================================
# PHASE 2.7 — MEMORY MANAGEMENT (ISSUE-077)
# =============================================================================
# Per MEMORY_STORAGE_CONTRACT_V1:
# - Memory is advisory-only, operator-managed context
# - Memory MUST NOT influence execution_result, governance, lifecycle, or projection truth
# - These endpoints call ONLY system.memory.memory_store primitives
# - No orchestrator, planner, agent, trace, or projection functions are invoked
# =============================================================================

def _memory_unavailable():
    raise HTTPException(status_code=503, detail="memory_store_unavailable")


def _memory_validate_scope(scope: str):
    if _validate_memory_scope is None:
        _memory_unavailable()
    try:
        return _validate_memory_scope(scope)
    except _MemoryValidationError as e:
        raise HTTPException(status_code=400, detail=f"invalid_scope: {e}")


def _memory_validate_category(category: str):
    if _validate_memory_category is None:
        _memory_unavailable()
    try:
        return _validate_memory_category(category)
    except _MemoryValidationError as e:
        raise HTTPException(status_code=400, detail=f"invalid_category: {e}")


def _memory_validate_confidence(confidence: float):
    if _validate_memory_confidence is None:
        _memory_unavailable()
    try:
        return _validate_memory_confidence(confidence)
    except _MemoryValidationError as e:
        raise HTTPException(status_code=400, detail=f"invalid_confidence: {e}")


def _memory_validate_key(key: str):
    if _validate_memory_key is None:
        _memory_unavailable()
    try:
        return _validate_memory_key(key)
    except _MemoryValidationError as e:
        raise HTTPException(status_code=400, detail=f"invalid_key: {e}")


def _memory_validate_source(source: str):
    if _validate_memory_source is None:
        _memory_unavailable()
    try:
        return _validate_memory_source(source)
    except _MemoryValidationError as e:
        raise HTTPException(status_code=400, detail=f"invalid_source: {e}")


def _memory_require_project_id(scope: str, project_id: Optional[str]):
    if scope == _MEMORY_SCOPE_PROJECT and not project_id:
        raise HTTPException(status_code=400, detail="project_id required for PROJECT scope")
    if scope == _MEMORY_SCOPE_GLOBAL and project_id:
        raise HTTPException(status_code=400, detail="project_id must not be provided for GLOBAL scope")


@app.get("/memory/list")
def memory_list(
    scope: Optional[str] = None,
    project_id: Optional[str] = None,
    category: Optional[str] = None,
):
    """
    GET /memory/list
    List memory entries with optional filtering.
    """
    if _memory_store is None:
        _memory_unavailable()

    validated_scope = None
    if scope is not None:
        validated_scope = _memory_validate_scope(scope)
        _memory_require_project_id(validated_scope, project_id)
    if category is not None:
        category = _memory_validate_category(category)

    return {"entries": _memory_store.list_entries(scope=validated_scope, project_id=project_id, category=category)}


@app.get("/memory/read")
def memory_read(
    scope: str,
    key: str,
    project_id: Optional[str] = None,
):
    """
    GET /memory/read
    Read a single memory entry by scope and key.
    """
    if _memory_store is None:
        _memory_unavailable()

    validated_scope = _memory_validate_scope(scope)
    validated_key = _memory_validate_key(key)
    _memory_require_project_id(validated_scope, project_id)

    entry = _memory_store.read(validated_scope, validated_key, project_id=project_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="memory_entry_not_found")
    return entry


@app.post("/memory/write")
def memory_write(req: MemoryWriteRequest):
    """
    POST /memory/write
    Write a memory entry. Replaces existing entry with same scope+key.
    """
    if _memory_store is None:
        _memory_unavailable()

    validated_scope = _memory_validate_scope(req.scope)
    validated_key = _memory_validate_key(req.key)
    validated_category = _memory_validate_category(req.category)
    _memory_validate_confidence(req.confidence)
    if req.source is not None:
        _memory_validate_source(req.source)
    _memory_require_project_id(validated_scope, req.project_id)

    entry = _memory_store.write(
        scope=validated_scope,
        key=validated_key,
        value=req.value,
        category=validated_category,
        project_id=req.project_id,
        source=req.source or "user",
        confidence=req.confidence,
        editable=req.editable,
        deletable=req.deletable,
    )
    if entry is None:
        raise HTTPException(status_code=500, detail="memory_write_failed")

    # ISSUE-078: Trace operator-initiated memory write
    _record_memory_trace(
        event="MEMORY_WRITE",
        key=validated_key,
        data={"scope": validated_scope, "source": "operator", "category": validated_category},
    )

    return {"status": "ok", "entry": entry}


@app.post("/memory/update")
def memory_update(req: MemoryUpdateRequest):
    """
    POST /memory/update
    Update an existing memory entry.
    """
    if _memory_store is None:
        _memory_unavailable()

    validated_scope = _memory_validate_scope(req.scope)
    validated_key = _memory_validate_key(req.key)
    _memory_require_project_id(validated_scope, req.project_id)

    entry = _memory_store.update(validated_scope, validated_key, req.value, project_id=req.project_id)
    if entry is None:
        raise HTTPException(status_code=400, detail="memory_update_failed: entry not found or not editable")

    # ISSUE-078: Trace operator-initiated memory update
    _record_memory_trace(
        event="MEMORY_UPDATE",
        key=validated_key,
        data={"scope": validated_scope, "source": "operator"},
    )

    return {"status": "ok", "entry": entry}


@app.post("/memory/delete")
def memory_delete(req: MemoryDeleteRequest):
    """
    POST /memory/delete
    Delete a memory entry if deletable.
    """
    if _memory_store is None:
        _memory_unavailable()

    validated_scope = _memory_validate_scope(req.scope)
    validated_key = _memory_validate_key(req.key)
    _memory_require_project_id(validated_scope, req.project_id)

    deleted = _memory_store.delete(validated_scope, validated_key, project_id=req.project_id)
    if not deleted:
        raise HTTPException(status_code=400, detail="memory_delete_failed: entry not found or not deletable")

    # ISSUE-078: Trace operator-initiated memory delete
    _record_memory_trace(
        event="MEMORY_DELETE",
        key=validated_key,
        data={"scope": validated_scope, "source": "operator"},
    )

    return {"status": "ok", "deleted": True}


@app.post("/memory/reset")
def memory_reset(req: MemoryResetRequest):
    """
    POST /memory/reset
    Reset memory entries for a given scope.
    Scope "ALL" requires confirm_all=true.
    """
    if _memory_store is None:
        _memory_unavailable()

    scope_raw = req.scope.strip().upper() if req.scope else ""

    if scope_raw == "ALL":
        if not req.confirm_all:
            raise HTTPException(status_code=400, detail="reset ALL requires confirm_all=true")
        ok = _memory_store.reset("ALL")
        if not ok:
            raise HTTPException(status_code=500, detail="memory_reset_all_failed")

        # ISSUE-078: Trace operator-initiated memory reset (ALL)
        _record_memory_trace(
            event="MEMORY_RESET",
            key="ALL",
            data={"scope": "ALL", "source": "operator"},
        )

        return {"status": "ok", "scope": "ALL", "reset": True}

    validated_scope = _memory_validate_scope(req.scope)
    _memory_require_project_id(validated_scope, req.project_id)

    ok = _memory_store.reset(validated_scope, project_id=req.project_id)
    if not ok:
        raise HTTPException(status_code=500, detail="memory_reset_failed")

    # ISSUE-078: Trace operator-initiated memory reset
    _record_memory_trace(
        event="MEMORY_RESET",
        key=validated_scope,
        data={"scope": validated_scope, "source": "operator"},
    )

    return {"status": "ok", "scope": validated_scope, "reset": True}


# =============================================================================
# PHASE 2.8 — PLAN CONTROL (Per PLAN_CONTROL_CONTRACT_V1)
# =============================================================================

@app.get("/plan/{workflow_id}")
def get_plan_endpoint(workflow_id: str):
    """
    GET /plan/{workflow_id}
    Retrieve the current execution plan for a workflow.
    """
    result = get_plan(workflow_id)
    if result.get("status") == "failure":
        raise HTTPException(status_code=404, detail=result.get("reason"))
    return result


@app.post("/plan/edit")
def edit_step_endpoint(req: PlanEditRequest):
    """
    POST /plan/edit
    Edit a step in the workflow plan.

    Per MUTATION_AUTHORITY_CONSOLIDATION:
    - Legacy endpoint now routes through canonical mutation authority
    - Thin adapter only — delegates to request_plan_mutation()
    - Preserves backward compatibility while ensuring contract compliance

    Per PLAN_CONTROL_CONTRACT_V1: validates edit and dependency graph.
    Per CANONICAL_PROJECTION_MODEL_V1 §7: uses canonical mutation flow.
    """
    if _request_plan_mutation is None:
        raise HTTPException(status_code=503, detail="mutation_manager_unavailable")

    # === MUTATION AUTHORITY CONSOLIDATION ===
    # Route through canonical mutation authority instead of direct workflow_control call
    # This ensures: validation, trace logging, projection invalidation, resurrection bridge
    result = _request_plan_mutation(
        workflow_id=req.workflow_id,
        mutation_type="edit_step",
        payload={"step_id": req.step_id, "updates": req.updates},
        actor="user",
    )

    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))

    # === EXECUTION RESURRECTION BRIDGE ===
    # Per ORCHESTRATOR_EXECUTION_CONTRACT: edit mutations that revive terminal workflows
    # MUST trigger execution re-entry. Already handled by mutation manager for edit_step.
    if result.get("status") == "success":
        _bg_id = _maybe_resurrect_execution(req.workflow_id)
        if _bg_id is not None:
            result["bg_id"] = _bg_id
            result["execution_resumed"] = True

    return result


@app.post("/plan/add")
def add_step_endpoint(req: PlanAddRequest):
    """
    POST /plan/add
    Add a new step to the workflow plan.

    Per MUTATION_AUTHORITY_CONSOLIDATION:
    - Legacy endpoint now routes through canonical mutation authority
    - Thin adapter only — delegates to request_plan_mutation()
    - Preserves backward compatibility while ensuring contract compliance

    Per PLAN_CONTROL_CONTRACT_V1: validates and appends step.
    Per CANONICAL_PROJECTION_MODEL_V1 §7: uses canonical mutation flow.
    """
    if _request_plan_mutation is None:
        raise HTTPException(status_code=503, detail="mutation_manager_unavailable")

    # === MUTATION AUTHORITY CONSOLIDATION ===
    # Route through canonical mutation authority instead of direct workflow_control call
    # This ensures: validation, trace logging, projection invalidation
    result = _request_plan_mutation(
        workflow_id=req.workflow_id,
        mutation_type="add_step",
        payload={"step_data": req.step_data},
        actor="user",
    )

    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))

    return result


@app.post("/plan/remove")
def remove_step_endpoint(req: PlanRemoveRequest):
    """
    POST /plan/remove
    Remove a step from the workflow plan.

    Per MUTATION_AUTHORITY_CONSOLIDATION:
    - Legacy endpoint now routes through canonical mutation authority
    - Thin adapter only — delegates to request_plan_mutation()
    - Preserves backward compatibility while ensuring contract compliance

    Per PLAN_CONTROL_CONTRACT_V1: rejects if step is COMPLETED or has dependents.
    Per CANONICAL_PROJECTION_MODEL_V1 §7: uses canonical mutation flow.
    """
    if _request_plan_mutation is None:
        raise HTTPException(status_code=503, detail="mutation_manager_unavailable")

    # === MUTATION AUTHORITY CONSOLIDATION ===
    # Route through canonical mutation authority instead of direct workflow_control call
    # This ensures: validation, trace logging, projection invalidation
    result = _request_plan_mutation(
        workflow_id=req.workflow_id,
        mutation_type="remove_step",
        payload={"step_id": req.step_id},
        actor="user",
    )

    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))

    return result


@app.post("/plan/reorder")
def reorder_steps_endpoint(req: PlanReorderRequest):
    """
    POST /plan/reorder
    Reorder steps in the workflow plan.

    Per MUTATION_AUTHORITY_CONSOLIDATION:
    - TODO: Reorder requires MUTATION_TYPE_REORDER_STEP addition to mutation manager
    - Currently uses direct workflow_control path (validated but no invalidation/tracing)
    - Future: route through request_plan_mutation() when reorder type added

    Per PLAN_CONTROL_CONTRACT_V1: validates dependency constraints.
    """
    # === MUTATION AUTHORITY GAP ===
    # reorder_steps is NOT in ALLOWED_MUTATION_TYPES — cannot route through mutation manager yet
    # The validate_reorder function exists in mutation_validation.py but is not wired to manager
    # This is a KNOWN GAP requiring: add MUTATION_TYPE_REORDER_STEP + _handle_reorder_step()
    # For now: direct call with validation but NO projection invalidation, NO trace logging
    # Workaround: mutation manager handles add/remove/edit; reorder deferred
    result = reorder_steps(req.workflow_id, req.new_order)
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return result


# =============================================================================
# PHASE 2.8 — CONTROL ACTIONS (Per ORCHESTRATOR_CONTRACT_V2)
# =============================================================================

@app.post("/step/retry")
def retry_step_endpoint(req: RetryStepRequest):
    """
    POST /step/retry
    Retry a failed or blocked step.

    Per MUTATION_AUTHORITY_CONSOLIDATION:
    - Legacy endpoint now routes through canonical mutation authority
    - Thin adapter only — delegates to request_plan_mutation()
    - Preserves backward compatibility while ensuring contract compliance

    Requires workflow_id and step_id.
    """
    if _request_plan_mutation is None:
        raise HTTPException(status_code=503, detail="mutation_manager_unavailable")

    # === MUTATION AUTHORITY CONSOLIDATION ===
    # Route through canonical mutation authority instead of direct workflow_control call
    # This ensures: validation, trace logging, projection invalidation, resurrection bridge
    result = _request_plan_mutation(
        workflow_id=req.workflow_id,
        mutation_type="retry_step",
        payload={"step_id": req.step_id},
        actor="user",
    )

    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))

    # === EXECUTION RESURRECTION BRIDGE ===
    # Per ORCHESTRATOR_EXECUTION_CONTRACT: retry mutations that revive terminal workflows
    # MUST trigger execution re-entry. Mutation manager handles ACTIVE transition;
    # this bridge spawns the execution thread.
    # Note: _maybe_resurrect_execution is also called internally by mutation manager;
    # this is a safety net for the legacy endpoint path.
    if result.get("status") == "success":
        _bg_id = _maybe_resurrect_execution(req.workflow_id)
        if _bg_id is not None:
            result["bg_id"] = _bg_id
            result["execution_resumed"] = True

    return result


@app.post("/workflow/stop")
def stop_workflow_endpoint(req: StopWorkflowRequest):
    """
    POST /workflow/stop
    Stop a running workflow via intentional operator cancellation.
    Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
      ACTIVE|PAUSED|BLOCKED → CANCELLED (immutable terminal)
    """
    result = cancel_workflow(req.workflow_id, reason="user_stop")
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return result


@app.post("/workflow/cancel")
def cancel_workflow_endpoint(req: StopWorkflowRequest):
    """
    POST /workflow/cancel
    Cancel a running workflow — authoritative immutable terminal convergence.
    Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
      ACTIVE|PAUSED|BLOCKED → CANCELLED
    """
    result = cancel_workflow(req.workflow_id, reason="user_cancel")
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return result


# =============================================================================
# ISSUE-060 — WORKFLOW RETENTION OPERATIONALIZATION
# =============================================================================

@app.post("/workflow/{workflow_id}/archive")
def archive_workflow_endpoint(workflow_id: str):
    """
    POST /workflow/{workflow_id}/archive

    Archive workflow — retention-layer action ONLY.

    Per WORKFLOW_RETENTION_AND_ARCHIVAL_CONTRACT_V1:
    - retention actions do NOT alter lifecycle truth
    - lifecycle state remains unchanged
    - workflow record is preserved (not deleted)
    - retry metadata is preserved

    Returns:
        {"status": "success", "workflow_id": ..., "retention_state": "archived"}
    """
    result = set_retention_state(workflow_id, "archived")
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return {
        "status": "success",
        "workflow_id": workflow_id,
        "retention_state": "archived",
    }


@app.post("/workflow/{workflow_id}/dismiss")
def dismiss_workflow_endpoint(workflow_id: str):
    """
    POST /workflow/{workflow_id}/dismiss

    Dismiss workflow — retention-layer action ONLY.

    Per WORKFLOW_RETENTION_AND_ARCHIVAL_CONTRACT_V1:
    - retention actions do NOT alter lifecycle truth
    - lifecycle state remains unchanged
    - workflow record is preserved (not deleted)
    - retry metadata is preserved

    Returns:
        {"status": "success", "workflow_id": ..., "retention_state": "dismissed"}
    """
    result = set_retention_state(workflow_id, "dismissed")
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return {
        "status": "success",
        "workflow_id": workflow_id,
        "retention_state": "dismissed",
    }


# =============================================================================
# PHASE 4B.1 — PLAN MUTATION INTENT ENDPOINT
# =============================================================================

@app.post("/workflow/{workflow_id}/mutation")
def plan_mutation_endpoint(workflow_id: str, req: MutationRequest):
    """
    POST /workflow/{workflow_id}/mutation

    Mutation intent endpoint — transport-only.

    Per CANONICAL_PROJECTION_MODEL_V1 §7 (Projection Mutation Flow):
    - API layer acts as schema validation boundary and intent routing layer only
    - API MUST NOT own mutation authority
    - API MUST NOT synthesize workflow state
    - API forwards mutation intent to orchestrator-owned PlanMutationManager

    Per GUI_FUNCTIONALITY_CONTRACT_V1 §LIFECYCLE ACTION MODEL:
    - GUI actions REQUEST mutations — they do NOT define them

    Allowed mutation_type values (this phase):
      edit_step, add_step, remove_step, retry_step

    Payload per mutation_type:
      edit_step:    {step_id, updates: {field: value, ...}}
      add_step:     {step_data: {...}}
      remove_step:  {step_id}
      retry_step:   {step_id}
    """
    if _request_plan_mutation is None:
        raise HTTPException(status_code=503, detail="mutation_manager_unavailable")

    # Schema validation boundary: reject unknown mutation types before dispatch
    if req.mutation_type not in _ALLOWED_MUTATION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown_mutation_type:{req.mutation_type}"
        )

    # Forward intent to orchestrator-owned mutation authority
    result = _request_plan_mutation(
        workflow_id=workflow_id,
        mutation_type=req.mutation_type,
        payload=req.payload,
        actor=req.actor or "user",
    )

    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason", "mutation_failed"))

    # === EXECUTION RESURRECTION BRIDGE (Phase 2 — Retry/Edit Runtime Re-entry) ===
    # Per ORCHESTRATOR_EXECUTION_CONTRACT: mutations that revive a terminal workflow MUST
    # trigger execution re-entry.  retry_step and edit_step write ACTIVE into the registry
    # via _update_workflow_state, but the original run_workflow thread has already exited.
    # _maybe_resurrect_execution detects registry ACTIVE and spawns a new run_workflow
    # thread, identical to the /resume/{workflow_id} re-entry path.
    # Only triggered for mutation types that can revive execution; harmless for others.
    if req.mutation_type in ("retry_step", "edit_step"):
        _bg_id = _maybe_resurrect_execution(workflow_id)
        if _bg_id is not None:
            result["bg_id"] = _bg_id
            result["execution_resumed"] = True

    return result


# =============================================================================
# PHASE 4A.0 — CANONICAL PROJECTION TRANSPORT
# =============================================================================

@app.get("/projection/{workflow_id}")
def get_canonical_projection(workflow_id: str):
    """
    GET /projection/{workflow_id}
    Returns the latest canonical WorkflowProjection for a workflow.

    Per PHASE 1 REMEDIATION:
    - Frontend may ONLY hydrate from persistence-backed workflows
    - Persistence validation required before returning to frontend

    Per CANONICAL_PROJECTION_MODEL_V1:
    - API is transport layer ONLY
    - API does NOT own projection truth
    - API does NOT mutate projection lifecycle
    - API does NOT synthesize workflow state

    Per CANONICAL_PROJECTION_MODEL_V1 §3 (Projection Identity):
    Response MUST include: workflow_id, projection_type, projection_version,
    projection_timestamp

    Returns 404 if no projection has been emitted for workflow_id.
    Returns 503 if projection manager is unavailable.
    """
    # === FRONTEND AUTHORITY ENFORCEMENT ===
    # Fast O(1) existence check — do NOT call validate_runtime_activation() here (full scan).
    if not _wf_persistence_exists(workflow_id):
        raise HTTPException(status_code=404, detail="workflow_not_found")

    if _get_proj_mgr is None:
        raise HTTPException(status_code=503, detail="projection_manager_unavailable")

    try:
        proj_mgr = _get_proj_mgr()
        projection = proj_mgr.get_latest_projection(workflow_id)
    except Exception:
        raise HTTPException(status_code=503, detail="projection_read_error")

    if projection is None:
        # === ISSUE-098KY: Build projection from persisted data for workflows.json workflows ===
        # Terminal workflows (COMPLETED) may not have an in-memory projection.
        # Synthesize one from the persisted workflow file so the frontend can hydrate.
        _wf_data = None
        try:
            _wf_data = load_workflow(workflow_id)
        except Exception:
            pass
        # Fallback: workflows.json for COMPLETED workflows
        if _wf_data is None:
            try:
                import json as _json
                _wf_json_path = os.path.join(ROOT, "memory", "workflows.json")
                if os.path.isfile(_wf_json_path):
                    with open(_wf_json_path, "r", encoding="utf-8") as f:
                        _completed_list = _json.load(f)
                    if isinstance(_completed_list, list):
                        for _cwf in _completed_list:
                            if isinstance(_cwf, dict) and _cwf.get("id") == workflow_id:
                                _wf_data = _cwf
                                break
            except Exception:
                pass
        if _wf_data and isinstance(_wf_data, dict):
            try:
                _synthetic_projection = project_workflow_for_gui(_wf_data)
                _synthetic_projection["workflow_id"] = workflow_id
                _synthetic_projection["lifecycle_status"] = _wf_data.get("status", "UNKNOWN")
                # Per CANONICAL_PROJECTION_MODEL_V1 §3: required identity fields
                if "projection_type" not in _synthetic_projection:
                    _synthetic_projection["projection_type"] = "workflow"
                if "projection_version" not in _synthetic_projection:
                    _synthetic_projection["projection_version"] = 1
                if "projection_timestamp" not in _synthetic_projection:
                    from datetime import datetime, timezone
                    _synthetic_projection["projection_timestamp"] = datetime.now(timezone.utc).isoformat()
                projection = _synthetic_projection
            except Exception:
                pass
        if projection is None:
            raise HTTPException(status_code=404, detail="projection_not_found")

    # Schema validation boundary: ensure projection identity is complete
    # Per CANONICAL_PROJECTION_MODEL_V1 §9 (API Boundary Rules)
    if validate_projection_identity is not None:
        if not validate_projection_identity(projection):
            raise HTTPException(status_code=500, detail="projection_identity_invalid")

    return projection


@app.get("/projection/{workflow_id}/version")
def get_projection_version(workflow_id: str):
    """
    GET /projection/{workflow_id}/version
    Returns the current projection version and state for a workflow.

    Per CANONICAL_PROJECTION_MODEL_V1 §4 (Projection Versioning):
    Enables frontend to detect when projection has been updated
    without fetching the full projection payload.

    API is transport-only: reads from ProjectionManager, does not mutate.
    """
    if _get_proj_mgr is None:
        raise HTTPException(status_code=503, detail="projection_manager_unavailable")

    try:
        proj_mgr = _get_proj_mgr()
        version = proj_mgr.get_projection_version(workflow_id)
        state = proj_mgr.get_projection_state(workflow_id)
    except Exception:
        raise HTTPException(status_code=503, detail="projection_read_error")

    if state is None:
        raise HTTPException(status_code=404, detail="projection_not_found")

    return {
        "workflow_id": workflow_id,
        "projection_version": version,
        "projection_state": state,
    }


@app.get("/projection/{workflow_id}/continuity")
def get_projection_continuity(workflow_id: str):
    """
    GET /projection/{workflow_id}/continuity
    Returns projection continuity diagnostics for a workflow.

    Per PROJECTION_CONTINUITY_CONTRACT_V1 §11 (SUB-PHASE 3E):
    Exposes continuity context for reconnect gap detection and stale repair.

    Returns:
    - projection_version: current version
    - projection_state: ACTIVE / STALE / INVALIDATED / TERMINAL
    - continuity_anchor: last confirmed synchronized version
    - stale_rejections: count of rejected stale projections
    - is_terminal: whether projection is in terminal state
    - has_projection: whether any projection has been emitted
    - latest_bus_sequence_id: current bus sequence for gap detection

    API is transport-only — does NOT mutate projection state.
    """
    if _get_proj_mgr is None:
        raise HTTPException(status_code=503, detail="projection_manager_unavailable")

    try:
        proj_mgr = _get_proj_mgr()
        summary = proj_mgr.get_continuity_summary(workflow_id)
    except Exception:
        raise HTTPException(status_code=503, detail="projection_read_error")

    # Enrich with bus sequence for reconnect gap detection
    from system.interface.event_bus import get_latest_sequence as _get_latest_seq
    summary["latest_bus_sequence_id"] = _get_latest_seq(workflow_id)

    return summary


# =============================================================================
# PHASE 4A.1 — RUNTIME OBSERVABILITY + DETERMINISTIC VALIDATION SUPPORT
# =============================================================================
# Per VALIDATION_ARCHITECTURE.txt §9 + WINDSURF_EXECUTION_TASK:
# Minimal read-only runtime inspection surfaces for debugging and
# deterministic survivability validation. NO authority inversion.
# =============================================================================

@app.get("/runtime/inspect/{workflow_id}")
def runtime_inspect(workflow_id: str):
    """
    GET /runtime/inspect/{workflow_id}
    Returns comprehensive runtime inspection metadata for debugging and validation.

    Per VALIDATION_ARCHITECTURE.txt §9.4: Runtime Survivability Validation
    Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1: execution_generation visibility
    Per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1: registry state visibility

    READ-ONLY: Does NOT mutate runtime state, define authority, or synthesize truth.
    Data sources: runtime registry (lifecycle authority), projection layer (read-model).

    Returns:
    - workflow_id: target workflow
    - lifecycle_status: authoritative status from runtime registry
    - execution_generation: current generation counter (mutation/retry invalidation)
    - persistence_exists: whether workflow has persisted state
    - active_execution: metadata about active execution context (if any)
    - projection_metadata: version/timestamp from projection layer
    - retry_lineage: retry count and history (if available)
    - timing_metadata: last lifecycle commit, projection refresh (if available)
    """
    from system.orchestrator.workflow_control import _workflow_state_registry, _workflow_state_lock

    result = {
        "workflow_id": workflow_id,
        "lifecycle_status": None,
        "execution_generation": None,
        "persistence_exists": False,
        "active_execution": None,
        "projection_metadata": None,
        "retry_lineage": None,
        "retry_target_step_id": None,
        "timing_metadata": None,
        "observability_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Authoritative runtime registry state (lifecycle authority)
    with _workflow_state_lock:
        if workflow_id in _workflow_state_registry:
            state = _workflow_state_registry[workflow_id]
            result["lifecycle_status"] = state.get("status", "UNKNOWN")
            result["execution_generation"] = state.get("execution_generation", 1)
            result["retry_lineage"] = {
                "retry_count": state.get("retry_count", 0),
                "last_retry_at": state.get("last_retry_at"),
                "steps": [],
            }
            # Timing metadata if available
            if "last_status_change" in state:
                result["timing_metadata"] = {
                    "last_lifecycle_commit": state.get("last_status_change"),
                }

    # 1b. Per-step retry lineage enrichment (read-only observability)
    # Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1: retry lineage is observability metadata
    if result["retry_lineage"] is not None:
        try:
            from system.orchestrator.persistence import load_workflow
            _wf = load_workflow(workflow_id)
            if _wf and _wf.get("steps"):
                result["retry_lineage"]["steps"] = [
                    {
                        "step_id": step.get("id") or step.get("step_id"),
                        "retry_generation": step.get("_retry_generation", 0),
                    }
                    for step in _wf["steps"]
                    if step.get("_retry_generation", 0) > 0
                ]
                # ISSUE-057 FIX E: Compute retry target from authoritative persisted steps
                _steps = _wf["steps"]
                # Rule 1: First FAILED step
                for step in _steps:
                    if step.get("status") == "FAILED":
                        result["retry_target_step_id"] = step.get("id")
                        break
                # Rule 2: BLOCKED with permanent-block reason (only if no FAILED)
                # Mirrors orchestrator_runtime.py permanent block logic.
                # Stale dependency reasons (dependency status mismatch) identify
                # the current step as the retry target to force re-evaluation.
                if result["retry_target_step_id"] is None:
                    _steps_by_id = {s.get("id"): s for s in _steps if s.get("id")}
                    for step in _steps:
                        if step.get("status") == "BLOCKED":
                            reason = step.get("blocked_reason", "")
                            _is_perm = (
                                reason.startswith("dependency_failed")
                                or (
                                    reason.startswith("dependency_not_completed")
                                    and reason.split(":")[-1] in ("FAILED", "BLOCKED")
                                )
                                or reason in ("max_retries_exceeded", "escalated")
                            )
                            if not _is_perm:
                                continue
                            # Check for stale dependency reason
                            _is_stale = False
                            if reason.startswith("dependency_not_completed") or reason.startswith("dependency_failed"):
                                parts = reason.split(":")
                                if len(parts) >= 3:
                                    dep_id = parts[1]
                                    claimed_status = parts[-1]
                                    dep = _steps_by_id.get(dep_id)
                                    if dep is None or dep.get("status") != claimed_status:
                                        _is_stale = True
                            if _is_stale or reason in ("max_retries_exceeded", "escalated"):
                                result["retry_target_step_id"] = step.get("id")
                                break
                            # Matching dependency status → victim, skip
        except Exception:
            pass  # Per-step lineage is non-fatal observability enrichment

    # 2. Persistence existence check
    result["persistence_exists"] = _wf_persistence_exists(workflow_id)

    # 3. Active execution context from stream registry (projection-only cache)
    with _stream_registry_lock:
        for bg_id, entry in _stream_registry.items():
            if entry.get("orchestrator_workflow_id") == workflow_id:
                result["active_execution"] = {
                    "bg_id": bg_id,
                    "stream_status": entry.get("status"),  # projection cache only
                    "has_result": entry.get("result") is not None,
                    "has_error": entry.get("error") is not None,
                }
                break

    # 4. Projection metadata (read-model)
    if _get_proj_mgr:
        try:
            proj_mgr = _get_proj_mgr()
            proj_version = proj_mgr.get_projection_version(workflow_id)
            proj_state = proj_mgr.get_projection_state(workflow_id)
            if proj_state:
                result["projection_metadata"] = {
                    "version": proj_version,
                    "state": proj_state,
                    "timestamp": proj_state.get("projection_timestamp"),
                }
                # Enrich timing metadata
                if result["timing_metadata"] is None:
                    result["timing_metadata"] = {}
                result["timing_metadata"]["last_projection_refresh"] = proj_state.get("projection_timestamp")
        except Exception:
            pass  # Projection unavailable is non-fatal for observability

    return result


@app.get("/runtime/registry/summary")
def runtime_registry_summary():
    """
    GET /runtime/registry/summary
    Returns summary of runtime registry state for debugging and validation.

    Per VALIDATION_ARCHITECTURE.txt §9: Runtime observability for survivability debugging.
    Per LIFECYCLE_AUTHORITY_CONTRACT_V1: Runtime registry is sole lifecycle authority.

    READ-ONLY: Does NOT expose internal registry references or enable mutation.
    Returns aggregated counts and workflow state distribution.

    Returns:
    - total_workflows: count in runtime registry
    - status_distribution: count by lifecycle status
    - execution_generations: list of (workflow_id, generation) for validation
    - stream_registry_count: active stream entries
    - observability_timestamp: inspection time
    """
    try:
        from system.orchestrator.workflow_control import _workflow_state_registry, _workflow_state_lock

        result = {
            "total_workflows": 0,
            "status_distribution": {},
            "execution_generations": [],
            "stream_registry_count": 0,
            "observability_timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 1. Runtime registry summary (lifecycle authority)
        with _workflow_state_lock:
            result["total_workflows"] = len(_workflow_state_registry)
            for wf_id, state in _workflow_state_registry.items():
                status = state.get("status", "UNKNOWN")
                result["status_distribution"][status] = result["status_distribution"].get(status, 0) + 1
                # Include execution_generation for stale-owner validation
                result["execution_generations"].append({
                    "workflow_id": wf_id,
                    "execution_generation": state.get("execution_generation", 1),
                    "status": status,
                })

        # 2. Stream registry count (projection cache)
        with _stream_registry_lock:
            result["stream_registry_count"] = len(_stream_registry)

        return result
    except Exception as e:
        import traceback
        print(f"[RUNTIME_REGISTRY_SUMMARY_ERROR] {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Runtime registry summary error: {type(e).__name__}: {e}")


# =============================================================================
# TEST/ADMIN ONLY — AUTHORITATIVE RUNTIME RESET
# =============================================================================
# Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §7:
#   Orphan runtime artifacts may be invalidated or rebuilt without affecting
#   lifecycle authority.
# Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
#   Terminalization MUST terminate execution and retry workers.
# Per STATE_TRANSITIONS_CONTRACT_V1: ACTIVE|PAUSED|BLOCKED|ACTIVATING|PENDING_RECOVERY → FAILED
#
# WARNING: This endpoint is TEST/ADMIN SCOPED ONLY. It is NOT a GUI feature.
# It safely terminates active workflows and clears runtime coordination state
# to ensure test isolation. It does NOT redesign orchestration or weaken
# authority boundaries.
# =============================================================================

@app.post("/admin/test/reset_runtime")
def reset_runtime(request: Request):
    """
    TEST/ADMIN ONLY: Authoritative runtime reset.
    Gated by _require_admin_test_enabled. Disabled by default.

    Safely terminates all active workflows via lifecycle authority,
    clears runtime coordination state, and recreates the execution executor.

    Reset sequence (all steps failure-isolated):
      1. Stop all active workflows via stop_workflow() (authoritative terminal convergence)
      2. Cooperative exit window for execution loops
      3. Shutdown ThreadPoolExecutor and create fresh executor
      4. Clear _workflow_state_registry
      5. Clear _stream_registry
      6. Clear _bg_manager tracking
      7. Clear _pending_approvals
      8. Clear projection stores
      9. Clear bg_id_map persistence
      10. Delete disk artifacts (active workflows, checkpoints, bg_id_map)
    """
    _require_admin_test_enabled(request)

    from system.orchestrator.workflow_control import _workflow_state_registry, _workflow_state_lock

    stopped_count = 0
    evicted_count = 0

    # ── PHASE 1: Authoritative terminal convergence for active workflows ──
    with _workflow_state_lock:
        wf_ids = list(_workflow_state_registry.keys())

    for wf_id in wf_ids:
        try:
            state = _get_workflow_state(wf_id)
            if state and state.get("status") in ("ACTIVE", "PAUSED", "BLOCKED", "ACTIVATING", "PENDING_RECOVERY"):
                result = stop_workflow(wf_id)
                if result.get("status") == "success":
                    stopped_count += 1
                else:
                    # Fallback: mark registry FAILED directly if stop_workflow failed
                    _update_runtime_registry_only(wf_id, "FAILED", "reset_evict_fallback")
                    evicted_count += 1
            else:
                # Already terminal or missing — mark FAILED to ensure no stale active entry
                _update_runtime_registry_only(wf_id, "FAILED", "reset_cleanup")
                evicted_count += 1
        except Exception:
            pass

    print(f"[RESET] stopped={stopped_count} evicted={evicted_count}")

    # ── PHASE 2: Cooperative exit window ──
    # Execution loops check registry at step boundaries. Give them a brief
    # window to observe FAILED and exit cooperatively.
    import time
    time.sleep(2)

    # ── PHASE 2b: Wait for BackgroundManager threads ──
    # BackgroundManager threads are NOT part of ThreadPoolExecutor.
    # Old threads must exit before new tests start to avoid LLM API contention.
    try:
        with _bg_manager._lock:
            _bg_entries = list(_bg_manager._workflows.items())
        for _wid, _entry in _bg_entries:
            _thread = _entry.get("thread")
            if _thread is not None and _thread.is_alive():
                _thread.join(timeout=5)
    except Exception:
        pass

    # ── PHASE 3: Executor shutdown and recreation ──
    global _executor
    try:
        _executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    _executor = ThreadPoolExecutor(max_workers=4)

    # ── PHASE 4: Clear runtime registries ──
    with _workflow_state_lock:
        _workflow_state_registry.clear()

    with _stream_registry_lock:
        _stream_registry.clear()

    # ── PHASE 5: Clear background manager tracking ──
    with _bg_manager._lock:
        _bg_manager._workflows.clear()

    # ── PHASE 6: Clear pending approvals ──
    # Per USER_APPROVAL_CONTRACT_V1: clear approval registry on runtime reset
    try:
        from system.orchestrator.user_approval import _approval_registry, _approval_registry_lock
        with _approval_registry_lock:
            _approval_registry.clear()
    except Exception:
        pass

    # ── PHASE 7: Clear projection stores ──
    try:
        if _get_proj_mgr is not None:
            _pm = _get_proj_mgr()
            for _wf_id in list(_pm.get_workflow_ids()):
                try:
                    _pm.remove_workflow(_wf_id)
                except Exception:
                    pass
    except Exception:
        pass

    # ── PHASE 8: Clear bg_id_map persistence ──
    try:
        if _load_bg_id_map is not None and _deregister_bg_id is not None:
            _all_bg = _load_bg_id_map()
            for _bg_id in list(_all_bg.keys()):
                try:
                    _deregister_bg_id(_bg_id)
                except Exception:
                    pass
    except Exception:
        pass

    # ── PHASE 9: Delete disk artifacts ──
    # Active workflow files
    try:
        from system.orchestrator.persistence import ACTIVE_WORKFLOW_DIR as _aw_dir
        if os.path.exists(_aw_dir):
            for _f in os.listdir(_aw_dir):
                if _f.endswith(".json"):
                    try:
                        os.remove(os.path.join(_aw_dir, _f))
                    except Exception:
                        pass
    except Exception:
        pass

    # Checkpoint files
    try:
        from system.orchestrator.checkpoint_manager import CHECKPOINT_DIR as _cp_dir
        if os.path.exists(_cp_dir):
            for _f in os.listdir(_cp_dir):
                if _f.endswith(".json"):
                    try:
                        os.remove(os.path.join(_cp_dir, _f))
                    except Exception:
                        pass
    except Exception:
        pass

    # bg_id_map file
    try:
        from system.orchestrator.bg_id_map import _MAP_PATH as _bg_map_path
        if os.path.exists(_bg_map_path):
            try:
                os.remove(_bg_map_path)
            except Exception:
                pass
    except Exception:
        pass

    print("[RESET] runtime reset complete")

    return {
        "status": "reset_complete",
        "stopped_workflows": stopped_count,
        "evicted_workflows": evicted_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# PHASE TEST-DETERMINISTIC — AUTHENTIC DETERMINISTIC FAILURE GENERATION
# =============================================================================
# Per AUTHENTIC_DETERMINISTIC_FAILURE_CONTRACT_V1:
#   Creates REAL runtime failure through legitimate orchestration execution.
#
# Purpose:
#   - Reliable FAILED state generation for retry/recovery validation
#   - Deterministic failure WITHOUT LLM dependency
#   - Authentic runtime semantics (events, projections, stale-owner)
#
# Mechanism:
#   Uses edit_step mutation to inject deterministic failure trigger.
#   Runtime naturally executes → fails → propagates through normal paths.
#
# WARNING: TEST/ADMIN SCOPED ONLY. NOT a GUI feature.
# =============================================================================

@app.post("/admin/test/execute_deterministic_fail")
def execute_deterministic_fail(req: ExecuteFailToolRequest, request: Request):
    """
    TEST ONLY: Authentic deterministic failure through runtime execution.
    Gated by _require_admin_test_enabled. Disabled by default.

    Creates REAL step failure by routing through legitimate orchestration:
      1. Edit step to include deterministic failure trigger
      2. Runtime naturally executes step
      3. Execution fails authentically
      4. Failure propagates: step → workflow → events → projections
      5. Retry legality appears naturally

    Per AUTHENTIC_FAILURE_CONTRACT:
      - Routes through mutation manager (not synthetic state write)
      - Runtime executes failure (not API-layer mutation)
      - Events emit naturally
      - Projections reconcile naturally
      - Stale-owner invalidation authentic

    Returns:
      { "status": "fail_triggered", "workflow_id": "...", "step_id": "..." }

    Raises:
      404: workflow not found
      404: step not found
      400: step already terminal
      503: mutation manager unavailable
    """
    _require_admin_test_enabled(request)

    if _request_plan_mutation is None:
        raise HTTPException(status_code=503, detail="mutation_manager_unavailable")

    # ── Load workflow to validate existence ───────────────────────────────────
    from system.orchestrator.persistence import load_workflow
    workflow = load_workflow(req.workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="workflow_not_found")

    # ── Find step to validate existence ───────────────────────────────────────
    steps = workflow.get("steps", [])
    target_step = None
    for s in steps:
        if s.get("id") == req.step_id or s.get("step_id") == req.step_id:
            target_step = s
            break

    if not target_step:
        raise HTTPException(status_code=404, detail=f"step_not_found: {req.step_id}")

    # ── Validate step is not already terminal ────────────────────────────────
    current_status = target_step.get("status", "PENDING")
    if current_status in ("COMPLETED", "FAILED", "CANCELLED"):
        raise HTTPException(
            status_code=400,
            detail=f"step_already_terminal: {current_status}"
        )

    # ── AUTHENTIC FAILURE: Edit step to trigger deterministic failure ─────────
    # This routes through mutation manager → runtime naturally executes
    # The _test_fail_trigger marker causes the runtime to raise an exception
    result = _request_plan_mutation(
        workflow_id=req.workflow_id,
        mutation_type="edit_step",
        payload={
            "step_id": req.step_id,
            "updates": {
                "_test_fail_trigger": True,
                "_test_fail_reason": req.reason,
            }
        },
        actor="test",
    )

    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason", "fail_trigger_failed"))

    print(f"[DETERMINISTIC_FAIL] workflow={req.workflow_id} step={req.step_id} reason={req.reason}")

    return {
        "status": "fail_triggered",
        "workflow_id": req.workflow_id,
        "step_id": req.step_id,
        "previous_step_status": current_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# DEV/TEST HELPER: Create Approval Request
# =============================================================================
# Per ISSUE-096B Run 2 manual validation requirement.
# Gated under /admin/test/ — NOT a production GUI feature.
# Used by head-dev to deterministically create an approval for frontend testing.
# Does NOT modify governance semantics; only creates a registered ApprovalRequest.
# =============================================================================

class CreateApprovalTestRequest(BaseModel):
    workflow_id: str
    step_id: Optional[str] = None
    reason: str = "approval_required"
    risk_level: str = "MEDIUM"
    requested_action: str = "execute_step"
    timeout_seconds: int = 1800


@app.post("/admin/test/create_approval_request")
def create_approval_request_test(req: CreateApprovalTestRequest, request: Request):
    """
    TEST ONLY: Create and register an ApprovalRequest for manual frontend validation.
    Gated by _require_admin_test_enabled. Disabled by default.

    Returns:
      { "status": "created", "approval_id": "...", "workflow_id": "..." }

    Raises:
      503: user_approval module unavailable
    """
    _require_admin_test_enabled(request)

    try:
        from system.orchestrator.user_approval import create_approval_request
    except Exception:
        raise HTTPException(status_code=503, detail="user_approval_module_unavailable")

    approval_req = create_approval_request(
        workflow_id=req.workflow_id,
        step_id=req.step_id,
        reason=req.reason,
        risk_level=req.risk_level,
        requested_action=req.requested_action,
        timeout_seconds=req.timeout_seconds,
    )

    return {
        "status": "created",
        "approval_id": approval_req.approval_id,
        "workflow_id": req.workflow_id,
        "step_id": req.step_id,
        "reason": req.reason,
        "risk_level": req.risk_level,
        "requested_action": req.requested_action,
        "created_at": approval_req.created_at,
        "expires_at": approval_req.expires_at,
    }


# =============================================================================
# ISSUE-094B + ISSUE-094C — LLM BUDGET / PROVIDER ROUTING OBSERVABILITY
# =============================================================================
# Per ISSUE-094B/094C: Read-only budget/status + runtime settings endpoints.
# No lifecycle/governance impact.
# =============================================================================

@app.get("/llm/budget/status")
def get_llm_budget_status():
    """
    GET /llm/budget/status
    Returns current LLM routing configuration, budget state, and OpenRouter status.
    Enhanced in ISSUE-094C with cloud_active, cloud_block_reason, effective_provider.
    """
    if _llm_budget is None:
        raise HTTPException(status_code=503, detail="llm_budget_module_unavailable")
    return _llm_budget.get_current_status()


@app.post("/llm/budget/refresh")
def post_llm_budget_refresh():
    """
    POST /llm/budget/refresh
    Refreshes OpenRouter key status and model catalogue.
    Returns updated status.
    """
    if _llm_budget is None:
        raise HTTPException(status_code=503, detail="llm_budget_module_unavailable")
    _llm_budget.refresh_openrouter_key_status()
    catalogue = _llm_budget.refresh_model_catalogue()
    if catalogue is not None:
        _llm_budget.set_model_catalogue(catalogue)
    return _llm_budget.get_current_status()


@app.post("/llm/settings")
def post_llm_settings(req: dict):
    """
    POST /llm/settings
    Update runtime-only LLM settings. Does NOT write .env.
    Accepted keys:
      mode, planner_provider, agent_provider, formatter_provider, validator_provider,
      planner_pool, agent_pool, formatter_pool, validator_pool,
      daily_budget_usd, monthly_budget_usd, credit_reserve_usd,
      fallback_on_budget, fallback_provider
    """
    if _llm_budget is None:
        raise HTTPException(status_code=503, detail="llm_budget_module_unavailable")
    return _llm_budget.update_runtime_settings(req)


@app.post("/llm/settings/reset-local")
def post_llm_settings_reset_local():
    """
    POST /llm/settings/reset-local
    Reset all runtime settings to safe local defaults.
    Does NOT remove the OpenRouter API key from env.
    """
    if _llm_budget is None:
        raise HTTPException(status_code=503, detail="llm_budget_module_unavailable")
    return _llm_budget.reset_local_settings()


@app.get("/llm/usage/recent")
def get_llm_usage_recent(limit: int = 10):
    """
    GET /llm/usage/recent?limit=10
    Returns recent LLM usage ledger entries.
    No secrets exposed (no prompt text, no API key, no raw response).
    """
    try:
        from system.llm import usage_ledger as _ledger
        entries = _ledger.query_recent(limit=limit)
        # Sanitize: drop any fields that might contain secrets
        safe_fields = {
            "timestamp_iso",
            "caller_role",
            "provider",
            "model",
            "status",
            "fallback_used",
            "fallback_attempt_index",
            "route_reason",
            "estimated_cost_usd",
            "error_type",
            "is_free_model",
        }
        sanitized = []
        for entry in entries:
            sanitized.append({k: entry.get(k) for k in safe_fields})
        return {"entries": sanitized}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ledger_query_failed: {e}")


@app.get("/llm/usage/workflow/{workflow_id}")
def get_llm_usage_workflow(workflow_id: str, limit: int = 50):
    """
    GET /llm/usage/workflow/{workflow_id}?limit=50
    Returns LLM usage ledger entries for a specific workflow.
    No secrets exposed (no prompt text, no API key, no raw response).
    """
    try:
        from system.llm import usage_ledger as _ledger
        entries = _ledger.query_workflow(workflow_id, limit=limit)
        # Sanitize: drop any fields that might contain secrets
        safe_fields = {
            "timestamp_iso",
            "workflow_id",
            "caller_role",
            "provider",
            "model",
            "status",
            "fallback_used",
            "fallback_attempt_index",
            "route_reason",
            "estimated_cost_usd",
            "error_type",
            "is_free_model",
        }
        sanitized = []
        for entry in entries:
            sanitized.append({k: entry.get(k) for k in safe_fields})
        return {"workflow_id": workflow_id, "entries": sanitized}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ledger_query_failed: {e}")

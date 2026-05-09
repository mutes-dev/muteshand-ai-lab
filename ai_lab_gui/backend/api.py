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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Optional
import asyncio
import threading
import uuid as _uuid_mod
from concurrent.futures import ThreadPoolExecutor

# === SYSTEM IMPORTS (verified real contracts) ===
from system.orchestrator.orchestrator_runtime import execute_from_input, get_workflow_id_for_thread, run_workflow
from system.orchestrator.user_control import (
    set_override,
    get_override,
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
)
from system.orchestrator.persistence import load_active_workflows
from system.orchestrator.bootstrap import initialize_system
from system.runtime.background_manager import BackgroundManager

# ── module-level singletons ──────────────────────────────────────────────────
_bg_manager = BackgroundManager()
_executor = ThreadPoolExecutor(max_workers=4)

# ── pending approvals queue (GUI-facing approval flow) ──────────────────────
# Maps step_id → {"step": dict, "resolve": asyncio.Future}
_pending_approvals: dict[str, dict] = {}


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
            "retries": step.get("retries", 0)
        }
        
        # Add blocked_reason if present (runtime state, not execution field)
        if step.get("blocked_reason"):
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


@app.on_event("startup")
def on_startup():
    initialize_system()


# =============================================================================
# REQUEST MODELS
# =============================================================================

class ExecuteRequest(BaseModel):
    input: str


class OverrideRequest(BaseModel):
    value: bool


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


class BackgroundStartRequest(BaseModel):
    input: str


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

# Registry: bg_id → {"orchestrator_workflow_id": str|None, "result": dict|None, "status": str}
_stream_registry: dict = {}
_stream_registry_lock = threading.Lock()


def _stream_execute_wrapper(bg_id: str, user_input: str) -> None:
    """
    Thread target: runs execute_from_input and writes orchestrator workflow_id
    and final result into _stream_registry as soon as they are available.
    Does NOT modify execute_from_input — pure wrapper.
    """
    import time as _time

    tid = threading.current_thread().ident

    # Background poller: checks thread registry every 200ms for early workflow_id.
    # Stops once workflow_id is found or execution completes.
    _wfid_found = threading.Event()

    def _poll_workflow_id():
        while not _wfid_found.is_set():
            wf_id = get_workflow_id_for_thread(tid)
            if wf_id:
                with _stream_registry_lock:
                    if _stream_registry[bg_id]["orchestrator_workflow_id"] is None:
                        _stream_registry[bg_id]["orchestrator_workflow_id"] = wf_id
                _wfid_found.set()
                return
            _time.sleep(0.2)

    poller = threading.Thread(target=_poll_workflow_id, daemon=True, name=f"wfid-poller-{bg_id[:8]}")
    poller.start()

    try:
        result = execute_from_input(user_input, bg_id, _stream_registry, _stream_registry_lock)
        _wfid_found.set()  # stop poller
        orchestrator_wf_id = result.get("workflow_id")
        with _stream_registry_lock:
            _stream_registry[bg_id]["orchestrator_workflow_id"] = orchestrator_wf_id
            _stream_registry[bg_id]["result"] = result
            _stream_registry[bg_id]["status"] = "COMPLETED"
    except Exception as e:
        _wfid_found.set()  # stop poller
        with _stream_registry_lock:
            _stream_registry[bg_id]["status"] = "FAILED"
            _stream_registry[bg_id]["error"] = str(e)


@app.post("/execute/stream")
def execute_stream(req: ExecuteRequest):
    """
    POST /execute/stream
    Starts execute_from_input in a background thread.
    Returns bg_id immediately — frontend uses this to poll for workflow_id and result.
    Execution path is identical to /execute — no bypass of system_entry.
    """
    if not req.input or not req.input.strip():
        raise HTTPException(status_code=400, detail="input must not be empty")

    bg_id = str(_uuid_mod.uuid4())
    with _stream_registry_lock:
        _stream_registry[bg_id] = {
            "orchestrator_workflow_id": None,
            "workflow": None,
            "result": None,
            "status": "ACTIVE",
            "error": None,
        }

    t = threading.Thread(
        target=_stream_execute_wrapper,
        args=(bg_id, req.input),
        daemon=True,
        name=f"stream-{bg_id[:8]}",
    )
    t.start()
    return {"bg_id": bg_id, "status": "ACTIVE"}


@app.get("/execute/stream/workflow_id/{bg_id}")
def stream_workflow_id(bg_id: str):
    """
    GET /execute/stream/workflow_id/{bg_id}
    Returns orchestrator workflow_id once planning completes (written by thread).
    Returns null if planning not yet complete.
    Frontend polls this at startup to get the real workflow_id for event streaming.
    
    When status == COMPLETED, includes the projected result in the response to eliminate
    the race condition where UI shows COMPLETED but "No result yet".
    """
    with _stream_registry_lock:
        entry = _stream_registry.get(bg_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="bg_id not found")
    
    response = {
        "bg_id": bg_id,
        "workflow_id": entry["orchestrator_workflow_id"],
        "status": entry["status"],
    }
    
    # Embed projected result when workflow has workflow (during ACTIVE or COMPLETED)
    workflow = entry.get("workflow")
    if workflow and isinstance(workflow, dict) and "steps" in workflow:
        projected = project_workflow_for_gui(workflow)
        response["result"] = projected
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
    return {"status": "ok", "paused": True, "workflow_id": workflow_id}


@app.post("/resume/{workflow_id}")
async def resume_workflow_endpoint(workflow_id: str):
    """
    POST /resume/{workflow_id}
    Resume a specific workflow using state transition.
    Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED → ACTIVE
    Per GUI_FUNCTIONALITY_CONTRACT_V1: ALL actions require workflow_id
    """
    result = resume_workflow(workflow_id)
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))

    # Load workflow from persistence
    persisted_workflows = load_active_workflows()
    workflow = None
    for pw in persisted_workflows:
        if pw.get("id") == workflow_id:
            workflow = pw
            break

    if workflow is None:
        raise HTTPException(status_code=404, detail="workflow_not_found")

    # Verify transition occurred
    if workflow.get("status") != "ACTIVE":
        raise HTTPException(status_code=400, detail="workflow_not_resumed")

    # Create a bg_id for streaming the resume result
    bg_id = str(_uuid_mod.uuid4())
    with _stream_registry_lock:
        _stream_registry[bg_id] = {
            "orchestrator_workflow_id": workflow_id,
            "result": None,
            "status": "ACTIVE",
            "error": None,
        }

    # Workflow re-entry: run_workflow continues execution
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, run_workflow, workflow)

    # Store result in stream registry for frontend polling
    with _stream_registry_lock:
        _stream_registry[bg_id]["result"] = result
        _stream_registry[bg_id]["status"] = "COMPLETED"

    return {"status": "ok", "resumed": True, "workflow_id": workflow_id, "bg_id": bg_id}


@app.post("/override")
def set_override_flag(req: OverrideRequest):
    """POST /override → user_control.set_override(value)"""
    set_override(req.value)
    return {"status": "ok", "override": req.value}


@app.get("/status")
def get_status():
    """GET /status → user_control.get_control_state()"""
    return get_control_state()


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
def get_events(workflow_id: str, since: int = -1, limit: int = 100):
    """
    GET /events/{workflow_id}?since={event_id}&limit={count}
    Returns live events for workflow state streaming.
    
    Per HAND_ARCHITECTURE_V2 Section 15: LIVE mode provides step-by-step visibility
    Per CONTROL_MODEL: Events are advisory, non-authoritative
    Per TRACE_LOGGING_CONTRACT_V1: UI uses STATE (events), not trace, for live updates
    
    Args:
        since: Return only events after this event index (for polling)
        limit: Maximum events to return (default 100)
    
    Returns:
        List of events with:
        - event_type: step_started, step_completed, governance_decision, etc.
        - timestamp: ISO8601 timestamp
        - data: Event payload (step_id, status, result, etc.)
    """
    from system.interface.event_bus import get_events as _get_events
    
    since_event_id = since if since >= 0 else None
    events = _get_events(workflow_id, since_event_id=since_event_id, limit=limit)

    # Add sequential IDs for since-based polling
    base = since + 1 if since >= 0 else 0
    for i, event in enumerate(events):
        event["event_id"] = base + i

    return {
        "workflow_id": workflow_id,
        "events": events,
        "count": len(events),
        "latest_event_id": base + len(events) - 1 if events else since
    }


# =============================================================================
# PHASE 2.4 — APPROVAL
# =============================================================================

@app.get("/approval/pending")
def approval_pending():
    """
    GET /approval/pending
    Returns list of steps currently awaiting GUI approval.
    Steps are projected to remove execution-only fields (tool_call, execution_result).
    """
    pending = [
        {
            "step_id": sid,
            "step": project_step_for_approval(entry["step"]),
        }
        for sid, entry in _pending_approvals.items()
        if not entry.get("resolved", False)
    ]
    return {"pending": pending}


@app.post("/approve")
def approve_step(req: ApprovalRequest):
    """
    POST /approve  { workflow_id, step_id, approved: true }
    Resolves the pending approval — MUST NOT bypass governance.
    Governance already decided BLOCK; this only records user choice.
    Per GUI_FUNCTIONALITY_CONTRACT_V1: ALL actions require workflow_id
    """
    entry = _pending_approvals.get(req.step_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="no pending approval for that step_id")
    if entry.get("resolved"):
        raise HTTPException(status_code=409, detail="already resolved")
    entry["approved"] = req.approved
    entry["resolved"] = True
    future: asyncio.Future = entry.get("future")
    if future and not future.done():
        future.get_loop().call_soon_threadsafe(future.set_result, req.approved)
    return {"status": "ok", "workflow_id": req.workflow_id, "step_id": req.step_id, "approved": req.approved}


@app.post("/deny")
def deny_step(req: ApprovalRequest):
    """
    POST /deny  { workflow_id, step_id, approved: false }
    Convenience alias — delegates to /approve with approved=False.
    Per GUI_FUNCTIONALITY_CONTRACT_V1: ALL actions require workflow_id
    """
    req.approved = False
    return approve_step(req)


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
    return {
        "control_state": get_control_state(),
        "pending_approvals": list(_pending_approvals.keys()),
        "background_count": _bg_manager.active_count(),
    }


# =============================================================================
# PHASE 2.7 — PLAN CONTROL (Per PLAN_CONTROL_CONTRACT_V1)
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
    Per PLAN_CONTROL_CONTRACT_V1: validates edit and dependency graph.
    """
    result = edit_step(req.workflow_id, req.step_id, req.updates)
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return result


@app.post("/plan/add")
def add_step_endpoint(req: PlanAddRequest):
    """
    POST /plan/add
    Add a new step to the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1: validates and appends step.
    """
    result = add_plan_step(req.workflow_id, req.step_data)
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return result


@app.post("/plan/remove")
def remove_step_endpoint(req: PlanRemoveRequest):
    """
    POST /plan/remove
    Remove a step from the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1: rejects if step is COMPLETED or has dependents.
    """
    result = remove_plan_step(req.workflow_id, req.step_id)
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return result


@app.post("/plan/reorder")
def reorder_steps_endpoint(req: PlanReorderRequest):
    """
    POST /plan/reorder
    Reorder steps in the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1: validates dependency constraints.
    """
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
    Requires workflow_id and step_id.
    """
    result = retry_step(req.workflow_id, req.step_id)
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return result


@app.post("/workflow/stop")
def stop_workflow_endpoint(req: StopWorkflowRequest):
    """
    POST /workflow/stop
    Stop a running workflow.
    Per STATE_TRANSITIONS_CONTRACT_V1: ACTIVE|PAUSED|BLOCKED → FAILED
    """
    result = stop_workflow(req.workflow_id)
    if result.get("status") == "failure":
        raise HTTPException(status_code=400, detail=result.get("reason"))
    return result

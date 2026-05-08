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
    pause,
    resume,
    set_override,
    get_override,
    is_paused,
    get_control_state,
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


class ApprovalRequest(BaseModel):
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
    Returns execution_result as-is — no mutation.
    """
    if not req.input or not req.input.strip():
        raise HTTPException(status_code=400, detail="input must not be empty")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, execute_from_input, req.input)
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
        result = execute_from_input(user_input)
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
    """
    with _stream_registry_lock:
        entry = _stream_registry.get(bg_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="bg_id not found")
    return {
        "bg_id": bg_id,
        "workflow_id": entry["orchestrator_workflow_id"],
        "status": entry["status"],
    }


@app.get("/execute/stream/result/{bg_id}")
def stream_result(bg_id: str):
    """
    GET /execute/stream/result/{bg_id}
    Returns final execution result once workflow completes.
    Frontend polls this after receiving workflow_id, to get the final result.
    """
    with _stream_registry_lock:
        entry = _stream_registry.get(bg_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="bg_id not found")
    return {
        "bg_id": bg_id,
        "status": entry["status"],
        "result": entry["result"],
        "error": entry.get("error"),
    }


# =============================================================================
# PHASE 2.2 — SYSTEM CONTROL
# =============================================================================

@app.post("/pause")
def pause_system():
    """POST /pause → user_control.pause()"""
    pause()
    return {"status": "ok", "paused": True}


@app.post("/resume")
async def resume_system(req: ResumeRequest):
    """
    POST /resume → user_control.resume() + workflow re-entry
    
    Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED → ACTIVE transition
    Resume must use workflow re-entry (NOT loop continuation).
    """
    # Resume control state
    resume()
    
    # Load workflow from persistence
    workflow_id = req.workflow_id
    persisted_workflows = load_active_workflows()
    workflow = None
    for pw in persisted_workflows:
        if pw.get("id") == workflow_id:
            workflow = pw
            break
    
    if workflow is None:
        raise HTTPException(status_code=404, detail="workflow_not_found")
    
    # Explicit PAUSED → ACTIVE transition (per STATE_TRANSITIONS_CONTRACT_V1)
    # ONLY this endpoint may perform this transition
    if workflow.get("status") == "PAUSED":
        workflow["status"] = "ACTIVE"
    
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
    """
    pending = [
        {
            "step_id": sid,
            "step": entry["step"],
        }
        for sid, entry in _pending_approvals.items()
        if not entry.get("resolved", False)
    ]
    return {"pending": pending}


@app.post("/approve")
def approve_step(req: ApprovalRequest):
    """
    POST /approve  { step_id, approved: true }
    Resolves the pending approval — MUST NOT bypass governance.
    Governance already decided BLOCK; this only records user choice.
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
    return {"status": "ok", "step_id": req.step_id, "approved": req.approved}


@app.post("/deny")
def deny_step(req: ApprovalRequest):
    """
    POST /deny  { step_id, approved: false }
    Convenience alias — delegates to /approve with approved=False.
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

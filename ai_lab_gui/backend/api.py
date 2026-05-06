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
from concurrent.futures import ThreadPoolExecutor

# === SYSTEM IMPORTS (verified real contracts) ===
from system.orchestrator.orchestrator_runtime import execute_from_input
from system.orchestrator.user_control import (
    pause,
    resume,
    set_override,
    get_override,
    is_paused,
    get_control_state,
)
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
# PHASE 2.2 — SYSTEM CONTROL
# =============================================================================

@app.post("/pause")
def pause_system():
    """POST /pause → user_control.pause()"""
    pause()
    return {"status": "ok", "paused": True}


@app.post("/resume")
def resume_system():
    """POST /resume → user_control.resume()"""
    resume()
    return {"status": "ok", "paused": False}


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

@app.get("/debug/control_state")
def debug_control_state():
    """GET /debug/control_state — raw control state dump"""
    return {
        "control_state": get_control_state(),
        "pending_approvals": list(_pending_approvals.keys()),
        "background_count": _bg_manager.active_count(),
    }

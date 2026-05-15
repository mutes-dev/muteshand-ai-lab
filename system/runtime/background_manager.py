"""
BACKGROUND EXECUTION MANAGER — Non-Blocking Workflow Wrapper (Phase 7)

Responsibility:
- Enable non-blocking, background workflow execution
- Track multiple concurrent workflows
- Expose workflow status for user visibility

Architecture Alignment (Phase VII Authority Hardening):
- WRAPPER ONLY — does NOT modify orchestrator, scheduler, or governance
- All execution flows through existing execute_from_input → run_workflow → system_entry
- Workflow-level state is a READ-ONLY MIRROR of the authoritative registry
- Does NOT interfere with step state transitions or governance decisions
- Does NOT own, infer, or cache lifecycle — consumes from _get_workflow_state()

Rules:
- NO execution logic — delegates entirely to workflow_fn
- NO modification of orchestrator_runtime
- NO bypass of system_entry
- Thread-safe workflow registry
- Daemon threads — background workflows terminate with main process
- NO direct lifecycle mutations — registry is sole authority

Known Limitations (Phase 2B):
- trace_collector is global singleton — concurrent workflows may overwrite traces
- conflict_detector is shared — concurrent workflows share conflict state (by design)
- user_control (pause/override) is global — affects all workflows
"""

import threading
import uuid
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from system.orchestrator.workflow_control import _get_workflow_state


class BackgroundManager:
    """
    Manages non-blocking workflow execution via threading.

    Each workflow runs in its own daemon thread using the existing
    orchestrator execution path. The manager tracks lifecycle state
    (QUEUED → ACTIVE → COMPLETED/FAILED) without interfering with
    step-level state transitions managed by governance.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._workflows: Dict[str, Dict[str, Any]] = {}

    def start_workflow(self, workflow_fn: Callable, *args, **kwargs) -> str:
        """
        Start a workflow in the background.

        Args:
            workflow_fn: The function to execute (e.g., execute_from_input)
            *args: Positional arguments for workflow_fn
            **kwargs: Keyword arguments for workflow_fn

        Returns:
            workflow_id: Unique identifier for tracking this workflow
        """
        workflow_id = str(uuid.uuid4())

        with self._lock:
            self._workflows[workflow_id] = {
                "result": None,
                "error": None,
                "thread": None,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": None,
            }

        thread = threading.Thread(
            target=self._run_workflow,
            args=(workflow_id, workflow_fn, args, kwargs),
            daemon=True,
            name=f"workflow-{workflow_id[:8]}",
        )

        with self._lock:
            self._workflows[workflow_id]["thread"] = thread

        thread.start()
        return workflow_id

    def _run_workflow(
        self,
        workflow_id: str,
        workflow_fn: Callable,
        args: tuple,
        kwargs: dict,
    ) -> None:
        """
        Internal thread target. Runs the workflow function and captures result.

        Per PHASE VII Authority Hardening:
        - background_manager does NOT own, write, or cache lifecycle.
        - Local cache stores execution metadata only (result, error, timestamps).
        - Job status is derived from completion metadata, NOT written directly.
        """
        try:
            result = workflow_fn(*args, **kwargs)
            with self._lock:
                self._workflows[workflow_id]["result"] = result
                self._workflows[workflow_id]["completed_at"] = (
                    datetime.now(timezone.utc).isoformat()
                )
        except Exception as e:
            with self._lock:
                self._workflows[workflow_id]["error"] = str(e)
                self._workflows[workflow_id]["completed_at"] = (
                    datetime.now(timezone.utc).isoformat()
                )

    def _derive_job_status(self, entry: dict) -> str:
        """Derive job status from completion metadata (read-only, no lifecycle ownership)."""
        if entry.get("completed_at") is not None:
            return "FAILED" if entry.get("error") is not None else "COMPLETED"
        if entry.get("thread") is not None:
            return "ACTIVE"
        return "QUEUED"

    def get_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the current status of a workflow.

        Per PHASE VII: status is sourced from the authoritative registry.
        Job tracker provides derived status only as fallback.

        Returns:
            Dict with status, result, error, timestamps — or None if not found.
            Thread object is excluded from output (not serializable).
        """
        with self._lock:
            entry = self._workflows.get(workflow_id)
            if entry is None:
                return None

        # Authority-first: read from registry, fall back to derived job status
        _auth = _get_workflow_state(workflow_id)
        _status = _auth.get("status") if _auth else None
        if _status is None:
            _status = self._derive_job_status(entry)

        return {
            "workflow_id": workflow_id,
            "status": _status,
            "result": entry["result"],
            "error": entry["error"],
            "started_at": entry["started_at"],
            "completed_at": entry["completed_at"],
        }

    def list_workflows(self) -> List[Dict[str, Any]]:
        """
        List all tracked workflows and their statuses.

        Per PHASE VII: status is sourced from the authoritative registry.

        Returns:
            List of workflow status dicts (thread excluded).
        """
        with self._lock:
            entries = list(self._workflows.items())

        result = []
        for wid, entry in entries:
            _auth = _get_workflow_state(wid)
            _status = _auth.get("status") if _auth else self._derive_job_status(entry)
            result.append({
                "workflow_id": wid,
                "status": _status,
                "started_at": entry["started_at"],
                "completed_at": entry["completed_at"],
            })
        return result

    def is_active(self, workflow_id: str) -> bool:
        """Check if a workflow is still running."""
        _auth = _get_workflow_state(workflow_id)
        if _auth:
            return _auth.get("status") in ("QUEUED", "ACTIVE", "ACTIVATING", "PENDING_RECOVERY")
        with self._lock:
            entry = self._workflows.get(workflow_id)
            if entry is None:
                return False
            return entry.get("completed_at") is None

    def active_count(self) -> int:
        """Return the number of currently active workflows."""
        with self._lock:
            entries = list(self._workflows.items())
        _active_from_registry = [
            wid for wid, _ in entries
            if (_get_workflow_state(wid) or {}).get("status") in ("QUEUED", "ACTIVE", "ACTIVATING", "PENDING_RECOVERY")
        ]
        if _active_from_registry:
            return len(_active_from_registry)
        # Fallback: count jobs that have not completed
        return sum(
            1 for _, entry in entries
            if entry.get("completed_at") is None
        )

    def wait_for(self, workflow_id: str, timeout: float = None) -> Optional[Dict[str, Any]]:
        """
        Block until a workflow completes (or timeout).

        Args:
            workflow_id: The workflow to wait for
            timeout: Max seconds to wait (None = wait forever)

        Returns:
            Workflow status dict, or None if not found.
        """
        with self._lock:
            entry = self._workflows.get(workflow_id)
            if entry is None:
                return None
            thread = entry.get("thread")

        if thread is not None:
            thread.join(timeout=timeout)

        return self.get_status(workflow_id)

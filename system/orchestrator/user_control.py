"""
USER CONTROL — Contract-Safe User-Control / Override / Force-Execution Request Model (ISSUE-098C)

Responsibility:
- Backend-owned user-control request creation, identity, and validation
- Thread-safe request bridge for future GUI user-control flow
- Distinct from ApprovalRequest: user-control is scoped intent, not governance BLOCK confirmation

Contracts:
- USER_CONTROL_CONTRACT_V2
- GOVERNANCE_CONTRACT_V2
- LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1
- TRACE_LOGGING_CONTRACT_V1

Authority:
- Governance remains the SOLE authority that decides execution outcomes
- This module creates the user-control request AFTER governance decides (or when operator initiates)
- Backend validates and resolves all user-control decisions
- Frontend is projection-only; may display and capture intent only
- User-control acceptance does NOT bypass governance, lifecycle, mutation, or dependency legality

Scope:
- Backend request model, registry, validation shell, trace emission, API endpoints ONLY
- NO runtime loop blocking/wiring in this issue
- NO governance decision action changes
- NO lifecycle state changes on accept/reject
- NO SKIPPED state
"""

import json
import os
import tempfile
import uuid
import threading
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, Any, List, Optional
from concurrent.futures import Future

from system.orchestrator import trace_collector

# ── PERSISTENCE ───────────────────────────────────────────────────────────────
# Per ISSUE-098N: user-control request persistence is a non-authoritative
# recovery mirror. The active _user_control_registry remains sole authority.
_MEMORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "memory"
)
_USER_CONTROLS_PERSISTENCE_PATH = os.path.join(_MEMORY_DIR, "user_controls.json")


# ── APPROVED REQUESTED_ACTION VALUES (098C ONLY) ──────────────────────────────
# Per USER_CONTROL_CONTRACT_V2 §10 + ISSUE-098C scope boundaries.
_USER_CONTROL_APPROVED_ACTIONS = frozenset({
    "force_step_retry",
    "force_workflow_replan",
    "override_low_confidence_block",
    "accept_external_call_risk",
    "continue_after_warning",
    "provide_replacement_input",
})

# Force retry budget constant per USER_CONTROL_CONTRACT_V2 §23.
FORCE_RETRY_LIMIT = 1

# Explicitly excluded / disallowed action names for 098C.
# These MUST be rejected with a clear error.
_USER_CONTROL_DISALLOWED_ACTIONS = frozenset({
    "cancel_blocked_branch",
    "force_success",
    "force_lifecycle_transition",
    "force_dependency_bypass",
    "force_active_mutation",
    "force_terminal_resurrection",
    "global_override",
    "project_override",
    "agent_override",
    "skip_step",
    "continue_execution",
    "force_retry",
    "stop_execution",
})


# ── ENUMS ─────────────────────────────────────────────────────────────────────

class UserControlStatus(str, Enum):
    """User-control request statuses per USER_CONTROL_CONTRACT_V2 §9."""
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"
    APPLIED = "APPLIED"


class UserControlRequestedAction(str, Enum):
    """
    Approved requested_action values for ISSUE-098C.
    These are the ONLY values accepted by create_user_control_request().
    """
    FORCE_STEP_RETRY = "force_step_retry"
    FORCE_WORKFLOW_REPLAN = "force_workflow_replan"
    OVERRIDE_LOW_CONFIDENCE_BLOCK = "override_low_confidence_block"
    ACCEPT_EXTERNAL_CALL_RISK = "accept_external_call_risk"
    CONTINUE_AFTER_WARNING = "continue_after_warning"
    PROVIDE_REPLACEMENT_INPUT = "provide_replacement_input"


# ── MODEL ─────────────────────────────────────────────────────────────────────

class UserControlRequest:
    """
    Backend-authored user-control / override / force-execution request.

    Per USER_CONTROL_CONTRACT_V2 §9:
    - Distinct from ApprovalRequest
    - scoped to workflow_id / step_id
    - carries requested_action, original_decision, risk_level, confirmation_text
    - backend_decision records the backend's validation outcome

    Thread-safe: all mutable state mutations protected by internal lock.
    """

    def __init__(
        self,
        workflow_id: str,
        step_id: Optional[str],
        requested_action: str,
        reason: str,
        original_decision: Optional[Dict[str, Any]] = None,
        risk_level: str = "MEDIUM",
        actor: str = "user",
        confirmation_text: Optional[str] = None,
        execution_generation: Optional[int] = None,
        retry_generation: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 1800,
    ):
        # Identity
        self.control_id = str(uuid.uuid4())
        self.workflow_id = workflow_id
        self.step_id = step_id

        # Action semantics
        self.requested_action = requested_action
        self.status = UserControlStatus.PENDING
        self.reason = reason
        self.original_decision = original_decision or {}
        self.risk_level = risk_level
        self.actor = actor
        self.confirmation_text = confirmation_text
        self.backend_decision: Optional[str] = None

        # Coordination / staleness
        self.execution_generation = execution_generation
        self.retry_generation = retry_generation
        self.metadata = metadata or {}

        # Timestamps
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.expires_at = (datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)).isoformat()
        self.resolved_at: Optional[str] = None
        self.resolved_by: Optional[str] = None

        # Thread-safe decision bridge (Future present for future runtime compatibility)
        # Per ISSUE-098C: Future may be present but MUST NOT be wired into runtime loop.
        self._future: Future = Future()
        self._lock = threading.RLock()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserControlRequest":
        """Reconstruct a UserControlRequest from serialized dict."""
        instance = object.__new__(cls)
        instance.control_id = data.get("control_id", str(uuid.uuid4()))
        instance.workflow_id = data.get("workflow_id", "")
        instance.step_id = data.get("step_id")
        instance.requested_action = data.get("requested_action", "")
        instance.status = UserControlStatus(data.get("status", "PENDING"))
        instance.reason = data.get("reason", "")
        instance.original_decision = data.get("original_decision") or {}
        instance.risk_level = data.get("risk_level", "MEDIUM")
        instance.actor = data.get("actor", "user")
        instance.confirmation_text = data.get("confirmation_text")
        instance.backend_decision = data.get("backend_decision")
        instance.execution_generation = data.get("execution_generation")
        instance.retry_generation = data.get("retry_generation")
        instance.metadata = data.get("metadata") or {}
        instance.created_at = data.get("created_at", datetime.now(timezone.utc).isoformat())
        instance.expires_at = data.get("expires_at", datetime.now(timezone.utc).isoformat())
        instance.resolved_at = data.get("resolved_at")
        instance.resolved_by = data.get("resolved_by")
        # Fresh thread-safe objects for runtime (old Future/Lock are not serializable)
        instance._future = Future()
        instance._lock = threading.RLock()
        return instance

    def to_dict(self, include_internal: bool = False) -> Dict[str, Any]:
        """Serialize to dict for API responses. JSON-safe."""
        data = {
            "control_id": self.control_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "requested_action": self.requested_action,
            "status": self.status.value,
            "reason": self.reason,
            "original_decision": self.original_decision,
            "risk_level": self.risk_level,
            "actor": self.actor,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
            "confirmation_text": self.confirmation_text,
            "backend_decision": self.backend_decision,
            "metadata": self.metadata,
        }
        if self.execution_generation is not None:
            data["execution_generation"] = self.execution_generation
        if self.retry_generation is not None:
            data["retry_generation"] = self.retry_generation
        if include_internal:
            data["_future_done"] = self._future.done()
        return data

    def is_expired(self) -> bool:
        """Check if user-control request has exceeded its expiry time."""
        try:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.now(timezone.utc) > expires
        except Exception:
            return False

    def is_pending(self) -> bool:
        """Check if user-control request is still PENDING."""
        with self._lock:
            return self.status == UserControlStatus.PENDING

    def resolve(self, accepted: bool, actor: str = "operator") -> None:
        """
        Resolve the user-control request. Called by API endpoint.

        Thread-safe. Sets the Future result so future runtime integration can continue.
        Per ISSUE-098C: does NOT apply runtime behavior itself.
        """
        with self._lock:
            if self._future.done():
                return
            self.status = UserControlStatus.ACCEPTED if accepted else UserControlStatus.REJECTED
            self.resolved_at = datetime.now(timezone.utc).isoformat()
            self.resolved_by = actor
            self._future.set_result(accepted)

    def expire(self) -> None:
        """Mark user-control as EXPIRED without resolving the future."""
        with self._lock:
            if not self._future.done():
                self.status = UserControlStatus.EXPIRED
                self.resolved_at = datetime.now(timezone.utc).isoformat()
                self._future.set_exception(TimeoutError("user_control_expired"))

    def cancel(self) -> None:
        """Mark user-control as CANCELLED without resolving the future."""
        with self._lock:
            if not self._future.done():
                self.status = UserControlStatus.CANCELLED
                self.resolved_at = datetime.now(timezone.utc).isoformat()
                self._future.set_exception(RuntimeError("user_control_cancelled"))

    def supersede(self, superseded_by: Optional[str] = None) -> None:
        """Mark user-control as SUPERSEDED."""
        with self._lock:
            if not self._future.done():
                self.status = UserControlStatus.SUPERSEDED
                self.resolved_at = datetime.now(timezone.utc).isoformat()
                if superseded_by:
                    self.metadata["superseded_by"] = superseded_by
                self._future.set_exception(RuntimeError("user_control_superseded"))


# ── REGISTRY ──────────────────────────────────────────────────────────────────
# control_id -> UserControlRequest
# Thread-safe via _user_control_registry_lock
_user_control_registry: Dict[str, UserControlRequest] = {}
_user_control_registry_lock = threading.Lock()


def _save_user_controls() -> None:
    """
    Persist all user-control requests to disk.
    Atomic write via tempfile + os.replace.
    FAILURE-ISOLATED: persistence failure must not break runtime.
    """
    try:
        with _user_control_registry_lock:
            snapshot = [req.to_dict() for req in _user_control_registry.values()]
        if not snapshot:
            # Write empty list so file exists and is valid JSON
            snapshot = []
        fd, tmp_path = tempfile.mkstemp(dir=_MEMORY_DIR, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2)
            os.replace(tmp_path, _USER_CONTROLS_PERSISTENCE_PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise
    except Exception as e:
        # Trace but do not crash
        try:
            trace_collector.record_transition(
                step_id="persistence",
                previous_status="PENDING",
                new_status="PENDING",
                reason=f"user_control_persistence_save_failed: {e}",
            )
        except Exception:
            pass


def _load_user_controls() -> Dict[str, Any]:
    """
    Load persisted user-control requests and validate each one.
    Returns {"loaded": int, "rejected": int, "rejection_reasons": List[str]}.
    """
    result = {"loaded": 0, "rejected": 0, "rejection_reasons": []}
    if not os.path.exists(_USER_CONTROLS_PERSISTENCE_PATH):
        return result

    try:
        with open(_USER_CONTROLS_PERSISTENCE_PATH, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        result["rejection_reasons"].append(f"parse_error: {e}")
        _emit_user_control_trace(
            event_name="user_control_persistence_loaded",
            workflow_id="global",
            step_id="load",
            control_id="global",
            data={"loaded": 0, "rejected": 0, "error": str(e)},
        )
        return result

    if not isinstance(snapshot, list):
        result["rejection_reasons"].append("top_level_not_list")
        return result

    loaded_count = 0
    rejected_count = 0
    rejection_reasons = []

    for req_dict in snapshot:
        if not isinstance(req_dict, dict):
            rejected_count += 1
            rejection_reasons.append("not_a_dict")
            continue
        try:
            req = UserControlRequest.from_dict(req_dict)
        except Exception as e:
            rejected_count += 1
            rejection_reasons.append(f"from_dict_failed: {e}")
            continue

        val = _validate_reconstructed_request(req)
        if val["valid"]:
            with _user_control_registry_lock:
                _user_control_registry[req.control_id] = req
            loaded_count += 1
        else:
            rejected_count += 1
            reason = val.get("reason", "unknown")
            rejection_reasons.append(reason)
            _emit_user_control_trace(
                event_name="user_control_stale_rejected",
                workflow_id=req.workflow_id,
                step_id=req.step_id,
                control_id=req.control_id,
                data={"reason": reason},
            )

    result["loaded"] = loaded_count
    result["rejected"] = rejected_count
    result["rejection_reasons"] = rejection_reasons

    _emit_user_control_trace(
        event_name="user_control_persistence_loaded",
        workflow_id="global",
        step_id="load",
        control_id="global",
        data={"loaded": loaded_count, "rejected": rejected_count, "path": _USER_CONTROLS_PERSISTENCE_PATH},
    )
    return result


def _validate_reconstructed_request(req: UserControlRequest) -> Dict[str, Any]:
    """
    Validate a reconstructed request against current authoritative state.
    Per PERSISTENCE_AND_DURABILITY_CONTRACT_V1: persistence is a mirror;
    stale or inconsistent persisted state MUST be rejected.
    """
    from system.orchestrator.persistence import load_workflow

    # 1. Workflow must exist
    wf = load_workflow(req.workflow_id)
    if wf is None:
        return {"valid": False, "reason": "workflow_not_found"}

    # 2. Workflow must not be terminal
    wf_status = wf.get("status", "UNKNOWN")
    if wf_status in ("COMPLETED", "CANCELLED", "QUARANTINED"):
        return {"valid": False, "reason": "workflow_terminal"}

    # 3. Step must exist
    steps = wf.get("steps", [])
    step = None
    for s in steps:
        if s.get("step_id") == req.step_id:
            step = s
            break
    if step is None:
        return {"valid": False, "reason": "step_not_found"}

    # 4. Step must still be BLOCKED or the block still applies
    step_status = step.get("status", "UNKNOWN")
    blocked_reason = step.get("blocked_reason", "")
    if step_status != "BLOCKED":
        return {"valid": False, "reason": "step_not_blocked"}
    if "external_call_risk" not in blocked_reason and req.requested_action == "accept_external_call_risk":
        return {"valid": False, "reason": "blocked_reason_mismatch"}

    # 5. execution_generation must match
    wf_exec_gen = wf.get("execution_generation")
    if wf_exec_gen is not None and req.execution_generation is not None:
        if req.execution_generation != wf_exec_gen:
            return {"valid": False, "reason": "execution_generation_mismatch"}

    # 6. retry_generation must match
    step_retry_gen = step.get("retry_generation")
    if step_retry_gen is not None and req.retry_generation is not None:
        if req.retry_generation != step_retry_gen:
            return {"valid": False, "reason": "retry_generation_mismatch"}

    # 7. Not expired
    if req.is_expired():
        return {"valid": False, "reason": "expired"}

    # 8. requested_action still approved
    action_check = _validate_requested_action(req.requested_action)
    if not action_check["valid"]:
        return {"valid": False, "reason": "disallowed_action"}

    return {"valid": True}


def _reconstruct_orphaned_user_control(workflow_id: str) -> Optional[UserControlRequest]:
    """
    If a BLOCKED workflow has a step with execution_result containing
    control_id + request_status: PENDING, but the registry is missing it,
    attempt validated reconstruction from the step metadata.
    """
    from system.orchestrator.persistence import load_workflow

    wf = load_workflow(workflow_id)
    if wf is None:
        return None

    wf_status = wf.get("status", "UNKNOWN")
    if wf_status != "BLOCKED":
        return None

    steps = wf.get("steps", [])
    for step in steps:
        if step.get("status") != "BLOCKED":
            continue
        er = step.get("execution_result", {})
        if not isinstance(er, dict):
            continue
        control_id = er.get("control_id")
        request_status = er.get("request_status")
        if not control_id or request_status != "PENDING":
            continue

        # Already in registry?
        if get_user_control_request(control_id) is not None:
            continue

        # Reconstruct from metadata
        req_dict = {
            "control_id": control_id,
            "workflow_id": workflow_id,
            "step_id": step.get("step_id"),
            "requested_action": "accept_external_call_risk",
            "status": "PENDING",
            "reason": er.get("reason", "external_call_risk"),
            "risk_level": er.get("risk_level", "MEDIUM"),
            "actor": er.get("actor", "runtime"),
            "execution_generation": wf.get("execution_generation"),
            "retry_generation": step.get("retry_generation"),
            "metadata": er.get("metadata", {}),
            "created_at": er.get("created_at", datetime.now(timezone.utc).isoformat()),
            "expires_at": er.get("expires_at", (datetime.now(timezone.utc) + timedelta(seconds=1800)).isoformat()),
        }
        try:
            req = UserControlRequest.from_dict(req_dict)
        except Exception:
            continue

        val = _validate_reconstructed_request(req)
        if val["valid"]:
            _emit_user_control_trace(
                event_name="user_control_reconstruction_attempted",
                workflow_id=workflow_id,
                step_id=step.get("step_id"),
                control_id=control_id,
                data={"success": True},
            )
            return req
        else:
            _emit_user_control_trace(
                event_name="user_control_reconstruction_attempted",
                workflow_id=workflow_id,
                step_id=step.get("step_id"),
                control_id=control_id,
                data={"success": False, "reason": val.get("reason")},
            )

    return None


def _register_user_control(request: UserControlRequest) -> None:
    """Register a user-control request in the global registry."""
    with _user_control_registry_lock:
        _user_control_registry[request.control_id] = request
    _save_user_controls()


def _unregister_user_control(control_id: str) -> None:
    """Remove a user-control request from the global registry."""
    with _user_control_registry_lock:
        _user_control_registry.pop(control_id, None)
    _save_user_controls()


# ── VALIDATION SHELL ─────────────────────────────────────────────────────────
# Per ISSUE-098C: backend foundation only. Full lifecycle/mutation/dependency
# validation is represented as explicit TODO-safe placeholders that default
# to reject when insufficient data is available.

def _validate_requested_action(requested_action: str) -> Dict[str, Any]:
    """
    Validate requested_action is one of the approved 098C values.
    Reject disallowed legacy/action names explicitly.
    """
    if not requested_action or not isinstance(requested_action, str):
        return {"valid": False, "error": "requested_action is required and must be a string"}

    if requested_action in _USER_CONTROL_DISALLOWED_ACTIONS:
        return {
            "valid": False,
            "error": f"requested_action '{requested_action}' is explicitly disallowed for 098C",
        }

    if requested_action not in _USER_CONTROL_APPROVED_ACTIONS:
        return {
            "valid": False,
            "error": f"requested_action '{requested_action}' is not an approved user-control action",
        }

    return {"valid": True}


def _validate_risk_level(risk_level: str) -> Dict[str, Any]:
    """Validate risk_level is one of the allowed values."""
    allowed = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    if risk_level not in allowed:
        return {"valid": False, "error": f"risk_level must be one of {allowed}, got '{risk_level}'"}
    return {"valid": True}


def _validate_actor(actor: Optional[str]) -> Dict[str, Any]:
    """Validate actor is present and non-empty."""
    if not actor or not isinstance(actor, str):
        return {"valid": False, "error": "actor is required and must be a non-empty string"}
    return {"valid": True}


def _validate_workflow_id(workflow_id: Optional[str]) -> Dict[str, Any]:
    """Validate workflow_id is present and non-empty."""
    if not workflow_id or not isinstance(workflow_id, str):
        return {"valid": False, "error": "workflow_id is required and must be a non-empty string"}
    return {"valid": True}


def _validate_stale_generations(
    request: UserControlRequest,
    current_execution_generation: Optional[int] = None,
    current_retry_generation: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Check if execution_generation / retry_generation have drifted.
    Reject as stale if mismatch is detected.
    """
    if current_execution_generation is not None and request.execution_generation is not None:
        if request.execution_generation != current_execution_generation:
            return {
                "valid": False,
                "error": (
                    f"execution_generation mismatch: request={request.execution_generation} "
                    f"current={current_execution_generation}"
                ),
                "stale_reason": "execution_generation_mismatch",
            }

    if current_retry_generation is not None and request.retry_generation is not None:
        if request.retry_generation != current_retry_generation:
            return {
                "valid": False,
                "error": (
                    f"retry_generation mismatch: request={request.retry_generation} "
                    f"current={current_retry_generation}"
                ),
                "stale_reason": "retry_generation_mismatch",
            }

    return {"valid": True}


def _validate_terminal_request(request: UserControlRequest) -> Dict[str, Any]:
    """Reject if request is already in a terminal or resolved state."""
    terminal_statuses = {
        UserControlStatus.ACCEPTED,
        UserControlStatus.REJECTED,
        UserControlStatus.EXPIRED,
        UserControlStatus.CANCELLED,
        UserControlStatus.SUPERSEDED,
        UserControlStatus.APPLIED,
    }
    if request.status in terminal_statuses:
        return {
            "valid": False,
            "error": f"request is already terminal (status={request.status.value})",
        }
    return {"valid": True}


def _validate_expired_request(request: UserControlRequest) -> Dict[str, Any]:
    """Reject if request has expired."""
    if request.is_expired():
        return {"valid": False, "error": "request has expired"}
    return {"valid": True}


# ── TRACE HELPERS ─────────────────────────────────────────────────────────────

_USER_CONTROL_TRACE_PREFIX = "user_control"


def _emit_user_control_trace(
    event_name: str,
    workflow_id: str,
    step_id: Optional[str],
    control_id: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Emit a user-control trace event.
    FAILURE-ISOLATED: trace failure must not break request handling.
    """
    try:
        _tc = trace_collector.get_collector(workflow_id)
        if _tc:
            _tc._safe(
                event_name,
                lambda: _tc.steps.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "project_id": workflow_id,
                    "step_id": step_id or "unknown",
                    "level": "NORMAL",
                    "event": event_name,
                    "data": {
                        "control_id": control_id,
                        "workflow_id": workflow_id,
                        "step_id": step_id,
                        **(data or {}),
                    }
                })
            )
    except Exception:
        pass

    # Also emit via legacy record_transition for broader observability
    try:
        trace_collector.record_transition(
            step_id=step_id or "unknown",
            previous_status="PENDING",
            new_status="PENDING",
            reason=event_name,
        )
    except Exception:
        pass


# ── PUBLIC REGISTRY FUNCTIONS ─────────────────────────────────────────────────

def create_user_control_request(
    workflow_id: str,
    step_id: Optional[str],
    requested_action: str,
    reason: str,
    original_decision: Optional[Dict[str, Any]] = None,
    risk_level: str = "MEDIUM",
    actor: str = "user",
    confirmation_text: Optional[str] = None,
    execution_generation: Optional[int] = None,
    retry_generation: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 1800,
) -> Dict[str, Any]:
    """
    Create and register a new user-control request.

    Per USER_CONTROL_CONTRACT_V2 §9:
    - Backend validates requested_action against approved list
    - Backend validates risk_level
    - Backend validates actor presence
    - Backend validates workflow_id presence
    - Returns the created request dict on success, or error dict on failure

    Per ISSUE-098C:
    - Does NOT apply runtime behavior
    - Does NOT mutate workflow state
    - Does NOT bypass governance
    """
    # 1. Validate requested_action
    action_check = _validate_requested_action(requested_action)
    if not action_check["valid"]:
        return {"success": False, "error": action_check["error"]}

    # 2. Validate risk_level
    risk_check = _validate_risk_level(risk_level)
    if not risk_check["valid"]:
        return {"success": False, "error": risk_check["error"]}

    # 3. Validate actor
    actor_check = _validate_actor(actor)
    if not actor_check["valid"]:
        return {"success": False, "error": actor_check["error"]}

    # 4. Validate workflow_id
    wf_check = _validate_workflow_id(workflow_id)
    if not wf_check["valid"]:
        return {"success": False, "error": wf_check["error"]}

    # 5. Create request
    request = UserControlRequest(
        workflow_id=workflow_id,
        step_id=step_id,
        requested_action=requested_action,
        reason=reason,
        original_decision=original_decision,
        risk_level=risk_level,
        actor=actor,
        confirmation_text=confirmation_text,
        execution_generation=execution_generation,
        retry_generation=retry_generation,
        metadata=metadata or {},
        timeout_seconds=timeout_seconds,
    )
    _register_user_control(request)

    # 6. Emit trace
    _emit_user_control_trace(
        event_name="user_control_requested",
        workflow_id=workflow_id,
        step_id=step_id,
        control_id=request.control_id,
        data={
            "requested_action": requested_action,
            "risk_level": risk_level,
            "reason": reason,
            "actor": actor,
            "execution_generation": execution_generation,
            "retry_generation": retry_generation,
        },
    )

    # ISSUE-098N: save persistence on creation
    _save_user_controls()

    return {"success": True, "request": request.to_dict()}


def get_user_control_request(control_id: str) -> Optional[UserControlRequest]:
    """Lookup a user-control request by control_id."""
    with _user_control_registry_lock:
        return _user_control_registry.get(control_id)


def get_pending_user_controls_for_workflow(workflow_id: str) -> List[UserControlRequest]:
    """Return all PENDING user-control requests for a specific workflow."""
    with _user_control_registry_lock:
        return [
            req for req in _user_control_registry.values()
            if req.workflow_id == workflow_id and req.status == UserControlStatus.PENDING
        ]


def get_all_pending_user_controls() -> List[UserControlRequest]:
    """Return all PENDING user-control requests across all workflows."""
    with _user_control_registry_lock:
        return [req for req in _user_control_registry.values() if req.status == UserControlStatus.PENDING]


def resolve_user_control_request(
    control_id: str,
    decision: str,  # "accept" or "reject"
    actor: str = "operator",
    confirmation_text: Optional[str] = None,
    validate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Resolve a user-control request with full validation.

    Called by API endpoints. Performs stale/invalidity checks before resolving.
    Per ISSUE-098C: does NOT apply runtime behavior; only changes request status.

    Args:
        control_id: The control request to resolve
        decision: "accept" or "reject"
        actor: Who is resolving (for audit)
        confirmation_text: Optional confirmation text provided by operator
        validate: Optional dict with fields to validate:
            - workflow_id: str — must match
            - execution_generation: int — must match if provided
            - retry_generation: int — must match if provided
            - workflow_status: str — must not be terminal ( advisory only; not enforced in 098C)

    Returns:
        Dict with {"success": bool, "status": str, "control_id": str, "error": str|None}
    """
    if decision not in ("accept", "reject"):
        return {
            "success": False,
            "status": "invalid_decision",
            "control_id": control_id,
            "error": f"decision must be 'accept' or 'reject', got '{decision}'",
        }

    request = get_user_control_request(control_id)
    if request is None:
        return {
            "success": False,
            "status": "not_found",
            "control_id": control_id,
            "error": "control_id not found",
        }

    with request._lock:
        # 1. Terminal check
        term_check = _validate_terminal_request(request)
        if not term_check["valid"]:
            return {
                "success": False,
                "status": request.status.value,
                "control_id": control_id,
                "error": term_check["error"],
            }

        # 2. Expired check
        expired_check = _validate_expired_request(request)
        if not expired_check["valid"]:
            request.status = UserControlStatus.EXPIRED
            if not request._future.done():
                request._future.set_exception(TimeoutError("user_control_expired"))
            _emit_user_control_trace(
                event_name="user_control_expired",
                workflow_id=request.workflow_id,
                step_id=request.step_id,
                control_id=control_id,
                data={"reason": "resolved_past_expiry"},
            )
            return {
                "success": False,
                "status": "EXPIRED",
                "control_id": control_id,
                "error": expired_check["error"],
            }

        # 3. workflow_id mismatch
        if validate and "workflow_id" in validate:
            if request.workflow_id != validate["workflow_id"]:
                return {
                    "success": False,
                    "status": "mismatch",
                    "control_id": control_id,
                    "error": "workflow_id mismatch",
                }

        # 4. Stale generation checks
        stale_check = _validate_stale_generations(
            request,
            current_execution_generation=validate.get("execution_generation") if validate else None,
            current_retry_generation=validate.get("retry_generation") if validate else None,
        )
        if not stale_check["valid"]:
            request.status = UserControlStatus.SUPERSEDED
            if not request._future.done():
                request._future.set_exception(RuntimeError("user_control_stale_rejected"))
            _emit_user_control_trace(
                event_name="user_control_stale_rejected",
                workflow_id=request.workflow_id,
                step_id=request.step_id,
                control_id=control_id,
                data={
                    "reason": stale_check.get("stale_reason", "generation_mismatch"),
                    "error": stale_check["error"],
                },
            )
            return {
                "success": False,
                "status": "SUPERSEDED",
                "control_id": control_id,
                "error": stale_check["error"],
            }

        # 5. All validations passed — resolve
        accepted = decision == "accept"
        if confirmation_text:
            request.confirmation_text = confirmation_text
        request.resolve(accepted=accepted, actor=actor)

    # 6. Emit trace after lock release
    trace_event = "user_control_accepted" if accepted else "user_control_rejected"
    _emit_user_control_trace(
        event_name=trace_event,
        workflow_id=request.workflow_id,
        step_id=request.step_id,
        control_id=control_id,
        data={
            "actor": actor,
            "previous_status": "PENDING",
            "new_status": "ACCEPTED" if accepted else "REJECTED",
            "confirmation_text": confirmation_text,
        },
    )

    # 7. Dismiss associated notification to prevent stale banner
    # Per ISSUE-098KL: notification must not remain actionable after request resolution.
    try:
        from system.interface.notification_manager import dismiss_notifications_for_control_id
        dismiss_notifications_for_control_id(control_id)
    except Exception:
        pass

    # ISSUE-098N: save persistence on resolution
    _save_user_controls()

    return {
        "success": True,
        "status": "ACCEPTED" if accepted else "REJECTED",
        "control_id": control_id,
        "error": None,
    }


def get_accepted_continue_after_warning_for_step(
    workflow_id: str,
    step_id: Optional[str],
) -> Optional[UserControlRequest]:
    """
    Locate an ACCEPTED UserControlRequest for a given workflow/step.

    Matches only `requested_action == "continue_after_warning"`.
    Per ISSUE-098E: governance may inspect this to authorize the existing
    legal retry branch when the operator has explicitly accepted continuation
    after a warning.

    Args:
        workflow_id: The workflow ID.
        step_id: The step ID (may be None for workflow-level controls).

    Returns:
        The ACCEPTED UserControlRequest if found, else None.
    """
    with _user_control_registry_lock:
        for req in _user_control_registry.values():
            if (
                req.workflow_id == workflow_id
                and req.step_id == step_id
                and req.status == UserControlStatus.ACCEPTED
                and req.requested_action == "continue_after_warning"
            ):
                return req
    return None


def get_accepted_external_call_risk_for_step(
    workflow_id: str,
    step_id: Optional[str],
    execution_generation: Optional[int] = None,
    retry_generation: Optional[int] = None,
) -> Optional[UserControlRequest]:
    """
    Locate an ACCEPTED `accept_external_call_risk` UserControlRequest.

    Per ISSUE-098I: runtime inspects this before executing external-call tools.
    Validates execution_generation and retry_generation if supplied.

    Args:
        workflow_id: The workflow ID.
        step_id: The step ID.
        execution_generation: Current execution generation for staleness check.
        retry_generation: Current retry generation for staleness check.

    Returns:
        The validated ACCEPTED UserControlRequest, or None.
    """
    with _user_control_registry_lock:
        for req in _user_control_registry.values():
            if (
                req.workflow_id == workflow_id
                and req.step_id == step_id
                and req.status == UserControlStatus.ACCEPTED
                and req.requested_action == "accept_external_call_risk"
            ):
                # Stale generation validation
                stale_check = _validate_stale_generations(
                    req,
                    current_execution_generation=execution_generation,
                    current_retry_generation=retry_generation,
                )
                if stale_check["valid"]:
                    return req
    return None


def get_pending_external_call_risk_for_step(
    workflow_id: str,
    step_id: Optional[str],
    tool_name: Optional[str] = None,
    destination: Optional[str] = None,
) -> Optional[UserControlRequest]:
    """
    Locate a PENDING `accept_external_call_risk` UserControlRequest.

    Per ISSUE-098J: runtime checks for existing pending requests before
    creating duplicates.

    Args:
        workflow_id: The workflow ID.
        step_id: The step ID.
        tool_name: Optional tool name for tighter matching.
        destination: Optional destination for tighter matching.

    Returns:
        The PENDING UserControlRequest if found, else None.
    """
    with _user_control_registry_lock:
        for req in _user_control_registry.values():
            if (
                req.workflow_id == workflow_id
                and req.step_id == step_id
                and req.status == UserControlStatus.PENDING
                and req.requested_action == "accept_external_call_risk"
            ):
                # Tight match on tool_name and destination if provided
                if tool_name is not None:
                    req_tool = req.metadata.get("tool_name") if req.metadata else None
                    if req_tool != tool_name:
                        continue
                if destination is not None:
                    req_dest = req.metadata.get("destination") if req.metadata else None
                    if req_dest != destination:
                        continue
                return req
    return None


def get_rejected_external_call_risk_for_step(
    workflow_id: str,
    step_id: Optional[str],
    tool_name: Optional[str] = None,
    destination: Optional[str] = None,
) -> Optional[UserControlRequest]:
    """
    Locate a REJECTED `accept_external_call_risk` UserControlRequest.

    Per ISSUE-098KL: runtime checks for rejected requests to avoid
    recreating pending requests and to show clear rejection state.

    Args:
        workflow_id: The workflow ID.
        step_id: The step ID.
        tool_name: Optional tool name for tighter matching.
        destination: Optional destination for tighter matching.

    Returns:
        The REJECTED UserControlRequest if found, else None.
    """
    with _user_control_registry_lock:
        for req in _user_control_registry.values():
            if (
                req.workflow_id == workflow_id
                and req.step_id == step_id
                and req.status == UserControlStatus.REJECTED
                and req.requested_action == "accept_external_call_risk"
            ):
                if tool_name is not None:
                    req_tool = req.metadata.get("tool_name") if req.metadata else None
                    if req_tool != tool_name:
                        continue
                if destination is not None:
                    req_dest = req.metadata.get("destination") if req.metadata else None
                    if req_dest != destination:
                        continue
                return req
    return None


def get_latest_external_call_risk_for_step(
    workflow_id: str,
    step_id: Optional[str],
) -> Optional[UserControlRequest]:
    """
    Return the most recent `accept_external_call_risk` request for this step,
    regardless of status (PENDING, ACCEPTED, REJECTED, etc.).

    Per ISSUE-098KL: runtime needs to know the latest request status to decide
    whether to create a new pending request or honor a previous rejection.

    Args:
        workflow_id: The workflow ID.
        step_id: The step ID.

    Returns:
        The most recent matching UserControlRequest, or None.
    """
    latest = None
    with _user_control_registry_lock:
        for req in _user_control_registry.values():
            if (
                req.workflow_id == workflow_id
                and req.step_id == step_id
                and req.requested_action == "accept_external_call_risk"
            ):
                if latest is None or (req.created_at and latest.created_at and req.created_at > latest.created_at):
                    latest = req
    return latest


def get_or_create_external_call_risk_request(
    workflow_id: str,
    step_id: Optional[str],
    tool_name: str,
    provider: Optional[str] = None,
    destination: Optional[str] = None,
    data_leaving_system: Optional[str] = None,
    privacy_classification: Optional[str] = None,
    risk_level: str = "MEDIUM",
    read_only: bool = True,
    mutating: bool = False,
    external_call: bool = True,
    confirmation_text: Optional[str] = None,
    execution_generation: Optional[int] = None,
    retry_generation: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Get an existing or create a new `accept_external_call_risk` request.

    Per ISSUE-098J:
    - Prefer existing PENDING request (deduplication).
    - Prefer existing ACCEPTED request (resume path).
    - If existing request is REJECTED/EXPIRED/CANCELLED/SUPERSEDED/APPLIED,
      and no active PENDING/ACCEPTED exists, create a new request.
    - Never create duplicate PENDING requests for the same workflow/step/action/tool.

    Args:
        workflow_id: The workflow ID.
        step_id: The step ID.
        tool_name: Name of the external-call tool.
        provider: External provider name.
        destination: External destination.
        data_leaving_system: What data leaves the system.
        privacy_classification: Privacy classification string.
        risk_level: Risk level (default "MEDIUM").
        read_only: Whether the tool is read-only.
        mutating: Whether the tool is mutating.
        external_call: Whether the tool makes external calls.
        confirmation_text: Operator-facing confirmation text.
        execution_generation: Current execution generation.
        retry_generation: Current retry generation.

    Returns:
        Dict with {"success": bool, "request": UserControlRequest or None,
                   "created": bool, "control_id": str or None, "error": str or None}
    """
    # 1. Prefer existing PENDING request (dedup)
    pending = get_pending_external_call_risk_for_step(
        workflow_id, step_id, tool_name=tool_name, destination=destination
    )
    if pending is not None:
        return {
            "success": True,
            "request": pending,
            "created": False,
            "control_id": pending.control_id,
            "error": None,
        }

    # 2. Prefer existing ACCEPTED request (resume path)
    accepted = get_accepted_external_call_risk_for_step(
        workflow_id, step_id,
        execution_generation=execution_generation,
        retry_generation=retry_generation,
    )
    if accepted is not None:
        return {
            "success": True,
            "request": accepted,
            "created": False,
            "control_id": accepted.control_id,
            "error": None,
        }

    # 3. Check for any active request that would prevent creation
    # REJECTED/EXPIRED/CANCELLED/SUPERSEDED/APPLIED do not block creation,
    # but if a non-terminal active request exists for a different tool/destination,
    # we should still create a new one because the step's tool/destination may have changed.

    # 4. Build metadata
    request_metadata = {
        "tool_name": tool_name,
        "provider": provider,
        "destination": destination,
        "data_leaving_system": data_leaving_system,
        "privacy_classification": privacy_classification,
        "risk_level": risk_level,
        "read_only": read_only,
        "mutating": mutating,
        "external_call": external_call,
        "source": "runtime",
    }

    # 5. Create new request
    result = create_user_control_request(
        workflow_id=workflow_id,
        step_id=step_id,
        requested_action="accept_external_call_risk",
        reason=f"external-call risk for tool {tool_name}",
        risk_level=risk_level,
        actor="runtime",
        confirmation_text=confirmation_text,
        execution_generation=execution_generation,
        retry_generation=retry_generation,
        metadata=request_metadata,
    )

    if not result.get("success"):
        return {
            "success": False,
            "request": None,
            "created": False,
            "control_id": None,
            "error": result.get("error", "create_failed"),
        }

    # Retrieve the created request object from registry
    created_control_id = result["request"]["control_id"]
    created_request = get_user_control_request(created_control_id)
    return {
        "success": True,
        "request": created_request,
        "created": True,
        "control_id": created_control_id,
        "error": None,
    }


def record_user_control_applied(
    request: UserControlRequest,
    original_decision: str,
    backend_decision: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Emit `user_control_applied` trace and mark request as APPLIED.

    Per ISSUE-098E: trace failure must be isolated.
    Per USER_CONTROL_CONTRACT_V2: backend_decision records the outcome.

    Args:
        request: The consumed UserControlRequest.
        original_decision: The governance decision before user-control was applied.
        backend_decision: The final governance decision after user-control.
        metadata: Optional additional metadata (e.g., external-risk fields for 098I).
    """
    try:
        with request._lock:
            request.status = UserControlStatus.APPLIED
            request.backend_decision = backend_decision
    except Exception:
        pass

    trace_data: Dict[str, Any] = {
        "requested_action": request.requested_action,
        "original_decision": original_decision,
        "backend_decision": backend_decision,
        "execution_generation": request.execution_generation,
        "retry_generation": request.retry_generation,
        "actor": request.actor,
        "reason": request.reason,
    }
    if metadata:
        trace_data["metadata"] = metadata

    _emit_user_control_trace(
        event_name="user_control_applied",
        workflow_id=request.workflow_id,
        step_id=request.step_id,
        control_id=request.control_id,
        data=trace_data,
    )

    # ISSUE-098N: save persistence on applied
    _save_user_controls()


def expire_user_control_request(control_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """
    Mark a user-control request as EXPIRED.
    """
    request = get_user_control_request(control_id)
    if request is None:
        return {
            "success": False,
            "status": "not_found",
            "control_id": control_id,
            "error": "control_id not found",
        }

    with request._lock:
        term_check = _validate_terminal_request(request)
        if not term_check["valid"]:
            return {
                "success": False,
                "status": request.status.value,
                "control_id": control_id,
                "error": term_check["error"],
            }
        request.expire()

    _emit_user_control_trace(
        event_name="user_control_expired",
        workflow_id=request.workflow_id,
        step_id=request.step_id,
        control_id=control_id,
        data={"reason": reason or "explicit_expire"},
    )

    # ISSUE-098N: save persistence on expiration
    _save_user_controls()

    return {
        "success": True,
        "status": "EXPIRED",
        "control_id": control_id,
        "error": None,
    }


def cancel_user_control_request(control_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """
    Mark a user-control request as CANCELLED.
    """
    request = get_user_control_request(control_id)
    if request is None:
        return {
            "success": False,
            "status": "not_found",
            "control_id": control_id,
            "error": "control_id not found",
        }

    with request._lock:
        term_check = _validate_terminal_request(request)
        if not term_check["valid"]:
            return {
                "success": False,
                "status": request.status.value,
                "control_id": control_id,
                "error": term_check["error"],
            }
        request.cancel()

    _emit_user_control_trace(
        event_name="user_control_cancelled",
        workflow_id=request.workflow_id,
        step_id=request.step_id,
        control_id=control_id,
        data={"reason": reason or "explicit_cancel"},
    )

    # ISSUE-098N: save persistence on cancellation
    _save_user_controls()

    return {
        "success": True,
        "status": "CANCELLED",
        "control_id": control_id,
        "error": None,
    }


def supersede_user_control_request(
    control_id: str,
    superseded_by: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Mark a user-control request as SUPERSEDED.
    """
    request = get_user_control_request(control_id)
    if request is None:
        return {
            "success": False,
            "status": "not_found",
            "control_id": control_id,
            "error": "control_id not found",
        }

    with request._lock:
        term_check = _validate_terminal_request(request)
        if not term_check["valid"]:
            return {
                "success": False,
                "status": request.status.value,
                "control_id": control_id,
                "error": term_check["error"],
            }
        request.supersede(superseded_by=superseded_by)

    _emit_user_control_trace(
        event_name="user_control_superseded",
        workflow_id=request.workflow_id,
        step_id=request.step_id,
        control_id=control_id,
        data={
            "superseded_by": superseded_by,
            "reason": reason or "explicit_supersede",
        },
    )

    # ISSUE-098N: save persistence on supersession
    _save_user_controls()

    return {
        "success": True,
        "status": "SUPERSEDED",
        "control_id": control_id,
        "error": None,
    }


def cleanup_expired_user_controls() -> int:
    """
    Scan registry and mark expired user-control requests.
    Returns count cleaned.

    Called periodically or on demand. Does not remove from registry
    so audit trail remains.
    """
    cleaned = 0
    with _user_control_registry_lock:
        for req in list(_user_control_registry.values()):
            if req.status == UserControlStatus.PENDING and req.is_expired():
                req.expire()
                cleaned += 1
    # ISSUE-098N: save persistence after cleanup
    if cleaned > 0:
        _save_user_controls()
    return cleaned


# ── ISSUE-098N: MODULE INIT ────────────────────────────────────────────────────
# Load persisted user-control requests on module import.
# Per PERSISTENCE_AND_DURABILITY_CONTRACT_V1: load happens after module init;
# validation inside _load_user_controls ensures stale requests are rejected.
_load_user_controls()


# ── ISSUE-098KP: DYNAMIC TOOL SELECTION EXTERNAL-CALL ENFORCEMENT ─────────────

def enforce_external_call_user_control(
    workflow_id: str,
    step_id: Optional[str],
    tool_name: str,
    tool_args: Optional[Dict[str, Any]] = None,
    source: str = "dynamic_tool_selection",
    execution_generation: Optional[int] = None,
    retry_generation: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Enforce external-call user-control for dynamically selected tools.

    This helper is called after a tool is selected but before system_entry
    executes it. It complements the predeclared tool_call gate in
    orchestrator_runtime.py for AG1 dynamic tool selection paths.

    Args:
        workflow_id: The workflow ID.
        step_id: The step ID (optional but recommended).
        tool_name: Name of the selected tool.
        tool_args: Optional tool arguments dict (e.g., {"url": "..."}).
        source: Source of the enforcement call for tracing.
        execution_generation: Current execution generation.
        retry_generation: Current retry generation.

    Returns:
        Dict with:
        - "allowed": bool — True if execution should proceed
        - "blocked": bool — True if execution should NOT proceed
        - "reason": str — Human-readable reason
        - "control_id": str or None — Control request ID if created/found
        - "request_status": str or None — PENDING/ACCEPTED/REJECTED/etc
        - "error": str or None — Error message if enforcement failed
    """
    from system.security.tool_policy import get_external_call_risk_metadata

    # 1. Query external-call risk metadata
    try:
        risk = get_external_call_risk_metadata(tool_name, tool_args)
    except Exception as e:
        return {
            "allowed": False,
            "blocked": True,
            "reason": f"metadata_query_failed: {e}",
            "control_id": None,
            "request_status": None,
            "error": str(e),
        }

    # 2. Not an external-call tool — allow execution
    if not risk.get("external_call"):
        return {
            "allowed": True,
            "blocked": False,
            "reason": "not_external_call_tool",
            "control_id": None,
            "request_status": None,
            "error": None,
        }

    # 3. Fail-closed: non-overrideable tools must not be allowed through user-control
    if not risk.get("overrideable_with_user_control"):
        block_reason = risk.get("block_reason_if_not_overrideable", "tool_not_overrideable")
        return {
            "allowed": False,
            "blocked": True,
            "reason": block_reason,
            "control_id": None,
            "request_status": None,
            "error": None,
        }

    # 4. Check for accepted request
    accepted = get_accepted_external_call_risk_for_step(
        workflow_id,
        step_id,
        execution_generation=execution_generation,
        retry_generation=retry_generation,
    )
    if accepted is not None:
        return {
            "allowed": True,
            "blocked": False,
            "reason": "accepted_request_found",
            "control_id": accepted.control_id,
            "request_status": "ACCEPTED",
            "error": None,
        }

    # 5. Check for rejected request
    rejected = get_rejected_external_call_risk_for_step(
        workflow_id,
        step_id,
        tool_name=tool_name,
        destination=risk.get("destination"),
    )
    if rejected is not None:
        return {
            "allowed": False,
            "blocked": True,
            "reason": "external_call_risk_rejected",
            "control_id": rejected.control_id,
            "request_status": "REJECTED",
            "error": None,
        }

    # 6. Create or reuse pending request
    req_result = get_or_create_external_call_risk_request(
        workflow_id=workflow_id,
        step_id=step_id,
        tool_name=tool_name,
        provider=risk.get("provider"),
        destination=risk.get("destination"),
        data_leaving_system=risk.get("data_leaving_system"),
        privacy_classification=risk.get("privacy_classification"),
        risk_level=risk.get("risk_level", "MEDIUM"),
        read_only=risk.get("read_only", True),
        mutating=risk.get("mutating", False),
        external_call=risk.get("external_call", True),
        confirmation_text=risk.get("confirmation_text"),
        execution_generation=execution_generation,
        retry_generation=retry_generation,
    )

    if not req_result.get("success"):
        return {
            "allowed": False,
            "blocked": True,
            "reason": "request_creation_failed",
            "control_id": None,
            "request_status": None,
            "error": req_result.get("error", "unknown"),
        }

    return {
        "allowed": False,
        "blocked": True,
        "reason": "pending_user_control_request",
        "control_id": req_result.get("control_id"),
        "request_status": req_result["request"].status.value if req_result.get("request") else "PENDING",
        "error": None,
    }


# ── ISSUE-098A: BACKEND DISPATCHER ───────────────────────────────────────────
# Per USER_CONTROL_CONTRACT_V2 §26: Slice 1 backend dispatcher outside governance.py.

# Slice 1 supported actions for dispatcher application.
_DISPATCHER_SUPPORTED_ACTIONS = frozenset({
    "force_step_retry",
    "accept_external_call_risk",
})

# Deferred actions that must fail closed in Slice 1.
_DISPATCHER_DEFERRED_ACTIONS = frozenset({
    "force_workflow_replan",
    "continue_after_warning",
    "override_low_confidence_block",
    "provide_replacement_input",
    "cancel_blocked_branch",
})


def dispatch_user_control_action(
    request: UserControlRequest,
) -> Dict[str, Any]:
    """
    Dispatch an ACCEPTED user-control request to the appropriate backend action.

    Per USER_CONTROL_CONTRACT_V2 §26:
    - Does not modify governance decision authority.
    - Does not bypass lifecycle authority, mutation legality, or dependency rules.
    - Emits required trace/audit events.
    - Rejects stale/expired/superseded requests.
    - Validates workflow_id / step_id / retry_target_step_id.
    - Validates execution_generation / retry_generation where applicable.

    Supported actions (Slice 1):
      - accept_external_call_risk: no-op (runtime loop handles it)
      - force_step_retry: validate candidate, check budget, call retry_step

    Unsupported/deferred actions fail closed with structured error.

    Returns:
        {"success": bool, "reason": str|None, "error": str|None, "details": dict}
    """
    # 1. Request must be ACCEPTED
    if request.status != UserControlStatus.ACCEPTED:
        return {
            "success": False,
            "reason": "request_not_accepted",
            "error": f"Cannot dispatch request with status={request.status.value}",
            "details": {"control_id": request.control_id, "status": request.status.value},
        }

    action = request.requested_action

    # 2. Fail closed for explicitly deferred actions
    if action in _DISPATCHER_DEFERRED_ACTIONS:
        return {
            "success": False,
            "reason": "deferred_action",
            "error": f"requested_action '{action}' is deferred and not supported in Slice 1",
            "details": {"action": action},
        }

    # 3. Fail closed for unsupported actions
    if action not in _DISPATCHER_SUPPORTED_ACTIONS:
        return {
            "success": False,
            "reason": "unsupported_action",
            "error": f"requested_action '{action}' is not supported by the dispatcher",
            "details": {"action": action},
        }

    # 4. accept_external_call_risk: no-op (runtime handles it)
    if action == "accept_external_call_risk":
        return {
            "success": True,
            "reason": "runtime_handled",
            "error": None,
            "details": {"action": action, "note": "runtime loop manages external-call risk acceptance"},
        }

    # 5. force_step_retry: full validation + application
    if action == "force_step_retry":
        return _dispatch_force_step_retry(request)

    # Fallback fail-closed
    return {
        "success": False,
        "reason": "unknown_action",
        "error": f"Unhandled requested_action '{action}'",
        "details": {"action": action},
    }


def _dispatch_force_step_retry(
    request: UserControlRequest,
) -> Dict[str, Any]:
    """
    Validate and apply force_step_retry.

    Validation sequence:
    - workflow exists and is not terminal
    - step exists and is FAILED or BLOCKED
    - failed_recoverable is true
    - normal retries are exhausted (retries >= max_retries)
    - force retry budget is not exhausted (_force_retry_count < FORCE_RETRY_LIMIT)
    - generation metadata matches if supplied on request
    """
    # Local imports to avoid circular dependencies at module level
    try:
        from system.orchestrator.persistence import load_workflow
        from system.orchestrator.workflow_control import (
            retry_step,
            _get_workflow_state,
            _get_failed_metadata,
        )
    except Exception as e:
        return {
            "success": False,
            "reason": "import_error",
            "error": f"Failed to import workflow control dependencies: {e}",
            "details": {},
        }

    workflow_id = request.workflow_id
    step_id = request.step_id

    # --- Workflow validation ---
    workflow = load_workflow(workflow_id)
    if workflow is None:
        return {
            "success": False,
            "reason": "workflow_not_found",
            "error": f"Workflow {workflow_id} not found",
            "details": {"workflow_id": workflow_id},
        }

    wf_status = workflow.get("status", "UNKNOWN")
    if wf_status in ("COMPLETED", "CANCELLED", "QUARANTINED"):
        return {
            "success": False,
            "reason": "workflow_terminal",
            "error": f"Workflow {workflow_id} is in terminal status {wf_status}",
            "details": {"workflow_id": workflow_id, "status": wf_status},
        }

    # --- Step validation ---
    steps = workflow.get("steps", [])
    step = None
    for s in steps:
        if s.get("id") == step_id:
            step = s
            break

    if step is None:
        return {
            "success": False,
            "reason": "step_not_found",
            "error": f"Step {step_id} not found in workflow {workflow_id}",
            "details": {"workflow_id": workflow_id, "step_id": step_id},
        }

    step_status = step.get("status", "UNKNOWN")
    if step_status not in ("FAILED", "BLOCKED"):
        return {
            "success": False,
            "reason": "step_not_retryable",
            "error": f"Step {step_id} status is {step_status}, not FAILED or BLOCKED",
            "details": {"step_id": step_id, "status": step_status},
        }

    # --- Recoverability validation ---
    _meta = _get_failed_metadata(workflow_id)
    if not _meta.get("failed_recoverable", True):
        return {
            "success": False,
            "reason": "not_recoverable",
            "error": f"Workflow {workflow_id} is not recoverable",
            "details": {"failed_recoverable": False},
        }

    # --- Retry target validation ---
    # The step must be a valid retry target: FAILED, or BLOCKED with retryable reason
    if step_status == "BLOCKED":
        blocked_reason = step.get("blocked_reason", "")
        # Only retryable if the block reason is one that retry can resolve
        _retryable_reasons = (
            "max_retries_exceeded",
            "escalated",
            "dependency_not_completed",
            "dependency_failed",
        )
        # Allow prefix matches for compound reasons like "dependency_not_completed:s1:BLOCKED"
        _is_retryable = any(blocked_reason.startswith(r) or blocked_reason == r for r in _retryable_reasons)
        if not _is_retryable:
            return {
                "success": False,
                "reason": "blocked_reason_not_retryable",
                "error": f"Step {step_id} blocked_reason '{blocked_reason}' is not retryable",
                "details": {"blocked_reason": blocked_reason},
            }

    # --- Normal retry exhaustion check ---
    retries = step.get("retries", 0)
    max_retries = step.get("max_retries", 3)
    if retries < max_retries:
        return {
            "success": False,
            "reason": "normal_retries_not_exhausted",
            "error": f"Normal retries not exhausted ({retries} < {max_retries}). Use normal retry.",
            "details": {"retries": retries, "max_retries": max_retries},
        }

    # --- Force retry budget check ---
    _force_count = step.get("_force_retry_count", 0)
    if _force_count >= FORCE_RETRY_LIMIT:
        return {
            "success": False,
            "reason": "force_retry_exhausted",
            "error": f"Force retry budget exhausted ({_force_count} >= {FORCE_RETRY_LIMIT})",
            "details": {"force_retry_count": _force_count, "force_retry_limit": FORCE_RETRY_LIMIT},
        }

    # --- Generation metadata validation ---
    if request.execution_generation is not None:
        try:
            wf_state = _get_workflow_state(workflow_id)
            current_exec_gen = wf_state.get("execution_generation") if wf_state else None
            if current_exec_gen is not None and request.execution_generation != current_exec_gen:
                return {
                    "success": False,
                    "reason": "execution_generation_mismatch",
                    "error": (
                        f"execution_generation mismatch: request={request.execution_generation} "
                        f"current={current_exec_gen}"
                    ),
                    "details": {
                        "request_execution_generation": request.execution_generation,
                        "current_execution_generation": current_exec_gen,
                    },
                }
        except Exception:
            pass

    if request.retry_generation is not None:
        current_retry_gen = step.get("_retry_generation")
        if current_retry_gen is not None and request.retry_generation != current_retry_gen:
            return {
                "success": False,
                "reason": "retry_generation_mismatch",
                "error": (
                    f"retry_generation mismatch: request={request.retry_generation} "
                    f"current={current_retry_gen}"
                ),
                "details": {
                    "request_retry_generation": request.retry_generation,
                    "current_retry_generation": current_retry_gen,
                },
            }

    # --- Apply force retry ---
    try:
        result = retry_step(workflow_id, step_id, _force_retry=True)
    except Exception as e:
        return {
            "success": False,
            "reason": "retry_step_failed",
            "error": f"retry_step raised exception: {e}",
            "details": {"exception": str(e)},
        }

    if result.get("status") != "success":
        return {
            "success": False,
            "reason": result.get("reason", "retry_step_rejected"),
            "error": result.get("reason", "retry_step returned failure"),
            "details": result,
        }

    # --- Record applied trace ---
    record_user_control_applied(
        request=request,
        original_decision="FAILED",
        backend_decision="force_retry",
        metadata={
            "retries_before": retries,
            "max_retries": max_retries,
            "force_retry_count": step.get("_force_retry_count", 0),
            "force_retry_at_generation": step.get("_force_retry_at_generation"),
        },
    )

    return {
        "success": True,
        "reason": "force_retry_applied",
        "error": None,
        "details": {
            "workflow_id": workflow_id,
            "step_id": step_id,
            "control_id": request.control_id,
            "force_retry_count": step.get("_force_retry_count", 0),
        },
    }


# ── LEGACY COMPATIBILITY ──────────────────────────────────────────────────────
# Keep get_control_state() for existing API consumers.

def get_control_state() -> Dict[str, Any]:
    """
    Get current control state (for debugging/observability).

    Per ISSUE-098C: extended to include pending user-control count.
    """
    pending_count = len(get_all_pending_user_controls())
    return {"pending_user_controls": pending_count}


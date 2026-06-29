"""
USER APPROVAL — Contract-Safe Approval Request Model (ISSUE-096B)

Responsibility:
- Backend-owned approval request creation, identity, and validation
- Thread-safe runtime bridge for GUI approval flow
- CLI fallback for non-GUI contexts

Contracts:
- USER_APPROVAL_CONTRACT_V1
- LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1
- TRACE_LOGGING_CONTRACT_V1

Authority:
- Governance is the SOLE authority that decides BLOCK
- This module creates the approval request AFTER governance decides
- Backend validates and resolves all approval decisions
- Frontend is projection-only; may display and capture intent only
"""

import uuid
import threading
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, Any, List, Optional
from concurrent.futures import Future

from system.orchestrator import trace_collector


class ApprovalStatus(str, Enum):
    """Approval request statuses per USER_APPROVAL_CONTRACT_V1 §5."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalRequest:
    """
    Backend-authored approval request per USER_APPROVAL_CONTRACT_V1 §4.

    Thread-safe: all mutable state mutations protected by internal lock.
    """

    def __init__(
        self,
        workflow_id: str,
        step_id: Optional[str],
        reason: str,
        risk_level: str = "MEDIUM",
        requested_action: str = "execute_step",
        source: str = "governance",
        details: Optional[Dict[str, Any]] = None,
        requires_confirmation: bool = True,
        execution_generation: Optional[int] = None,
        timeout_seconds: int = 1800,
    ):
        self.approval_id = str(uuid.uuid4())
        self.workflow_id = workflow_id
        self.step_id = step_id
        self.status = ApprovalStatus.PENDING
        self.reason = reason
        self.risk_level = risk_level
        self.requested_action = requested_action
        self.source = source
        self.details = details or {}
        self.requires_confirmation = requires_confirmation
        self.execution_generation = execution_generation
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.expires_at = (datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)).isoformat()
        self.resolved_at: Optional[str] = None
        self.resolved_by: Optional[str] = None

        # Thread-safe decision bridge using concurrent.futures.Future
        # Runtime thread blocks on .result(); API endpoint resolves via .set_result()
        self._future: Future = Future()
        self._lock = threading.RLock()

    def to_dict(self, include_internal: bool = False) -> Dict[str, Any]:
        """Serialize to dict for API responses."""
        data = {
            "approval_id": self.approval_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "status": self.status.value,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "requested_action": self.requested_action,
            "source": self.source,
            "details": self.details,
            "requires_confirmation": self.requires_confirmation,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
        }
        if self.execution_generation is not None:
            data["execution_generation"] = self.execution_generation
        if include_internal:
            data["_future_done"] = self._future.done()
        return data

    def is_expired(self) -> bool:
        """Check if approval request has exceeded its expiry time."""
        try:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.now(timezone.utc) > expires
        except Exception:
            return False

    def is_pending(self) -> bool:
        """Check if approval request is still PENDING."""
        with self._lock:
            return self.status == ApprovalStatus.PENDING

    def wait_for_decision(self, timeout: Optional[float] = None) -> bool:
        """
        Block until the approval is resolved by the API endpoint.

        Called by the runtime thread. Uses concurrent.futures.Future.result()
        which is thread-safe and compatible with ThreadPoolExecutor contexts.

        Args:
            timeout: Maximum seconds to wait. None = wait until resolved.

        Returns:
            True if approved, False if rejected, expired, or timed out.
        """
        try:
            result = self._future.result(timeout=timeout)
            return bool(result)
        except Exception:
            # Timeout, cancellation, or any error -> treat as not approved
            return False

    def resolve(self, approved: bool, actor: str = "operator") -> None:
        """
        Resolve the approval request. Called by API endpoint.

        Thread-safe. Sets the Future result so runtime can continue.
        """
        with self._lock:
            if self._future.done():
                return
            self.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            self.resolved_at = datetime.now(timezone.utc).isoformat()
            self.resolved_by = actor
            self._future.set_result(approved)

    def expire(self) -> None:
        """Mark approval as EXPIRED without resolving the future."""
        with self._lock:
            if not self._future.done():
                self.status = ApprovalStatus.EXPIRED
                self.resolved_at = datetime.now(timezone.utc).isoformat()
                self._future.set_exception(TimeoutError("approval_expired"))

    def cancel(self) -> None:
        """Mark approval as CANCELLED without resolving the future."""
        with self._lock:
            if not self._future.done():
                self.status = ApprovalStatus.CANCELLED
                self.resolved_at = datetime.now(timezone.utc).isoformat()
                self._future.set_exception(RuntimeError("approval_cancelled"))


# ── Approval Registry ─────────────────────────────────────────────────────────
# approval_id -> ApprovalRequest
# Thread-safe via _approval_registry_lock
_approval_registry: Dict[str, ApprovalRequest] = {}
_approval_registry_lock = threading.Lock()


def _register_approval(request: ApprovalRequest) -> None:
    """Register an approval request in the global registry."""
    with _approval_registry_lock:
        _approval_registry[request.approval_id] = request


def _unregister_approval(approval_id: str) -> None:
    """Remove an approval request from the global registry."""
    with _approval_registry_lock:
        _approval_registry.pop(approval_id, None)


def create_approval_request(
    workflow_id: str,
    step_id: Optional[str],
    reason: str,
    risk_level: str = "MEDIUM",
    requested_action: str = "execute_step",
    source: str = "governance",
    details: Optional[Dict[str, Any]] = None,
    execution_generation: Optional[int] = None,
    timeout_seconds: int = 1800,
) -> ApprovalRequest:
    """
    Create and register a new approval request.

    Called by governance or runtime when a step requires approval.
    Emits approval_created trace event.

    Returns:
        The created ApprovalRequest (runtime should call wait_for_decision()).
    """
    request = ApprovalRequest(
        workflow_id=workflow_id,
        step_id=step_id,
        reason=reason,
        risk_level=risk_level,
        requested_action=requested_action,
        source=source,
        details=details,
        execution_generation=execution_generation,
        timeout_seconds=timeout_seconds,
    )
    _register_approval(request)

    # TRACE: approval_created
    try:
        trace_collector.record_transition(
            step_id=step_id or "unknown",
            previous_status="BLOCKED",
            new_status="BLOCKED",
            reason="approval_created",
        )
        _tc = trace_collector.get_collector(workflow_id)
        if _tc:
            _tc._safe(
                "record_approval_event",
                lambda: _tc.steps.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "project_id": workflow_id,
                    "step_id": step_id,
                    "level": "NORMAL",
                    "event": "approval_created",
                    "data": {
                        "approval_id": request.approval_id,
                        "workflow_id": workflow_id,
                        "step_id": step_id,
                        "risk_level": risk_level,
                        "reason": reason,
                        "requested_action": requested_action,
                        "source": source,
                    }
                })
            )
    except Exception:
        pass

    # AGENT-001J-FIX1: Emit approval_created refresh signal.
    # NON-AUTHORITATIVE — trace_collector above remains the authoritative record.
    # FAILURE-ISOLATED: must not affect execution or approval Future.
    try:
        from system.interface.event_emitter import emit_approval_created
        emit_approval_created(
            workflow_id=workflow_id,
            approval_id=request.approval_id,
            step_id=step_id,
            risk_level=risk_level,
            reason=reason,
        )
    except Exception:
        pass

    return request


def get_approval(approval_id: str) -> Optional[ApprovalRequest]:
    """Lookup an approval request by approval_id."""
    with _approval_registry_lock:
        return _approval_registry.get(approval_id)


def get_pending_approvals_for_workflow(workflow_id: str) -> List[ApprovalRequest]:
    """Return all PENDING approvals for a specific workflow."""
    with _approval_registry_lock:
        return [
            req for req in _approval_registry.values()
            if req.workflow_id == workflow_id and req.status == ApprovalStatus.PENDING
        ]


def get_all_pending_approvals() -> List[ApprovalRequest]:
    """Return all PENDING approvals across all workflows."""
    with _approval_registry_lock:
        return [req for req in _approval_registry.values() if req.status == ApprovalStatus.PENDING]


def resolve_approval(
    approval_id: str,
    approved: bool,
    actor: str = "operator",
    validate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Resolve an approval request with full validation.

    Called by API endpoints. Performs stale/invalidity checks before resolving.

    Args:
        approval_id: The approval to resolve
        approved: True = approve, False = reject
        actor: Who is resolving (for audit)
        validate: Optional dict with fields to validate:
            - workflow_id: str — must match
            - execution_generation: int — must match if provided
            - workflow_status: str — must not be terminal
            - step_exists: bool — step must still exist in workflow

    Returns:
        Dict with {"success": bool, "status": str, "approval_id": str, "error": str|None}
    """
    request = get_approval(approval_id)
    if request is None:
        return {
            "success": False,
            "status": "not_found",
            "approval_id": approval_id,
            "error": "approval_id not found",
        }

    with request._lock:
        # Already resolved
        if not request.is_pending():
            return {
                "success": False,
                "status": request.status.value,
                "approval_id": approval_id,
                "error": f"approval already resolved as {request.status.value}",
            }

        # Expired
        if request.is_expired():
            request.status = ApprovalStatus.EXPIRED
            if not request._future.done():
                request._future.set_exception(TimeoutError("approval_expired"))
            return {
                "success": False,
                "status": "EXPIRED",
                "approval_id": approval_id,
                "error": "approval expired",
            }

        # workflow_id mismatch
        if validate and "workflow_id" in validate:
            if request.workflow_id != validate["workflow_id"]:
                return {
                    "success": False,
                    "status": "mismatch",
                    "approval_id": approval_id,
                    "error": "workflow_id mismatch",
                }

        # execution_generation mismatch
        if validate and "execution_generation" in validate:
            if request.execution_generation is not None:
                if request.execution_generation != validate["execution_generation"]:
                    request.status = ApprovalStatus.SUPERSEDED
                    if not request._future.done():
                        request._future.set_exception(RuntimeError("approval_superseded"))
                    return {
                        "success": False,
                        "status": "SUPERSEDED",
                        "approval_id": approval_id,
                        "error": "execution generation changed; approval superseded",
                    }

        # Terminal workflow check
        if validate and "workflow_status" in validate:
            terminal_statuses = {"COMPLETED", "CANCELLED"}
            wf_status = validate["workflow_status"]
            if wf_status in terminal_statuses:
                request.status = ApprovalStatus.CANCELLED
                if not request._future.done():
                    request._future.set_exception(RuntimeError("workflow_terminal"))
                return {
                    "success": False,
                    "status": "CANCELLED",
                    "approval_id": approval_id,
                    "error": f"workflow is {wf_status}; approval cancelled",
                }
            if wf_status == "FAILED":
                # Only reject if explicitly non-actionable FAILED
                # Some FAILED workflows may be retry-eligible; let caller decide
                if validate.get("actionable_failed") is False:
                    request.status = ApprovalStatus.CANCELLED
                    if not request._future.done():
                        request._future.set_exception(RuntimeError("workflow_failed"))
                    return {
                        "success": False,
                        "status": "CANCELLED",
                        "approval_id": approval_id,
                        "error": "workflow failed and is not actionable",
                    }

        # Step no longer exists
        if validate and validate.get("step_exists") is False:
            request.status = ApprovalStatus.CANCELLED
            if not request._future.done():
                request._future.set_exception(RuntimeError("step_removed"))
            return {
                "success": False,
                "status": "CANCELLED",
                "approval_id": approval_id,
                "error": "step no longer exists",
            }

        # All validations passed — resolve
        request.resolve(approved=approved, actor=actor)

    # TRACE: approval_approved or approval_rejected
    trace_event = "approval_approved" if approved else "approval_rejected"
    try:
        _tc = trace_collector.get_collector(request.workflow_id)
        if _tc:
            _tc._safe(
                trace_event,
                lambda: _tc.steps.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "project_id": request.workflow_id,
                    "step_id": request.step_id,
                    "level": "NORMAL",
                    "event": trace_event,
                    "data": {
                        "approval_id": approval_id,
                        "workflow_id": request.workflow_id,
                        "step_id": request.step_id,
                        "actor": actor,
                        "previous_status": "PENDING",
                        "new_status": "APPROVED" if approved else "REJECTED",
                    }
                })
            )
    except Exception:
        pass

    # AGENT-001J-FIX1: Emit approval_resolved refresh signal.
    # NON-AUTHORITATIVE — trace_collector above remains the authoritative record.
    # FAILURE-ISOLATED: must not affect execution or approval Future.
    try:
        from system.interface.event_emitter import emit_approval_resolved
        emit_approval_resolved(
            workflow_id=request.workflow_id,
            approval_id=approval_id,
            decision="APPROVED" if approved else "REJECTED",
            step_id=request.step_id,
        )
    except Exception:
        pass

    return {
        "success": True,
        "status": "APPROVED" if approved else "REJECTED",
        "approval_id": approval_id,
        "error": None,
    }


def cleanup_stale_approvals() -> int:
    """
    Scan registry and mark expired approvals. Returns count cleaned.

    Called periodically or on demand. Does not remove from registry
    so audit trail remains.
    """
    cleaned = 0
    with _approval_registry_lock:
        for req in list(_approval_registry.values()):
            if req.status == ApprovalStatus.PENDING and req.is_expired():
                req.expire()
                cleaned += 1
    return cleaned


# ── LEGACY CLI FALLBACK ─────────────────────────────────────────────────────
# Kept for non-GUI/test contexts. Not used by the API bridge.

def request_approval(step: Dict[str, Any]) -> bool:
    """
    CLI-only approval request (legacy fallback).

    Called by runtime when no GUI bridge is available.
    Does NOT create an ApprovalRequest object — this is pure terminal interaction.

    For GUI mode, runtime should use create_approval_request() + wait_for_decision().
    """
    step_id = step.get("id", "unknown")

    # TRACE: APPROVAL_REQUESTED (legacy)
    try:
        trace_collector.record_transition(
            step_id=step_id,
            previous_status="BLOCKED",
            new_status="BLOCKED",
            reason="APPROVAL_REQUESTED"
        )
    except Exception:
        pass

    print("\n" + "=" * 50)
    print("[APPROVAL REQUIRED]")
    print("=" * 50)
    print(f"  Step:    {step.get('purpose', 'Unknown purpose')}")
    print(f"  Type:    {step.get('type', 'Unknown')}")
    print(f"  Risk:    {step.get('risk', 'Unknown')}")
    print(f"  Tool:    {step.get('tool_call', 'Unknown')}")
    if step.get("resource_targets"):
        print(f"  Targets: {step.get('resource_targets')}")
    print("=" * 50)

    try:
        response = input("Approve execution? (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        response = "n"

    approved = response == "y"

    # TRACE: APPROVAL_RESULT (legacy)
    try:
        trace_collector.record_transition(
            step_id=step_id,
            previous_status="BLOCKED",
            new_status="BLOCKED" if not approved else "ACTIVE",
            reason=f"APPROVAL_{'GRANTED' if approved else 'DENIED'}"
        )
    except Exception:
        pass

    return approved

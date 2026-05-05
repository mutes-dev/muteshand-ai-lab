"""
TRACE COLLECTOR — READ-ONLY OBSERVABILITY LAYER

Complies with TRACE_MODEL.txt:
- Strictly read-only observation
- No control flow influence
- No state modification
- Passive data capture only
- FAILURE-ISOLATED: No exception may escape this module

HARDENING GUARANTEES:
1. All public methods are internally exception-safe
2. Schema validation before recording
3. Invalid data is silently discarded (never crashes execution)
4. All methods explicitly return None
"""

from typing import Any, Dict, List, Optional, Union
from datetime import datetime

# === SCHEMA DEFINITION ===
# Defines expected types for trace entries
TRACE_SCHEMA = {
    "step_id": str,
    "purpose": str,
    "input": (str, dict, type(None)),
    "execution_result": (dict, type(None)),
    "governance_decision": (str, type(None)),
    "retries": int,
    "status": str,
}


class TraceCollector:
    """
    Read-only observability collector for workflow execution.
    
    RULES:
    - NEVER modifies execution_result
    - NEVER modifies step state
    - NEVER influences governance decisions
    - ONLY records events AFTER they occur
    - Returns are never used for control flow
    """
    
    def __init__(self, workflow_id: str = None):
        self.workflow_id = workflow_id or "unknown"
        self.steps: List[Dict[str, Any]] = []
        self.created_at = datetime.utcnow().isoformat()
        self._failure_count = 0  # Track internal failures for diagnostics
    
    def _safe(self, operation: str, func, *args, **kwargs) -> Any:
        """
        Internal failure isolation wrapper.
        
        All trace operations are wrapped to prevent exceptions escaping.
        Failures are silently absorbed to protect execution.
        """
        try:
            return func(*args, **kwargs)
        except Exception:
            self._failure_count += 1
            # Failure absorbed - execution must continue unaffected
            return None
    
    def record_step_execution(
        self,
        step_id: str,
        purpose: str,
        step_input: Any,
        execution_result: Optional[Dict],
        governance_decision: Optional[str],
        retries: int,
        status: str,
        validator_advisory: Optional[str] = None,
        validator_signals: Optional[Dict] = None
    ) -> None:
        """
        Record a step execution event.
        
        CALL AFTER:
        - execution_result is returned
        - governance decision is finalized
        - step state is updated
        
        THIS METHOD:
        - Appends to internal trace list ONLY
        - Returns None (no control influence)
        - Does NOT modify any input data
        - FAILURE-SAFE: All exceptions are internally contained
        """
        self._safe("record_step_execution", self._do_record_step,
                   step_id, purpose, step_input, execution_result,
                   governance_decision, retries, status,
                   validator_advisory, validator_signals)
        return None
    
    def _do_record_step(
        self,
        step_id: str,
        purpose: str,
        step_input: Any,
        execution_result: Optional[Dict],
        governance_decision: Optional[str],
        retries: int,
        status: str,
        validator_advisory: Optional[str] = None,
        validator_signals: Optional[Dict] = None
    ) -> None:
        """Internal implementation - not exception-safe, wrapped by _safe()."""
        # Schema validation
        if not self._validate_step_data(step_id, purpose, retries, status):
            return  # Invalid data - silently discard

        # TRACE_LOGGING_CONTRACT_V1 format — wrap existing payload
        trace_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "project_id": self.workflow_id,
            "level": "NORMAL",
            "event": "step_execution",
            "data": {
                # Existing payload (UNCHANGED)
                "step_id": str(step_id) if step_id else "unknown",
                "purpose": str(purpose) if purpose else "",
                "input": self._sanitize_input(step_input),
                "execution_result": execution_result if isinstance(execution_result, dict) else None,
                "governance_decision": str(governance_decision) if governance_decision else None,
                "retries": int(retries) if isinstance(retries, int) else 0,
                "status": str(status) if status else "unknown",
                "validator_advisory": str(validator_advisory) if validator_advisory else None,
                "validator_signals": validator_signals if isinstance(validator_signals, dict) else None
            }
        }
        self.steps.append(trace_entry)
    
    def record_governance_decision(
        self,
        step_id: str,
        decision: str,
        execution_result: Optional[Dict] = None,
        context: Optional[Dict] = None
    ) -> None:
        """
        Record governance decision as a standalone event.
        
        CALL AFTER:
        - governance.decide_next_action() returns
        
        PURPOSE:
        - Audit trail for governance decisions
        - No influence on actual governance logic
        - FAILURE-SAFE: All exceptions are internally contained
        """
        self._safe("record_governance_decision", self._do_record_governance,
                   step_id, decision, execution_result, context)
        return None
    
    def _do_record_governance(
        self,
        step_id: str,
        decision: str,
        execution_result: Optional[Dict] = None,
        context: Optional[Dict] = None
    ) -> None:
        """Internal implementation - not exception-safe, wrapped by _safe()."""
        # Safe attribute access with type checking
        exec_status = None
        if isinstance(execution_result, dict):
            exec_status = execution_result.get("status")

        # TRACE_LOGGING_CONTRACT_V1 format — wrap existing payload
        trace_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "project_id": self.workflow_id,
            "level": "NORMAL",
            "event": "governance_decision",
            "data": {
                # Existing payload (UNCHANGED)
                "step_id": str(step_id) if step_id else "unknown",
                "decision": str(decision) if decision else "unknown",
                "execution_result_status": str(exec_status) if exec_status else None,
                "context": context if isinstance(context, dict) else None
            }
        }
        self.steps.append(trace_entry)
    
    def record_state_transition(
        self,
        step_id: str,
        previous_status: str,
        new_status: str,
        reason: Optional[str] = None
    ) -> None:
        """
        Record step state transition.
        
        CALL AFTER:
        - step["status"] is updated
        
        PURPOSE:
        - Audit trail for state machine transitions
        - FAILURE-SAFE: All exceptions are internally contained
        """
        self._safe("record_state_transition", self._do_record_transition,
                   step_id, previous_status, new_status, reason)
        return None
    
    def _do_record_transition(
        self,
        step_id: str,
        previous_status: str,
        new_status: str,
        reason: Optional[str] = None
    ) -> None:
        """Internal implementation - not exception-safe, wrapped by _safe()."""
        # TRACE_LOGGING_CONTRACT_V1 format — wrap existing payload
        trace_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "project_id": self.workflow_id,
            "level": "NORMAL",
            "event": "state_transition",
            "data": {
                # Existing payload (UNCHANGED)
                "step_id": str(step_id) if step_id else "unknown",
                "previous_status": str(previous_status) if previous_status else None,
                "new_status": str(new_status) if new_status else "unknown",
                "reason": str(reason) if reason else None
            }
        }
        self.steps.append(trace_entry)
    
    def get_trace(self) -> Dict[str, Any]:
        """
        Return complete trace data.
        
        PURPOSE:
        - External inspection (debugging, dashboards)
        - Never called by execution logic
        """
        return {
            "workflow_id": self.workflow_id,
            "created_at": self.created_at,
            "completed_at": datetime.utcnow().isoformat(),
            "step_count": len(self.steps),
            "steps": self.steps
        }
    
    def _sanitize_input(self, step_input: Any) -> Any:
        """
        Sanitize input for trace storage.
        
        Removes potentially sensitive or large data.
        FAILURE-SAFE: Returns safe fallback on any error.
        """
        try:
            if step_input is None:
                return None
            
            # If input is a string, truncate if too long
            if isinstance(step_input, str):
                if len(step_input) > 1000:
                    return step_input[:1000] + "... [truncated]"
                return step_input
            
            # For dicts, preserve structure but limit size
            if isinstance(step_input, dict):
                sanitized = {}
                for k, v in step_input.items():
                    if isinstance(v, str) and len(v) > 500:
                        sanitized[k] = v[:500] + "... [truncated]"
                    else:
                        sanitized[k] = v
                return sanitized
            
            # For other types, convert to string safely
            return str(step_input)[:500]
        except Exception:
            # Fail-safe: return placeholder on any error
            return "[sanitize_error]"
    
    def _validate_step_data(self, step_id: Any, purpose: Any, retries: Any, status: Any) -> bool:
        """
        Validate required fields match schema before recording.
        
        Returns False if data is invalid (will be silently discarded).
        """
        # Check required string fields
        if not isinstance(step_id, (str, int)):
            return False
        if not isinstance(purpose, (str, int, type(None))):
            return False
        if not isinstance(status, (str, int, type(None))):
            return False
        
        # Check retries is numeric
        if retries is not None and not isinstance(retries, int):
            return False
        
        return True
    
    def get_failure_count(self) -> int:
        """
        Return number of trace failures since initialization.
        
        For diagnostics only - never used in execution logic.
        """
        return self._failure_count
    
    def record_memory_event(
        self,
        event: str,
        key: Optional[str] = None,
        data: Optional[Dict] = None
    ) -> None:
        """
        Record a memory operation event (Phase 3A).

        Per MEMORY_STORAGE_CONTRACT_V1 TRACE REQUIREMENT:
        - Memory writes MUST be logged
        - Memory updates MUST be logged
        - Memory usage in decisions MUST be logged

        Event types: MEMORY_READ | MEMORY_WRITE | MEMORY_UPDATE

        CALL AFTER:
        - Memory read (before agent execution)
        - Memory write (after successful step completion only)
        - Memory update (confidence adjustment)

        THIS METHOD:
        - Appends to internal trace list ONLY
        - Returns None (no control influence)
        - FAILURE-SAFE: All exceptions are internally contained
        """
        self._safe("record_memory_event", self._do_record_memory,
                   event, key, data)
        return None

    def _do_record_memory(
        self,
        event: str,
        key: Optional[str] = None,
        data: Optional[Dict] = None
    ) -> None:
        """Internal implementation - not exception-safe, wrapped by _safe()."""
        valid_events = {"MEMORY_READ", "MEMORY_WRITE", "MEMORY_UPDATE"}
        if event not in valid_events:
            return
        trace_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "project_id": self.workflow_id,
            "level": "NORMAL",
            "event": event,
            "data": {
                "key": str(key) if key else None,
                "detail": data if isinstance(data, dict) else {}
            }
        }
        self.steps.append(trace_entry)

    def record_drift_event(
        self,
        event: str,
        step_id: Optional[str] = None,
        drift_type: Optional[str] = None,
        confidence: Optional[float] = None,
        reason: Optional[str] = None,
        expected: Optional[str] = None,
        actual: Optional[Any] = None
    ) -> None:
        """
        Record a drift detection event (Phase 3B).

        Per TRACE_LOGGING_CONTRACT_V1:
        - Drift events MUST be logged for observability
        - Drift signals are advisory only, no control influence

        Event types: DRIFT_DETECTED | DRIFT_NONE

        CALL AFTER:
        - Drift comparison completes in step_executor

        THIS METHOD:
        - Appends to internal trace list ONLY
        - Returns None (no control influence)
        - FAILURE-SAFE: All exceptions are internally contained
        """
        self._safe("record_drift_event", self._do_record_drift,
                   event, step_id, drift_type, confidence, reason, expected, actual)
        return None

    def record_notification_event(
        self,
        notification_type: str,
        category: str,
        message: str,
        step_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record a notification event (Phase 3C — TRACE MIRRORING).

        Per TRACE_LOGGING_CONTRACT_V1:
        - Trace is PRIMARY, notifications are SECONDARY
        - This provides trace observability for notification emissions
        - Zero control influence

        Event types: NOTIFICATION_EMITTED

        THIS METHOD:
        - Mirrors notification emissions to trace (observational)
        - Returns None (no control influence)
        - FAILURE-SAFE: All exceptions are internally contained
        """
        self._safe("record_notification_event", self._do_record_notification,
                   notification_type, category, message, step_id, metadata)
        return None

    def _do_record_notification(
        self,
        notification_type: str,
        category: str,
        message: str,
        step_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Internal implementation - not exception-safe, wrapped by _safe()."""
        trace_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "project_id": self.workflow_id,
            "level": "NORMAL",
            "event": "NOTIFICATION_EMITTED",
            "data": {
                "notification_type": notification_type,
                "category": category,
                "message": message[:100] if message else "",  # Truncate for trace
                "step_id": step_id,
                "metadata": metadata if isinstance(metadata, dict) else {}
            }
        }
        self.steps.append(trace_entry)

    def _do_record_drift(
        self,
        event: str,
        step_id: Optional[str] = None,
        drift_type: Optional[str] = None,
        confidence: Optional[float] = None,
        reason: Optional[str] = None,
        expected: Optional[str] = None,
        actual: Optional[Any] = None
    ) -> None:
        """Internal implementation - not exception-safe, wrapped by _safe()."""
        valid_events = {"DRIFT_DETECTED", "DRIFT_NONE"}
        if event not in valid_events:
            return
        trace_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "project_id": self.workflow_id,
            "level": "NORMAL",
            "event": event,
            "data": {
                "step_id": step_id,
                "drift_type": drift_type,
                "confidence": float(confidence) if confidence is not None else None,
                "reason": reason,
                "expected": expected,
                "actual": str(actual) if actual is not None else None
            }
        }
        self.steps.append(trace_entry)

    def clear(self) -> None:
        """
        Clear all trace data.
        
        PURPOSE:
        - Memory management only
        - Never called during active execution
        """
        self.steps = []


# Global instance for runtime use
# Created fresh per workflow execution
_active_collector: Optional[TraceCollector] = None


def create_collector(workflow_id: str = None) -> TraceCollector:
    """
    Create a new trace collector instance.
    
    Called at start of workflow execution.
    """
    global _active_collector
    _active_collector = TraceCollector(workflow_id)
    return _active_collector


def get_collector() -> Optional[TraceCollector]:
    """
    Get current active collector.
    
    Returns None if no collector exists.
    """
    return _active_collector


def record_step(
    step_id: str,
    purpose: str,
    step_input: Any,
    execution_result: Optional[Dict],
    governance_decision: Optional[str],
    retries: int,
    status: str,
    validator_advisory: Optional[str] = None,
    validator_signals: Optional[Dict] = None
) -> None:
    """
    Convenience function to record step via global collector.
    
    SAFE: Does nothing if no collector exists.
    FAILURE-SAFE: Even if collector methods fail, returns None.
    """
    try:
        collector = get_collector()
        if collector:
            collector.record_step_execution(
                step_id=step_id,
                purpose=purpose,
                step_input=step_input,
                execution_result=execution_result,
                governance_decision=governance_decision,
                retries=retries,
                status=status,
                validator_advisory=validator_advisory,
                validator_signals=validator_signals
            )
    except Exception:
        # Absolute guarantee: trace failure cannot affect execution
        pass
    return None


def record_governance(
    step_id: str,
    decision: str,
    execution_result: Optional[Dict] = None,
    context: Optional[Dict] = None
) -> None:
    """
    Convenience function to record governance decision.
    
    SAFE: Does nothing if no collector exists.
    FAILURE-SAFE: Even if collector methods fail, returns None.
    """
    try:
        collector = get_collector()
        if collector:
            collector.record_governance_decision(
                step_id=step_id,
                decision=decision,
                execution_result=execution_result,
                context=context
            )
    except Exception:
        # Absolute guarantee: trace failure cannot affect execution
        pass
    return None


def record_transition(
    step_id: str,
    previous_status: str,
    new_status: str,
    reason: Optional[str] = None
) -> None:
    """
    Convenience function to record state transition.
    
    SAFE: Does nothing if no collector exists.
    FAILURE-SAFE: Even if collector methods fail, returns None.
    """
    try:
        collector = get_collector()
        if collector:
            collector.record_state_transition(
                step_id=step_id,
                previous_status=previous_status,
                new_status=new_status,
                reason=reason
            )
    except Exception:
        # Absolute guarantee: trace failure cannot affect execution
        pass
    return None


def record_memory_event(
    event: str,
    key: Optional[str] = None,
    data: Optional[Dict] = None
) -> None:
    """
    Convenience function to record a memory event via global collector.

    Event types: MEMORY_READ | MEMORY_WRITE | MEMORY_UPDATE

    SAFE: Does nothing if no collector exists.
    FAILURE-SAFE: Even if collector methods fail, returns None.
    """
    try:
        collector = get_collector()
        if collector:
            collector.record_memory_event(event=event, key=key, data=data)
    except Exception:
        pass
    return None


def record_drift_event(
    event: str,
    step_id: Optional[str] = None,
    drift_type: Optional[str] = None,
    confidence: Optional[float] = None,
    reason: Optional[str] = None,
    expected: Optional[str] = None,
    actual: Optional[Any] = None
) -> None:
    """
    Convenience function to record a drift event via global collector.

    Event types: DRIFT_DETECTED | DRIFT_NONE

    SAFE: Does nothing if no collector exists.
    FAILURE-SAFE: Even if collector methods fail, returns None.
    """
    try:
        collector = get_collector()
        if collector:
            collector.record_drift_event(
                event=event,
                step_id=step_id,
                drift_type=drift_type,
                confidence=confidence,
                reason=reason,
                expected=expected,
                actual=actual
            )
    except Exception:
        pass
    return None


def record_notification_event(
    notification_type: str,
    category: str,
    message: str,
    step_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Convenience function to record a notification event via global collector.

    Event types: NOTIFICATION_EMITTED

    SAFE: Does nothing if no collector exists.
    FAILURE-SAFE: Even if collector methods fail, returns None.
    """
    try:
        collector = get_collector()
        if collector:
            collector.record_notification_event(
                notification_type=notification_type,
                category=category,
                message=message,
                step_id=step_id,
                metadata=metadata
            )
    except Exception:
        pass
    return None


def get_trace() -> Optional[Dict[str, Any]]:
    """
    Get complete trace from active collector.
    
    Returns None if no collector exists.
    FAILURE-SAFE: Returns None on any error.
    """
    try:
        collector = get_collector()
        if collector:
            return collector.get_trace()
    except Exception:
        # Fail-safe: return None on any error
        pass
    return None

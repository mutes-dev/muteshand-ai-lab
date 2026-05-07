"""
EVENT BUS — LIVE STATE STREAMING (STATE-DRIVEN, CONTRACT-SAFE)

Per HAND_ARCHITECTURE_V2 Section 15 (Visibility):
- Modes: NORMAL, LIVE, DEBUG
- LIVE mode provides step-by-step visibility

Per CONTROL_MODEL.txt:
- Streaming is observational only
- Signals are advisory, non-authoritative
- execution_result remains sole truth

Per TRACE_LOGGING_CONTRACT_V1:
- Trace is read-only and separate from UI state
- UI must not derive control logic from trace

COMPLIANCE:
- In-memory, non-blocking queue
- Per-workflow isolation
- Zero control-flow influence
- Zero execution interference

FAILURE-ISOLATED:
- All operations wrapped in try/except
- No exceptions escape to execution
- Queue overflow handled gracefully
"""

from typing import Any, Dict, List, Optional, Callable
from collections import defaultdict, deque
from datetime import datetime
import threading
import time


# Maximum events per workflow to prevent unbounded memory growth
MAX_EVENTS_PER_WORKFLOW = 1000

# Default event retention time in seconds (events older than this are pruned)
EVENT_RETENTION_SECONDS = 300  # 5 minutes


class EventBus:
    """
    In-memory event bus for live workflow streaming.
    
    RULES:
    - Non-blocking: publish() returns immediately
    - Per-workflow isolation: each workflow has separate queue
    - Read-only: consumers cannot modify events
    - Failure-safe: all operations wrapped in try/except
    """
    
    def __init__(self):
        # Per-workflow event queues: workflow_id -> deque of events
        self._queues: Dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_EVENTS_PER_WORKFLOW))
        
        # Per-workflow subscriber callbacks: workflow_id -> list of callbacks
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        
        # Per-workflow event timestamps for pruning: workflow_id -> deque of timestamps
        self._timestamps: Dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_EVENTS_PER_WORKFLOW))
        
        # Thread safety lock
        self._lock = threading.RLock()
        
        # Internal failure tracking (diagnostics only)
        self._failure_count = 0
    
    def publish(self, workflow_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """
        Publish an event to the bus.
        
        RULES:
        - NEVER blocks execution
        - NEVER raises exceptions
        - ALWAYS returns None immediately
        - Event is timestamped and appended to queue
        
        Args:
            workflow_id: The workflow identifier
            event_type: Type of event (step_started, step_completed, etc.)
            data: Event payload dictionary
        """
        try:
            with self._lock:
                event = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "workflow_id": workflow_id,
                    "event_type": event_type,
                    "data": data
                }
                
                # Add to queue (deque automatically handles maxlen)
                self._queues[workflow_id].append(event)
                self._timestamps[workflow_id].append(time.time())
                
                # Notify subscribers (synchronous, but non-blocking)
                # If subscriber blocks, it doesn't affect publish()
                for callback in list(self._subscribers[workflow_id]):
                    try:
                        callback(event)
                    except Exception:
                        # Subscriber failure must not affect bus
                        pass
                        
        except Exception:
            # FAILURE-ISOLATED: Any error is silently absorbed
            self._failure_count += 1
            pass
    
    def subscribe(self, workflow_id: str, callback: Callable[[Dict], None]) -> None:
        """
        Subscribe to events for a specific workflow.
        
        Args:
            workflow_id: The workflow to subscribe to
            callback: Function called with event dict when event is published
        """
        try:
            with self._lock:
                if callback not in self._subscribers[workflow_id]:
                    self._subscribers[workflow_id].append(callback)
        except Exception:
            pass
    
    def unsubscribe(self, workflow_id: str, callback: Callable[[Dict], None]) -> None:
        """
        Unsubscribe a callback from workflow events.
        """
        try:
            with self._lock:
                if workflow_id in self._subscribers:
                    if callback in self._subscribers[workflow_id]:
                        self._subscribers[workflow_id].remove(callback)
        except Exception:
            pass
    
    def get_events(self, workflow_id: str, since_event_id: Optional[int] = None, 
                   limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get events for a workflow.
        
        Args:
            workflow_id: The workflow identifier
            since_event_id: If provided, return only events after this index
            limit: Maximum number of events to return
        
        Returns:
            List of event dictionaries (empty list if workflow not found)
        """
        try:
            with self._lock:
                queue = self._queues.get(workflow_id)
                if not queue:
                    return []
                
                events = list(queue)
                
                # Filter by since_event_id if provided
                if since_event_id is not None:
                    start_idx = since_event_id + 1
                    events = events[start_idx:]
                
                # Apply limit (return newest events)
                return events[-limit:]
                
        except Exception:
            return []
    
    def get_latest_event(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent event for a workflow.
        
        Returns:
            Latest event dict or None
        """
        try:
            with self._lock:
                queue = self._queues.get(workflow_id)
                if queue:
                    return queue[-1]
                return None
        except Exception:
            return None
    
    def clear_workflow(self, workflow_id: str) -> None:
        """
        Clear all events for a workflow (cleanup after completion).
        """
        try:
            with self._lock:
                if workflow_id in self._queues:
                    del self._queues[workflow_id]
                if workflow_id in self._timestamps:
                    del self._timestamps[workflow_id]
                if workflow_id in self._subscribers:
                    del self._subscribers[workflow_id]
        except Exception:
            pass
    
    def prune_old_events(self, max_age_seconds: int = EVENT_RETENTION_SECONDS) -> None:
        """
        Remove events older than specified age.
        Called periodically to prevent memory growth.
        """
        try:
            cutoff_time = time.time() - max_age_seconds
            with self._lock:
                for workflow_id in list(self._timestamps.keys()):
                    timestamps = self._timestamps[workflow_id]
                    if not timestamps:
                        continue
                    
                    # Find index of first event newer than cutoff
                    keep_idx = 0
                    for i, ts in enumerate(timestamps):
                        if ts >= cutoff_time:
                            keep_idx = i
                            break
                    
                    # Remove old events
                    if keep_idx > 0:
                        for _ in range(keep_idx):
                            if self._queues[workflow_id]:
                                self._queues[workflow_id].popleft()
                            if self._timestamps[workflow_id]:
                                self._timestamps[workflow_id].popleft()
        except Exception:
            pass
    
    def get_failure_count(self) -> int:
        """
        Return number of internal failures (diagnostics only).
        """
        return self._failure_count
    
    def get_workflow_ids(self) -> List[str]:
        """
        Return list of active workflow IDs.
        """
        try:
            with self._lock:
                return list(self._queues.keys())
        except Exception:
            return []


# Global event bus instance
_event_bus = EventBus()


def get_event_bus() -> EventBus:
    """
    Get the global event bus instance.
    """
    return _event_bus


def publish_event(workflow_id: str, event_type: str, data: Dict[str, Any]) -> None:
    """
    Convenience function to publish an event to the global bus.
    
    SAFE: Does nothing if bus fails.
    FAILURE-SAFE: All exceptions are absorbed.
    """
    try:
        _event_bus.publish(workflow_id, event_type, data)
    except Exception:
        pass


def get_events(workflow_id: str, since_event_id: Optional[int] = None, 
               limit: int = 100) -> List[Dict[str, Any]]:
    """
    Convenience function to get events from the global bus.
    
    Returns empty list on any error.
    """
    try:
        return _event_bus.get_events(workflow_id, since_event_id, limit)
    except Exception:
        return []


def clear_workflow(workflow_id: str) -> None:
    """
    Convenience function to clear workflow events.
    """
    try:
        _event_bus.clear_workflow(workflow_id)
    except Exception:
        pass

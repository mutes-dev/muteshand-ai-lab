"""
CONFLICT DETECTOR — Pre-execution Safety Gate

Complies with CONFLICT_RESOLUTION_CONTRACT_V1:
- Detects conflicts BEFORE execution
- Prevents unsafe parallel execution
- Uses resource_targets for conflict identification
- BLOCKS execution when conflicts detected

Complies with ORCHESTRATOR_CONTRACT_V2:
- Orchestrator layer ONLY
- No core execution modification
- Deterministic conflict detection

Thread Safety:
- Thread-safe global state access for parallel execution
- Lock protects _active_workflows dictionary
- Lock protects singleton initialization
- Prevents concurrent mutation during iteration
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
import threading


@dataclass
class WorkflowState:
    """Tracks state of an active workflow for conflict detection."""
    workflow_id: str
    status: str = "ACTIVE"
    current_step: Optional[dict] = None
    resource_targets: Set[str] = field(default_factory=set)


class ConflictDetector:
    """
    Deterministic pre-execution conflict detection.
    
    RULES:
    - Conflict detection runs BEFORE execute_step()
    - Only ACTIVE workflows are checked
    - resource_targets is the ONLY source for resource identification
    - BLOCK decision is valid per GOVERNANCE_CONTRACT
    - No core execution modification
    
    Thread Safety:
    - Lock protects _active_workflows dictionary
    - Lock prevents concurrent mutation during iteration
    """
    
    def __init__(self):
        # Active workflows registry: workflow_id -> WorkflowState
        self._active_workflows: Dict[str, WorkflowState] = {}
        # Thread safety lock for _active_workflows access
        self._lock = threading.Lock()
    
    def register_workflow(self, workflow_id: str) -> None:
        """
        Register a workflow as ACTIVE for conflict detection.
        
        CALL: When workflow starts (run_workflow entry)
        Thread-safe: Uses lock to protect _active_workflows access.
        """
        with self._lock:
            self._active_workflows[workflow_id] = WorkflowState(
                workflow_id=workflow_id,
                status="ACTIVE"
            )
    
    def unregister_workflow(self, workflow_id: str) -> None:
        """
        Remove workflow from active registry.
        
        CALL: When workflow completes, fails, or is blocked
        Thread-safe: Uses lock to protect _active_workflows access.
        """
        with self._lock:
            if workflow_id in self._active_workflows:
                del self._active_workflows[workflow_id]
    
    def update_step(self, workflow_id: str, step: dict) -> None:
        """
        Update current step for a workflow.
        
        CALL: Before conflict detection, when step becomes ACTIVE
        Thread-safe: Uses lock to protect _active_workflows access.
        """
        with self._lock:
            if workflow_id not in self._active_workflows:
                return
            
            wf_state = self._active_workflows[workflow_id]
            wf_state.current_step = step
            
            # Extract resource_targets from step
            resources = step.get("resource_targets", [])
            if resources:
                wf_state.resource_targets = set(resources)
            else:
                wf_state.resource_targets = set()
    
    def detect_conflict(self, workflow_id: str, step: dict) -> dict:
        """
        Detect resource conflicts with other ACTIVE workflows.
        
        RETURNS:
        {
            "conflict": bool,
            "conflicts": [  # only if conflict=True
                {
                    "workflow_id": str,
                    "resources": [str]
                }
            ],
            "severity": str  # LOW, MEDIUM, HIGH (per CONFLICT_RESOLUTION_CONTRACT)
        }
        
        DETERMINISM: Set intersection is deterministic
        Thread-safe: Uses lock to protect _active_workflows access during iteration.
        """
        resources = step.get("resource_targets", [])
        
        # No resources declared → no conflict possible
        if not resources:
            return {
                "conflict": False,
                "severity": "NONE"
            }
        
        resource_set = set(resources)
        conflicts = []
        max_severity = "LOW"
        
        # Check against all other ACTIVE workflows
        # Lock prevents concurrent modification during iteration
        with self._lock:
            active_workflows_snapshot = dict(self._active_workflows)
        
        for other_id, other_wf in active_workflows_snapshot.items():
            if other_id == workflow_id:
                continue
            
            if other_wf.status != "ACTIVE":
                continue
            
            # Detect overlap
            overlap = resource_set & other_wf.resource_targets
            
            if overlap:
                # Determine severity based on step types
                severity = self._calculate_severity(step, other_wf.current_step)
                if severity == "HIGH":
                    max_severity = "HIGH"
                elif severity == "MEDIUM" and max_severity == "LOW":
                    max_severity = "MEDIUM"
                
                conflicts.append({
                    "workflow_id": other_id,
                    "resources": list(overlap),
                    "severity": severity
                })
        
        if conflicts:
            return {
                "conflict": True,
                "conflicts": conflicts,
                "severity": max_severity
            }
        
        return {
            "conflict": False,
            "severity": "NONE"
        }
    
    def _calculate_severity(self, step1: dict, step2: Optional[dict]) -> str:
        """
        Calculate conflict severity based on step characteristics.
        
        Per CONFLICT_RESOLUTION_CONTRACT_V1:
        - HIGH: destructive actions (EXECUTE_FILE with delete, EXECUTE_INSTALL, etc.)
        - MEDIUM: mixed read/write
        - LOW: read-only
        """
        # Get step types
        type1 = step1.get("type", "EXECUTE_API")
        type2 = step2.get("type", "EXECUTE_API") if step2 else "EXECUTE_API"
        
        # HIGH severity: destructive operations
        destructive_types = {
            "EXECUTE_FILE",      # file delete/overwrite
            "EXECUTE_INSTALL",   # system modification
            "EXECUTE_SYSTEM_SETTINGS_SERVICES",  # system changes
            "EXECUTE_ENVIRONMENT"  # env changes
        }
        
        if type1 in destructive_types or type2 in destructive_types:
            return "HIGH"
        
        # MEDIUM severity: write operations
        write_types = {"EXECUTE_LOCAL", "EXECUTE_API"}
        if type1 in write_types or type2 in write_types:
            return "MEDIUM"
        
        # LOW: read-only operations
        return "LOW"
    
    def get_active_workflow_count(self) -> int:
        """Return number of currently registered workflows."""
        return len(self._active_workflows)
    
    def get_active_workflow_ids(self) -> List[str]:
        """Return list of active workflow IDs."""
        return list(self._active_workflows.keys())


# Global instance for runtime use
_conflict_detector: Optional[ConflictDetector] = None
# Thread safety lock for singleton initialization
_detector_lock = threading.Lock()


def get_detector() -> ConflictDetector:
    """
    Get or create the global conflict detector instance.
    
    Singleton pattern — one detector for the runtime.
    Thread-safe: Uses lock to protect singleton initialization.
    """
    global _conflict_detector
    with _detector_lock:
        if _conflict_detector is None:
            _conflict_detector = ConflictDetector()
    return _conflict_detector


def reset_detector() -> None:
    """
    Reset the global detector (for testing only).
    """
    global _conflict_detector
    _conflict_detector = None

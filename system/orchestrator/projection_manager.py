"""
CANONICAL PROJECTION MANAGER — PHASE 4A.0 / 4A.1

Per CANONICAL_PROJECTION_MODEL_V1:
- Orchestrator Runtime owns canonical projection generation and emission
- Projections are workflow-scoped, isolated, and deterministically versioned
- Projection lifecycle is separate from workflow lifecycle

Per ORCHESTRATOR_CONTRACT_V2 (CANONICAL PROJECTION RESPONSIBILITY):
- Orchestrator MUST generate synchronized canonical projections
- Orchestrator MUST emit projection updates deterministically
- Orchestrator MUST maintain workflow-scoped projection isolation
- Orchestrator MUST NOT delegate projection ownership to frontend
- Orchestrator MUST NOT allow uncontrolled projection mutation

Per LIFECYCLE_AUTHORITY_CONTRACT_V1:
- ProjectionManager MUST NOT own lifecycle authority
- ProjectionManager reads lifecycle state FROM Lifecycle Authority only
- ProjectionManager MUST NOT synthesize execution truth

Per PROJECTION_CONTINUITY_CONTRACT_V1:
- Newer projections supersede older (monotonic versioning)
- Late/stale projections MUST NOT overwrite newer synchronized projections
- Cross-workflow contamination is prohibited
- Terminal projections MUST NOT revert unless Lifecycle Authority explicitly invalidates
- Projection invalidation MUST refresh from authority, rebuild deterministically
- Stale projection detection MUST trigger refresh/reconciliation

PROHIBITED:
- ProjectionManager MUST NOT own lifecycle authority
- ProjectionManager MUST NOT synthesize execution truth
- ProjectionManager MUST NOT reconcile continuity
- ProjectionManager MUST NOT mutate frontend state
"""

import threading
from typing import Any, Dict, List, Optional

from system.orchestrator.projection_schema import (
    PROJECTION_STATE_ACTIVE,
    PROJECTION_STATE_STALE,
    PROJECTION_STATE_INVALIDATED,
    PROJECTION_STATE_TERMINAL,
    TERMINAL_WORKFLOW_STATES,
    build_workflow_projection,
    build_step_projection,
    build_output_projection,
    build_plan_projection,
    build_trace_projection,
    validate_projection_identity,
)


# =============================================================================
# PER-WORKFLOW PROJECTION STORE
# =============================================================================

class _WorkflowProjectionStore:
    """
    Isolated per-workflow projection storage.

    Per CANONICAL_PROJECTION_MODEL_V1 §13:
    Projections MUST remain isolated per workflow_id.
    Cross-workflow contamination is prohibited.

    Per PROJECTION_CONTINUITY_CONTRACT_V1 §3:
    Maintains continuity context:
    - monotonic version counter
    - latest canonical WorkflowProjection
    - projection lifecycle state
    - stale rejection count (diagnostics)
    - reconnect continuity anchor (last confirmed synchronized version)
    """

    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self._version: int = 0
        self._latest_projection: Optional[Dict[str, Any]] = None
        self._projection_state: str = PROJECTION_STATE_ACTIVE
        self._lock = threading.RLock()
        # Continuity context (Phase 4A.1)
        self._stale_rejection_count: int = 0
        self._continuity_anchor_version: int = 0  # last version confirmed synchronized

    def next_version(self) -> int:
        """Atomically increment and return the next projection version."""
        with self._lock:
            self._version += 1
            return self._version

    def current_version(self) -> int:
        with self._lock:
            return self._version

    def store(self, projection: Dict[str, Any]) -> bool:
        """
        Store a new projection.

        Per CANONICAL_PROJECTION_MODEL_V1 §4 (Projection Versioning):
        Only stores if the incoming version is >= current stored version
        (prevents stale overwrites).

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §8 (Merge Semantics):
        Projection merge MUST NOT invalidate newer synchronized state.
        Terminal projections MUST NOT be overwritten by non-terminal.

        Returns:
            True if stored, False if rejected as stale/invalid.
        """
        incoming_version = projection.get("projection_version", 0)
        incoming_state = projection.get("projection_state", PROJECTION_STATE_ACTIVE)
        with self._lock:
            if self._latest_projection is not None:
                stored_version = self._latest_projection.get("projection_version", 0)
                # SUB-PHASE 3A: reject older version (stale overwrite)
                if incoming_version < stored_version:
                    self._stale_rejection_count += 1
                    return False
                # SUB-PHASE 3C: reject non-terminal overwrite of TERMINAL projection
                if self._projection_state == PROJECTION_STATE_TERMINAL and incoming_state != PROJECTION_STATE_TERMINAL:
                    self._stale_rejection_count += 1
                    return False
            self._latest_projection = projection
            self._projection_state = projection.get("projection_state", PROJECTION_STATE_ACTIVE)
            # Update continuity anchor on successful store
            self._continuity_anchor_version = incoming_version
            return True

    def get_latest(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._latest_projection

    def get_state(self) -> str:
        with self._lock:
            return self._projection_state

    def set_state(self, state: str) -> None:
        with self._lock:
            self._projection_state = state
            if self._latest_projection is not None:
                self._latest_projection["projection_state"] = state

    def get_stale_rejection_count(self) -> int:
        """Return number of stale/invalid projections rejected (diagnostics)."""
        with self._lock:
            return self._stale_rejection_count

    def get_continuity_anchor(self) -> int:
        """
        Return last confirmed synchronized projection version.

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §11:
        Used to detect continuity gaps on reconnect.
        """
        with self._lock:
            return self._continuity_anchor_version

    def is_version_stale(self, candidate_version: int) -> bool:
        """
        Check if candidate_version is stale relative to current stored version.

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §6:
        Late or stale stream events MUST NOT overwrite newer projection state.

        Returns:
            True if candidate is older than stored (stale), False if fresh/valid.
        """
        with self._lock:
            if self._latest_projection is None:
                return False  # nothing stored yet — not stale
            stored_version = self._latest_projection.get("projection_version", 0)
            return candidate_version < stored_version

    def is_terminal(self) -> bool:
        """
        Return True if current projection is in TERMINAL state.

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §9:
        Terminal projections MUST NOT revert.
        """
        with self._lock:
            return self._projection_state == PROJECTION_STATE_TERMINAL


# =============================================================================
# CANONICAL PROJECTION MANAGER
# =============================================================================

class ProjectionManager:
    """
    Orchestrator-owned canonical projection manager.

    Responsibilities:
    - Generate canonical projections from live workflow state
    - Store projections with monotonic versioning
    - Enforce workflow-scoped isolation
    - Emit projection events via EventBus

    DOES NOT:
    - Own lifecycle authority
    - Synthesize execution truth
    - Reconcile continuity
    - Mutate frontend state
    """

    def __init__(self):
        # Per-workflow projection stores: workflow_id -> _WorkflowProjectionStore
        self._stores: Dict[str, _WorkflowProjectionStore] = {}
        self._stores_lock = threading.RLock()

    # ── Store lifecycle ───────────────────────────────────────────────────────

    def _get_or_create_store(self, workflow_id: str) -> _WorkflowProjectionStore:
        """Get or create isolated projection store for workflow_id."""
        with self._stores_lock:
            if workflow_id not in self._stores:
                self._stores[workflow_id] = _WorkflowProjectionStore(workflow_id)
            return self._stores[workflow_id]

    def _get_store(self, workflow_id: str) -> Optional[_WorkflowProjectionStore]:
        """Get existing store; returns None if not found."""
        with self._stores_lock:
            return self._stores.get(workflow_id)

    def invalidate_workflow(self, workflow_id: str) -> None:
        """
        Mark all projections for workflow as INVALIDATED.

        Per CANONICAL_PROJECTION_MODEL_V1 §10 (Projection Invalidation):
        Called when workflow re-executes or lifecycle authority invalidates continuity.
        """
        store = self._get_store(workflow_id)
        if store:
            store.set_state(PROJECTION_STATE_INVALIDATED)

    def remove_workflow(self, workflow_id: str) -> None:
        """Remove projection store for a workflow (cleanup)."""
        with self._stores_lock:
            self._stores.pop(workflow_id, None)

    def get_workflow_ids(self) -> List[str]:
        """Return list of workflow IDs with active projection stores."""
        with self._stores_lock:
            return list(self._stores.keys())

    # ── Projection generation ─────────────────────────────────────────────────

    def emit_workflow_initialized(
        self,
        workflow: Dict[str, Any],
        lifecycle_status: str,
    ) -> Dict[str, Any]:
        """
        Generate and store a canonical WorkflowProjection on workflow initialization.

        Per CANONICAL_PROJECTION_MODEL_V1 §5 (Projection Emission Model):
        Projections MUST be emitted when workflow initializes.

        Args:
            workflow: live workflow dict
            lifecycle_status: authoritative lifecycle status (from Lifecycle Authority)

        Returns:
            Canonical WorkflowProjection dict
        """
        workflow_id = workflow.get("id", "unknown")
        store = self._get_or_create_store(workflow_id)
        version = store.next_version()

        projection = build_workflow_projection(
            workflow=workflow,
            projection_version=version,
            lifecycle_status=lifecycle_status,
            workflow_output=workflow.get("output"),
        )
        store.store(projection)
        self._emit_to_event_bus(workflow_id, "projection_workflow_initialized", projection)
        return projection

    def emit_lifecycle_changed(
        self,
        workflow: Dict[str, Any],
        lifecycle_status: str,
    ) -> Dict[str, Any]:
        """
        Generate and store a canonical WorkflowProjection on lifecycle state change.

        Per CANONICAL_PROJECTION_MODEL_V1 §5:
        Projections MUST be emitted when lifecycle changes.

        Per CANONICAL_PROJECTION_MODEL_V1 §14 (Terminal Projection Rules):
        Terminal projections (COMPLETED/FAILED) MUST remain stable.

        Args:
            workflow: live workflow dict
            lifecycle_status: new authoritative lifecycle status

        Returns:
            Canonical WorkflowProjection dict
        """
        workflow_id = workflow.get("id", "unknown")
        store = self._get_or_create_store(workflow_id)

        # Per §14: do not overwrite terminal projection with non-terminal
        if store.get_state() == PROJECTION_STATE_TERMINAL:
            existing = store.get_latest()
            if existing is not None:
                return existing

        version = store.next_version()
        projection = build_workflow_projection(
            workflow=workflow,
            projection_version=version,
            lifecycle_status=lifecycle_status,
            workflow_output=workflow.get("output"),
        )
        store.store(projection)
        self._emit_to_event_bus(workflow_id, "projection_lifecycle_changed", projection)
        return projection

    def emit_step_updated(
        self,
        workflow: Dict[str, Any],
        step: Dict[str, Any],
        lifecycle_status: str,
    ) -> Dict[str, Any]:
        """
        Generate and store updated WorkflowProjection after a step state change.

        Per CANONICAL_PROJECTION_MODEL_V1 §5:
        Projections MUST be emitted when steps update.

        Args:
            workflow: live workflow dict (with updated step)
            step: the step dict that was updated
            lifecycle_status: current authoritative lifecycle status

        Returns:
            Canonical WorkflowProjection dict
        """
        workflow_id = workflow.get("id", "unknown")
        store = self._get_or_create_store(workflow_id)
        version = store.next_version()

        projection = build_workflow_projection(
            workflow=workflow,
            projection_version=version,
            lifecycle_status=lifecycle_status,
            workflow_output=workflow.get("output"),
        )
        store.store(projection)
        self._emit_to_event_bus(workflow_id, "projection_step_updated", projection)
        return projection

    def emit_output_updated(
        self,
        workflow: Dict[str, Any],
        step_id: str,
        lifecycle_status: str,
    ) -> Dict[str, Any]:
        """
        Generate and store updated WorkflowProjection after an output is available.

        Per CANONICAL_PROJECTION_MODEL_V1 §5:
        Projections MUST be emitted when outputs update.

        Args:
            workflow: live workflow dict (with execution_result attached to step)
            step_id: step that produced the output
            lifecycle_status: current authoritative lifecycle status

        Returns:
            Canonical WorkflowProjection dict
        """
        workflow_id = workflow.get("id", "unknown")
        store = self._get_or_create_store(workflow_id)
        version = store.next_version()

        projection = build_workflow_projection(
            workflow=workflow,
            projection_version=version,
            lifecycle_status=lifecycle_status,
            workflow_output=workflow.get("output"),
        )
        store.store(projection)
        self._emit_to_event_bus(workflow_id, "projection_output_updated", projection)
        return projection

    def emit_plan_mutated(
        self,
        workflow: Dict[str, Any],
        lifecycle_status: str,
    ) -> Dict[str, Any]:
        """
        Invalidate stale projection and re-emit canonical WorkflowProjection
        after a plan mutation.

        Per CANONICAL_PROJECTION_MODEL_V1 §7 (Projection Mutation Flow) steps 6-7:
        - Projection regeneration after runtime update
        - Projection re-emission via EventBus

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §10 (Projection Invalidation):
        - Invalid projections MUST refresh from authority
        - Rebuild deterministically

        Per CANONICAL_PROJECTION_MODEL_V1 §5:
        Projections MUST be emitted when plans mutate.

        Args:
            workflow: live workflow dict (post-mutation)
            lifecycle_status: authoritative lifecycle status

        Returns:
            Canonical WorkflowProjection dict
        """
        workflow_id = workflow.get("id", "unknown")
        store = self._get_or_create_store(workflow_id)

        # Per §14: do not overwrite terminal projection with non-terminal
        if store.get_state() == PROJECTION_STATE_TERMINAL:
            existing = store.get_latest()
            if existing is not None:
                return existing

        version = store.next_version()
        projection = build_workflow_projection(
            workflow=workflow,
            projection_version=version,
            lifecycle_status=lifecycle_status,
            workflow_output=workflow.get("output"),
        )
        store.store(projection)
        self._emit_to_event_bus(workflow_id, "projection_plan_mutated", projection)
        return projection

    # ── Projection retrieval ──────────────────────────────────────────────────

    def get_latest_projection(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """
        Return the latest canonical projection for a workflow.

        Returns None if no projection has been emitted yet.
        """
        store = self._get_store(workflow_id)
        if store is None:
            return None
        return store.get_latest()

    def get_projection_version(self, workflow_id: str) -> int:
        """Return current projection version for workflow_id (0 if none)."""
        store = self._get_store(workflow_id)
        if store is None:
            return 0
        return store.current_version()

    def get_projection_state(self, workflow_id: str) -> Optional[str]:
        """Return current projection lifecycle state for workflow_id."""
        store = self._get_store(workflow_id)
        if store is None:
            return None
        return store.get_state()

    # ── Continuity validation (Phase 4A.1) ───────────────────────────────────

    def is_version_stale(self, workflow_id: str, candidate_version: int) -> bool:
        """
        Check if candidate_version is stale for the given workflow.

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §6:
        Late or stale stream events MUST NOT overwrite newer projection state.

        Returns:
            True if candidate is stale (older than stored), False if fresh/valid.
            False if no projection stored yet (can't be stale with no reference).
        """
        store = self._get_store(workflow_id)
        if store is None:
            return False
        return store.is_version_stale(candidate_version)

    def is_workflow_terminal(self, workflow_id: str) -> bool:
        """
        Return True if the workflow's projection is in TERMINAL state.

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §9:
        Terminal projections MUST NOT revert.
        """
        store = self._get_store(workflow_id)
        if store is None:
            return False
        return store.is_terminal()

    def get_continuity_anchor(self, workflow_id: str) -> int:
        """
        Return the last confirmed synchronized projection version for reconnect validation.

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §11:
        Used to detect continuity gaps (missing segments) on reconnect.

        Returns 0 if no projection has been stored.
        """
        store = self._get_store(workflow_id)
        if store is None:
            return 0
        return store.get_continuity_anchor()

    def get_stale_rejection_count(self, workflow_id: str) -> int:
        """
        Return count of stale/invalid projections rejected for diagnostics.

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §11:
        Projection systems MUST detect stale lifecycle snapshots.
        """
        store = self._get_store(workflow_id)
        if store is None:
            return 0
        return store.get_stale_rejection_count()

    def validate_hydration_projection(
        self,
        workflow_id: str,
        candidate_projection: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Validate a candidate projection for safe hydration on reconnect/reload.

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §4 (Hydration Semantics):
        Hydration MUST reconstruct latest valid projection state.
        Hydration MUST NOT restore stale projections blindly.
        Hydration MUST NOT synthesize missing lifecycle state.

        Returns dict:
            valid: bool — True if safe to hydrate
            reason: str — explanation if invalid
            stale: bool — True if candidate is older than stored
            terminal_conflict: bool — True if non-terminal replacing terminal
        """
        from system.orchestrator.projection_schema import validate_projection_identity

        result = {"valid": True, "reason": "ok", "stale": False, "terminal_conflict": False}

        # Identity validation
        if not validate_projection_identity(candidate_projection):
            result["valid"] = False
            result["reason"] = "invalid_projection_identity"
            return result

        # Workflow ID must match
        if candidate_projection.get("workflow_id") != workflow_id:
            result["valid"] = False
            result["reason"] = "workflow_id_mismatch"
            return result

        store = self._get_store(workflow_id)
        if store is None:
            # No existing projection — hydration is safe
            return result

        candidate_version = candidate_projection.get("projection_version", 0)
        candidate_state = candidate_projection.get("projection_state", PROJECTION_STATE_ACTIVE)

        # Stale check
        if store.is_version_stale(candidate_version):
            result["valid"] = False
            result["stale"] = True
            result["reason"] = "candidate_version_stale"
            return result

        # Terminal conflict check
        if store.is_terminal() and candidate_state != PROJECTION_STATE_TERMINAL:
            result["valid"] = False
            result["terminal_conflict"] = True
            result["reason"] = "terminal_overwrite_rejected"
            return result

        return result

    def get_continuity_summary(self, workflow_id: str) -> Dict[str, Any]:
        """
        Return a diagnostics summary of projection continuity state for a workflow.

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §11:
        Stale detection MUST be observable for repair/reconciliation.
        """
        store = self._get_store(workflow_id)
        if store is None:
            return {
                "workflow_id": workflow_id,
                "projection_version": 0,
                "projection_state": None,
                "continuity_anchor": 0,
                "stale_rejections": 0,
                "is_terminal": False,
                "has_projection": False,
            }
        return {
            "workflow_id": workflow_id,
            "projection_version": store.current_version(),
            "projection_state": store.get_state(),
            "continuity_anchor": store.get_continuity_anchor(),
            "stale_rejections": store.get_stale_rejection_count(),
            "is_terminal": store.is_terminal(),
            "has_projection": store.get_latest() is not None,
        }

    # ── Event bus integration ─────────────────────────────────────────────────

    def _emit_to_event_bus(
        self,
        workflow_id: str,
        event_type: str,
        projection: Dict[str, Any],
    ) -> None:
        """
        Emit projection event to the global EventBus.

        Per CANONICAL_PROJECTION_MODEL_V1 §5:
        Projection emission MUST remain workflow-scoped.

        Per SUB-PHASE 3D: Event payload includes projection identity metadata.

        FAILURE-ISOLATED: Event bus failures must not affect projection storage.
        """
        try:
            from system.interface.event_bus import publish_event
            publish_event(
                workflow_id=workflow_id,
                event_type=event_type,
                data={
                    "workflow_id": projection.get("workflow_id"),
                    "projection_type": projection.get("projection_type"),
                    "projection_version": projection.get("projection_version"),
                    "projection_timestamp": projection.get("projection_timestamp"),
                    "projection_state": projection.get("projection_state"),
                    "lifecycle_status": projection.get("lifecycle_status"),
                },
            )
        except Exception:
            # FAILURE-ISOLATED: EventBus failure must not block projection generation
            pass


# =============================================================================
# MODULE-LEVEL SINGLETON
# =============================================================================

_projection_manager: Optional[ProjectionManager] = None
_projection_manager_lock = threading.Lock()


def get_projection_manager() -> ProjectionManager:
    """
    Get the module-level singleton ProjectionManager.

    Per CANONICAL_PROJECTION_MODEL_V1 §1:
    Canonical projections are owned by Orchestrator Runtime.
    Single manager instance ensures workflow-scoped isolation.
    """
    global _projection_manager
    if _projection_manager is None:
        with _projection_manager_lock:
            if _projection_manager is None:
                _projection_manager = ProjectionManager()
    return _projection_manager

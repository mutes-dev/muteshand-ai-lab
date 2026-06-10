"""
EXECUTION SCHEDULER — Contract-Aligned Scheduling Layer

Complies with EXECUTION_SCHEDULING_CONTRACT_V1:
- Derives execution groups dynamically at runtime
- Does NOT persist groups in plan
- Does NOT modify plan structure
- Does NOT introduce new step entities

Complies with ORCHESTRATOR_CONTRACT_V2:
- Orchestrator layer ONLY
- No core execution modification
- No direct tool execution

Complies with CONFLICT_RESOLUTION_CONTRACT_V1:
- Runs conflict detection BEFORE group formation
- Applies severity rules: LOW=allow, MEDIUM=sequentialize, HIGH=exclude
- Does NOT resolve conflicts, only coordinates

Complies with GOVERNANCE_CONTRACT:
- No group-level governance decisions
- No batching of governance across steps

Complies with STATE_TRANSITIONS_CONTRACT_V1:
- Multiple ACTIVE steps allowed ONLY in parallel group
"""

import uuid
from typing import Any, Dict, List, Optional, Set, Tuple
from system.orchestrator.conflict_detector import ConflictDetector
from system.orchestrator import trace_collector
# Per LIFECYCLE_AUTHORITY_CONTRACT_V1: scheduler MUST NOT directly mutate lifecycle state.
# All step status changes MUST be requested through lifecycle authority.
from system.orchestrator.workflow_control import request_step_transition, _get_workflow_state


# === DESTRUCTIVE STEP TYPES (NEVER PARALLEL) ===
# Per EXECUTION_SCHEDULING_CONTRACT_V1 Section 2
DESTRUCTIVE_TYPES = {
    "EXECUTE_INSTALL",
    "EXECUTE_SYSTEM_SETTINGS_SERVICES",
    "EXECUTE_ENVIRONMENT",
}

# Types that are destructive only when risk=HIGH or resource_target indicates write+delete
CONDITIONALLY_DESTRUCTIVE_TYPES = {
    "EXECUTE_FILE",
}


def _is_destructive_step(step: dict) -> bool:
    """
    Determine if a step is destructive per EXECUTION_SCHEDULING_CONTRACT_V1.

    NEVER parallel:
    - type = EXECUTE_INSTALL
    - type = EXECUTE_SYSTEM_SETTINGS_SERVICES
    - type = EXECUTE_ENVIRONMENT (if modifying)
    - risk = HIGH with destructive resource_target
    - resource_target indicates write+delete operation

    NO inference. NO natural language reasoning.
    """
    step_type = step.get("type", "")

    # Unconditionally destructive types
    if step_type in DESTRUCTIVE_TYPES:
        return True

    # EXECUTE_FILE is destructive if risk=HIGH or resource indicates destruction
    if step_type in CONDITIONALLY_DESTRUCTIVE_TYPES:
        risk = step.get("risk", "LOW")
        if risk == "HIGH":
            return True

    # HIGH risk with any destructive indicator
    if step.get("risk") == "HIGH":
        return True

    return False


def _get_resource_targets(step: dict) -> Set[str]:
    """
    Extract resource_targets from step.

    Per STEP_SCHEMA_CONTRACT_V1: resource_targets is a list of resource identifiers.
    Per EXECUTION_SCHEDULING_CONTRACT_V1: dependency detection uses resource_target analysis ONLY.
    """
    targets = step.get("resource_targets", [])
    if isinstance(targets, list):
        return set(targets)
    return set()


def _check_dependencies_satisfied(step: dict, step_states: Dict[str, str], steps_map: Dict[str, dict]) -> Tuple[bool, str]:
    """
    Check if all dependencies of a step are satisfied (COMPLETED).

    Per DEPENDENCY_MODEL_CONTRACT_V1 Section 3:
    - step may execute ONLY when all dependencies are COMPLETED
    - dependency completion = governance COMPLETE
    - FAILED dependencies block dependent steps

    Returns:
        (satisfied: bool, reason: str)
    """
    step_id = step.get("id", "unknown")
    depends_on = step.get("depends_on", [])

    if not depends_on:
        return True, "no_dependencies"

    for dep_id in depends_on:
        # Per DEPENDENCY_MODEL_CONTRACT_V1: authoritative state is the live step object.
        # steps_map holds refs to the same dicts mutated by the executor, so
        # dep_step["status"] is always current.  step_states is a snapshot that
        # may lag by one pre-flight mutation cycle; use it only as a fallback when
        # the dep_id has no live object (e.g. unknown / not yet registered step).
        dep_step = steps_map.get(dep_id)
        dep_state = dep_step.get("status", "PENDING") if dep_step else step_states.get(dep_id, "PENDING")

        # Per contract: FAILED dependencies block dependent steps
        if dep_state == "FAILED":
            return False, f"dependency_failed:{dep_id}"

        # Per contract: Only COMPLETED dependencies satisfy requirement
        if dep_state != "COMPLETED":
            return False, f"dependency_not_completed:{dep_id}:{dep_state}"

    return True, "all_dependencies_completed"


def _has_dependency(step_a: dict, step_b: dict) -> bool:
    """
    Check if step_a depends on step_b via resource overlap.

    Per EXECUTION_SCHEDULING_CONTRACT_V1 Section 2 - DEPENDENCY DETECTION:
    - Step A produces output consumed by Step B
    - Step A modifies a resource_target read or written by Step B
    - Explicit dependency declaration

    Detection method:
    - Explicit dependency fields (if available)
    - resource_target analysis ONLY

    MUST NOT infer from purpose or natural language.
    """
    # Check explicit dependency field
    depends_on = step_a.get("depends_on", [])
    if isinstance(depends_on, list) and step_b.get("id") in depends_on:
        return True

    # Resource-based dependency: overlap in resource_targets
    # Per contract: dependency only if Step A MODIFIES a resource_target of Step B
    # Read-only step types do NOT modify resources
    targets_a = _get_resource_targets(step_a)
    targets_b = _get_resource_targets(step_b)

    if targets_a and targets_b and targets_a & targets_b:
        # Check if at least one step modifies the resource
        # Read-only types: ANALYZE, RESEARCH, VALIDATE, PLAN, PROPOSE, GENERATE
        read_only_types = {"ANALYZE", "RESEARCH", "VALIDATE", "PLAN", "PROPOSE", "GENERATE"}
        type_a = step_a.get("type", "EXECUTE_API")
        type_b = step_b.get("type", "EXECUTE_API")
        # Dependency exists only if at least one step is NOT read-only
        if type_a not in read_only_types or type_b not in read_only_types:
            return True
        # Both read-only → no modification → no dependency
        return False

    return False


def _check_pairwise_conflicts(
    candidates: List[dict],
    conflict_detector: ConflictDetector,
    workflow_id: str
) -> Dict[str, str]:
    """
    Run pairwise conflict detection on candidate steps' resource_targets.

    Returns dict mapping step_id -> severity for conflicting steps.

    Per CONFLICT_RESOLUTION_CONTRACT_V1:
    - LOW -> allow in parallel
    - MEDIUM -> move to sequential group
    - HIGH -> exclude from parallel, mark for sequential
    """
    conflict_map: Dict[str, str] = {}

    for i, step_a in enumerate(candidates):
        targets_a = _get_resource_targets(step_a)
        if not targets_a:
            continue

        for j, step_b in enumerate(candidates):
            if j <= i:
                continue

            targets_b = _get_resource_targets(step_b)
            if not targets_b:
                continue

            overlap = targets_a & targets_b
            if overlap:
                severity = conflict_detector._calculate_severity(step_a, step_b)

                if severity in ("MEDIUM", "HIGH"):
                    # Mark the later step for exclusion from parallel
                    step_b_id = step_b.get("id", f"unknown_{j}")
                    existing = conflict_map.get(step_b_id, "LOW")
                    # Escalate severity
                    if severity == "HIGH" or existing == "HIGH":
                        conflict_map[step_b_id] = "HIGH"
                    elif severity == "MEDIUM":
                        conflict_map[step_b_id] = "MEDIUM"

                    # TRACE: CONFLICT_EXCLUSION
                    try:
                        trace_collector.record_transition(
                            step_id=step_b_id,
                            previous_status="PENDING",
                            new_status="PENDING",
                            reason=f"CONFLICT_EXCLUSION:severity={severity}:resources={list(overlap)}"
                        )
                    except Exception:
                        pass

    return conflict_map


def _check_parallel_eligibility(
    step: dict,
    other_pending: List[dict],
    conflict_detector: ConflictDetector,
    workflow_id: str
) -> Tuple[bool, str]:
    """
    Check if a step is eligible for parallel execution.

    Per EXECUTION_SCHEDULING_CONTRACT_V1 Section 2:

    A step is eligible ONLY if:
    1. NO DEPENDENCIES (resource-based only)
    2. NO RESOURCE CONFLICTS (LOW or NONE only)
    3. NOT EXCLUDED BY TYPE (not destructive)

    Returns (eligible, reason).
    """
    step_id = step.get("id", "unknown")

    # Rule 3: Destructive type exclusion
    if _is_destructive_step(step):
        reason = "EXCLUDED_TYPE"
        # TRACE: PARALLEL_ELIGIBILITY_CHECK
        try:
            trace_collector.record_transition(
                step_id=step_id,
                previous_status="PENDING",
                new_status="PENDING",
                reason=f"PARALLEL_ELIGIBILITY_CHECK:eligible=false:reason={reason}"
            )
        except Exception:
            pass
        return False, reason

    # Rule 1: Dependency detection (resource-based ONLY)
    for other in other_pending:
        if other.get("id") == step_id:
            continue
        if _has_dependency(step, other):
            reason = "DEPENDENCY_DETECTED"
            try:
                trace_collector.record_transition(
                    step_id=step_id,
                    previous_status="PENDING",
                    new_status="PENDING",
                    reason=f"PARALLEL_ELIGIBILITY_CHECK:eligible=false:reason={reason}"
                )
            except Exception:
                pass
            return False, reason

    # Rule 2: No resource conflicts (checked later in pairwise)
    # Individual eligibility passed
    reason = "NO_CONFLICTS"
    try:
        trace_collector.record_transition(
            step_id=step_id,
            previous_status="PENDING",
            new_status="PENDING",
            reason=f"PARALLEL_ELIGIBILITY_CHECK:eligible=true:reason={reason}"
        )
    except Exception:
        pass
    return True, reason


def create_execution_group(
    workflow: dict,
    step_states: Dict[str, str],
    conflict_detector: ConflictDetector,
    workflow_id: str
) -> Optional[dict]:
    """
    Derive the NEXT execution group dynamically from workflow steps.

    Per EXECUTION_SCHEDULING_CONTRACT_V1:
    - Groups are DERIVED at runtime, NOT persisted
    - Plan remains flat
    - Scheduling MUST NOT modify plan structure

    Per STATE_TRANSITIONS_CONTRACT_V1:
    - PAUSED workflows MUST NOT schedule new steps

    Process (per Section 1.5 SCHEDULING TRIGGER):
    1. Evaluate all PENDING steps
    2. Determine dependency readiness
    3. Run conflict detection on eligible steps
    4. Form next execution group (SEQUENTIAL or PARALLEL)

    Args:
        workflow: The workflow dict (NOT modified)
        step_states: Dict mapping step_id -> current status
        conflict_detector: The conflict detector instance
        workflow_id: The workflow ID

    Returns:
        Execution group dict or None if no steps to execute:
        {
            "group_id": str,
            "group_type": "SEQUENTIAL" | "PARALLEL",
            "steps": [step_id, ...],
            "boundary_rules": {
                "wait_for_all": True,
                "allow_partial_completion": False
            }
        }
    """
    # === PAUSED STATE CHECK (Phase 4A.1) ===
    # Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED workflows must not schedule
    # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: read authoritative runtime registry,
    # NOT stale workflow dict (workflow["status"] may still say PAUSED after resume_workflow()
    # has already updated the registry to ACTIVE).
    _wf_id_for_check = workflow.get("id", "unknown_workflow")
    _sched_auth_state = (_get_workflow_state(_wf_id_for_check) or {}).get("status", workflow.get("status"))
    if _sched_auth_state == "PAUSED":
        return None

    steps = workflow.get("steps", [])

    # Build steps_map for dependency lookups
    steps_map = {s.get("id"): s for s in steps if s.get("id")}
    
    # DIAGNOSTIC: log all step statuses at scheduler entry
    print(f"[SCHEDULER_ENTRY] workflow={workflow_id} steps={[(s.get('id'), s.get('status')) for s in steps]}")

    # Step scheduling begins

    # Step 1: Evaluate all schedulable steps
    # Includes PENDING, BLOCKED (for re-evaluation), and approval-resumed ACTIVE steps
    # Per DEPENDENCY_MODEL_CONTRACT_V1: BLOCKED steps may become runnable
    # Use actual step status (which reflects runtime state changes) over stale step_states
    candidate_steps = []
    for s in steps:
        # Prioritize step's current status (may have been updated by runtime)
        # Only fall back to step_states for steps not yet seen by runtime
        current_status = s.get("status", "PENDING")
        if current_status not in ("PENDING", "BLOCKED", "ACTIVE"):
            # For terminal states or unknown states, use step_states if available
            current_status = step_states.get(s.get("id"), current_status)

        # === RESURRECTION INSTRUMENTATION (Point 5a) ===
        step_id = s.get("id", "unknown")
        acceptance_reason = None

        # Include PENDING and BLOCKED (for re-evaluation)
        # Per STATE_TRANSITIONS_CONTRACT_V1: RETRY is not a valid lifecycle state.
        # Retry candidates are in PENDING state after retry_step() (PHASE-IA).
        if current_status in ("PENDING", "BLOCKED"):
            candidate_steps.append(s)
            acceptance_reason = f"status_in_candidates: {current_status}"
        elif current_status == "ACTIVE" and s.get("_approval_resumed"):
            # Approval-resumed step: BLOCKED → ACTIVE, awaiting execution
            candidate_steps.append(s)
            acceptance_reason = "approval_resumed"
        elif current_status == "ACTIVE" and s.get("_retry_pending"):
            # Retry-pending step: ACTIVE but awaiting re-dispatch, not currently running
            candidate_steps.append(s)
            acceptance_reason = "retry_pending"
        else:
            acceptance_reason = f"rejected_status: {current_status}"

        # Log acceptance/rejection for all steps
        print(f"[RESURRECTION_INSTRUMENTATION] Step {step_id}: status={current_status}, accepted={acceptance_reason}")

    if not candidate_steps:
        print("[DEBUG_REEVAL] No candidate steps found")
        return None

    # Pre-flight: re-evaluate all non-terminal steps for dependency changes
    # Check dependencies for PENDING and BLOCKED steps before group formation
    # This allows BLOCKED steps to become runnable when dependencies complete
    for step in steps:
        step_id = step.get("id", "unknown")
        current_status = step.get("status", "PENDING")
        
        # Only check non-terminal steps
        # Per STATE_TRANSITIONS_CONTRACT_V1: RETRY is not a valid lifecycle state (PHASE-IA).
        if current_status not in ("PENDING", "BLOCKED"):
            continue

        # ISSUE-098IJ: external_call_risk blocked steps must NOT be auto-resumed
        # by dependency satisfaction. Only operator acceptance (via runtime resume
        # path) may transition them back to ACTIVE.
        if step.get("blocked_reason") == "external_call_risk":
            continue
            
        deps_satisfied, deps_reason = _check_dependencies_satisfied(step, step_states, steps_map)
        
        if deps_satisfied:
            if current_status == "BLOCKED":
                print(f"[DEBUG_REEVAL] Step {step_id}: BLOCKED -> PENDING (deps satisfied)")
                # Internal dependency-release transition: BLOCKED → PENDING
                # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: request through authority
                request_step_transition(step, "PENDING", reason="dep_satisfied", _internal=True)
        else:
            if current_status == "PENDING":
                # PENDING step became BLOCKED - deps not satisfied
                print(f"[DEBUG_REEVAL] Step {step_id}: {current_status} -> BLOCKED ({deps_reason})")
                # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: request through authority
                request_step_transition(step, "BLOCKED", reason=deps_reason)
            # If already BLOCKED, keep it BLOCKED

    # Step 1b: DEPENDENCY SATISFACTION CHECK (DEPENDENCY_MODEL_CONTRACT_V1)
    # Per contract: FAILED dependencies MUST block dependent steps
    # Re-evaluate all candidates including previously BLOCKED steps
    schedulable_steps = []
    # Dependencies re-evaluated
    for step in candidate_steps:
        step_id = step.get("id", "unknown")
        deps_satisfied, deps_reason = _check_dependencies_satisfied(step, step_states, steps_map)

        # === RESURRECTION INSTRUMENTATION (Point 5b) ===
        schedulable_reason = None

        if deps_satisfied:
            # ISSUE-098IJ: external_call_risk blocked steps must NOT be auto-resumed
            # by dependency satisfaction. Only operator acceptance may resume them.
            if step.get("blocked_reason") == "external_call_risk":
                schedulable_reason = "rejected_external_call_risk_block"
            else:
                # Dependencies now satisfied - step becomes schedulable
                if step.get("status") == "BLOCKED":
                    print(f"[DEBUG_REEVAL] Step {step_id}: BLOCKED -> PENDING (deps satisfied)")
                    # Internal dependency-release transition: BLOCKED → PENDING
                    # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: request through authority
                    request_step_transition(step, "PENDING", reason="dep_satisfied", _internal=True)
                # PENDING steps remain as-is when deps satisfied
                schedulable_steps.append(step)
                schedulable_reason = f"deps_satisfied: {deps_reason}"
        else:
            # Dependency not satisfied — step becomes/remains BLOCKED
            if step.get("status") not in ("BLOCKED",):
                print(f"[DEBUG_REEVAL] Step {step_id}: {step.get('status')} -> BLOCKED ({deps_reason})")
                # Per LIFECYCLE_AUTHORITY_CONTRACT_V1: request through authority
                request_step_transition(step, "BLOCKED", reason=deps_reason)
            schedulable_reason = f"rejected_deps_not_satisfied: {deps_reason}"
            # TRACE: DEPENDENCY_BLOCKED
            try:
                trace_collector.record_transition(
                    step_id=step_id,
                    previous_status=step.get("status", "PENDING"),
                    new_status="BLOCKED",
                    reason=f"DEPENDENCY_BLOCKED:{deps_reason}"
                )
            except Exception:
                pass

        # Log schedulable decision for all candidate steps
        print(f"[RESURRECTION_INSTRUMENTATION] Step {step_id}: schedulable={schedulable_reason}")

    # Steps selected for scheduling

    if not schedulable_steps:
        return None

    # Replace pending_steps with filtered schedulable steps
    pending_steps = schedulable_steps

    # Step 2: Check for any ACTIVE steps from previous groups
    # (ensures group boundary synchronization - BLOCKED steps will be re-evaluated)
    # Exclude approval-resumed ACTIVE steps (they ARE the next group candidates)
    # Exclude retry-pending ACTIVE steps (they are waiting for re-dispatch, not running)
    active_steps = [
        s for s in steps
        if s.get("status") == "ACTIVE"
        and not s.get("_approval_resumed")
        and not s.get("_retry_pending")
    ]
    if active_steps:
        # Previous group not complete — cannot form new group
        # Cannot form group - active steps still running
        return None

    # Step 3: Check parallel eligibility for each pending step
    parallel_candidates = []
    sequential_forced = []

    for step in pending_steps:
        eligible, reason = _check_parallel_eligibility(
            step, pending_steps, conflict_detector, workflow_id
        )
        if eligible:
            parallel_candidates.append(step)
        else:
            sequential_forced.append((step, reason))

    # Step 4: Run pairwise conflict detection on parallel candidates
    if len(parallel_candidates) > 1:
        conflict_map = _check_pairwise_conflicts(
            parallel_candidates, conflict_detector, workflow_id
        )

        # Remove conflicting steps from parallel group
        final_parallel = []
        demoted_to_sequential = []
        for step in parallel_candidates:
            step_id = step.get("id", "unknown")
            if step_id in conflict_map:
                severity = conflict_map[step_id]
                demoted_to_sequential.append((step, f"RESOURCE_CONFLICT:{severity}"))
            else:
                final_parallel.append(step)

        parallel_candidates = final_parallel
        sequential_forced.extend(demoted_to_sequential)

    # Step 5: Form execution group
    group_id = f"group_{uuid.uuid4().hex[:8]}"

    if len(parallel_candidates) > 1:
        # PARALLEL GROUP: multiple independent, non-conflicting steps
        step_ids = [s.get("id") for s in parallel_candidates]
        group = {
            "group_id": group_id,
            "group_type": "PARALLEL",
            "steps": step_ids,
            "boundary_rules": {
                "wait_for_all": True,
                "allow_partial_completion": False
            }
        }
    else:
        # SEQUENTIAL GROUP: single step or forced sequential
        # Take the first pending step in plan order (preserves deterministic ordering)
        first_step = pending_steps[0]
        step_ids = [first_step.get("id")]
        group = {
            "group_id": group_id,
            "group_type": "SEQUENTIAL",
            "steps": step_ids,
            "boundary_rules": {
                "wait_for_all": True,
                "allow_partial_completion": False
            }
        }

    # TRACE: GROUP_FORMED
    try:
        trace_collector.record_transition(
            step_id=group_id,
            previous_status="NONE",
            new_status="FORMED",
            reason=f"GROUP_FORMED:type={group['group_type']}:step_count={len(step_ids)}:step_ids={step_ids}"
        )
    except Exception:
        pass

    return group

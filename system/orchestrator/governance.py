# === LIVE STATE STREAMING (Phase 3) — OBSERVATIONAL ONLY ===
# Per HAND_ARCHITECTURE_V2: Streaming reflects state, never influences it
# Per CONTROL_MODEL: Events are advisory, non-authoritative
try:
    from system.interface import event_emitter as _event_emitter
except Exception:
    _event_emitter = None


def _structured_log(event_type, workflow_id, step_id, data):
    """Structured debug logger for runtime trace evidence."""
    import json
    log_entry = {
        "EVENT": event_type,
        "workflow_id": workflow_id,
        "step_id": step_id,
        "timestamp": __import__('datetime').datetime.now().isoformat(),
        "data": data
    }
    print(f"[RUNTIME_TRACE] {json.dumps(log_entry, default=str)}")


def _get_step_tool_name(step: dict) -> str:
    """
    Extract the executed tool name from a step dict using the most reliable
    available source, in priority order.

    Returns the tool name string, or "" if none can be determined.
    """
    # 1. AG1 advisory metadata (already attached by step_executor)
    _agent_meta = step.get("_agent_metadata")
    if isinstance(_agent_meta, dict):
        _selected = _agent_meta.get("selected_tool")
        if isinstance(_selected, str) and _selected.strip():
            return _selected.strip()

    # 2. executed_input parsed tool name
    _ei = step.get("executed_input")
    if isinstance(_ei, str) and _ei.strip():
        _parts = _ei.strip().split()
        if _parts:
            return _parts[0]

    # 3. tool_call parsed tool name
    _tc = step.get("tool_call")
    if isinstance(_tc, str) and _tc.strip():
        _parts = _tc.strip().split()
        if _parts:
            return _parts[0]

    # 4. capability_metadata allowed_tool
    _cm = step.get("capability_metadata")
    if isinstance(_cm, dict):
        _allowed = _cm.get("allowed_tool")
        if isinstance(_allowed, str) and _allowed.strip():
            return _allowed.strip()

    # 5. purpose-based fallback (last resort)
    _purpose = step.get("purpose", "")
    if isinstance(_purpose, str) and _purpose.strip():
        _p_lower = _purpose.strip().lower()
        if _p_lower.startswith("read ") or _p_lower.startswith("fetch "):
            return "read_file"
        if _p_lower.startswith("list "):
            return "list_files"
        if _p_lower.startswith("search "):
            return "web_search"

    return ""


# Raw acquisition/read/fetch tools whose output is literal external content.
# Phase-2A false-success detection must NOT scan these outputs because
# external source content may legitimately contain template syntax,
# TODO markers, or other patterns that look like false-success signals.
_PHASE2A_RAW_ACQUISITION_TOOLS = frozenset({
    "read_file",
    "read_webpage",
    "web_search",
    "list_files",
})


# === GOVERNANCE DECISION NORMALIZATION (Phase 1) ===
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class GovernanceDecision:
    """
    Explicit structured governance decision object.

    Per GOVERNANCE DECISION NORMALIZATION Phase 1:
    - Normalizes governance decision handling into explicit structured objects
    - Preserves ALL existing governance behavior, authority semantics, retry semantics
    - Adds explicit governance rationale, authority provenance, and observability structure
    - NO semantic behavior changes — strictly normalization and observability hardening

    Architecture compliance:
    - execution_result remains sole execution truth (authority_source tracks this)
    - governance remains sole decision authority (this object IS the decision)
    - validator signals remain advisory-only (stored in validator_advisory)
    - projections remain non-authoritative (this object is for governance layer only)
    - lifecycle authority remains centralized (runtime applies this decision)
    - trace remains observational-only (metadata fields for trace enrichment)

    Rules:
    - MUST be immutable (frozen=True)
    - MUST NOT mutate runtime behavior
    - MUST NOT introduce hidden authority
    - MUST NOT introduce new execution paths
    - action MUST be one of: "complete", "retry", "fail", "escalate", "block"
    """

    action: str
    """The governance action: 'complete', 'retry', 'fail', 'escalate', or 'block'."""

    reason: str
    """Human-readable rationale for the decision."""

    authority_source: str = "execution_result"
    """Primary authority source — per AUTHORITY_MODEL.txt, execution_result is sole truth."""

    retry_strategy: Optional[str] = None
    """
    Retry strategy placeholder — Phase 2 normalization only.
    Current allowed value: None or RetryStrategy.SAME.
    """

    retry_guidance: Optional[Any] = None
    """
    Retry guidance metadata — Phase 3 normalization.
    Contains RetryGuidance object with strategy, rationale, suggested_adjustment.
    Observational only — no control flow influence.
    """

    retry_remediation: Optional[Any] = None
    """
    Retry remediation metadata — Phase 5 normalization.
    Contains RetryRemediation object with remediation_type, rationale, proposed_adjustment.
    Observational only — metadata only, NEVER executable.
    """

    escalation_level: Optional[str] = None
    """Escalation severity level for 'escalate' decisions (advisory only)."""

    validator_advisory: Optional[Dict[str, Any]] = None
    """
    Advisory validator signals — stored for observability only.
    Per VALIDATION_ARCHITECTURE.txt: validator signals are advisory, do NOT influence decisions.
    """

    confidence_context: Optional[Dict[str, Any]] = None
    """
    Confidence/risk context — advisory metadata for trace/observability.
    Per CONTROL_MODEL.txt §292-306: confidence influences retry vs escalate (future enhancement).
    Phase 1: stored as metadata only, zero control impact.
    """

    metadata: Dict[str, Any] = field(default_factory=dict)
    """
    Additional structured observability fields.
    Examples: retry_count, max_retries, risk_level, purpose_met, validity_reason
    """

    def __post_init__(self):
        """Validate action is one of the allowed values."""
        valid_actions = {"complete", "retry", "fail", "escalate", "block"}
        if self.action not in valid_actions:
            raise ValueError(f"Invalid governance action: {self.action}. Must be one of: {valid_actions}")

    def __str__(self) -> str:
        """Return action string for backward compatibility with string comparisons."""
        return self.action

    def __eq__(self, other) -> bool:
        """
        Support comparison with both GovernanceDecision objects and strings.
        Enables backward compatibility: decision == "retry" works as expected.
        """
        if isinstance(other, GovernanceDecision):
            return self.action == other.action
        elif isinstance(other, str):
            return self.action == other
        return NotImplemented

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for trace/serialization (observational only)."""
        # Convert retry_guidance to dict if present
        retry_guidance_dict = None
        if self.retry_guidance is not None:
            if hasattr(self.retry_guidance, 'to_dict'):
                retry_guidance_dict = self.retry_guidance.to_dict()
            else:
                retry_guidance_dict = str(self.retry_guidance)
        
        # Convert retry_remediation to dict if present
        retry_remediation_dict = None
        if self.retry_remediation is not None:
            if hasattr(self.retry_remediation, 'to_dict'):
                retry_remediation_dict = self.retry_remediation.to_dict()
            else:
                retry_remediation_dict = str(self.retry_remediation)
        
        return {
            "action": self.action,
            "reason": self.reason,
            "authority_source": self.authority_source,
            "retry_strategy": self.retry_strategy,
            "retry_guidance": retry_guidance_dict,  # Phase 3: structured retry guidance
            "retry_remediation": retry_remediation_dict,  # Phase 5: structured retry remediation
            "escalation_level": self.escalation_level,
            "validator_advisory": self.validator_advisory,
            "confidence_context": self.confidence_context,
            "metadata": self.metadata
        }


class RetryStrategy:
    """
    Explicit deterministic retry strategy constants.
    
    Per GOVERNANCE RETRY STRATEGY NORMALIZATION Phase 2:
    - deterministic only
    - static only
    - metadata only
    - NO adaptive intelligence
    - NO probabilistic logic
    
    Current Phase 2 implementation:
    - SAME only (placeholder normalization)
    
    Future phases (NOT IMPLEMENTED):
    - REFINED: retry with refined input
    - FALLBACK: retry with fallback approach
    - SAFE_ALTERNATIVE: retry with safe alternative
    """
    
    # CURRENTLY ACTIVE (Phase 2)
    SAME = "same"  # Retry with same input (deterministic retry)
    CONSTRAINT_REFINED = "constraint_refined"  # Retry with constraint-aware refinement (Phase 2)
    
    # RESERVED FOR FUTURE PHASES (NOT IMPLEMENTED)
    REFINED = "refined"  # Retry with refined input (future)
    FALLBACK = "fallback"  # Retry with fallback approach (future)
    SAFE_ALTERNATIVE = "safe_alternative"  # Retry with safe alternative (future)


@dataclass(frozen=True)
class RetryGuidance:
    """
    Explicit deterministic retry guidance metadata.
    
    Per RETRY GUIDANCE NORMALIZATION Phase 3:
    - deterministic only
    - metadata only
    - observational only
    - NO adaptive intelligence
    - NO probabilistic logic
    - NO confidence-driven behavior
    - NO semantic orchestration
    
    Current Phase 3 implementation:
    - strategy: RetryStrategy.SAME only
    - rationale: execution_failure | purpose_not_met | invalid_execution
    - suggested_adjustment: None (placeholder for future phases)
    
    Future phases (NOT IMPLEMENTED):
    - suggested_adjustment: refined_input, fallback_tool, constraint_remediation
    """
    
    strategy: str
    """Retry strategy — currently ONLY RetryStrategy.SAME (placeholder)."""
    
    rationale: str
    """Human-readable rationale for retry — advisory only."""
    
    suggested_adjustment: Optional[str] = None
    """
    Suggested adjustment for retry — RESERVED FOR FUTURE PHASES.
    Phase 3: ALWAYS None (placeholder normalization).
    Future: refined_input, fallback_tool, constraint_remediation, etc.
    """
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional retry guidance metadata — observational only."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for trace/serialization (observational only)."""
        return {
            "strategy": self.strategy,
            "rationale": self.rationale,
            "suggested_adjustment": self.suggested_adjustment,
            "metadata": self.metadata
        }


@dataclass(frozen=True)
class GovernanceContext:
    """
    Explicit immutable governance input snapshot.
    
    Per GOVERNANCE CONTEXT NORMALIZATION Phase 4:
    - immutable only (frozen=True)
    - deterministic only
    - snapshot-only (captures state at evaluation boundary)
    - NO hidden logic
    - NO runtime mutation
    - NO semantic behavior changes
    
    Purpose:
    - Packages all governance inputs into explicit deterministic snapshot
    - Provides stable evaluation boundary for governance stages
    - Enables replay-safe governance evaluation
    - Supports observability alignment
    
    Architecture compliance:
    - execution_result is PRIMARY authority (captured as-is)
    - validator signals remain advisory (captured as advisory metadata)
    - retry metadata is deterministic (captured from step state)
    """
    
    # PRIMARY AUTHORITY (per AUTHORITY_MODEL)
    execution_result: Optional[Dict[str, Any]]
    """PRIMARY authority — sole basis for governance decisions."""
    
    # RETRY METADATA (deterministic from step state)
    retry_count: int
    """Current retry count — deterministic from step['retries']."""
    
    max_retries: int
    """Maximum allowed retries — deterministic from risk-based calculation."""
    
    # ADVISORY SIGNALS (non-authoritative, observational only)
    validator_result: Optional[Dict[str, Any]] = None
    """Advisory validator output — stored for observability, NEVER influences decisions."""
    
    # NORMALIZED RETRY METADATA (Phases 2-3)
    retry_strategy: Optional[str] = None
    """Retry strategy from prior governance decisions — observational only."""
    
    retry_guidance: Optional[Any] = None
    """Retry guidance from prior governance decisions — observational only."""
    
    # WORKFLOW/STEP STATE (for trace correlation)
    workflow_id: str = "unknown"
    """Workflow identifier for trace correlation."""
    
    step_id: str = "unknown"
    """Step identifier for trace correlation."""
    
    step_state: Optional[str] = None
    """Step status/state snapshot — for observability only."""
    
    # EXTENSIBILITY METADATA
    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional governance context metadata — observational only."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for trace/serialization (observational only)."""
        # Convert nested objects
        retry_guidance_dict = None
        if self.retry_guidance is not None and hasattr(self.retry_guidance, 'to_dict'):
            retry_guidance_dict = self.retry_guidance.to_dict()
        
        return {
            "execution_result": self.execution_result,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "validator_result": self.validator_result,
            "retry_strategy": self.retry_strategy,
            "retry_guidance": retry_guidance_dict,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "step_state": self.step_state,
            "metadata": self.metadata
        }


@dataclass(frozen=True)
class RetryRemediation:
    """
    Explicit immutable retry remediation metadata.
    
    Per RETRY REMEDIATION SURFACE NORMALIZATION Phase 5:
    - deterministic only
    - metadata only
    - observational only
    - NO adaptive intelligence
    - NO probabilistic logic
    - NO confidence-driven behavior
    - NO semantic orchestration
    - NO executable remediation (metadata only)
    
    Current Phase 5 implementation:
    - remediation_type: "same_retry" only (deterministic placeholder)
    - rationale: execution_failure | purpose_not_met | invalid_execution
    - proposed_adjustment: None (placeholder for future phases)
    
    Future phases (NOT IMPLEMENTED):
    - remediation_type: prompt_rewrite, tool_refinement, fallback_execution, constraint_remediation
    - proposed_adjustment: actual remediation payload (still metadata-only, not executable)
    
    Architecture compliance:
    - Remediation remains metadata-only — NEVER executes automatically
    - Governance remains sole decision authority
    - execution_result remains sole execution truth
    """
    
    remediation_type: str
    """
    Remediation type — currently ONLY "same_retry" (deterministic placeholder).
    Future: prompt_rewrite, tool_refinement, fallback_execution, constraint_remediation
    """
    
    rationale: str
    """Human-readable rationale for remediation — advisory only."""
    
    proposed_adjustment: Optional[str] = None
    """
    Proposed adjustment for remediation — RESERVED FOR FUTURE PHASES.
    Phase 5: ALWAYS None (placeholder normalization).
    Future: refined_prompt, fallback_tool, constraint_fix, etc. (still metadata-only)
    """
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional remediation metadata — observational only."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for trace/serialization (observational only)."""
        return {
            "remediation_type": self.remediation_type,
            "rationale": self.rationale,
            "proposed_adjustment": self.proposed_adjustment,
            "metadata": self.metadata
        }


def _create_governance_context(
    execution_result: Optional[Dict[str, Any]],
    step: Dict[str, Any],
    context: Optional[Dict[str, Any]],
    validator_output: Optional[Dict[str, Any]] = None,
    retry_guidance: Optional[Any] = None
) -> GovernanceContext:
    """
    Factory function to create immutable GovernanceContext snapshot.
    
    Per GOVERNANCE CONTEXT NORMALIZATION Phase 4:
    - Creates deterministic snapshot of ALL governance inputs
    - Captures state at evaluation boundary (replay-safe)
    - NO runtime mutation after creation
    
    Args:
        execution_result: PRIMARY authority
        step: Step dict (source for retry_count, max_retries, state)
        context: Workflow context
        validator_output: Advisory validator signals
        retry_guidance: Prior retry guidance (if any)
    
    Returns:
        GovernanceContext: Immutable snapshot of governance inputs
    """
    workflow_id = context.get("workflow_id", "unknown") if context else "unknown"
    step_id = step.get("id", "unknown")
    retry_count = step.get("retries", 0)
    step_state = step.get("status")
    
    # Calculate max_retries deterministically
    risk_level = step.get("risk", "MEDIUM")
    max_retries = _get_risk_based_max_retries(risk_level)
    
    return GovernanceContext(
        execution_result=execution_result,
        retry_count=retry_count,
        max_retries=max_retries,
        validator_result=validator_output,
        retry_strategy=None,  # Will be set by governance decision
        retry_guidance=retry_guidance,
        workflow_id=workflow_id,
        step_id=step_id,
        step_state=step_state,
        metadata={
            "risk_level": risk_level,
            "purpose_met": step.get("purpose_met", True),
            "executed_input": step.get("executed_input")
        }
    )


# === GOVERNANCE EVALUATION STAGE HELPERS (Phase 1B) ===
# Explicit deterministic evaluation stages for internal pipeline normalization.
# These helpers normalize the governance flow while preserving ALL semantics.

def _evaluate_approval(step: dict, context: dict, workflow_id: str, step_id: str) -> tuple:
    """
    STAGE 1: Approval Evaluation
    
    Determines if approval is required before execution.
    
    Returns:
        (is_blocked: bool, decision: GovernanceDecision|None)
        - If blocked: returns (True, block_decision)
        - If not blocked: returns (False, None)
    """
    if _check_approval_required(step, context or {}):
        step["blocked_reason"] = "approval_required"
        
        _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
            "stage": "approval_evaluation",
            "result": "blocked",
            "reason": "approval_required"
        })
        
        decision = GovernanceDecision(
            action="block",
            reason="approval_required",
            authority_source="governance",
            metadata={
                "workflow_id": workflow_id,
                "step_id": step_id,
                "stage": "approval_evaluation",
                "risk_level": step.get("risk", "MEDIUM"),
                "importance": step.get("importance", "normal")
            }
        )
        return True, decision
    
    _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
        "stage": "approval_evaluation",
        "result": "approved"
    })
    return False, None


def _evaluate_execution_result(execution_result: dict, step: dict, workflow_id: str, step_id: str) -> tuple:
    """
    STAGE 2: Execution Result Evaluation
    
    Evaluates execution_result status and determines if execution succeeded or failed.
    
    Returns:
        (status: str, validity_info: dict)
        - status: "success" | "failure" | "none"
        - validity_info: dict with validation details
    """
    if execution_result is None:
        _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
            "stage": "execution_result_evaluation",
            "result": "no_execution_result"
        })
        return "none", {"present": False}
    
    exec_status = execution_result.get("status")
    
    if exec_status == "success":
        # Validate execution for success case
        valid, validity_reason = is_execution_valid(execution_result, step)
        step["_execution_validity"] = {"valid": valid, "reason": validity_reason}
        
        _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
            "stage": "execution_result_evaluation",
            "result": "success",
            "valid": valid,
            "validity_reason": validity_reason
        })
        return "success", {"valid": valid, "reason": validity_reason}
    
    elif exec_status == "failure":
        # Check for fail-fast schema violations
        fail_reason = execution_result.get("reason", "")
        if fail_reason in ("missing_tool_call", "missing_tool_call_and_purpose"):
            _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
                "stage": "execution_result_evaluation",
                "result": "failure_fail_fast",
                "fail_reason": fail_reason
            })
            return "failure_fail_fast", {"fail_reason": fail_reason}
        
        _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
            "stage": "execution_result_evaluation",
            "result": "failure_retryable"
        })
        return "failure_retryable", {}
    
    _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
        "stage": "execution_result_evaluation",
        "result": "unknown_status",
        "status": exec_status
    })
    return "none", {"present": True, "unknown_status": True}


def _evaluate_retry_eligibility(step: dict, workflow_id: str, step_id: str) -> tuple:
    """
    STAGE 3: Retry Eligibility Evaluation
    
    Determines if the step is eligible for retry based on retry count vs max retries.
    
    Returns:
        (eligible: bool, retry_info: dict)
        - eligible: True if retries < max_retries
        - retry_info: dict with retry_count, max_retries, risk_level
    """
    retries = step.get("retries", 0)
    risk = step.get("risk", "MEDIUM")
    max_retries = _get_risk_based_max_retries(risk)
    step["max_retries"] = max_retries  # Update step with risk-based limit
    
    eligible = retries < max_retries
    
    _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
        "stage": "retry_eligibility_evaluation",
        "eligible": eligible,
        "retry_count": retries,
        "max_retries": max_retries,
        "risk_level": risk
    })
    
    return eligible, {
        "retry_count": retries,
        "max_retries": max_retries,
        "risk_level": risk
    }


def _evaluate_retry_exhaustion(step: dict, workflow_id: str, step_id: str) -> tuple:
    """
    STAGE 4: Retry Exhaustion Evaluation
    
    Determines outcome when retries are exhausted.
    
    Returns:
        (action: str, reason: str, branch: str)
        - action: "escalate"
        - reason: detailed reason string
        - branch: branch identifier for trace
    """
    # Standard escalation path — retry exhausted, workflow blocked
    _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
        "stage": "retry_exhaustion_evaluation",
        "result": "escalate"
    })
    return "escalate", "max_retries_reached", "max_retries_escalate"


def _evaluate_completion_validity(step: dict, execution_result: dict, 
                                   validity_info: dict, workflow_id: str, step_id: str) -> tuple:
    """
    STAGE 5: Completion Validity Evaluation
    
    Determines if a successful execution can complete or needs retry.
    
    Returns:
        (can_complete: bool, completion_info: dict)
        - can_complete: True if purpose_met AND valid
        - completion_info: dict with purpose_met, valid, validity_reason
    """
    purpose_met = step.get("purpose_met", True)
    valid = validity_info.get("valid", False)
    validity_reason = validity_info.get("reason")
    
    can_complete = purpose_met and valid
    
    _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
        "stage": "completion_validity_evaluation",
        "can_complete": can_complete,
        "purpose_met": purpose_met,
        "valid": valid,
        "validity_reason": validity_reason
    })
    
    return can_complete, {
        "purpose_met": purpose_met,
        "valid": valid,
        "validity_reason": validity_reason
    }


def _finalize_governance_decision(action: str, reason: str, authority_source: str,
                                   step_id: str, workflow_id: str, branch: str,
                                   retry_count: int, execution_status: str,
                                   extra_metadata: dict = None,
                                   step: dict = None) -> GovernanceDecision:
    """
    FINAL STAGE: Governance Decision Finalization
    
    Creates the final GovernanceDecision through a single explicit path.
    
    Args:
        action: The governance action
        reason: Human-readable reason
        authority_source: Source of authority
        step_id: Step identifier
        workflow_id: Workflow identifier
        branch: Decision branch identifier
        retry_count: Current retry count
        execution_status: Execution status
        extra_metadata: Additional metadata dict
        step: The step dict (for constraint violation detection - Phase 2)
    
    Returns:
        GovernanceDecision: The finalized decision object
    """
    # Phase 2: Determine retry_strategy based on action AND constraint violations
    retry_strategy = RetryStrategy.SAME if action == "retry" else None
    
    # Phase 2: Check for constraint violations to authorize constraint-aware refinement
    if action == "retry" and step is not None:
        signals = step.get("_validator_signals", {}) or {}
        extracted_constraints = step.get("_extracted_constraints", {})
        constraint_ok = signals.get("constraint_ok", True)
        
        # If constraint violation detected and constraints present, use constraint-aware refinement
        if not constraint_ok and extracted_constraints:
            retry_strategy = RetryStrategy.CONSTRAINT_REFINED
            _structured_log("GOVERNANCE_CONSTRAINT_REFINEMENT", workflow_id, step_id, {
                "retry_strategy": retry_strategy,
                "constraint_ok": constraint_ok,
                "extracted_constraints": extracted_constraints,
                "signals": signals,
                "reason": "Constraint violation detected - authorizing constraint-aware refinement"
            })
    
    escalation_level = None
    if action in ("escalate", "fail"):
        escalation_level = "max_retries_reached" if "max_retries" in reason else "system_error"
    
    # Phase 3: Create RetryGuidance for retry decisions (metadata only)
    retry_guidance = None
    if action == "retry":
        # Determine rationale based on reason string
        rationale = "execution_failure"  # default
        if "purpose" in reason:
            rationale = "purpose_not_met"
        elif "invalid" in reason:
            rationale = "invalid_execution"
        elif "retry_" in reason:
            rationale = "execution_failure"
        
        retry_guidance = RetryGuidance(
            strategy=RetryStrategy.SAME,
            rationale=rationale,
            suggested_adjustment=None,  # Phase 3: placeholder for future
            metadata={"branch": branch, "retry_count": retry_count}
        )
        
        # Phase 5: Create RetryRemediation for retry decisions (metadata only, NEVER executable)
        retry_remediation = RetryRemediation(
            remediation_type="same_retry",  # Phase 5: deterministic placeholder only
            rationale=rationale,
            proposed_adjustment=None,  # Phase 5: placeholder for future phases
            metadata={"branch": branch, "retry_count": retry_count, "note": "metadata_only_not_executable"}
        )
    else:
        retry_remediation = None
    
    # Build metadata
    metadata = {
        "workflow_id": workflow_id,
        "step_id": step_id,
        "branch": branch,
        "retry_count": retry_count,
        "execution_status": execution_status
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    
    # Create final decision
    decision = GovernanceDecision(
        action=action,
        reason=reason,
        authority_source=authority_source,
        retry_strategy=retry_strategy,
        retry_guidance=retry_guidance,  # Phase 3: structured retry guidance
        retry_remediation=retry_remediation,  # Phase 5: structured retry remediation
        escalation_level=escalation_level,
        metadata=metadata
    )
    
    # Log final decision with retry remediation observability (Phase 5)
    _structured_log("GOVERNANCE_DECISION_FINALIZED", workflow_id, step_id, {
        "action": action,
        "reason": reason,
        "authority_source": authority_source,
        "branch": branch,
        "retry_strategy": retry_strategy,  # Phase 2: explicit retry strategy trace
        "retry_guidance": retry_guidance.to_dict() if retry_guidance else None,  # Phase 3: structured retry guidance
        "retry_remediation": retry_remediation.to_dict() if retry_remediation else None,  # Phase 5: structured retry remediation
        "retry_count": retry_count,
        "max_retries": extra_metadata.get("max_retries") if extra_metadata else None
    })
    
    # Emit live streaming event (observational only)
    if _event_emitter is not None:
        try:
            _event_emitter.emit_governance_decision(
                workflow_id=workflow_id,
                step_id=step_id,
                decision=action,
                reason=reason,
                execution_result_status=execution_status
            )
        except Exception:
            pass
    
    # === NOTIFICATION EMISSION (Phase 3C — OUTPUT ONLY) ===
    # Per AUTHORITY_MODEL: Notifications are OUTPUT ONLY — zero control impact
    try:
        from system.interface.notification_manager import (
            notify_governance_retry,
            notify_governance_escalation,
            notify_approval_required
        )
        _risk_level = extra_metadata.get("risk_level", "MEDIUM") if extra_metadata else "MEDIUM"
        
        if action == "retry":
            notify_governance_retry(step_id, workflow_id, retry_count + 1)
        elif action == "escalate":
            notify_governance_escalation(step_id, workflow_id, reason="max_retries_reached")
        elif action == "block":
            notify_approval_required(step_id, workflow_id, _risk_level, approval_id=None)
    except Exception:
        # FAILURE-ISOLATED: Notification failure MUST NOT affect execution
        pass
    
    return decision


# === END GOVERNANCE EVALUATION STAGE HELPERS ===


def is_execution_valid(execution_result, step):
    """
    Execution validity gate.

    Per HAND_ARCHITECTURE_V2 Section 4 STEP COMPLETION:
    A step is complete ONLY if: execution success AND purpose_met AND validation passed.

    This function enforces the structural validity of the execution result:
    - status must be "success"
    - result field must exist and not be None
    - a real tool execution must have occurred (executed_input recorded on step)

    Per SYSTEM_GOALS_V2 Section 4: if any condition fails, step is NOT complete.

    MUST NOT modify execution_result.
    MUST NOT use heuristics or LLM inference.
    MUST NOT bypass system_entry.

    Returns:
        (True, None) if valid
        (False, reason_str) if invalid
    """
    if execution_result is None:
        return False, "no_execution_result"

    if execution_result.get("status") != "success":
        return False, "tool_failure"

    if "result" not in execution_result:
        return False, "missing_result"

    if execution_result.get("result") is None:
        return False, "missing_result"

    # A real tool execution MUST have been recorded.
    # Per HAND_ARCHITECTURE_V2 Section 17: all execution goes through system_entry.
    # step["executed_input"] is set by agent_executor only when system_entry ran.
    # If it is absent or empty, no real tool execution occurred.
    if not step.get("executed_input"):
        return False, "no_tool_execution"

    return True, None


def resolve_decision(validator_output, execution_result, context):
    """
    Determine final output based on execution truth.
    SINGLE SOURCE: execution_result only
    """

    # SINGLE SOURCE — execution_result only
    if execution_result is not None:
        return execution_result

    # DEFAULT — no result
    return None


def _get_risk_based_max_retries(risk_level: str) -> int:
    """Return max retries based on risk level per GOVERNANCE_CONTRACT."""
    risk_limits = {
        "LOW": 5,
        "MEDIUM": 3,
        "HIGH": 1
    }
    return risk_limits.get(risk_level, 2)


def _check_approval_required(step: dict, context: dict) -> bool:
    """Check if approval is required for this step."""
    # Placeholder: approval_required flag from classification or step
    if step.get("approval_required"):
        return True
    if context.get("approval_required"):
        return True
    # HIGH risk steps may require approval
    if step.get("risk") == "HIGH" and step.get("importance") == "HIGH":
        return True
    return False


def _evaluate_user_control_for_retry(
    step: dict,
    workflow_id: str,
    step_id: str,
) -> Optional[Any]:
    """
    ISSUE-098E: Check for an accepted `continue_after_warning` user-control request.

    Validates:
    - Request is ACCEPTED and action is exactly "continue_after_warning".
    - execution_generation matches current workflow state (if present on request).
    - retry_generation matches current step state (if present on request).
    - Step is NOT blocked for approval_required (hard block).
    - Workflow is NOT in a terminal state (COMPLETED / FAILED / CANCELLED).

    Does NOT check retry eligibility — caller must verify with
    _evaluate_retry_eligibility().  Per 098E constraints, user-control
    may only authorize the existing legal "retry" outcome when retry is
    already legal.

    Returns:
        The validated UserControlRequest object, or None.
    """
    try:
        from system.orchestrator.user_control import (
            get_accepted_continue_after_warning_for_step,
            _validate_stale_generations,
        )
    except Exception:
        return None

    request = get_accepted_continue_after_warning_for_step(workflow_id, step_id)
    if request is None:
        return None

    # Stale generation validation
    current_exec_gen = None
    current_retry_gen = step.get("_retry_generation")
    try:
        from system.orchestrator.workflow_control import _get_workflow_state
        wf_state = _get_workflow_state(workflow_id)
        if wf_state:
            current_exec_gen = wf_state.get("execution_generation")
    except Exception:
        pass

    stale_check = _validate_stale_generations(
        request,
        current_execution_generation=current_exec_gen,
        current_retry_generation=current_retry_gen,
    )
    if not stale_check["valid"]:
        return None

    # Hard approval block check — user-control must never bypass approval
    if step.get("blocked_reason") == "approval_required":
        return None

    # Terminal workflow check
    try:
        from system.orchestrator.workflow_control import _get_workflow_state
        wf_state = _get_workflow_state(workflow_id)
        if wf_state and wf_state.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
            return None
    except Exception:
        pass

    return request


def decide_next_action(validator_output, execution_result, step, context, memory_confidence=None):
    """
    Determines next action for a step.

    AUTHORITY: execution_result is the PRIMARY decision driver.

    Validator signals are advisory only and MUST NOT influence control flow.
    All retry and completion decisions are based solely on execution_result.

    Args:
        validator_output: Advisory validator output (NEVER used in decisions)
        execution_result: PRIMARY authority — sole basis for decisions
        step: The step dict (may be updated with advisory metadata)
        context: Workflow context dict
        memory_confidence: Optional advisory confidence from global memory
            (Phase 3A — MUST NOT change decision logic, MUST NOT trigger retry,
             MUST NOT override execution_result. Stored as metadata ONLY.)

    Returns:
        GovernanceDecision — structured decision object with action, reason, authority_source,
        retry_strategy, escalation_level, validator_advisory, confidence_context, and metadata.
        Backward compatible: decision.action contains former string values ("retry", "complete",
        "fail", "block", "escalate"), and decision == "retry" works as expected.

    Decision semantics (GOVERNANCE_CONTRACT):
        retry     — execution failed, retries remain
        block     — approval required before execution
        escalate  — execution failed, max retries reached
        complete  — execution succeeded AND purpose_met (signals are advisory only)
        fail      — execution_result missing (system error only)
    """
    # === NORMALIZED GOVERNANCE PIPELINE (Phase 1B) ===
    # Extract context information
    workflow_id = context.get("workflow_id", "unknown") if context else "unknown"
    step_id = step.get("id", "unknown")
    retry_count = step.get("retries", 0)

    # RUNTIME TRACE: Governance pipeline entry
    _structured_log("GOVERNANCE_ENTRY", workflow_id, step_id, {
        "execution_result": execution_result,
        "execution_status": execution_result.get("status") if execution_result else None,
        "validator_output": validator_output,
        "retry_count": retry_count,
        "purpose_met": step.get("purpose_met", True),
        "validator_signals": step.get("_validator_signals"),
        "validator_decision": step.get("_validator_decision")
    })
    
    # === STAGE 1: APPROVAL EVALUATION ===
    is_blocked, approval_decision = _evaluate_approval(step, context or {}, workflow_id, step_id)
    if is_blocked:
        return approval_decision

    # === PHASE 4: GOVERNANCE CONTEXT NORMALIZATION ===
    # Create immutable snapshot of ALL governance inputs
    gov_context = _create_governance_context(
        execution_result=execution_result,
        step=step,
        context=context,
        validator_output=validator_output,
        retry_guidance=None  # Fresh evaluation — no prior guidance
    )
    
    # RUNTIME TRACE: Governance context snapshot (observational only)
    _structured_log("GOVERNANCE_CONTEXT_SNAPSHOT", workflow_id, step_id, {
        "governance_context": gov_context.to_dict(),  # Phase 4: explicit context observability
        "snapshot_boundary": "post_approval_pre_evaluation"
    })

    # === ADVISORY SIGNALS (metadata only, NO decision influence) ===
    if validator_output:
        step["_validator_advisory"] = validator_output.get("reason")
        step["_validator_decision"] = validator_output.get("recommendation")
        step["_validator_signals"] = validator_output.get("signals")

    # === MEMORY CONFIDENCE (advisory metadata only — Phase 3A) ===
    # Per MEMORY_STORAGE_CONTRACT_V1: memory MUST NOT change decision outputs
    # Per AUTHORITY_MODEL: execution_result remains sole truth
    # Stored as step metadata for trace/observability ONLY — zero control impact
    if memory_confidence is not None:
        try:
            step["_memory_confidence"] = float(memory_confidence)
        except Exception:
            pass

    if step.get("mismatch") is True:
        step["_mismatch_advisory"] = True

    # === STAGE 2: EXECUTION RESULT EVALUATION ===
    exec_status, validity_info = _evaluate_execution_result(execution_result, step, workflow_id, step_id)
    
    # === STAGE 3+: BRANCH BASED ON EXECUTION STATUS ===
    
    # Branch: No execution result
    if exec_status == "none":
        return _finalize_governance_decision(
            action="fail",
            reason="no_execution_result",
            authority_source="system",
            step_id=step_id,
            workflow_id=workflow_id,
            branch="no_execution_result",
            retry_count=retry_count,
            execution_status="none",
            step=step
        )
    
    # Branch: Fail-fast schema violation
    if exec_status == "failure_fail_fast":
        from system.orchestrator.workflow_control import request_step_transition as _rst_gv
        _rst_gv(step, "FAILED", "schema_violation", _internal=True)
        fail_reason = validity_info.get("fail_reason", "")
        return _finalize_governance_decision(
            action="fail",
            reason="schema_violation",
            authority_source="execution_result",
            step_id=step_id,
            workflow_id=workflow_id,
            branch="fail_fast_schema",
            retry_count=retry_count,
            execution_status="failure",
            extra_metadata={"fail_reason": fail_reason},
            step=step
        )
    
    # Branch: Failure with retry evaluation
    if exec_status == "failure_retryable":
        # === STAGE 3: RETRY ELIGIBILITY EVALUATION ===
        eligible, retry_info = _evaluate_retry_eligibility(step, workflow_id, step_id)
        
        # === ISSUE-098E: USER-CONTROL RETRY AUTHORIZATION ===
        # Check for accepted continue_after_warning request.
        # Only consumed when retry is already legal (eligible=True).
        # Structural integration for future advisory escalation branches.
        user_control = _evaluate_user_control_for_retry(step, workflow_id, step_id)
        
        if eligible:
            if user_control:
                try:
                    from system.orchestrator.user_control import record_user_control_applied
                    record_user_control_applied(
                        request=user_control,
                        original_decision="retry",
                        backend_decision="retry",
                    )
                except Exception:
                    pass
            # Can retry
            return _finalize_governance_decision(
                action="retry",
                reason=f"retry_{retry_info['retry_count'] + 1}_of_{retry_info['max_retries']}",
                authority_source="execution_result",
                step_id=step_id,
                workflow_id=workflow_id,
                branch="execution_failure_retry",
                retry_count=retry_count,
                execution_status="failure",
                extra_metadata=retry_info,
                step=step
            )
        else:
            # === STAGE 4: RETRY EXHAUSTION EVALUATION ===
            action, reason, branch = _evaluate_retry_exhaustion(step, workflow_id, step_id)
            return _finalize_governance_decision(
                action=action,
                reason=reason,
                authority_source="execution_result",
                step_id=step_id,
                workflow_id=workflow_id,
                branch=branch,
                retry_count=retry_info['retry_count'],
                execution_status="failure",
                extra_metadata=retry_info,
                step=step
            )
    
    # Branch: Success with completion validity evaluation
    if exec_status == "success":
        # === PHASE 2A: NARROW FALSE-SUCCESS GOVERNANCE INPUT ===
        # Per PDIAG-005 Phase 2A SA approval: unresolved_placeholder and
        # instruction_echo_output may set purpose_met=False.
        # All other warning codes remain advisory-only (Phase 1).
        # This check is deterministic, regex/structural only, and fail-safe.
        # It does NOT mutate lifecycle state directly; it only sets step
        # metadata so that the existing _evaluate_completion_validity()
        # gate naturally produces RETRY or ESCALATE.
        #
        # FOUNDATION-RETOUCH-001 FIX: Skip Phase-2A for raw acquisition tools
        # (read_file, read_webpage, web_search, list_files) because their
        # output is literal external/source content, which may legitimately
        # contain template syntax, TODO markers, or other patterns that
        # look like false-success signals. Synthesis/finalization steps
        # (e.g. finalize_output) continue to be checked normally.
        _step_tool_name = _get_step_tool_name(step)
        _is_raw_acquisition = _step_tool_name in _PHASE2A_RAW_ACQUISITION_TOOLS
        if not _is_raw_acquisition:
            try:
                from system.orchestrator.false_success_detector import compute_step_governance_input
                fs_input = compute_step_governance_input(step, context)
                if fs_input.get("false_success_detected"):
                    step["purpose_met"] = False
                    step["_false_success_reason"] = fs_input.get("governance_reason")
                    step["_false_success_evidence"] = fs_input.get("evidence")
                    _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
                        "stage": "phase2a_false_success_detected",
                        "governance_reason": fs_input.get("governance_reason"),
                        "evidence": fs_input.get("evidence"),
                        "scope": "step",
                    })
            except Exception:
                # Fail-safe: never let Phase 2A detection crash governance
                pass
        else:
            _structured_log("GOVERNANCE_STAGE", workflow_id, step_id, {
                "stage": "phase2a_skipped_raw_acquisition",
                "tool_name": _step_tool_name,
                "reason": "raw_acquisition_tool_exempt_from_phase2a",
            })

        # === STAGE 5: COMPLETION VALIDITY EVALUATION ===
        can_complete, completion_info = _evaluate_completion_validity(
            step, execution_result, validity_info, workflow_id, step_id
        )
        
        if can_complete:
            # Can complete
            return _finalize_governance_decision(
                action="complete",
                reason="purpose_met_and_execution_valid",
                authority_source="execution_result",
                step_id=step_id,
                workflow_id=workflow_id,
                branch="success_complete",
                retry_count=retry_count,
                execution_status="success",
                extra_metadata=completion_info,
                step=step
            )
        else:
            # Cannot complete — treat as retry-able failure
            # === STAGE 3 (again): RETRY ELIGIBILITY EVALUATION ===
            eligible, retry_info = _evaluate_retry_eligibility(step, workflow_id, step_id)
            
            # === ISSUE-098E: USER-CONTROL RETRY AUTHORIZATION ===
            user_control = _evaluate_user_control_for_retry(step, workflow_id, step_id)
            
            if eligible:
                if user_control:
                    try:
                        from system.orchestrator.user_control import record_user_control_applied
                        record_user_control_applied(
                            request=user_control,
                            original_decision="retry",
                            backend_decision="retry",
                        )
                    except Exception:
                        pass
                # Can retry on invalid completion
                reason = "purpose_not_met_or_invalid" if not completion_info['purpose_met'] else f"invalid_execution_{completion_info['validity_reason']}"
                branch = "success_but_purpose_not_met" if not completion_info['purpose_met'] else "success_but_invalid"
                
                return _finalize_governance_decision(
                    action="retry",
                    reason=reason,
                    authority_source="execution_result",
                    step_id=step_id,
                    workflow_id=workflow_id,
                    branch=branch,
                    retry_count=retry_count,
                    execution_status="success",
                    extra_metadata={**completion_info, **retry_info},
                    step=step
                )
            else:
                # Max retries reached on invalid completion
                return _finalize_governance_decision(
                    action="escalate",
                    reason="max_retries_reached",
                    authority_source="execution_result",
                    step_id=step_id,
                    workflow_id=workflow_id,
                    branch="success_exhausted",
                    retry_count=retry_count,
                    execution_status="success",
                    extra_metadata={**completion_info, **retry_info},
                    step=step
                )
    
    # Fallback: Unknown status
    return _finalize_governance_decision(
        action="fail",
        reason="unknown_execution_status",
        authority_source="system",
        step_id=step_id,
        workflow_id=workflow_id,
        branch="unknown_status",
        retry_count=retry_count,
        execution_status="unknown",
        step=step
    )


def replay_governance_decision(gov_context: GovernanceContext) -> GovernanceDecision:
    """
    Replay governance decision from immutable GovernanceContext snapshot.
    
    Per GOVERNANCE REPLAY VALIDATION Phase 6:
    - Deterministic replay validation only
    - MUST reuse existing governance pipeline
    - MUST NOT fork governance logic
    - MUST NOT introduce alternate evaluation paths
    - MUST NOT mutate runtime state
    - Replay validation only — NO lifecycle mutation
    
    Purpose:
    - Validate deterministic governance replayability
    - Prove same GovernanceContext → same GovernanceDecision
    - Enable replay testing without runtime side effects
    
    Architecture compliance:
    - execution_result remains sole execution truth
    - governance remains sole decision authority
    - replay remains validation-only (no mutation)
    
    Args:
        gov_context: Immutable GovernanceContext snapshot from prior evaluation
    
    Returns:
        GovernanceDecision: Deterministic decision (should match original)
    
    Example:
        # Capture context during runtime
        context = _create_governance_context(...)
        decision1 = decide_next_action(...)
        
        # Replay for validation
        decision2 = replay_governance_decision(context)
        assert decision1 == decision2  # Deterministic proof
    """
    # === REPLAY VALIDATION BOUNDARY ===
    # Log replay mode for observability (metadata only)
    _structured_log("GOVERNANCE_REPLAY_ENTRY", gov_context.workflow_id, gov_context.step_id, {
        "replay_mode": True,
        "governance_context": gov_context.to_dict()
    })
    
    # === DETERMINISTIC REPLAY ===
    # Reconstruct step dict from context (minimal, deterministic only)
    replay_step = {
        "id": gov_context.step_id,
        "status": gov_context.step_state or "ACTIVE",
        "retries": gov_context.retry_count,
        "max_retries": gov_context.max_retries,
        "risk": gov_context.metadata.get("risk_level", "MEDIUM"),
        "purpose_met": gov_context.metadata.get("purpose_met", True),
        "executed_input": gov_context.metadata.get("executed_input")
    }
    
    # Reconstruct minimal context
    replay_context = {"workflow_id": gov_context.workflow_id}
    
    # Replay using EXACT same pipeline as runtime
    # This proves determinism: same context → same decision
    replay_decision = decide_next_action(
        validator_output=gov_context.validator_result,
        execution_result=gov_context.execution_result,
        step=replay_step,
        context=replay_context,
        memory_confidence=None  # Not captured in GovernanceContext
    )
    
    # === REPLAY VALIDATION COMPLETE ===
    # Log replay result for observability (metadata only)
    _structured_log("GOVERNANCE_REPLAY_COMPLETE", gov_context.workflow_id, gov_context.step_id, {
        "replay_mode": True,
        "replay_validation": "deterministic_replay_executed",
        "decision_action": replay_decision.action,
        "decision_reason": replay_decision.reason
    })
    
    return replay_decision

"""Capability Router — Deterministic pre-planner gate.

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 9:
- Consume user prompt and task classification result
- Evaluate registered capabilities
- Select at most one initial route in Phase 1
- Return route decision + fallback decision
- Call capability only after route accepted

Phase 1 limitation:
- At most one capability normalizer/compiler invoked per prompt.
- No autonomous multi-capability coordination.
"""

from typing import Any, Optional

from system.orchestrator.capability_registry import get_capability
from system.orchestrator.profile_selector import capability_to_profile
from system.orchestrator.capabilities.arithmetic_capability import compile_arithmetic_workflow
from system.orchestrator.capabilities.document_local_read_capability import (
    compile_document_local_read_workflow,
    detect_document_local_read_fallback_reason,
    is_document_local_prompt,
)
from system.orchestrator.capabilities.web_read_capability import (
    compile_web_read_workflow,
    detect_web_read_fallback_reason,
    is_web_prompt,
)
from system.orchestrator.capabilities.structured_data_analysis_capability import (
    compile_structured_data_analysis_workflow,
    is_structured_data_analysis_intent,
)


def _normalize_route_metadata(
    route_attempted: bool = True,
    route_decision: str = None,
    capability_id: str = None,
    route_confidence: float = 0.0,
    route_reason_code: str = None,
    fallback_reason: str = None,
    candidate_workflow_emitted: bool = False,
    compiler_repairs_applied: str = None,
    compiler_handoff_status: str = None,
    validator_result: str = None,
    validator_handoff_status: str = None,
    runtime_handoff_status: str = None,
    error: str = None,
) -> dict:
    """
    Build a standardized, debug-only route metadata dict.

    Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 14:
    - Non-authoritative, observational only.
    - Must not influence routing, validation, lifecycle, governance, execution,
      retries, projection, or learning.
    """
    meta = {
        "route_attempted": route_attempted,
        "route_decision": route_decision,
        "capability_id": capability_id,
        "route_confidence": route_confidence,
        "route_reason_code": route_reason_code,
        "fallback_reason": fallback_reason,
        "candidate_workflow_emitted": candidate_workflow_emitted,
        "compiler_repairs_applied": compiler_repairs_applied or "not_recorded",
        "compiler_handoff_status": compiler_handoff_status or "not_applicable",
        "validator_result": validator_result or "not_applicable",
        "validator_handoff_status": validator_handoff_status or "not_applicable",
        "runtime_handoff_status": runtime_handoff_status or "not_applicable",
    }
    if error is not None:
        meta["error"] = str(error)[:500]
    return meta


def route_capability(user_input: str, classification: dict | None = None) -> dict:
    """
    Evaluate user prompt against registered capabilities and return route decision.

    Args:
        user_input: Raw user input string.
        classification: Task classification dict (advisory only).

    Returns:
        Route result dict with keys:
          - route_decision: ROUTE_ACCEPTED | ROUTE_FALLBACK_TO_PLANNER | ROUTE_BLOCKED_UNSAFE | ROUTE_ERROR
          - capability_id: str | None
          - route_confidence: float
          - route_reason_code: str
          - fallback_reason: str | None
          - candidate_workflow: dict | None
          - route_metadata: dict
    """
    # Default fallback result
    fallback_result = {
        "route_decision": "ROUTE_FALLBACK_TO_PLANNER",
        "capability_id": None,
        "route_confidence": 0.0,
        "route_reason_code": "no_matching_capability",
        "fallback_reason": "no_matching_capability",
        "candidate_workflow": None,
        "recommended_profile": None,
        "route_metadata": _normalize_route_metadata(
            route_decision="ROUTE_FALLBACK_TO_PLANNER",
            route_reason_code="no_matching_capability",
            fallback_reason="no_matching_capability",
        ),
    }

    if not user_input or not isinstance(user_input, str):
        fallback_result["fallback_reason"] = "empty_user_input"
        fallback_result["route_reason_code"] = "empty_user_input"
        fallback_result["recommended_profile"] = None
        fallback_result["route_metadata"] = _normalize_route_metadata(
            route_decision="ROUTE_FALLBACK_TO_PLANNER",
            route_reason_code="empty_user_input",
            fallback_reason="empty_user_input",
        )
        return fallback_result

    # === Phase 1: At most one capability per prompt ===
    # Evaluate arithmetic first (existing behavior), then document_local_read on fallback.
    arithmetic_meta = get_capability("arithmetic")
    document_meta = get_capability("document_local_read")

    # === Attempt arithmetic route ===
    if arithmetic_meta:
        try:
            candidate_workflow = compile_arithmetic_workflow(user_input)
        except Exception as e:
            # Fail-safe: any exception in capability compilation falls back to planner
            fallback_result["route_decision"] = "ROUTE_ERROR"
            fallback_result["fallback_reason"] = f"arithmetic_compilation_error:{str(e)}"
            fallback_result["route_reason_code"] = "arithmetic_compilation_error"
            fallback_result["route_metadata"] = _normalize_route_metadata(
                route_decision="ROUTE_ERROR",
                route_reason_code="arithmetic_compilation_error",
                fallback_reason=f"arithmetic_compilation_error:{str(e)}",
                error=str(e),
            )
            return fallback_result

        if candidate_workflow is not None:
            # === ROUTE_ACCEPTED (arithmetic) ===
            return {
                "route_decision": "ROUTE_ACCEPTED",
                "capability_id": "arithmetic",
                "route_confidence": 1.0,
                "route_reason_code": "pure_arithmetic_chain",
                "fallback_reason": None,
                "candidate_workflow": candidate_workflow,
                "recommended_profile": capability_to_profile("arithmetic"),
                "route_metadata": _normalize_route_metadata(
                    route_decision="ROUTE_ACCEPTED",
                    capability_id="arithmetic",
                    route_confidence=1.0,
                    route_reason_code="pure_arithmetic_chain",
                    candidate_workflow_emitted=True,
                ),
            }

    # === Attempt structured_data_analysis route (arithmetic already fell back) ===
    structured_meta = get_capability("structured_data_analysis")
    if structured_meta:
        try:
            candidate_workflow = compile_structured_data_analysis_workflow(user_input)
        except Exception as e:
            fallback_result["route_decision"] = "ROUTE_ERROR"
            fallback_result["fallback_reason"] = f"structured_data_analysis_compilation_error:{str(e)}"
            fallback_result["route_reason_code"] = "structured_data_analysis_compilation_error"
            fallback_result["route_metadata"] = _normalize_route_metadata(
                route_decision="ROUTE_ERROR",
                route_reason_code="structured_data_analysis_compilation_error",
                fallback_reason=f"structured_data_analysis_compilation_error:{str(e)}",
                error=str(e),
            )
            return fallback_result

        if candidate_workflow is not None:
            return {
                "route_decision": "ROUTE_ACCEPTED",
                "capability_id": "structured_data_analysis",
                "route_confidence": 1.0,
                "route_reason_code": "accepted_structured_data_analysis",
                "fallback_reason": None,
                "candidate_workflow": candidate_workflow,
                "recommended_profile": capability_to_profile("structured_data_analysis"),
                "route_metadata": _normalize_route_metadata(
                    route_decision="ROUTE_ACCEPTED",
                    capability_id="structured_data_analysis",
                    route_confidence=1.0,
                    route_reason_code="accepted_structured_data_analysis",
                    candidate_workflow_emitted=True,
                ),
            }

        # Non-trivial structured-data requests are owned by Planner/AG1.
        # The capability only validates and lowers; it does not perform composed
        # natural-language interpretation.
        if is_structured_data_analysis_intent(user_input):
            _sd_profile = capability_to_profile("structured_data_analysis")
            fallback_result["route_decision"] = "ROUTE_FALLBACK_TO_PLANNER"
            fallback_result["fallback_reason"] = "structured_data_analysis_requires_planner"
            fallback_result["route_reason_code"] = "structured_data_analysis_requires_planner"
            fallback_result["recommended_profile"] = _sd_profile
            fallback_result["route_metadata"] = _normalize_route_metadata(
                route_decision="ROUTE_FALLBACK_TO_PLANNER",
                route_reason_code="structured_data_analysis_requires_planner",
                fallback_reason="structured_data_analysis_requires_planner",
            )
            return fallback_result

    # === Attempt document_local_read route (arithmetic and structured_data_analysis fell back) ===
    if document_meta:
        try:
            candidate_workflow = compile_document_local_read_workflow(user_input)
        except Exception as e:
            fallback_result["route_decision"] = "ROUTE_ERROR"
            fallback_result["fallback_reason"] = f"document_local_read_compilation_error:{str(e)}"
            fallback_result["route_reason_code"] = "document_local_read_compilation_error"
            fallback_result["route_metadata"] = _normalize_route_metadata(
                route_decision="ROUTE_ERROR",
                route_reason_code="document_local_read_compilation_error",
                fallback_reason=f"document_local_read_compilation_error:{str(e)}",
                error=str(e),
            )
            return fallback_result

        if candidate_workflow is not None:
            # Determine reason code from workflow steps
            route_reason_code = "accepted_explicit_read_file"
            steps = candidate_workflow.get("steps", [])
            if steps:
                first_step_meta = steps[0].get("capability_metadata", {})
                route_reason_code = first_step_meta.get("route_reason_code", route_reason_code)

            # TOOL_PROFILE_GATING_CONTRACT_V1 §4: Recommend DocumentSummaryProfile
            # when the compiled workflow includes semantic_transform steps.
            _doc_profile = capability_to_profile("document_local_read")
            for _step in steps:
                _step_meta = _step.get("capability_metadata", {})
                if _step_meta.get("transform_required") is True:
                    _doc_profile = "DocumentSummaryProfile"
                    break

            if route_reason_code == "unsupported_spreadsheet_analysis":
                _doc_profile = "GeneralFallbackProfile"

            return {
                "route_decision": "ROUTE_ACCEPTED",
                "capability_id": "document_local_read",
                "route_confidence": 1.0,
                "route_reason_code": route_reason_code,
                "fallback_reason": None,
                "candidate_workflow": candidate_workflow,
                "recommended_profile": _doc_profile,
                "route_metadata": _normalize_route_metadata(
                    route_decision="ROUTE_ACCEPTED",
                    capability_id="document_local_read",
                    route_confidence=1.0,
                    route_reason_code=route_reason_code,
                    candidate_workflow_emitted=True,
                ),
            }

        # Local-file prompt but not accepted — use file-specific fallback reason code
        if is_document_local_prompt(user_input):
            doc_fallback_reason = detect_document_local_read_fallback_reason(user_input)
            fallback_result["route_decision"] = "ROUTE_FALLBACK_TO_PLANNER"
            fallback_result["fallback_reason"] = doc_fallback_reason
            fallback_result["route_reason_code"] = doc_fallback_reason
            fallback_result["route_metadata"] = _normalize_route_metadata(
                route_decision="ROUTE_FALLBACK_TO_PLANNER",
                route_reason_code=doc_fallback_reason,
                fallback_reason=doc_fallback_reason,
            )
            return fallback_result

    # === Attempt web_read route (arithmetic and document_local_read already fell back) ===
    web_read_meta = get_capability("web_read")
    if web_read_meta:
        try:
            candidate_workflow = compile_web_read_workflow(user_input)
        except Exception as e:
            fallback_result["route_decision"] = "ROUTE_ERROR"
            fallback_result["fallback_reason"] = f"web_read_compilation_error:{str(e)}"
            fallback_result["route_reason_code"] = "web_read_compilation_error"
            fallback_result["route_metadata"] = _normalize_route_metadata(
                route_decision="ROUTE_ERROR",
                route_reason_code="web_read_compilation_error",
                fallback_reason=f"web_read_compilation_error:{str(e)}",
                error=str(e),
            )
            return fallback_result

        if candidate_workflow is not None:
            route_reason_code = "accepted_explicit_url_read"
            steps = candidate_workflow.get("steps", [])
            if steps:
                first_step_meta = steps[0].get("capability_metadata", {})
                route_reason_code = first_step_meta.get("route_reason_code", route_reason_code)
            return {
                "route_decision": "ROUTE_ACCEPTED",
                "capability_id": "web_read",
                "route_confidence": 1.0,
                "route_reason_code": route_reason_code,
                "fallback_reason": None,
                "candidate_workflow": candidate_workflow,
                "recommended_profile": capability_to_profile("web_read"),
                "route_metadata": _normalize_route_metadata(
                    route_decision="ROUTE_ACCEPTED",
                    capability_id="web_read",
                    route_confidence=1.0,
                    route_reason_code=route_reason_code,
                    candidate_workflow_emitted=True,
                ),
            }

        # Web prompt but not accepted — use web-specific fallback reason code
        if is_web_prompt(user_input):
            web_fallback_reason = detect_web_read_fallback_reason(user_input)
            fallback_result["route_decision"] = "ROUTE_FALLBACK_TO_PLANNER"
            fallback_result["fallback_reason"] = web_fallback_reason
            fallback_result["route_reason_code"] = web_fallback_reason
            fallback_result["route_metadata"] = _normalize_route_metadata(
                route_decision="ROUTE_FALLBACK_TO_PLANNER",
                route_reason_code=web_fallback_reason,
                fallback_reason=web_fallback_reason,
            )
            return fallback_result

    # === No matching capability ===
    if not arithmetic_meta:
        fallback_result["fallback_reason"] = "arithmetic_not_registered"
        fallback_result["route_reason_code"] = "arithmetic_not_registered"
    elif not structured_meta:
        fallback_result["fallback_reason"] = "structured_data_analysis_not_registered"
        fallback_result["route_reason_code"] = "structured_data_analysis_not_registered"
    elif not document_meta:
        fallback_result["fallback_reason"] = "document_local_read_not_registered"
        fallback_result["route_reason_code"] = "document_local_read_not_registered"
    elif not web_read_meta:
        fallback_result["fallback_reason"] = "web_read_not_registered"
        fallback_result["route_reason_code"] = "web_read_not_registered"
    else:
        fallback_result["fallback_reason"] = "no_matching_capability"
        fallback_result["route_reason_code"] = "no_matching_capability"

    fallback_result["route_metadata"] = _normalize_route_metadata(
        route_decision="ROUTE_FALLBACK_TO_PLANNER",
        route_reason_code=fallback_result["route_reason_code"],
        fallback_reason=fallback_result["fallback_reason"],
    )
    return fallback_result

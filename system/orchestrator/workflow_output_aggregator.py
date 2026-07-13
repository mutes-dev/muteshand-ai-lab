"""
Workflow Output Aggregator
ISSUE-PDIAG-004 — Workflow Output Aggregation / Final Result Assembly

Pure deterministic helper for computing structured workflow-level output
aggregation from existing step states. Does NOT execute tools, call LLMs,
mutate execution_result, or decide lifecycle state.

Architecture rules preserved:
- runtime registry remains lifecycle authority
- governance remains retry/failure/escalation authority
- system_entry remains sole tool execution gateway
- execution_result remains execution truth
- projection/frontend remain non-authoritative
- persistence remains downstream/non-authoritative
"""

from typing import Any, Dict, List, Optional, Set

from system.orchestrator.false_success_detector import evaluate_false_success

# Conservative synthesis keyword hints for display metadata only.
# These MUST NOT affect lifecycle, governance, retry, or success determination.
_SYNTHESIS_KEYWORDS = {
    "summarize", "summary", "combine", "aggregate", "synthesize", "synthesis",
    "final answer", "final output", "report", "brief", "compare",
    "recommendation", "consolidate", "merge", "list both results",
    "use all previous results", "create final output", "write summary from sources",
}


def _has_synthesis_hint(step: Dict[str, Any]) -> bool:
    """
    Conservative synthesis detection using structural signals + keyword hints.
    Default is False when uncertain. This is a DISPLAY HINT ONLY.
    """
    purpose = (step.get("purpose") or "").lower()
    expected_outcome = (step.get("expected_outcome") or "").lower()
    step_type = (step.get("type") or "").lower()
    combined_text = f"{purpose} {expected_outcome} {step_type}"

    keyword_match = any(kw in combined_text for kw in _SYNTHESIS_KEYWORDS)
    if not keyword_match:
        return False

    # Structural signal: terminal successful step with multiple source dependencies
    depends_on = step.get("depends_on") or []
    if len(depends_on) >= 2:
        return True

    # Structural signal: terminal successful step depending on prior steps
    # when purpose/expected_outcome contains synthesis keywords
    if depends_on and keyword_match:
        return True

    # If only keyword matches but no multi-dependency, remain conservative
    return False


def _compute_dependent_step_ids(steps: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Build reverse dependency map: step_id -> list of step_ids that depend on it."""
    dependent_map: Dict[str, List[str]] = {}
    for step in steps:
        step_id = step.get("id")
        if not step_id:
            continue
        for dep in step.get("depends_on", []):
            dependent_map.setdefault(dep, []).append(step_id)
    return dependent_map


def _is_terminal_success_output(
    step: Dict[str, Any], dependent_map: Dict[str, List[str]], successful_ids: Set[str]
) -> bool:
    """
    A successful completed step is terminal if no OTHER successful completed
    step depends on it.
    """
    step_id = step.get("id")
    if not step_id:
        return False

    dependents = dependent_map.get(step_id, [])
    # Terminal if none of its dependents are successful completed steps
    for dep_id in dependents:
        if dep_id in successful_ids:
            return False
    return True


def _build_web_metadata_summary(workflow: Dict[str, Any]) -> tuple:
    """
    Build deterministic, additive source/privacy metadata summaries from web tool evidence.

    Does NOT:
    - call LLMs or external APIs
    - change execution_result or lifecycle state
    - invent cost/spend values
    - enforce privacy/spend/source policy gates
    """
    steps = workflow.get("steps", []) or []
    evidence_ref_ids: List[str] = []
    sources: List[Dict[str, Any]] = []
    source_domains: Set[str] = set()
    privacy_classifications: Set[str] = set()
    provider_hosts: Set[str] = set()
    tools: Set[str] = set()
    query_count = 0
    read_count = 0
    external_call_count = 0
    source_quality_status = {
        "unknown": 0,
        "blocked": 0,
        "inaccessible": 0,
        "retrieved": 0,
    }

    for step in steps:
        if not isinstance(step, dict):
            continue
        for ref in step.get("evidence_refs", []) or []:
            if not isinstance(ref, dict):
                continue
            tool_name = ref.get("tool_name")
            if tool_name not in ("web_search", "read_webpage"):
                continue
            evidence_ref_ids.append(ref.get("ref_id"))
            tools.add(tool_name)
            external_call_count += 1
            if tool_name == "web_search":
                query_count += 1
            elif tool_name == "read_webpage":
                read_count += 1
            domain = ref.get("source_domain") or ref.get("provider_host")
            if domain:
                source_domains.add(domain)
            privacy = ref.get("privacy_classification")
            if privacy:
                privacy_classifications.add(privacy)
            provider_host = ref.get("provider_host") or ref.get("source_domain")
            if provider_host:
                provider_hosts.add(provider_host)
            sources.append({
                "ref_id": ref.get("ref_id"),
                "tool_name": tool_name,
                "source_type": ref.get("source_type"),
                "query": ref.get("query"),
                "url": ref.get("url") or ref.get("requested_url"),
                "source_domain": domain,
                "outcome_kind": ref.get("outcome_kind"),
                "evidence_status": ref.get("evidence_status"),
            })
            status = ref.get("evidence_status")
            if status == "source_read":
                source_quality_status["retrieved"] += 1
            elif status == "blocked":
                source_quality_status["blocked"] += 1
            elif status == "failed_fetch":
                source_quality_status["inaccessible"] += 1
            else:
                source_quality_status["unknown"] += 1

    source_summary = {
        "source_count": len(sources),
        "sources_used": sources,
        "source_domains": sorted(source_domains),
        "evidence_refs": evidence_ref_ids,
        "tools": sorted(tools),
        "query_count": query_count,
        "read_count": read_count,
    }

    privacy_summary = {
        "privacy_classifications": sorted(privacy_classifications),
        "external_call_count": external_call_count,
        "external_search_count": query_count,
        "external_url_fetch_count": read_count,
        "provider_hosts": sorted(provider_hosts),
        "source_quality_status": source_quality_status,
    }

    return source_summary, privacy_summary


def aggregate_workflow_output(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute structured workflow output aggregation from existing step truth.

    Input: workflow dict after execution (steps have final status/execution_result)
    Output: deterministic aggregation payload (read-only, additive field)

    Does NOT:
    - execute tools
    - call LLMs
    - call system_entry
    - mutate step execution_result
    - decide lifecycle state
    - fabricate success
    - perform semantic quality scoring
    - invent cost/spend values
    - enforce privacy/spend/source policy gates
    """
    steps = workflow.get("steps", []) or []
    workflow_status = workflow.get("status", "UNKNOWN")

    # Build step lookup and reverse dependency map
    step_map = {s.get("id"): s for s in steps if s.get("id")}
    dependent_map = _compute_dependent_step_ids(steps)

    # Categorize steps by status and execution_result
    step_outputs: List[Dict[str, Any]] = []
    successful_step_outputs: List[Dict[str, Any]] = []
    successful_ids: Set[str] = set()
    completed_step_count = 0
    failed_step_count = 0
    blocked_step_count = 0

    for step in steps:
        step_id = step.get("id")
        if not step_id:
            continue

        status = step.get("status", "UNKNOWN")
        exec_res = step.get("execution_result")
        is_completed = status == "COMPLETED"
        is_success = (
            is_completed
            and exec_res is not None
            and isinstance(exec_res, dict)
            and exec_res.get("status") == "success"
        )

        if is_completed:
            completed_step_count += 1
        if status == "FAILED":
            failed_step_count += 1
        if status == "BLOCKED":
            blocked_step_count += 1

        if exec_res is not None:
            step_entry = {
                "step_id": step_id,
                "step_label": step.get("purpose") or step.get("expected_outcome") or step_id,
                "purpose": step.get("purpose"),
                "expected_outcome": step.get("expected_outcome"),
                "status": status,
                "execution_result": exec_res,
                "is_success": is_success,
                "is_completed": is_completed,
                "depends_on": step.get("depends_on") or [],
                "dependent_step_ids": dependent_map.get(step_id, []),
                "is_terminal_success_output": False,
                "is_synthesis_hint": False,
            }
            step_outputs.append(step_entry)

            if is_success:
                successful_step_outputs.append(step_entry)
                successful_ids.add(step_id)

    # Mark terminal success outputs and synthesis hints
    terminal_success_outputs: List[Dict[str, Any]] = []
    for entry in step_outputs:
        if entry["is_success"] and _is_terminal_success_output(
            step_map.get(entry["step_id"], {}), dependent_map, successful_ids
        ):
            entry["is_terminal_success_output"] = True
            terminal_success_outputs.append(entry)

    # Mark synthesis hints on terminal success outputs
    for entry in terminal_success_outputs:
        entry["is_synthesis_hint"] = _has_synthesis_hint(step_map.get(entry["step_id"], {}))

    # Detect explicit synthesis output
    synthesis_output = None
    synthesis_step_id = None
    for entry in terminal_success_outputs:
        if entry["is_synthesis_hint"]:
            synthesis_output = entry["execution_result"]
            synthesis_step_id = entry["step_id"]
            break

    # Build source_outputs:
    # - If synthesis detected: direct successful dependencies of the synthesis step
    # - Otherwise: all terminal_success_outputs
    source_outputs: List[Dict[str, Any]] = []
    if synthesis_step_id is not None:
        synthesis_step = step_map.get(synthesis_step_id, {})
        synthesis_deps = set(synthesis_step.get("depends_on", []))
        for entry in successful_step_outputs:
            if entry["step_id"] in synthesis_deps:
                source_outputs.append(entry)
    else:
        source_outputs = list(terminal_success_outputs)

    # Determine output_mode
    output_mode = "last_step_output"
    aggregation_warnings: List[str] = []

    has_successful_outputs = len(successful_step_outputs) > 0
    is_terminal = workflow_status in ("COMPLETED", "FAILED", "BLOCKED", "CANCELLED")
    is_failed_or_blocked = workflow_status in ("FAILED", "BLOCKED")

    if is_failed_or_blocked:
        if has_successful_outputs:
            output_mode = "partial_result_with_warning"
        else:
            output_mode = "failed_or_incomplete"
    elif workflow_status == "COMPLETED":
        if len(successful_step_outputs) == 1:
            output_mode = "single"
        elif synthesis_step_id is not None:
            output_mode = "explicit_final_synthesis_output"
            # Warn if other terminal outputs exist outside synthesis dependencies
            synthesis_step = step_map.get(synthesis_step_id, {})
            synthesis_deps = set(synthesis_step.get("depends_on", []))
            for entry in terminal_success_outputs:
                if entry["step_id"] != synthesis_step_id and entry["step_id"] not in synthesis_deps:
                    aggregation_warnings.append(
                        f"Terminal output {entry['step_id']} exists outside synthesis dependencies"
                    )
        elif len(terminal_success_outputs) > 1:
            output_mode = "multi_output_aggregate"
        else:
            output_mode = "last_step_output"
    else:
        # Non-terminal workflow (e.g. PAUSED, ACTIVE)
        if has_successful_outputs:
            output_mode = "partial_result_with_warning"
        else:
            output_mode = "failed_or_incomplete"

    # final_output: use existing workflow["output"] for backward compatibility.
    # If None, fallback to last successful completed step execution_result
    # (same logic as orchestrator_runtime.py post-loop fallback).
    final_output = workflow.get("output")
    if final_output is None:
        for s in reversed(steps):
            if s.get("status") == "COMPLETED" and s.get("execution_result") is not None:
                er = s.get("execution_result")
                if isinstance(er, dict) and er.get("status") == "success":
                    final_output = er
                    break

    result = {
        "final_output": final_output,
        "step_outputs": step_outputs,
        "successful_step_outputs": successful_step_outputs,
        "terminal_success_outputs": terminal_success_outputs,
        "source_outputs": source_outputs,
        "synthesis_output": synthesis_output,
        "synthesis_step_id": synthesis_step_id,
        "completed_step_count": completed_step_count,
        "successful_output_count": len(successful_step_outputs),
        "failed_step_count": failed_step_count,
        "blocked_step_count": blocked_step_count,
        "output_mode": output_mode,
        "aggregation_warnings": aggregation_warnings,
    }

    # === PDIAG-005 Phase 1: Advisory false-success detection ===
    # Per AUTHORITY_MODEL: execution_result remains sole truth.
    # This is additive observability only — does NOT affect lifecycle,
    # governance, retry, replan, execution_result, or purpose_met.
    try:
        result["false_success_analysis"] = evaluate_false_success(workflow, result)
    except Exception:
        # Fail-safe: never break aggregation on detector error
        result["false_success_analysis"] = {
            "warning": False,
            "warnings": [],
            "summary": "detector unavailable",
        }

    # === F3C: Additive source/privacy metadata summaries ===
    # These are deterministic, non-authoritative, and do not affect final output text.
    try:
        source_summary, privacy_summary = _build_web_metadata_summary(workflow)
        result["source_summary"] = source_summary
        result["privacy_summary"] = privacy_summary
    except Exception:
        # Fail-safe: never break aggregation on metadata summary error
        result["source_summary"] = {
            "source_count": 0,
            "sources_used": [],
            "source_domains": [],
            "evidence_refs": [],
            "tools": [],
            "query_count": 0,
            "read_count": 0,
        }
        result["privacy_summary"] = {
            "privacy_classifications": [],
            "external_call_count": 0,
            "external_search_count": 0,
            "external_url_fetch_count": 0,
            "provider_hosts": [],
            "source_quality_status": {
                "unknown": 0,
                "blocked": 0,
                "inaccessible": 0,
                "retrieved": 0,
            },
        }

    return result

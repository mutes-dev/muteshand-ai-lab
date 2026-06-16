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

    return {
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

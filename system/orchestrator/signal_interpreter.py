"""Signal Interpreter Module — Advisory Analysis Only.

Analyzes signals from execution and validation to produce structured
advisory insights. Output is stored only — NEVER used in governance,
control flow, or execution decisions.

Contract:
- MUST NOT return retry/complete/fail/escalate decisions
- MUST NOT modify step fields used by governance
- MUST NOT modify execution_result
- MUST NOT call governance or system_entry
- Output is pure data — no side effects
"""


def interpret_signals(step: dict, execution_result: dict) -> dict:
    """
    Analyze all available signals and produce an advisory interpretation.

    Args:
        step: The step dict (read-only — this function MUST NOT modify it)
        execution_result: The execution result dict (read-only)

    Returns:
        Advisory analysis dict with keys:
            - status_analysis: str — classified outcome
            - conflicts: list[str] — detected signal conflicts
            - issues: list[str] — advisory issues detected
            - confidence: str — "high" | "medium" | "low"
            - summary: str — human-readable advisory summary
    """
    conflicts = []
    issues = []

    exec_status = execution_result.get("status") if isinstance(execution_result, dict) else None
    exec_result_value = execution_result.get("result") if isinstance(execution_result, dict) else None

    validator_signals = step.get("_validator_signals") or {}
    final_answer_correct = validator_signals.get("final_answer_correct")
    constraint_ok = validator_signals.get("constraint_ok", True)
    constraint_violation = validator_signals.get("constraint_violation")

    validator_advisory = step.get("_validator_advisory")
    validator_decision = step.get("_validator_decision")
    mismatch = step.get("mismatch")
    mismatch_advisory = step.get("_mismatch_advisory")
    extracted_constraints = step.get("_extracted_constraints") or {}

    # --- CONFLICT DETECTION ---

    # Conflict 1: execution succeeded but validator flags failure
    if exec_status == "success" and validator_decision in ("retry", "escalate", "fail"):
        conflicts.append("execution_success_vs_validator_failure")

    # Conflict 2: execution succeeded but answer flagged incorrect
    if exec_status == "success" and final_answer_correct is False:
        conflicts.append("execution_success_vs_semantic_incorrect")

    # Conflict 3: execution succeeded but constraint violated
    if exec_status == "success" and not constraint_ok:
        conflicts.append("execution_success_vs_constraint_violation")

    # Conflict 4: output mismatch detected
    if exec_status == "success" and (mismatch is True or mismatch_advisory is True):
        conflicts.append("execution_success_vs_output_mismatch")

    # --- ISSUE DETECTION ---

    if final_answer_correct is False:
        issues.append("semantic_incorrect")

    if not constraint_ok:
        if constraint_violation:
            issues.append(f"constraint_violation:{constraint_violation}")
        else:
            issues.append("constraint_violation:unknown")

    if mismatch is True or mismatch_advisory is True:
        issues.append("output_mismatch_detected")

    if validator_advisory and validator_advisory not in ("correct", "unknown"):
        issues.append(f"validator_advisory:{validator_advisory}")

    # --- STATUS CLASSIFICATION ---
    # Priority order: constraint_conflict > semantic_incorrect > generic conflicts

    if exec_status == "success" and not conflicts:
        status_analysis = "consistent_success"
    elif exec_status == "success" and "execution_success_vs_constraint_violation" in conflicts:
        status_analysis = "successful_with_constraint_conflict"
    elif exec_status == "success" and "execution_success_vs_semantic_incorrect" in conflicts:
        status_analysis = "successful_but_incorrect"
    elif exec_status == "success" and conflicts:
        status_analysis = "successful_with_conflicts"
    elif exec_status == "failure":
        status_analysis = "execution_failure"
    else:
        status_analysis = "unknown"

    # --- CONFIDENCE SCORING ---

    if status_analysis == "consistent_success":
        confidence = "high"
    elif exec_status == "success" and len(conflicts) == 1:
        confidence = "medium"
    elif exec_status == "success" and len(conflicts) > 1:
        confidence = "medium"
    elif exec_status == "failure":
        confidence = "high"
    else:
        confidence = "low"

    # --- SUMMARY ---

    if status_analysis == "consistent_success":
        summary = "Execution succeeded with no signal conflicts."
    elif status_analysis == "successful_but_incorrect":
        summary = "Execution succeeded but semantic validation flagged incorrect result."
    elif status_analysis == "successful_with_constraint_conflict":
        summary = f"Execution succeeded but constraint was violated: {constraint_violation}."
    elif status_analysis == "successful_with_conflicts":
        summary = f"Execution succeeded but {len(conflicts)} signal conflict(s) detected."
    elif status_analysis == "execution_failure":
        summary = "Execution failed."
    else:
        summary = "Signal state is ambiguous or incomplete."

    return {
        "status_analysis": status_analysis,
        "conflicts": conflicts,
        "issues": issues,
        "confidence": confidence,
        "summary": summary,
    }

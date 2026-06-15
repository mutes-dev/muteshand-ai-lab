"""
Planning Compiler — Pre-Runtime Deterministic Plan Repair

Complies with PLANNING_COMPILER_CONTRACT_V1:
  - Receives planner output (candidate structure, not trusted)
  - Applies deterministic repairs within narrow rules
  - Hands verified plan to workflow_validator as fail-safe
  - Does NOT execute tools, mutate lifecycle, or bypass governance

Current scope:
  - ISSUE-PDIAG-002B: Final/all-prior/multi-source synthesis dependency auto-binding
"""

from system.orchestrator.synthesis_dependency_utils import (
    _get_required_synthesis_dependencies,
    _is_all_prior_synthesis_step,
)


def apply_synthesis_dependency_binding(workflow: dict) -> dict:
    """
    Deterministically repair missing dependencies for existing all-prior synthesis steps.

    Rules:
      1. Only operates on steps already identified as all-prior synthesis.
      2. Only binds prior non-synthesis source steps.
      3. Preserves existing valid dependencies.
      4. Does NOT create new steps.
      5. Does NOT modify targeted synthesis (explicit single references).
      6. Does NOT bind future steps or self.
      7. Idempotent: running twice produces the same result.

    Args:
        workflow: workflow dict with "steps" list

    Returns:
        Repaired workflow dict (mutates in place for efficiency, but conceptually pure).
    """
    steps = workflow.get("steps", [])
    if not isinstance(steps, list) or len(steps) <= 1:
        return workflow

    total_steps = len(steps)

    for i, step in enumerate(steps):
        if not _is_all_prior_synthesis_step(step, i, total_steps):
            continue

        step_id = step.get("id")
        if not step_id:
            continue

        required = _get_required_synthesis_dependencies(steps, i)
        if not required:
            continue

        declared = step.get("depends_on", []) or []
        if not isinstance(declared, list):
            declared = []

        # Preserve existing order, append missing deterministically
        missing = [dep for dep in sorted(required) if dep not in declared]
        if missing:
            step["depends_on"] = declared + missing

    return workflow

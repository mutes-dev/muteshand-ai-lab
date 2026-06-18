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


# === ISSUE-PDIAG-006-RS1: Same-Resource Sequencing Safety ===

import re

_WRITE_MARKERS = frozenset([
    "write", "write to", "save", "save to", "create", "create file",
    "output to", "export to",
])

_READ_MARKERS = frozenset([
    "read", "load", "open", "display", "show", "fetch", "get contents",
])

_EDIT_MARKERS = frozenset([
    "edit", "modify", "update", "replace", "change",
])

_SEQUENCE_MARKERS = frozenset([
    "then", "after reading", "after read", "read it first", "read first",
])

# Match Windows absolute paths, optionally preceded by a quote/bracket.
# Negative lookbehind prevents matching drive-letter-like fragments inside URLs (e.g. s:/ in https://).
# Captures the broad path string; trailing punctuation is stripped during normalization.
_PATH_RE = re.compile(
    r'(?i)(?<!\w)(?:[\'"\(\[])?([a-z]:[\\/][^\s]*)'
)


def _extract_local_file_paths(text: str) -> list[str]:
    """Extract concrete local file paths from step text."""
    if not text:
        return []
    paths = []
    for match in _PATH_RE.finditer(text):
        path = match.group(1)
        # Basic structural guard: must be drive-letter absolute
        if len(path) >= 3 and path[1] == ":" and path[2] in "\\/":
            paths.append(path)
    return paths


def _normalize_local_file_path(path: str) -> str | None:
    """
    Normalize an extracted path string.

    Returns None if:
      - path is not a concrete absolute local file path
      - path is a URL
      - path is relative
      - path is empty after stripping
    """
    if not path:
        return None
    # Reject URLs and relative paths
    if re.match(r'(?i)^https?://', path):
        return None
    if not re.match(r'(?i)^[a-z]:[\\/].', path):
        return None
    # Strip surrounding quotes/brackets
    path = path.strip('"\'()[]')
    # Lowercase and backslash-normalize
    path = path.lower().replace('/', '\\')
    # Strip trailing punctuation that may have been captured
    path = path.rstrip('.,;:!?\'"')
    # Reject if stripped to drive letter only or empty
    if len(path) <= 3:
        return None
    return path


def _classify_file_operation(step: dict) -> str:
    """
    Conservative keyword-based classification of file operation type.

    Returns one of: "write", "read", "edit", "unknown".
    """
    text = (step.get("purpose", "") + " " + step.get("expected_outcome", "")).lower()

    for marker in _WRITE_MARKERS:
        if marker in text:
            return "write"
    for marker in _EDIT_MARKERS:
        if marker in text:
            return "edit"
    for marker in _READ_MARKERS:
        if marker in text:
            return "read"

    return "unknown"


def _requires_same_resource_sequence(prev_op: str, curr_op: str, user_input: str | None = None) -> bool:
    """
    Determine whether a prior operation on the same path requires the current
    step to depend on it.

    Approved deterministic patterns:
      write -> read | edit | write
      edit  -> read | edit

    Conditional pattern (requires user_input sequence markers):
      read -> edit
    """
    if prev_op == "write" and curr_op in ("read", "edit", "write"):
        return True
    if prev_op == "edit" and curr_op in ("read", "edit"):
        return True

    if prev_op == "read" and curr_op == "edit":
        if not user_input:
            return False
        ui = user_input.lower()
        return any(marker in ui for marker in _SEQUENCE_MARKERS)

    return False


def _add_dependency_if_missing(step: dict, dep_id: str) -> bool:
    """Append dep_id to step depends_on if absent. Preserves order."""
    deps = step.get("depends_on", []) or []
    if not isinstance(deps, list):
        deps = []
    if dep_id in deps:
        return False
    step["depends_on"] = deps + [dep_id]
    return True


def apply_resource_sequencing_binding(workflow: dict, user_input: str | None = None) -> dict:
    """
    Deterministically repair missing same-resource file sequencing dependencies.

    Rules (per PLANNING_COMPILER_CONTRACT_V1 §11):
      1. Only operates on steps already in the plan.
      2. Only repairs when both steps reference the same concrete normalized local file path.
         A step also inherits paths from explicitly-declared prior step dependencies,
         enabling transitive same-resource sequencing when a step references a prior
         step's output without repeating the file path.
      3. Only adds dependency from later step -> most recent prior step on same path.
      4. Only repairs when operation pairing requires ordering.
      5. Existing dependencies are preserved and deduped.
      6. Does NOT create new steps, delete steps, modify purpose, or modify agent selection.
      7. Idempotent: running twice produces the same result.

    Args:
        workflow: workflow dict with "steps" list
        user_input: optional original user input for conditional read->edit detection

    Returns:
        Repaired workflow dict (mutates in place for efficiency, but conceptually pure).
    """
    steps = workflow.get("steps", [])
    if not isinstance(steps, list) or len(steps) <= 1:
        return workflow

    # Pre-compute metadata for every step to support transitive path inheritance
    step_meta: dict[str, dict] = {}
    for step in steps:
        step_id = step.get("id")
        if not step_id:
            continue
        text = (step.get("purpose", "") + " " + step.get("expected_outcome", "")).strip()
        own_paths = set()
        for path in _extract_local_file_paths(text):
            norm = _normalize_local_file_path(path)
            if norm:
                own_paths.add(norm)
        step_meta[step_id] = {
            "paths": own_paths,
            "op": _classify_file_operation(step),
        }

    # path -> (last_step_index, last_step_id, last_op)
    last_op_by_path: dict[str, tuple[int, str, str]] = {}

    for i, step in enumerate(steps):
        step_id = step.get("id")
        if not step_id:
            continue

        meta = step_meta[step_id]
        op = meta["op"]
        if op == "unknown":
            continue

        # Collect paths from step text + from explicitly-declared prior dependencies
        paths = set(meta["paths"])
        for dep_id in step.get("depends_on", []) or []:
            dep_meta = step_meta.get(dep_id)
            if dep_meta:
                paths.update(dep_meta["paths"])

        for path in paths:
            if path in last_op_by_path:
                _prior_idx, prior_id, prior_op = last_op_by_path[path]
                if _requires_same_resource_sequence(prior_op, op, user_input):
                    _add_dependency_if_missing(step, prior_id)

            last_op_by_path[path] = (i, step_id, op)

    return workflow

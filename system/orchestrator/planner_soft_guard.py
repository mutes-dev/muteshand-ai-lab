"""
Planner Soft Guard — Post-Planning Structural Correction

Responsibilities:
- Detect likely multi-objective step collapse in single-step workflows
- Split into two steps ONLY when structural evidence is clear and unambiguous
- Return workflow unchanged in ALL uncertain cases

Constraints (NON-NEGOTIABLE):
- NO hardcoded domain keywords
- NO semantic interpretation of step content
- NO contact with system_entry, governance, or constraint system
- NO modification of planner itself
- MUST be deterministic (no LLM required)
- MUST NOT break valid single-step workflows
- MUST NOT over-split

Principle: Guard, don't control. Assist, don't override.
"""

import re


_CONJUNCTION_PATTERN = re.compile(
    r'\b(but|yet|however|although|though|except|while|whereas)\b',
    re.IGNORECASE
)

_SPLIT_MARKER_PATTERN = re.compile(
    r'\b(then|and then|after that|followed by|subsequently)\b',
    re.IGNORECASE
)

_VERB_BOUNDARY_PATTERN = re.compile(
    r'(?<=[a-z]),\s+[A-Z]|(?<=[.!?])\s+[A-Z]'
)


def _count_verb_clauses(text: str) -> int:
    """
    Estimate the number of independent verb clauses in a purpose string.

    Strategy:
    - Split on conjunction markers and count resulting non-trivial segments.
    - A segment is non-trivial if it contains at least two tokens.

    Returns:
        int: estimated clause count (1 = single objective, >1 = multi-objective likely)
    """
    combined_pattern = re.compile(
        r'\b(but|yet|however|although|though|except|while|whereas|then|and then|and)\b',
        re.IGNORECASE
    )
    parts = combined_pattern.split(text)
    non_trivial = [p.strip() for p in parts if len(p.strip().split()) >= 2]
    return len(non_trivial)


def _split_on_conjunction(purpose: str) -> tuple[str, str] | None:
    """
    Attempt to split a purpose string into two parts on the first adversative
    or additive conjunction that separates two independently meaningful clauses.

    Rules:
    - Conjunction must have substantive content on BOTH sides (>=2 tokens each side)
    - Returns (part_1, part_2) if split is safe
    - Returns None if split is ambiguous or unsafe

    Does NOT interpret the content of either part.
    """
    matches = []

    for pattern in (_CONJUNCTION_PATTERN, _SPLIT_MARKER_PATTERN):
        matches.extend(pattern.finditer(purpose))

    additive_pattern = re.compile(r'\band\b', re.IGNORECASE)
    matches.extend(additive_pattern.finditer(purpose))

    matches.sort(key=lambda m: m.start())

    for match in matches:
        left = purpose[:match.start()].strip()
        right = purpose[match.end():].strip()

        left_tokens = left.split()
        right_tokens = right.split()

        if len(left_tokens) >= 2 and len(right_tokens) >= 2:
            return left, right

    return None


def _build_step_from(original_step: dict, purpose: str, suffix: str) -> dict:
    """
    Construct a new step dict derived from an existing step.

    - Preserves agent, estimated_complexity
    - Sets new id, name, purpose, input
    - Does NOT carry over execution-state fields (status, retries, etc.)
      — those are added by execute_from_input normalization after this guard runs
    """
    return {
        "id": original_step["id"] + suffix,
        "name": original_step.get("name", "Step") + suffix,
        "purpose": purpose,
        "agent": original_step.get("agent", "general_agent"),
        "estimated_complexity": original_step.get("estimated_complexity", "low"),
    }


def enforce_atomic_steps(workflow: dict) -> dict:
    """
    Post-planner soft structural guard.

    Conditions for activation (ALL must be true):
    1. workflow["steps"] has exactly 1 step
    2. step["purpose"] is a non-empty string
    3. step["purpose"] contains a clear conjunction-based split point
    4. Both resulting segments are substantively non-trivial (>=2 tokens)

    If ANY condition fails → return workflow UNCHANGED.

    Args:
        workflow: workflow dict as returned by plan_workflow and extracted by execute_from_input

    Returns:
        workflow dict — either original or with steps replaced by two atomic steps
    """
    # TEMP DISABLED: pass-through (Head Dev decision)
    return workflow

"""Arithmetic Capability — Deterministic pure arithmetic-chain detector/compiler.

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 10:
- High-confidence pure arithmetic-chain detection only
- No LLM. No system_entry import. No execution.
- Emits explicit candidate workflow/DAG with depends_on.
- Fallback for mixed-domain, bare continuation, multi-branch synthesis.

Scope reductions enforced (AGENT-001B):
- No bare continuation arithmetic (cross-turn or standalone)
- No multi-branch synthesis ("Give both results")
- No mixed-domain routing
"""

import re
from typing import Any


# === MIXED-Domain detection — conservative fallback keywords ===
_MIXED_DOMAIN_KEYWORDS = frozenset([
    "read file", "open file", "write file", "edit file", "append file",
    "read ", "open ", "folder", "document", "pdf", "docx", "spreadsheet",
    "search", "web", "browse", "website", "url", "http", "internet",
    "download", "upload", "email", "api", "external",
])

# === Synthesis / multi-branch detection — fallback keywords ===
_SYNTHESIS_KEYWORDS = frozenset([
    "give both", "give all", "list both", "list all",
    "compare", "compare both", "compare all",
    "summarize both", "summarize all",
    "both results", "all results", "multiple results",
    "final answer from", "answer from both",
])

# === Arithmetic operation patterns ===
# Each entry: (regex, tool_name, operand_extractor_func, is_full_match)
# Patterns are ordered by specificity (most specific first).
# is_full_match=True means both operands explicit; False means continuation (one operand).

_ARITHMETIC_PATTERNS = [
    # square root (single operand — full)
    (re.compile(r"square\s+root\s+(?:of\s+)?([\d.]+)", re.IGNORECASE), "square_root", lambda m: [m.group(1)], True),
    # factorial (single operand — full)
    (re.compile(r"factorial\s+(?:of\s+)?([\d.]+)", re.IGNORECASE), "factorial", lambda m: [m.group(1)], True),
    # fibonacci (single operand — full)
    (re.compile(r"fibonacci\s+(?:of\s+)?([\d.]+)", re.IGNORECASE), "fibonacci", lambda m: [m.group(1)], True),
    # cube (single operand — full)
    (re.compile(r"cube\s+([\d.]+)", re.IGNORECASE), "cube_number", lambda m: [m.group(1)], True),
    # square (single operand — full)
    (re.compile(r"square\s+([\d.]+)", re.IGNORECASE), "square_number", lambda m: [m.group(1)], True),

    # === Natural language two-operand (most specific first) ===
    # What is / Calculate / Find X plus Y
    (re.compile(r"(?:what\s+is|calculate|find)\s+([\d.]+)\s+plus\s+([\d.]+)", re.IGNORECASE), "add_numbers", lambda m: [m.group(1), m.group(2)], True),
    # What is / Calculate / Find X minus Y
    (re.compile(r"(?:what\s+is|calculate|find)\s+([\d.]+)\s+minus\s+([\d.]+)", re.IGNORECASE), "subtract_numbers", lambda m: [m.group(1), m.group(2)], True),
    # What is / Calculate / Find X times Y
    (re.compile(r"(?:what\s+is|calculate|find)\s+([\d.]+)\s+times\s+([\d.]+)", re.IGNORECASE), "multiply_numbers", lambda m: [m.group(1), m.group(2)], True),
    # What is / Calculate / Find X divided by Y
    (re.compile(r"(?:what\s+is|calculate|find)\s+([\d.]+)\s+divided\s+by\s+([\d.]+)", re.IGNORECASE), "divide_numbers", lambda m: [m.group(1), m.group(2)], True),

    # === Standalone natural two-operand (embedded in sentence) ===
    # X plus Y
    (re.compile(r"([\d.]+)\s+plus\s+([\d.]+)", re.IGNORECASE), "add_numbers", lambda m: [m.group(1), m.group(2)], True),
    # X minus Y
    (re.compile(r"([\d.]+)\s+minus\s+([\d.]+)", re.IGNORECASE), "subtract_numbers", lambda m: [m.group(1), m.group(2)], True),
    # X times Y
    (re.compile(r"([\d.]+)\s+times\s+([\d.]+)", re.IGNORECASE), "multiply_numbers", lambda m: [m.group(1), m.group(2)], True),
    # X divided by Y
    (re.compile(r"([\d.]+)\s+divided\s+by\s+([\d.]+)", re.IGNORECASE), "divide_numbers", lambda m: [m.group(1), m.group(2)], True),

    # === Explicit command two-operand ===
    # add X and Y (full)
    (re.compile(r"add\s+([\d.]+)\s+and\s+([\d.]+)", re.IGNORECASE), "add_numbers", lambda m: [m.group(1), m.group(2)], True),
    # subtract Y from X (full)
    (re.compile(r"subtract\s+([\d.]+)\s+from\s+([\d.]+)", re.IGNORECASE), "subtract_numbers", lambda m: [m.group(2), m.group(1)], True),
    # multiply X by Y (full)
    (re.compile(r"multiply\s+([\d.]+)\s+by\s+([\d.]+)", re.IGNORECASE), "multiply_numbers", lambda m: [m.group(1), m.group(2)], True),
    # divide X by Y (full)
    (re.compile(r"divide\s+([\d.]+)\s+by\s+([\d.]+)", re.IGNORECASE), "divide_numbers", lambda m: [m.group(1), m.group(2)], True),
    # calculate / compute X op Y (full)
    (re.compile(r"(?:calculate|compute)\s+([\d.]+)\s*([+\-*/])\s*([\d.]+)", re.IGNORECASE), None, None, True),

    # === Continuation patterns (one operand, relies on prior result) ===
    # add X (continuation)
    (re.compile(r"add\s+([\d.]+)", re.IGNORECASE), "add_numbers", lambda m: [m.group(1)], False),
    # subtract X (continuation)
    (re.compile(r"subtract\s+([\d.]+)", re.IGNORECASE), "subtract_numbers", lambda m: [m.group(1)], False),
    # multiply by X (continuation)
    (re.compile(r"multiply\s+by\s+([\d.]+)", re.IGNORECASE), "multiply_numbers", lambda m: [m.group(1)], False),
    # divide by X (continuation)
    (re.compile(r"divide\s+by\s+([\d.]+)", re.IGNORECASE), "divide_numbers", lambda m: [m.group(1)], False),
]

# Operator-to-tool mapping for calculate/compute expressions
_OPERATOR_TOOL_MAP = {
    "+": "add_numbers",
    "-": "subtract_numbers",
    "*": "multiply_numbers",
    "/": "divide_numbers",
}


def _is_mixed_domain(text: str) -> bool:
    """Return True if prompt contains mixed-domain keywords."""
    lower = text.lower()
    return any(kw in lower for kw in _MIXED_DOMAIN_KEYWORDS)


def _is_synthesis_request(text: str) -> bool:
    """Return True if prompt asks to synthesize/compare/list multiple results."""
    lower = text.lower()
    return any(kw in lower for kw in _SYNTHESIS_KEYWORDS)


def _parse_arithmetic_operations(text: str) -> list[dict] | None:
    """
    Parse prompt into a list of arithmetic operations.

    Returns list of dicts with keys:
      - tool_name: str
      - operands: list[str]  # numeric literals
      - raw_match: str       # matched text segment
      - is_full_match: bool  # True if both operands explicit
    
    Returns None if no arithmetic operations found or parsing fails.
    """
    # Normalize: replace "then" with period to split clauses
    normalized = text.replace(" then ", ". ").replace(", then ", ". ")
    # Split by sentence terminators
    segments = re.split(r"[.;]\s+", normalized)

    operations = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        matched = False
        for pattern, tool_name, extractor, is_full_match in _ARITHMETIC_PATTERNS:
            m = pattern.search(seg)
            if m:
                if tool_name is None and extractor is None:
                    # calculate/compute expression
                    op = m.group(2)
                    tool_name = _OPERATOR_TOOL_MAP.get(op)
                    if not tool_name:
                        continue
                    operands = [m.group(1), m.group(3)]
                    is_full_match = True
                else:
                    operands = extractor(m)
                operations.append({
                    "tool_name": tool_name,
                    "operands": operands,
                    "raw_match": m.group(0),
                    "segment": seg,
                    "is_full_match": is_full_match,
                })
                matched = True
                break
        if not matched:
            # If a segment has digits and arithmetic words but didn't match,
            # the prompt may be ambiguous — fail safe.
            if re.search(r"\d", seg) and re.search(r"add|subtract|multiply|divide|square|cube", seg, re.IGNORECASE):
                return None
    return operations if operations else None


def _build_step_purpose(op: dict, step_index: int, prior_step_id: str | None) -> str:
    """Build a clear purpose string for an arithmetic step."""
    tool_name = op["tool_name"]
    operands = op["operands"]
    seg = op["segment"]

    # For first step or steps with two explicit operands, preserve original intent
    if len(operands) == 2:
        return seg.capitalize()

    # For chained step with one explicit operand (depends_on prior result)
    if prior_step_id and len(operands) == 1:
        # Map tool to natural language verb
        verb_map = {
            "add_numbers": "Add",
            "subtract_numbers": "Subtract",
            "multiply_numbers": "Multiply",
            "divide_numbers": "Divide",
            "square_number": "Square",
            "cube_number": "Cube",
            "square_root": "Square root of",
            "factorial": "Factorial of",
            "fibonacci": "Fibonacci of",
        }
        verb = verb_map.get(tool_name, tool_name)
        operand = operands[0]
        return f"{verb} {operand} from the result of {prior_step_id}"

    # Single standalone operation (one operand, no chain)
    return seg.capitalize()


def compile_arithmetic_workflow(user_input: str) -> dict | None:
    """
    Compile a high-confidence pure arithmetic prompt into a candidate workflow.

    Returns workflow dict compatible with validate_workflow,
    or None if prompt should fall back to planner.

    Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1:
    - No LLM calls
    - No system_entry import
    - Explicit DAG emission with depends_on
    """
    # === FAIL-SAFE CHECKS ===
    if _is_mixed_domain(user_input):
        return None
    if _is_synthesis_request(user_input):
        return None

    operations = _parse_arithmetic_operations(user_input)
    if not operations:
        return None

    # Bare continuation guard: standalone prompt with no full-match operations.
    # e.g. "Subtract 20" alone → fallback (needs prior context)
    # e.g. "Square 5" alone → OK (single-operand tool is a full match)
    # e.g. "Add 50 and 11. Subtract 20." → OK (has full-match + continuation in chain)
    if len(operations) == 1 and not operations[0]["is_full_match"]:
        # Single continuation-only operation without any full match → bare continuation
        if operations[0]["tool_name"] in ("subtract_numbers", "add_numbers", "multiply_numbers", "divide_numbers"):
            return None

    steps = []
    for i, op in enumerate(operations):
        step_id = f"step_{i + 1}"
        prior_step_id = f"step_{i}" if i > 0 else None

        purpose = _build_step_purpose(op, i, prior_step_id)

        depends_on = []
        if prior_step_id and len(op["operands"]) == 1:
            depends_on = [prior_step_id]

        step = {
            "id": step_id,
            "type": "EXECUTE_API",
            "name": f"Arithmetic step {i + 1}",
            "purpose": purpose,
            "expected_outcome": "Execution completed",
            "risk": "LOW",
            "importance": "LOW",
            "resource_targets": [],
            "agent": "math_executor",  # semantic label only, not execution authority
            "depends_on": depends_on,
            "capability_metadata": {
                "capability_id": "arithmetic",
                "route_confidence": 1.0,
                "route_reason_code": "pure_arithmetic_chain",
                "allowed_tool_family": "math",
                "allowed_tool": op["tool_name"],
            },
        }
        # AGENT-001B-FIX2: Pre-populate tool_call for full_match steps.
        # This triggers the tool_selection_agent fast path, bypassing AG1 LLM
        # for known tool/operand combinations. Eliminates malformed directive
        # prefix risk for factorial/fibonacci and ensures exact deterministic
        # execution for natural-language arithmetic.
        if op["is_full_match"]:
            step["tool_call"] = f"USE_TOOL: {op['tool_name']} {' '.join(op['operands'])}"
        steps.append(step)

    workflow = {
        "id": None,  # set by caller from pre_generated_workflow_id
        "name": "arithmetic_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": steps,
        "approval_required": False,
    }
    return workflow

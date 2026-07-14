"""Structured Data Analysis Capability — F5A bounded deterministic compiler.

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 9 / STRUCTURED_DATA_ANALYSIS_CONTRACT_V1:
- High-confidence explicit local CSV/XLSX aggregate analysis only
- No LLM. No system_entry import. No execution.
- Emits explicit one-step candidate workflow with allowed_tool=analyze_table.
- Declines ambiguous, multi-file, unsupported-operation, and mixed-domain prompts.

Supported operations:
- overview
- count_rows
- max / maximum / highest
- min / minimum / lowest
- sum / total
- average / mean
"""

import re
from typing import Any


# === File path extraction ===
# Exactly one CSV or XLSX path must be present.
_CSV_XLSX_PATH_RE = re.compile(
    r'["\']([^"\']+?\.(?:csv|xlsx|xls|xlsm?))["\']'
    r'|(?:^|\s)([a-zA-Z0-9_./\\~ -]*[\\/][a-zA-Z0-9_./\\~ -]*\.(?:csv|xlsx|xls|xlsm?)'
    r'|[a-zA-Z]:[\\/][a-zA-Z0-9_./\\~ -]*\.(?:csv|xlsx|xls|xlsm?)'
    r'|[a-zA-Z0-9_ -]*\.(?:csv|xlsx|xls|xlsm?))'
    r'(?=\s|$|[.,;!?])',
    re.IGNORECASE,
)


# === Operation detection patterns ===
# Each tuple: (operation, regex, target_column_group_index, optional associated_column_group_index)
_OPERATION_PATTERNS = [
    (
        "count_rows",
        re.compile(
            r'\b(?:how many rows(?:\s+are there)?|count(?:\s+the)?\s+rows?|row count)\b',
            re.IGNORECASE,
        ),
        None,
        None,
    ),
    (
        "max",
        re.compile(
            r'\b(?:highest|maximum|max)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)(?:\s+(?:column|in|of|from))?\b',
            re.IGNORECASE,
        ),
        1,
        None,
    ),
    (
        "min",
        re.compile(
            r'\b(?:lowest|minimum|min)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)(?:\s+(?:column|in|of|from))?\b',
            re.IGNORECASE,
        ),
        1,
        None,
    ),
    (
        "sum",
        re.compile(
            r'\b(?:sum|total)\s+(?:of\s+)?(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)(?:\s+(?:column|in|of|from))?\b',
            re.IGNORECASE,
        ),
        1,
        None,
    ),
    (
        "average",
        re.compile(
            r'\b(?:average|mean)\s+(?:of\s+)?(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)(?:\s+(?:column|in|of|from))?\b',
            re.IGNORECASE,
        ),
        1,
        None,
    ),
    # "Which Name has the highest Score?"
    (
        "max",
        re.compile(
            r'\bwhich\s+([A-Za-z][A-Za-z0-9_]*)\s+has\s+(?:the\s+)?(?:highest|maximum|max)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)\b',
            re.IGNORECASE,
        ),
        2,
        1,
    ),
    (
        "min",
        re.compile(
            r'\bwhich\s+([A-Za-z][A-Za-z0-9_]*)\s+has\s+(?:the\s+)?(?:lowest|minimum|min)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)\b',
            re.IGNORECASE,
        ),
        2,
        1,
    ),
    # "Who has the highest Score?"  -> auto-detect name-like column
    (
        "max",
        re.compile(
            r'\bwho\s+has\s+(?:the\s+)?(?:highest|maximum|max)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)\b',
            re.IGNORECASE,
        ),
        1,
        "__AUTO_NAME_LIKE__",
    ),
    (
        "min",
        re.compile(
            r'\bwho\s+has\s+(?:the\s+)?(?:lowest|minimum|min)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)\b',
            re.IGNORECASE,
        ),
        1,
        "__AUTO_NAME_LIKE__",
    ),
    # "Which row has the highest Score?" -> no associated column
    (
        "max",
        re.compile(
            r'\bwhich\s+row\s+has\s+(?:the\s+)?(?:highest|maximum|max)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)\b',
            re.IGNORECASE,
        ),
        1,
        None,
    ),
    (
        "min",
        re.compile(
            r'\bwhich\s+row\s+has\s+(?:the\s+)?(?:lowest|minimum|min)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)\b',
            re.IGNORECASE,
        ),
        1,
        None,
    ),
]


# === Overview detection patterns ===
# Phrases that ask for a bounded table overview without semantic interpretation.
_OVERVIEW_PATTERNS = [
    re.compile(r"\b(?:give me an |show (?:me )?|get an |provide an )?overview of\b", re.IGNORECASE),
    re.compile(r"\banalyze\b(?:\s+(?:the\s+)?(?:table|file|data|spreadsheet))?(?:\s+in)?", re.IGNORECASE),
    re.compile(r"\bbasic statistics for\b", re.IGNORECASE),
    re.compile(r"\bsummarize the table structure and basic statistics\b", re.IGNORECASE),
    re.compile(r"\btable overview\b", re.IGNORECASE),
]


# === Sheet name extraction ===
_SHEET_NAME_RE = re.compile(
    r'\b(?:in|on)\s+(?:the\s+)?sheet\s+["\']([^"\']+)["\']'
    r'|\b(?:in|on)\s+(?:the\s+)?["\']([^"\']+)["\']\s+sheet',
    re.IGNORECASE,
)


# === Mixed-domain / unsupported guard ===
# If these keywords appear, the prompt is likely outside the bounded F5A scope.
_STRUCTURED_DATA_UNSUPPORTED_KEYWORDS = frozenset([
    "web", "website", "url", "http", "https", "internet", "browse",
    "search the web", "search online", "google", "find online",
    "download", "upload", "email", "send mail",
    "compare", "correlation", "pivot", "chart", "graph", "plot",
    "formula", "macro", "vba", "script", "python", "pandas",
    "filter", "sort", "group by", "groupby",
    "join", "merge", "union",
    # Arbitrary / semantic analysis remains unsupported for F5A.
    "why", "reason", "reasons", "meaning", "means", "explain why",
    "insight", "insights", "interesting", "pattern", "patterns",
    "predict", "prediction", "forecast", "recommend", "recommendation",
    "business decision", "business decisions", "decision",
    "cause", "causes", "causal", "trend", "trends",
    "unusual", "anomaly", "anomalies", "relationship", "relationships",
])


_NAME_LIKE_COLUMN_SENTINEL = "__AUTO_NAME_LIKE__"

# Column names that are deterministically not headers (prepositions / grammar noise).
_INVALID_COLUMN_NAMES = frozenset([
    "the", "a", "an", "in", "of", "from", "to", "for", "with", "by", "on", "at",
    "column", "columns", "row", "rows", "sheet", "sheets", "and", "or",
])


def _extract_csv_xlsx_paths(user_input: str) -> list[str]:
    """Return all CSV/XLSX file paths found in the input (quoted or unquoted)."""
    matches = _CSV_XLSX_PATH_RE.findall(user_input)
    paths = []
    for match in matches:
        path = next((g for g in match if g), None)
        if path:
            path = path.strip()
            ext = path.rsplit(".", 1)[-1].lower()
            # Capability only supports CSV and XLSX; legacy/binary Excel is rejected.
            if ext in {"csv", "xlsx"}:
                paths.append(path)
    return paths


def _contains_unsupported_keywords(user_input: str) -> bool:
    lower = user_input.lower()
    return any(kw in lower for kw in _STRUCTURED_DATA_UNSUPPORTED_KEYWORDS)


def _extract_sheet_name(user_input: str) -> str | None:
    m = _SHEET_NAME_RE.search(user_input)
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").strip()


def _is_valid_column_name(name: str | None) -> bool:
    if not name:
        return False
    return name.strip().lower() not in _INVALID_COLUMN_NAMES


def _classify_operation(user_input: str) -> tuple[str, str, Any] | None:
    """
    Classify a single supported operation and extract target/associated columns.

    Returns (operation, target_column, associated_column) or None.
    associated_column may be a string, the sentinel __AUTO_NAME_LIKE__, or None.
    """
    matches = []
    for op, pattern, target_group, assoc_source in _OPERATION_PATTERNS:
        m = pattern.search(user_input)
        if not m:
            continue
        target_column = m.group(target_group) if target_group is not None else None
        if target_column is not None and not _is_valid_column_name(target_column):
            continue
        if assoc_source is None:
            associated_column = None
        elif isinstance(assoc_source, int):
            associated_column = m.group(assoc_source)
        else:
            associated_column = assoc_source
        if associated_column is not None and not _is_valid_column_name(associated_column):
            continue
        matches.append((op, target_column, associated_column))

    # Only accept a single, unambiguous operation per prompt.
    distinct_ops = {m[0] for m in matches}
    if len(distinct_ops) > 1:
        return None

    # Prefer the most specific match (later patterns with associated columns are more specific).
    if matches:
        return matches[-1]

    # No specific aggregate/entity operation matched; fall back to bounded overview.
    for pattern in _OVERVIEW_PATTERNS:
        if pattern.search(user_input):
            return ("overview", None, None)

    return None


def is_structured_data_analysis_prompt(user_input: str) -> bool:
    """Return True only for high-confidence bounded F5A analysis grammar."""
    if not user_input or not isinstance(user_input, str):
        return False
    paths = _extract_csv_xlsx_paths(user_input)
    if len(paths) != 1:
        return False
    if _contains_unsupported_keywords(user_input):
        return False
    op_info = _classify_operation(user_input)
    if op_info is None:
        return False
    return True


def _build_tool_call(
    file_path: str,
    operation: str,
    target_column: str | None,
    sheet_name: str | None,
    associated_column: str | None,
) -> str:
    """Build a shlex-safe USE_TOOL directive for analyze_table."""
    path_arg = file_path.replace("\\", "/")
    op_arg = operation
    target_arg = target_column or ""
    sheet_arg = sheet_name or ""
    assoc_arg = associated_column or ""
    return (
        f'USE_TOOL: analyze_table "{path_arg}" "{op_arg}" "{target_arg}" "{sheet_arg}" "{assoc_arg}"'
    )


def compile_structured_data_analysis_workflow(user_input: str) -> dict | None:
    """
    Compile a high-confidence structured-data analysis prompt into a candidate workflow.

    Returns a workflow dict compatible with validate_workflow,
    or None if the prompt should fall back to the planner/document_local_read route.
    """
    if not user_input or not isinstance(user_input, str):
        return None

    paths = _extract_csv_xlsx_paths(user_input)
    if len(paths) != 1:
        return None

    if _contains_unsupported_keywords(user_input):
        return None

    op_info = _classify_operation(user_input)
    if op_info is None:
        return None

    operation, target_column, associated_column = op_info
    file_path = paths[0].replace("\\", "/")
    sheet_name = _extract_sheet_name(user_input)

    if operation == "overview":
        expected_outcome = "Bounded table overview returned"
        purpose = f'Provide a bounded overview of "{file_path}"'
    elif operation == "count_rows":
        target_column = None
        associated_column = None
        expected_outcome = "Row count returned"
        purpose = f'Count the rows in "{file_path}"'
    else:
        expected_outcome = f"{operation} of {target_column} computed"
        if associated_column == _NAME_LIKE_COLUMN_SENTINEL:
            purpose = f'Find who has the {operation} {target_column} in "{file_path}"'
        elif associated_column:
            purpose = f'Find the {associated_column} with the {operation} {target_column} in "{file_path}"'
        elif operation in ("max", "min"):
            purpose = f'Find the {operation}imum {target_column} in "{file_path}"'
        else:
            purpose = f'Compute the {operation} of {target_column} in "{file_path}"'

    tool_call = _build_tool_call(
        file_path,
        operation,
        target_column,
        sheet_name,
        associated_column,
    )

    step = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Analyze table",
        "purpose": purpose,
        "expected_outcome": expected_outcome,
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [file_path],
        "agent": "structured_data_analysis",
        "depends_on": [],
        "tool_call": tool_call,
        "capability_metadata": {
            "capability_id": "structured_data_analysis",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_structured_data_analysis",
            "allowed_tool_family": "structured_data_analysis",
            "allowed_tool": "analyze_table",
            "operation": operation,
            "target_column": target_column,
            "sheet_name": sheet_name,
            "associated_column": associated_column,
        },
    }

    return {
        "id": None,
        "name": "structured_data_analysis_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step],
        "approval_required": False,
    }

"""Structured Data Analysis Capability — F5A/F5B-1 bounded deterministic compiler.

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 9 / STRUCTURED_DATA_ANALYSIS_CONTRACT_V1:
- High-confidence explicit local CSV/XLSX aggregate analysis only
- No LLM. No system_entry import. No execution.
- Emits explicit one-step candidate workflow with allowed_tool=analyze_table.
- Declines ambiguous, multi-file, unsupported-operation, and mixed-domain prompts.

F5R additive: TableAnalysisPlanV1 metadata is attached to every compiled step as
capability_metadata.table_analysis_plan. The plan is OPTIONAL additive metadata only.
It does NOT replace tool_call (which remains a string), does NOT alter governance,
does NOT replace system_entry authority.

Supported operations:
- overview
- count_rows
- max / maximum / highest
- min / minimum / lowest
- sum / total
- average / mean
- filter (F5B-1: single-predicate, one column, approved operators only)
"""

import json
import re
from typing import Any


# F5R plan-mode token must match the value expected by analyze_table.run().
_PLAN_MODE_OPERATION_TOKEN = "__table_analysis_plan_v1__"


def _build_single_op_plan(
    file_path: str,
    operation: str,
    column: str | None = None,
    associated_column: str | None = None,
    filter_op: str | None = None,
    filter_value: str | None = None,
    filter_value_to: str | None = None,
    sheet: str | None = None,
) -> dict | None:
    """Build a TableAnalysisPlanV1 for a single operation.

    Returns None on ImportError so compilation degrades gracefully rather than
    failing if the structured_data package is unavailable.
    """
    try:
        from system.orchestrator.structured_data.table_analysis_plan import (
            build_single_op_plan,
        )
        return build_single_op_plan(
            source_path=file_path,
            operation_type=operation,
            operation_id=f"op_{operation}",
            column=column,
            associated_column=associated_column,
            filter_op=filter_op,
            filter_value=filter_value,
            filter_value_to=filter_value_to,
            sheet=sheet,
        )
    except ImportError:
        return None


def _validate_plan_or_none(plan: dict | None) -> dict | None:
    """Defensive validation at the capability/compiler boundary.

    Returns the plan only if it passes TableAnalysisPlanV1 validation.
    Returns None otherwise so the caller can fall back safely.
    """
    if plan is None:
        return None
    try:
        from system.orchestrator.structured_data.table_analysis_plan import (
            validate_plan,
        )
    except ImportError:
        return None
    if validate_plan(plan)["status"] != "success":
        return None
    return plan


def _serialize_plan(plan: dict) -> str:
    """Deterministic JSON serialization for lowering into a tool_call string."""
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def _build_plan_mode_tool_call(file_path: str, plan: dict) -> str:
    """Build a shlex-safe USE_TOOL directive carrying a TableAnalysisPlanV1.

    Preserves the legacy 8-argument manifest order:
      path, operation-token, serialized-plan, sheet, assoc, filter-op, filter-val, filter-val-to
    The legacy positional fields are populated from the plan for human readability
    and compatibility; the serialized plan in the third argument is authoritative.
    """
    serialized = _serialize_plan(plan)
    # Escape backslashes and double quotes so the quoted JSON survives shlex.split.
    escaped = serialized.replace("\\", "\\\\").replace('"', '\\"')

    source = plan.get("source", {}) if isinstance(plan, dict) else {}
    operations = plan.get("operations", []) if isinstance(plan, dict) else []
    first_op = operations[0] if operations and isinstance(operations[0], dict) else {}

    sheet = source.get("sheet") or ""
    associated = first_op.get("associated_column") or ""
    filter_op = first_op.get("filter_op") or ""
    filter_value = first_op.get("filter_value") or ""
    filter_value_to = first_op.get("filter_value_to") or ""

    args = [
        file_path.replace("\\", "/"),
        _PLAN_MODE_OPERATION_TOKEN,
        escaped,
        sheet.replace("\\", "/") if isinstance(sheet, str) else "",
        associated.replace("\\", "/") if isinstance(associated, str) else "",
        filter_op.replace("\\", "/") if isinstance(filter_op, str) else "",
        filter_value.replace("\\", "/") if isinstance(filter_value, str) else "",
        filter_value_to.replace("\\", "/") if isinstance(filter_value_to, str) else "",
    ]
    quoted = " ".join(f'"{a}"' for a in args)
    return f"USE_TOOL: analyze_table {quoted}"


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
    # "filter" removed — F5B-1 single-predicate filter is now supported.
    # "sort" not a keyword block here; non-matching grammar returns None naturally.
    "group by", "groupby",
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

# === F5B-1 Filter grammar ===
# Approved filter operators mapped from natural-language tokens (longest-first lookup).
_FILTER_OP_MAP = {
    "is greater than or equal to": "gte",
    "is less than or equal to": "lte",
    "greater than or equal to": "gte",
    "less than or equal to": "lte",
    "does not contain": "not_contains",
    "do not contain": "not_contains",
    "not contains": "not_contains",
    "does not equal": "neq",
    "do not equal": "neq",
    "not equal": "neq",
    "is not blank": "is_not_blank",
    "is not empty": "is_not_blank",
    "is between": "between",
    "is greater than": "gt",
    "is less than": "lt",
    "is at least": "gte",
    "is at most": "lte",
    "greater than": "gt",
    "less than": "lt",
    "starts with": "starts_with",
    "start with": "starts_with",
    "begins with": "starts_with",
    "begin with": "starts_with",
    "ends with": "ends_with",
    "end with": "ends_with",
    "contains": "contains",
    "between": "between",
    "is blank": "is_blank",
    "is empty": "is_blank",
    "is not": "neq",
    "equals": "eq",
    "equal": "eq",
    "is": "eq",
    "!=": "neq",
    "<>": "neq",
    ">=": "gte",
    "<=": "lte",
    ">": "gt",
    "<": "lt",
    "==": "eq",
    "=": "eq",
}

# Sorted longest-first so multi-word operators match before sub-tokens.
_FILTER_OP_TOKENS_SORTED = sorted(_FILTER_OP_MAP.keys(), key=len, reverse=True)

# Reject composed / multi-predicate patterns BEFORE attempting extraction.
# The between-and form ("between X and Y") must be stripped first.
_BETWEEN_STRIP_RE = re.compile(
    r'\bbetween\s+(?:"[^"]+"|[^\s,]+)\s+and\s+(?:"[^"]+"|[^\s,]+)',
    re.IGNORECASE,
)

# Strip approved multi-word operator phrases that contain 'and' or 'or' before
# checking for composition markers. This prevents false positives on:
# "greater than or equal to", "less than or equal to"
_OPERATOR_PHRASE_STRIP_RE = re.compile(
    r'\b(?:greater\s+than\s+or\s+equal\s+to|less\s+than\s+or\s+equal\s+to'
    r'|is\s+not\s+blank|is\s+not\s+empty'
    r'|does\s+not\s+contain|does\s+not\s+equal'
    r'|do\s+not\s+contain|do\s+not\s+equal'
    r'|not\s+contains|not\s+equal)\b',
    re.IGNORECASE,
)

_COMPOSED_FILTER_RE = re.compile(
    r'\b(?:and\s+(?!\d)|or\s+(?!\d))\b'
    r'|&&|\|\|'
    r'|\b(?:sort(?:ed)?\s+by|order\s+by|rank|top\s+\d|bottom\s+\d|group\s+by|having)\b'
    r'|\b(?:sum|count|average|max|min)\s+where\b',
    re.IGNORECASE,
)

# Pattern: rows where <Column> is blank / is not blank
_FILTER_BLANK_RE = re.compile(
    r'\b(?:show|find|list|get|return)?\s*rows?\s+where\s+'
    r'([A-Za-z][A-Za-z0-9_ ]*?)\s+'
    r'(is\s+not\s+blank|is\s+not\s+empty|is\s+blank|is\s+empty)'
    r'(?:\s+in\s+["\']|\s*$|\s*\.)',
    re.IGNORECASE,
)

# Pattern: rows where <Column> is between X and Y
_FILTER_BETWEEN_RE = re.compile(
    r'\b(?:show|find|list|get|return)?\s*rows?\s+where\s+'
    r'([A-Za-z][A-Za-z0-9_ ]*?)\s+'
    r'is\s+between\s+("[ ^"]+"|[^\s,]+)\s+and\s+("[ ^"]+"|[^\s,]+)'
    r'(?:\s+in\s+["\']|\s*$|\s*\.)',
    re.IGNORECASE,
)

# Pattern: rows where <Column> <operator> <value>  (general form)
# Operator alternatives are inserted dynamically.
_FILTER_GENERAL_TEMPLATE = (
    r'\b(?:show|find|list|get|return)?\s*rows?\s+where\s+'
    r'([A-Za-z][A-Za-z0-9_ ]*?)\s+'
    r'({ops})'
    r'\s+("[ ^"]*"|\S+)'
    r'(?:\s+in\s+["\']|\s*$|\s*\.)'
)


def _build_filter_general_re():
    ops_part = '|'.join(re.escape(t) for t in _FILTER_OP_TOKENS_SORTED)
    return re.compile(
        _FILTER_GENERAL_TEMPLATE.format(ops=ops_part),
        re.IGNORECASE,
    )


_FILTER_GENERAL_RE = _build_filter_general_re()


def _has_composed_filter(user_input: str) -> bool:
    """Return True if prompt contains multi-predicate / composed filter signals."""
    # Strip 'between X and Y' first, then strip operator phrases containing 'and'/'or',
    # then check for remaining composition markers.
    scrubbed = _BETWEEN_STRIP_RE.sub("BETWEEN_PLACEHOLDER", user_input)
    scrubbed = _OPERATOR_PHRASE_STRIP_RE.sub("OP_PLACEHOLDER", scrubbed)
    return bool(_COMPOSED_FILTER_RE.search(scrubbed))


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _classify_filter_operation(user_input: str):
    """
    Attempt to extract a single F5B-1 filter predicate from user_input.

    Returns (column, filter_op_code, filter_value, filter_value_to, sheet_name)
    or None if not deterministically parseable.
    """
    if _has_composed_filter(user_input):
        return None

    # Must contain 'rows where' grammar.
    if not re.search(r'\brows?\s+where\b', user_input, re.IGNORECASE):
        return None

    # Must contain exactly one CSV/XLSX file path.
    paths = _extract_csv_xlsx_paths(user_input)
    if len(paths) != 1:
        return None

    sheet_name = None
    sheet_m = _SHEET_NAME_RE.search(user_input)
    if sheet_m:
        sheet_name = (sheet_m.group(1) or sheet_m.group(2) or "").strip()

    # --- blank / not_blank (no value) ---
    blank_m = _FILTER_BLANK_RE.search(user_input)
    if blank_m:
        col = blank_m.group(1).strip()
        op_text = blank_m.group(2).strip().lower()
        op_text = re.sub(r'\s+', ' ', op_text)
        op_code = _FILTER_OP_MAP.get(op_text)
        if op_code and _is_valid_column_name(col):
            return (col, op_code, "", "", sheet_name)

    # --- between X and Y ---
    between_m = _FILTER_BETWEEN_RE.search(user_input)
    if between_m:
        col = between_m.group(1).strip()
        val_lo = _strip_quotes(between_m.group(2))
        val_hi = _strip_quotes(between_m.group(3))
        if _is_valid_column_name(col) and val_lo and val_hi:
            return (col, "between", val_lo, val_hi, sheet_name)

    # --- general operator form ---
    gen_m = _FILTER_GENERAL_RE.search(user_input)
    if gen_m:
        col = gen_m.group(1).strip()
        op_text = gen_m.group(2).strip().lower()
        op_text = re.sub(r'\s+', ' ', op_text)
        raw_val = _strip_quotes(gen_m.group(3))
        op_code = _FILTER_OP_MAP.get(op_text)
        if op_code and _is_valid_column_name(col) and raw_val:
            return (col, op_code, raw_val, "", sheet_name)

    return None


def _classify_filter_intent(user_input: str):
    """
    Detect and classify F5B-1 filter intent.

    Returns (operation, target_column, associated_column,
             filter_op, filter_value, filter_value_to, sheet_name)
    or None if not a filter prompt.
    """
    result = _classify_filter_operation(user_input)
    if result is None:
        return None
    col, op_code, val, val_to, sheet_name = result
    return ("filter", col, None, op_code, val, val_to, sheet_name)


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
    """Return True only for high-confidence bounded F5A/F5B-1 analysis grammar."""
    if not user_input or not isinstance(user_input, str):
        return False
    paths = _extract_csv_xlsx_paths(user_input)
    if len(paths) != 1:
        return False
    if _contains_unsupported_keywords(user_input):
        return False
    # F5B-1: check single-predicate filter intent first.
    if _classify_filter_intent(user_input) is not None:
        return True
    op_info = _classify_operation(user_input)
    if op_info is None:
        return False
    return True


def _build_tool_call(file_path: str, plan: dict) -> str:
    """Build a shlex-safe USE_TOOL directive carrying a TableAnalysisPlanV1.

    The legacy 8-argument signature is preserved:
      path, operation-token, serialized-plan, sheet, assoc, filter-op, filter-val, filter-val-to
    The actual plan (source, operations, bounds, trust metadata shape) is carried
    as a deterministic JSON string in the third positional argument.
    """
    return _build_plan_mode_tool_call(file_path, plan)


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

    file_path = paths[0].replace("\\", "/")

    # --- F5B-1: filter path (checked before F5A aggregates) ---
    filter_info = _classify_filter_intent(user_input)
    if filter_info is not None:
        _op, target_column, _, filter_op, filter_value, filter_value_to, sheet_name = filter_info
        pred_desc = f"{target_column} {filter_op} {filter_value}".strip()
        purpose = f'Filter rows in "{file_path}" where {pred_desc}'
        expected_outcome = f"Matched rows returned for filter predicate on {target_column}"
        table_analysis_plan = _build_single_op_plan(
            file_path=file_path,
            operation="filter",
            column=target_column,
            filter_op=filter_op,
            filter_value=filter_value,
            filter_value_to=filter_value_to,
            sheet=sheet_name,
        )
        tool_call = _build_tool_call(file_path, table_analysis_plan)
        step = {
            "id": "step_1",
            "type": "EXECUTE_API",
            "name": "Filter table rows",
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
                "operation": "filter",
                "target_column": target_column,
                "sheet_name": sheet_name,
                "associated_column": None,
                "filter_op": filter_op,
                "filter_value": filter_value,
                "filter_value_to": filter_value_to,
                "table_analysis_plan": table_analysis_plan,
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

    # --- F5A: aggregate / overview operations ---
    op_info = _classify_operation(user_input)
    if op_info is None:
        return None

    operation, target_column, associated_column = op_info
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

    table_analysis_plan = _build_single_op_plan(
        file_path=file_path,
        operation=operation,
        column=target_column,
        associated_column=associated_column,
        sheet=sheet_name,
    )

    tool_call = _build_tool_call(file_path, table_analysis_plan)

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
            "table_analysis_plan": table_analysis_plan,
        },
    }

    return {
        "id": None,
        "name": "structured_data_analysis_workflow",
        "status": "QUEUED",
        "profile_name": "StructuredDataAnalysisProfile",
        "goal": user_input,
        "steps": [step],
        "approval_required": False,
    }


def is_structured_data_analysis_intent(user_input: str) -> bool:
    """Return True when the prompt is clearly a bounded structured-data analysis request.

    This is intentionally broader than compile_structured_data_analysis_workflow:
    it also returns True for non-trivial composed requests that must be routed to the
    Planner/AG1 for interpretation, so the capability router can emit a fallback to
    StructuredDataAnalysisProfile instead of letting the prompt leak into other
    capability routes.
    """
    if not user_input or not isinstance(user_input, str):
        return False

    paths = _extract_csv_xlsx_paths(user_input)
    if len(paths) != 1:
        return False

    if _contains_unsupported_keywords(user_input):
        return False

    # Simple deterministic fast paths already owned by the capability.
    if _classify_filter_intent(user_input) is not None:
        return True
    if _classify_operation(user_input) is not None:
        return True

    # Non-trivial composed filter/sort intent: Planner/AG1 must own interpretation.
    # Limit to multi-predicate / filter+sort grammar; leave sort-only, top-N,
    # group-by, median, and semantic prompts for document_local_read unsupported path.
    if (
        re.search(r'\brows?\s+where\b', user_input, re.IGNORECASE)
        and _has_composed_filter(user_input)
    ):
        return True

    return False


def validate_and_build_structured_data_workflow(
    user_input: str,
    table_analysis_plan: dict,
) -> dict | None:
    """Validate a Planner/AG1-produced TableAnalysisPlanV1 and lower it to a workflow.

    This is the StructuredDataAnalysisCapability validation/lowerer boundary.
    It does NOT perform natural-language interpretation. It checks version, source,
    operation grammar, bounds, ordering, coverage, and profile/tool boundaries,
    then emits the existing string plan-mode tool_call.
    """
    plan = _validate_plan_or_none(table_analysis_plan)
    if plan is None:
        return None

    source = plan.get("source", {})
    file_path = (source.get("path") or "").replace("\\", "/")
    if not file_path:
        return None

    tool_call = _build_tool_call(file_path, plan)

    operations = plan.get("operations", [])
    filter_ops = [op for op in operations if op.get("type") == "filter"]
    sort_ops = [op for op in operations if op.get("type") == "sort"]

    if filter_ops and sort_ops:
        name = "Multi-filter and sort table rows"
        expected_outcome = "Matched rows returned for composed filter+sort sequence"
    elif len(filter_ops) > 1:
        name = "Multi-filter table rows"
        expected_outcome = "Matched rows returned for multi-predicate filter"
    elif sort_ops:
        name = "Sort table rows"
        expected_outcome = "Rows returned sorted by requested column"
    else:
        name = "Analyze table"
        expected_outcome = "Structured-data operation completed"

    step = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": name,
        "purpose": user_input,
        "expected_outcome": expected_outcome,
        "risk": "LOW",
        "importance": "LOW",
        "estimated_complexity": "low",
        "resource_targets": [file_path],
        "agent": "structured_data_analysis",
        "depends_on": [],
        "tool_call": tool_call,
        "capability_metadata": {
            "capability_id": "structured_data_analysis",
            "route_confidence": 1.0,
            "route_reason_code": "planner_owned_composed_plan",
            "allowed_tool_family": "structured_data_analysis",
            "allowed_tool": "analyze_table",
            "table_analysis_plan": plan,
        },
    }

    return {
        "id": None,
        "name": "structured_data_analysis_workflow",
        "status": "QUEUED",
        "profile_name": "StructuredDataAnalysisProfile",
        "goal": user_input,
        "steps": [step],
        "approval_required": False,
    }

"""Planner-owned deterministic TableAnalysisPlanV1 builder.

Per STRUCTURED_DATA_ANALYSIS_CONTRACT_V1 sections 22-24 and the SA verdict:
- The Planner/AG1 owns non-trivial natural-language interpretation.
- StructuredDataAnalysisCapability owns domain validation, coverage, bounds,
  trust classification, and lowering.
- This module is a deterministic planner-side interpreter for the bounded
  multi-predicate + optional sort grammar only.

It does NOT execute tools, access the filesystem, or emit lifecycle events.
"""

from __future__ import annotations

import json
import re
from typing import Any

from system.orchestrator.structured_data.table_analysis_plan import (
    build_multi_filter_sort_plan,
    validate_plan,
)

# === Shared deterministic grammar (mirrors capability vocabulary) ===

# Column names that are deterministically not headers.
_INVALID_COLUMN_NAMES = frozenset([
    "the", "a", "an", "in", "of", "from", "to", "for", "with", "by", "on", "at",
    "column", "columns", "row", "rows", "sheet", "sheets", "and", "or",
])

# Approved filter operators mapped from natural-language tokens (longest-first).
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

_FILTER_OP_TOKENS_SORTED = sorted(_FILTER_OP_MAP.keys(), key=len, reverse=True)

# CSV/XLSX path extraction.
_CSV_XLSX_PATH_RE = re.compile(
    r'["\']([^"\']+?\.(?:csv|xlsx|xls|xlsm?))["\']'
    r'|(?:^|\s)([a-zA-Z0-9_./\\~ -]*[\\/][a-zA-Z0-9_./\\~ -]*\.(?:csv|xlsx|xls|xlsm?)'
    r'|[a-zA-Z]:[\\/][a-zA-Z0-9_./\\~ -]*\.(?:csv|xlsx|xls|xlsm?)'
    r'|[a-zA-Z0-9_ -]*\.(?:csv|xlsx|xls|xlsm?))'
    r'(?=\s|$|[.,;!?])',
    re.IGNORECASE,
)

# Sheet name extraction.
_SHEET_NAME_RE = re.compile(
    r'\b(?:in|on)\s+(?:the\s+)?["\']([^"\']+)["\']\s+sheet'
    r'|\b(?:in|on)\s+(?:the\s+)?sheet\s+["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# Multi-predicate / composition markers.
_BETWEEN_STRIP_RE = re.compile(
    r'\bbetween\s+(?:"[^"]+"|[^\s,]+)\s+and\s+(?:"[^"]+"|[^\s,]+)',
    re.IGNORECASE,
)

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

_MULTI_BETWEEN_RE = re.compile(
    r'\b([A-Za-z][A-Za-z0-9_ ]*?)\s+is\s+between\s+("[^"]+"|[^\s,]+)\s+and\s+("[^"]+"|[^\s,]+)',
    re.IGNORECASE,
)

_SORT_BY_RE = re.compile(
    r'\b(?:then\s+)?sort(?:ed)?\s+by\s+([A-Za-z][A-Za-z0-9_]*)\s*(ascending|descending|asc|desc)?\b',
    re.IGNORECASE,
)


_STRUCTURED_DATA_UNSUPPORTED_KEYWORDS = frozenset([
    "web", "website", "url", "http", "https", "internet", "browse",
    "search the web", "search online", "google", "find online",
    "download", "upload", "email", "send mail",
    "compare", "correlation", "pivot", "chart", "graph", "plot",
    "formula", "macro", "vba", "script", "python", "pandas",
    "group by", "groupby",
    "join", "merge", "union",
    "why", "reason", "reasons", "meaning", "means", "explain why",
    "insight", "insights", "interesting", "pattern", "patterns",
    "predict", "prediction", "forecast", "recommend", "recommendation",
    "business decision", "business decisions", "decision",
    "cause", "causes", "causal", "trend", "trends",
    "unusual", "anomaly", "anomalies", "relationship", "relationships",
])


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _is_valid_column_name(name: str | None) -> bool:
    if not name:
        return False
    return name.strip().lower() not in _INVALID_COLUMN_NAMES


def _extract_csv_xlsx_paths(user_input: str) -> list[str]:
    """Return all CSV/XLSX file paths found in the input (quoted or unquoted)."""
    matches = _CSV_XLSX_PATH_RE.findall(user_input)
    paths = []
    for match in matches:
        path = next((g for g in match if g), None)
        if path:
            path = path.strip()
            ext = path.rsplit(".", 1)[-1].lower()
            if ext in {"csv", "xlsx"}:
                paths.append(path)
    return paths


def _extract_sheet_name(user_input: str) -> str | None:
    m = _SHEET_NAME_RE.search(user_input)
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").strip()


def _contains_unsupported_keywords(user_input: str) -> bool:
    lower = user_input.lower()
    return any(kw in lower for kw in _STRUCTURED_DATA_UNSUPPORTED_KEYWORDS)


def _has_or_composition(user_input: str) -> bool:
    """Detect explicit OR composition while allowing numeric/or-in-value cases."""
    scrubbed = _BETWEEN_STRIP_RE.sub(" BETWEEN_PLACEHOLDER ", user_input)
    scrubbed = _OPERATOR_PHRASE_STRIP_RE.sub(" OP_PLACEHOLDER ", scrubbed)
    return bool(re.search(r'\bor\s+(?!\d)\b|\|\|', scrubbed, re.IGNORECASE))


def _has_composed_filter(user_input: str) -> bool:
    """Return True if prompt contains multi-predicate / composed filter signals."""
    scrubbed = _BETWEEN_STRIP_RE.sub("BETWEEN_PLACEHOLDER", user_input)
    scrubbed = _OPERATOR_PHRASE_STRIP_RE.sub("OP_PLACEHOLDER", scrubbed)
    return bool(_COMPOSED_FILTER_RE.search(scrubbed))


def _parse_predicate_segment(segment: str) -> dict | None:
    """Parse a single predicate segment into a filter dict."""
    segment = segment.strip()
    if not segment:
        return None

    # Drop trailing 'in <path>' noise that may have been captured.
    segment = re.sub(r'\s+in\s+["\'][^"\']*["\']?\s*$', '', segment, flags=re.IGNORECASE).strip()
    segment = re.sub(r'[.,;!]$', '', segment)

    for op_text in _FILTER_OP_TOKENS_SORTED:
        pattern = re.compile(r'\b' + re.escape(op_text) + r'\b', re.IGNORECASE)
        m = pattern.search(segment)
        if not m:
            continue
        column = segment[:m.start()].strip()
        value = segment[m.end():].strip()
        value = re.sub(r'\s+in\s+["\'][^"\']*["\']?\s*$', '', value, flags=re.IGNORECASE).strip()
        value = re.sub(r'[.,;!]$', '', value)
        op_code = _FILTER_OP_MAP[op_text]
        if not _is_valid_column_name(column):
            return None
        if op_code in ("is_blank", "is_not_blank"):
            return {"column": column, "filter_op": op_code, "filter_value": "", "filter_value_to": ""}
        if not value:
            return None
        return {
            "column": column,
            "filter_op": op_code,
            "filter_value": _strip_quotes(value),
            "filter_value_to": "",
        }
    return None


def _extract_predicate_text(user_input: str) -> str | None:
    """Return the predicate clause between 'rows where' and the path/sort clause."""
    where_m = re.search(r'\brows?\s+where\b', user_input, re.IGNORECASE)
    if not where_m:
        return None
    start = where_m.end()

    paths = _extract_csv_xlsx_paths(user_input)
    if not paths:
        return None
    path = paths[0]

    end = user_input.lower().rfind(path.lower())
    if end == -1:
        end = len(user_input)

    sort_m = _SORT_BY_RE.search(user_input)
    if sort_m and sort_m.start() < end:
        end = sort_m.start()

    return user_input[start:end].strip()


def try_build_table_analysis_plan(user_input: str) -> dict | None:
    """
    Build a TableAnalysisPlanV1 for a bounded multi-predicate + optional sort request.

    Returns None if the prompt is not deterministically parseable as a non-trivial
    structured-data request within the approved grammar.
    """
    if not user_input or not isinstance(user_input, str):
        return None

    paths = _extract_csv_xlsx_paths(user_input)
    if len(paths) != 1:
        return None

    if not re.search(r'\brows?\s+where\b', user_input, re.IGNORECASE):
        return None

    if _contains_unsupported_keywords(user_input):
        return None

    if _has_or_composition(user_input):
        return None

    if not _has_composed_filter(user_input):
        return None

    predicate_text = _extract_predicate_text(user_input)
    if not predicate_text:
        return None

    file_path = paths[0].replace("\\", "/")
    sheet_name = _extract_sheet_name(user_input)

    between_predicates: list[dict[str, Any]] = []

    def _capture_between(m: re.Match) -> str:
        column = m.group(1).strip()
        if not _is_valid_column_name(column):
            return ""
        between_predicates.append({
            "column": column,
            "filter_op": "between",
            "filter_value": _strip_quotes(m.group(2)),
            "filter_value_to": _strip_quotes(m.group(3)),
        })
        return " BETWEEN_PREDICATE "

    scrubbed_text = _MULTI_BETWEEN_RE.sub(_capture_between, predicate_text)

    parts = re.split(r'\band\b', scrubbed_text, flags=re.IGNORECASE)
    predicates = list(between_predicates)
    for part in parts:
        part = part.strip()
        if not part or part == "BETWEEN_PREDICATE":
            continue
        parsed = _parse_predicate_segment(part)
        if parsed is None:
            return None
        predicates.append(parsed)

    if not predicates:
        return None

    sort_column = None
    sort_direction = None
    sort_m = _SORT_BY_RE.search(user_input)
    if sort_m:
        sort_column = sort_m.group(1).strip()
        sort_direction = (sort_m.group(2) or "asc").lower()
        if sort_direction == "ascending":
            sort_direction = "asc"
        elif sort_direction == "descending":
            sort_direction = "desc"
        if not _is_valid_column_name(sort_column):
            return None

    plan = build_multi_filter_sort_plan(
        source_path=file_path,
        filters=predicates,
        sort_column=sort_column,
        sort_direction=sort_direction,
        sheet=sheet_name,
    )

    if validate_plan(plan)["status"] != "success":
        return None
    return plan


# === Planner-output proposal parser (F5R-FIX3) =================================
# This parser validates a structured TableAnalysisPlanV1 proposal produced by
# the Planner/LLM. It does NOT construct the plan from raw user text.

_MAX_PLAN_PROPOSAL_BYTES = 8192

_CANONICAL_FILTER_OPERATORS = frozenset([
    "eq", "neq", "gt", "gte", "lt", "lte",
    "contains", "not_contains", "starts_with", "ends_with",
    "between", "is_blank", "is_not_blank",
])

_OPERATOR_ALIASES = {
    "equals": "eq",
    "equal": "eq",
    "is": "eq",
    "==": "eq",
    "=": "eq",
    "not equals": "neq",
    "not equal": "neq",
    "!=": "neq",
    "<>": "neq",
    "greater than": "gt",
    ">": "gt",
    "greater than or equal to": "gte",
    ">=": "gte",
    "less than": "lt",
    "<": "lt",
    "less than or equal to": "lte",
    "<=": "lte",
    "starts with": "starts_with",
    "begins with": "starts_with",
    "ends with": "ends_with",
    "does not contain": "not_contains",
    "does not equal": "neq",
    "is not blank": "is_not_blank",
    "is not empty": "is_not_blank",
    "is blank": "is_blank",
    "is empty": "is_blank",
    "is between": "between",
}


def _canonicalize_operator(op: str | None) -> str | None:
    if not isinstance(op, str):
        return None
    op = op.strip().lower()
    op = _OPERATOR_ALIASES.get(op, op)
    return op if op in _CANONICAL_FILTER_OPERATORS else None


def _canonicalize_direction(direction: str | None) -> str | None:
    if not isinstance(direction, str):
        return None
    d = direction.strip().lower()
    if d in ("asc", "ascending"):
        return "asc"
    if d in ("desc", "descending"):
        return "desc"
    return None


def _source_path_looks_local(path: Any) -> bool:
    if not isinstance(path, str):
        return False
    p = path.strip().lower()
    return p.endswith((".csv", ".xlsx", ".xls", ".xlsm"))


def _request_mentions_sort(user_input: str) -> bool:
    return bool(_SORT_BY_RE.search(user_input or ""))


def _request_mentions_and_predicate(user_input: str) -> bool:
    """Return True if the raw request has 'rows where ... and ...' before the path/sort."""
    text = user_input or ""
    where_m = re.search(r'\brows?\s+where\b', text, re.IGNORECASE)
    if not where_m:
        return False
    tail = text[where_m.end():]
    # Strip trailing path and sort clauses so we only inspect the predicate area.
    paths = _extract_csv_xlsx_paths(text)
    if paths:
        idx = tail.lower().rfind(paths[0].lower())
        if idx != -1:
            tail = tail[:idx]
    sort_m = _SORT_BY_RE.search(text)
    if sort_m:
        tail = tail[:sort_m.start() - where_m.end()]
    return bool(re.search(r'\band\b', tail, re.IGNORECASE))


def extract_table_analysis_plan_from_planner_output(raw_text: str) -> dict | None:
    """
    Extract a TableAnalysisPlanV1 dict from raw Planner/LLM text.

    Accepts either:
      - a direct TableAnalysisPlanV1 JSON object; or
      - a wrapper object containing {"table_analysis_plan_v1_proposal": {...}}.

    Returns the plan dict, or None if no valid plan structure is found.
    """
    if not isinstance(raw_text, str):
        return None

    raw = raw_text.strip()
    if not raw:
        return None

    # Strip optional markdown fences.
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()

    # Require at least one JSON object.
    if "{" not in raw:
        return None

    start = raw.index("{")
    raw = raw[start:]
    end = raw.rfind("}")
    if end == -1:
        return None
    raw = raw[: end + 1]

    try:
        parsed = json.loads(raw)
    except Exception:
        return None

    if not isinstance(parsed, dict):
        return None

    # Wrapped proposal (legacy/test mock shape).
    if "table_analysis_plan_v1_proposal" in parsed:
        proposal = parsed["table_analysis_plan_v1_proposal"]
        if isinstance(proposal, dict):
            return proposal
        return None

    # Direct plan object (dedicated contract).
    if parsed.get("version") == "TableAnalysisPlanV1":
        return parsed

    return None


def parse_planner_table_analysis_proposal(
    parsed_planner_output: dict,
    user_input: str | None = None,
) -> dict | None:
    """
    Extract and validate a TableAnalysisPlanV1 proposal from Planner JSON output.

    Returns a plan dict ready for the capability validator/lowering, or None if
    no valid proposal is present.

    This function does NOT interpret raw user text into operations. It only
    validates the Planner's structured proposal.

    Accepts either a wrapper dict or a direct TableAnalysisPlanV1 dict.
    """
    if not isinstance(parsed_planner_output, dict):
        return None

    proposal = parsed_planner_output.get("table_analysis_plan_v1_proposal")
    if proposal is None and parsed_planner_output.get("version") == "TableAnalysisPlanV1":
        proposal = parsed_planner_output
    if not isinstance(proposal, dict):
        return None

    # Bounded payload guard
    try:
        proposal_size = len(json.dumps(proposal).encode("utf-8"))
    except Exception:
        return None
    if proposal_size > _MAX_PLAN_PROPOSAL_BYTES:
        return None

    # Version
    if proposal.get("version") != "TableAnalysisPlanV1":
        return None

    # Guard against unsupported composed semantics that the Planner should not
    # have emitted in a verified TableAnalysisPlanV1 proposal.
    if _contains_unsupported_keywords(user_input or ""):
        return None
    if _has_or_composition(user_input or ""):
        return None

    # Source
    source = proposal.get("source")
    if not isinstance(source, dict):
        return None
    source_path = source.get("path")
    if not _source_path_looks_local(source_path):
        return None

    # If the raw request names explicit source path(s), the proposal source must
    # match one of them. This prevents hallucinated or swapped file paths.
    raw_paths = _extract_csv_xlsx_paths(user_input or "")
    if raw_paths:
        normalized_raw = {p.replace("\\", "/").lower() for p in raw_paths}
        if str(source_path).replace("\\", "/").lower() not in normalized_raw:
            return None

    sheet = source.get("sheet")

    # Operations
    operations = proposal.get("operations")
    if not isinstance(operations, list) or not operations:
        return None
    if len(operations) > 8:
        return None

    normalized_ops: list[dict[str, Any]] = []
    op_ids: set[str] = set()
    predicate_count = 0
    sort_count = 0

    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            return None
        op_id = op.get("operation_id")
        if not isinstance(op_id, str) or not op_id.strip():
            return None
        op_id = op_id.strip()
        if op_id in op_ids:
            return None
        op_ids.add(op_id)

        op_type = op.get("type")
        column = op.get("column")
        if op_type == "filter":
            predicate_count += 1
            operator = _canonicalize_operator(op.get("operator"))
            if operator is None:
                return None
            value = op.get("value")
            if value is None:
                value = ""
            if not isinstance(value, str):
                value = str(value)
            value_to = op.get("value_to") or ""
            if not isinstance(value_to, str):
                value_to = str(value_to)
            if operator in ("is_blank", "is_not_blank"):
                value = ""
                value_to = ""
            if operator == "between" and not value_to.strip():
                return None
            normalized_ops.append({
                "operation_id": op_id,
                "type": "filter",
                "column": column,
                "filter_op": operator,
                "filter_value": value,
                "filter_value_to": value_to,
            })
        elif op_type == "sort":
            sort_count += 1
            if sort_count > 1:
                return None
            direction = _canonicalize_direction(op.get("direction"))
            if direction is None:
                return None
            if not isinstance(column, str) or not column.strip():
                return None
            normalized_ops.append({
                "operation_id": op_id,
                "type": "sort",
                "column": column,
                "direction": direction,
            })
        else:
            return None

    if predicate_count > 6:
        return None

    # Shallow completeness guards: reject partial plans the Planner failed to fully
    # produce. These checks are NOT used to construct operations from raw text.
    if _request_mentions_sort(user_input or "") and sort_count == 0:
        return None
    if _request_mentions_and_predicate(user_input or "") and predicate_count < 2:
        return None

    # requested_operations must reference exactly produced operation IDs
    requested = proposal.get("requested_operations")
    if not isinstance(requested, list) or not requested:
        return None
    if any(r not in op_ids for r in requested):
        return None

    # result_operation must be one of the produced operation IDs
    result_op = proposal.get("result_operation")
    if not isinstance(result_op, str) or result_op not in op_ids:
        return None

    # bounds
    bounds = proposal.get("bounds")
    if not isinstance(bounds, dict):
        bounds = {}

    plan = {
        "version": "TableAnalysisPlanV1",
        "source": {
            "path": str(source_path).replace("\\", "/"),
            "sheet": sheet if isinstance(sheet, str) else None,
        },
        "operations": normalized_ops,
        "requested_operations": list(requested),
        "result_operation": result_op,
        "bounds": {
            "max_operations": int(bounds.get("max_operations", 8)),
            "max_predicates": int(bounds.get("max_predicates", 6)),
            "max_rows_scanned": int(bounds.get("max_rows_scanned", 10000)),
            "max_rows_returned": int(bounds.get("max_rows_returned", 1000)),
        },
        "trust": {
            "class": "verified",
            "verification_status": "pending_execution",
        },
    }

    vp = validate_plan(plan)
    if vp["status"] != "success":
        return None
    return plan

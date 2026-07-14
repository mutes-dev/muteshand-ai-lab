INPUT_SPEC = {
    "path": "string",
    "operation": "string",
    "target_column": "string",
    "sheet_name": "string",
    "associated_column": "string",
}

import csv
import datetime
import os
import re
import sys
from decimal import Decimal, InvalidOperation

BASE_PATH = os.path.abspath("E:/MutesHand")

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MAX_DATA_ROWS = 10000
MAX_COLUMNS = 100
MAX_WORKSHEETS = 1
MAX_TIED_ROWS = 100
MAX_CELL_CHARS = 500
MAX_OFFENDING_CELLS = 50

_ALLOWED_OPERATIONS = {"count_rows", "max", "min", "sum", "average", "overview"}

# Reuse name-like detection from resolve_table_reference to keep semantics identical.
_NAME_LIKE_HEADER_RE = re.compile(
    r"\b(?:name|names|person|people|user|users|entity|entities|contact|customer|client|"
    r"full\s*name|first\s*name|last\s*name)\b",
    re.IGNORECASE,
)


_NAME_LIKE_COLUMN_SENTINEL = "__AUTO_NAME_LIKE__"


# ---------------------------------------------------------------------------
# Numeric parsing / validation
# ---------------------------------------------------------------------------

_NUMERIC_STRING_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def _is_numeric_string(text: str) -> bool:
    """Return True for plain integer/decimal strings without formatting."""
    return bool(_NUMERIC_STRING_RE.fullmatch(text.strip()))


def _decimal_to_serializable(value: Decimal) -> str:
    """Render Decimal as a plain decimal string without scientific notation."""
    return format(value, "f")


def _is_integral(value: Decimal) -> bool:
    """Return True if the Decimal is mathematically an integer."""
    return value == value.to_integral_value()


def _parse_numeric(value, file_type: str = "csv"):
    """
    Parse a table cell value into a Decimal.

    Returns:
        (Decimal, numeric_kind) on success, where numeric_kind is "integer" or "decimal".
        (None, reason) on failure, where reason is one of:
            "blank", "formula_cell_present", "unsupported_value_type",
            "non_numeric_value_present".
    """
    if value is None:
        return (None, "blank")

    if isinstance(value, bool):
        return (None, "non_numeric_value_present")

    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return (None, "non_numeric_value_present")

    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float):
            try:
                decimal_value = Decimal(str(value))
            except (InvalidOperation, ValueError):
                return (None, "non_numeric_value_present")
        else:
            decimal_value = Decimal(value)
        numeric_kind = "integer" if _is_integral(decimal_value) else "decimal"
        return (decimal_value, numeric_kind)

    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return (None, "blank")
        # Formula cell detection applies only to XLSX. openpyxl returns strings
        # starting with '=' when read_only=True, data_only=False.
        if file_type == "xlsx" and text.startswith("="):
            return (None, "formula_cell_present")
        if _is_numeric_string(text):
            try:
                decimal_value = Decimal(text)
            except InvalidOperation:
                return (None, "non_numeric_value_present")
            numeric_kind = "integer" if _is_integral(decimal_value) else "decimal"
            return (decimal_value, numeric_kind)
        return (None, "non_numeric_value_present")

    return (None, "non_numeric_value_present")


# ---------------------------------------------------------------------------
# Path / file helpers
# ---------------------------------------------------------------------------

def _ensure_project_root_in_sys_path():
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)


def _validate_file_path(path):
    _ensure_project_root_in_sys_path()
    from system.security.path_validator import validate_path
    return validate_path(path, BASE_PATH)


def _file_type_from_path(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".xlsx"):
        return "xlsx"
    if lower.endswith(".xls") or lower.endswith(".xlsm"):
        return "unsupported_legacy"
    return "unsupported"


def _truncate_text(value, max_chars: int = MAX_CELL_CHARS) -> str:
    text = str(value) if value is not None else ""
    if len(text) > max_chars:
        return text[:max_chars] + " [additional cell content omitted]"
    return text


# ---------------------------------------------------------------------------
# Column / header helpers
# ---------------------------------------------------------------------------

def _build_headers(raw_values):
    headers = []
    for idx, h in enumerate(raw_values):
        h_str = str(h).strip() if h is not None else ""
        if h_str == "":
            headers.append(f"Column {idx + 1}")
        else:
            headers.append(h_str)
    return headers


def _has_duplicate_normalized_headers(headers):
    seen = set()
    for h in headers:
        normalized = h.strip().lower()
        if normalized in seen:
            return True
        seen.add(normalized)
    return False


def _resolve_column(headers, column_name, for_what="target"):
    """
    Resolve a column name to a 1-based index using case-insensitive match.

    Returns (1-based index, canonical_name, reason) where reason is None on success
    or one of: "column_not_found", "duplicate_column_header".
    """
    if column_name is None or str(column_name).strip() == "":
        return (None, None, "column_not_found")

    if _has_duplicate_normalized_headers(headers):
        return (None, None, "duplicate_column_header")

    lookup = {h.strip().lower(): (idx, h) for idx, h in enumerate(headers)}
    normalized = str(column_name).strip().lower()
    if normalized in lookup:
        idx, canonical = lookup[normalized]
        return (idx + 1, canonical, None)
    return (None, None, "column_not_found")


def _resolve_auto_name_like_column(headers):
    """Return the unique name-like header, or None if ambiguous/absent."""
    matches = [h for h in headers if _NAME_LIKE_HEADER_RE.search(h)]
    if len(matches) == 1:
        return matches[0]
    return None


def _column_letter(index: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(index)


# ---------------------------------------------------------------------------
# Table scanning
# ---------------------------------------------------------------------------

def _detect_csv_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        return dialect.delimiter
    except Exception:
        return ","


def _scan_csv(full_path: str):
    with open(full_path, "r", encoding="utf-8") as f:
        sample = f.read(4096)
        f.seek(0)
        delimiter = _detect_csv_delimiter(sample)
        reader = csv.reader(f, delimiter=delimiter)

        headers = None
        data_rows = []
        total_rows = 0

        for i, row in enumerate(reader):
            total_rows += 1
            if i == 0:
                headers = _build_headers(row)
                if len(headers) > MAX_COLUMNS:
                    return (None, None, "unsupported", "analysis_bounds_exceeded")
                continue
            if len(data_rows) >= MAX_DATA_ROWS:
                return (None, None, "unsupported", "analysis_bounds_exceeded")
            data_rows.append(row)

    return (headers, data_rows, None, None)


def _scan_xlsx(full_path: str, sheet_name=None):
    from openpyxl import load_workbook

    wb = load_workbook(full_path, read_only=True, data_only=False)
    try:
        sheet_names = wb.sheetnames
        if sheet_name is None:
            if len(sheet_names) != 1:
                return (None, None, "ambiguous", "multiple_sheets_require_selection")
            active_sheet = sheet_names[0]
        else:
            normalized_request = str(sheet_name).strip().lower()
            matches = [(s, s.strip().lower()) for s in sheet_names]
            candidates = [s for s, norm in matches if norm == normalized_request]
            if len(candidates) == 0:
                return (None, None, "not_found", "sheet_not_found")
            if len(candidates) > 1:
                return (None, None, "ambiguous", "sheet_name_ambiguous")
            active_sheet = candidates[0]

        ws = wb[active_sheet]
        headers = None
        data_rows = []
        for row in ws.iter_rows():
            values = [cell.value for cell in row]
            if headers is None:
                headers = _build_headers(values)
                if len(headers) > MAX_COLUMNS:
                    return (None, None, "unsupported", "analysis_bounds_exceeded")
                continue
            if len(data_rows) >= MAX_DATA_ROWS:
                return (None, None, "unsupported", "analysis_bounds_exceeded")
            data_rows.append(values)

        return (headers, data_rows, None, active_sheet)
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# Aggregate computation
# ---------------------------------------------------------------------------

def _row_has_any_nonblank(row):
    for cell in row:
        if cell is not None and str(cell).strip() != "":
            return True
    return False


def _compute_count_rows(data_rows):
    count = sum(1 for row in data_rows if _row_has_any_nonblank(row))
    return {
        "operation": "count_rows",
        "value": count,
        "value_kind": "integer",
        "rows_evaluated": len(data_rows),
        "numeric_cells": None,
        "blank_cells": None,
        "associated": None,
    }


def _compute_average_stats(numeric_values):
    """Return deterministic average metadata from a list of (Decimal, kind, row_index)."""
    from fractions import Fraction
    from decimal import localcontext, ROUND_HALF_EVEN

    exact_total = sum(Fraction(value) for value, _, _ in numeric_values)
    count = len(numeric_values)
    avg_fraction = exact_total / count

    def _terminates(frac):
        d = frac.denominator
        for p in (2, 5):
            while d % p == 0:
                d //= p
        return d == 1

    rounded = not _terminates(avg_fraction)

    if rounded:
        with localcontext() as ctx:
            ctx.prec = 12
            ctx.rounding = ROUND_HALF_EVEN
            display_avg = Decimal(avg_fraction.numerator) / Decimal(avg_fraction.denominator)
        precision = 12
    else:
        digits = max(len(str(abs(avg_fraction.numerator))), len(str(abs(avg_fraction.denominator)))) + 10
        with localcontext() as ctx:
            ctx.prec = max(28, digits)
            ctx.rounding = ROUND_HALF_EVEN
            display_avg = Decimal(avg_fraction.numerator) / Decimal(avg_fraction.denominator)
        precision = ctx.prec

    all_integral = all(kind == "integer" for _, kind, _ in numeric_values)
    value_kind = "integer" if _is_integral(display_avg) and all_integral else "decimal"

    return {
        "value": _decimal_to_serializable(display_avg),
        "value_kind": value_kind,
        "sum": _decimal_to_serializable(
            Decimal(exact_total.numerator) / Decimal(exact_total.denominator)
        ),
        "count": count,
        "precision": precision,
        "rounding_mode": "ROUND_HALF_EVEN",
        "rounded": rounded,
    }


def _collect_cell_refs(start_row, end_row, col_index):
    col_letter = _column_letter(col_index)
    return f"{col_letter}{start_row}:{col_letter}{end_row}"


def _cell_ref(col_index, row_number):
    return f"{_column_letter(col_index)}{row_number}"


def _compute_numeric_aggregate(
    headers,
    data_rows,
    operation,
    target_column,
    associated_column=None,
    header_row_number=1,
    file_type="csv",
):
    col_idx, canonical_target, reason = _resolve_column(headers, target_column, for_what="target")
    if reason is not None:
        return {"status": "not_found" if reason == "column_not_found" else "ambiguous", "status_reason": reason}

    # Determine requested associated column.
    requested_associated = None
    if associated_column == _NAME_LIKE_COLUMN_SENTINEL:
        auto_col = _resolve_auto_name_like_column(headers)
        if auto_col is None:
            return {"status": "ambiguous", "status_reason": "associated_column_ambiguous"}
        requested_associated = auto_col
    elif associated_column is not None and str(associated_column).strip() != "":
        requested_associated = str(associated_column).strip()

    associated_idx = None
    canonical_associated = None
    if requested_associated is not None:
        associated_idx, canonical_associated, assoc_reason = _resolve_column(
            headers, requested_associated, for_what="associated"
        )
        if assoc_reason is not None:
            return {
                "status": "not_found" if assoc_reason == "column_not_found" else "ambiguous",
                "status_reason": assoc_reason,
            }

    numeric_values = []
    blank_count = 0
    offending_cells = []
    formula_detected = []

    for row_index, row in enumerate(data_rows, start=header_row_number + 1):
        raw_value = row[col_idx - 1] if col_idx - 1 < len(row) else None
        parsed, kind = _parse_numeric(raw_value, file_type=file_type)
        if parsed is not None:
            numeric_values.append((parsed, kind, row_index))
        elif kind == "blank":
            blank_count += 1
        elif kind == "formula_cell_present":
            formula_detected.append((row_index, _truncate_text(raw_value)))
        else:
            offending_cells.append((row_index, _truncate_text(raw_value), kind))

    if formula_detected:
        return {
            "status": "unsupported",
            "status_reason": "formula_cell_present",
            "offending_cells": [
                {"row": row_idx, "cell": _cell_ref(col_idx, row_idx), "value_preview": preview}
                for row_idx, preview in formula_detected[:MAX_OFFENDING_CELLS]
            ],
        }

    if offending_cells:
        return {
            "status": "unsupported",
            "status_reason": "non_numeric_value_present",
            "offending_cells": [
                {"row": row_idx, "cell": _cell_ref(col_idx, row_idx), "value_preview": preview}
                for row_idx, preview, _ in offending_cells[:MAX_OFFENDING_CELLS]
            ],
        }

    if not numeric_values:
        return {"status": "not_found", "status_reason": "no_numeric_values"}

    # All parsed values have a kind recorded alongside them.
    all_integral = all(kind == "integer" for _, kind, _ in numeric_values)

    if operation == "sum":
        total = sum(value for value, _, _ in numeric_values)
        value_kind = "integer" if _is_integral(total) and all_integral else "decimal"
        return {
            "operation": operation,
            "value": _decimal_to_serializable(total),
            "value_kind": value_kind,
            "rows_evaluated": len(data_rows),
            "numeric_cells": len(numeric_values),
            "blank_cells": blank_count,
            "associated": None,
        }

    if operation == "average":
        avg_stats = _compute_average_stats(numeric_values)
        avg_stats.update({
            "operation": operation,
            "rows_evaluated": len(data_rows),
            "numeric_cells": len(numeric_values),
            "blank_cells": blank_count,
            "associated": None,
        })
        return avg_stats

    # max or min
    extreme_value = max((v for v, _, _ in numeric_values)) if operation == "max" else min((v for v, _, _ in numeric_values))
    tied_rows = [(row_idx, value, kind) for value, kind, row_idx in numeric_values if value == extreme_value]

    if len(tied_rows) > MAX_TIED_ROWS:
        return {"status": "unsupported", "status_reason": "tie_result_bounds_exceeded"}

    associated_entries = []
    if associated_idx is not None:
        for row_idx, _, _ in tied_rows:
            raw_assoc = data_rows[row_idx - header_row_number - 1][associated_idx - 1] if associated_idx - 1 < len(
                data_rows[row_idx - header_row_number - 1]
            ) else None
            associated_entries.append({
                "row": row_idx,
                "associated_column": canonical_associated,
                "associated_cell": _cell_ref(associated_idx, row_idx),
                "associated_value": _truncate_text(raw_assoc) if raw_assoc is not None else "",
            })

    value_kind = "integer" if all_integral and _is_integral(extreme_value) else "decimal"
    start_row = header_row_number + 1
    end_row = header_row_number + len(data_rows)

    return {
        "operation": operation,
        "value": _decimal_to_serializable(extreme_value),
        "value_kind": value_kind,
        "rows_evaluated": len(data_rows),
        "numeric_cells": len(numeric_values),
        "blank_cells": blank_count,
        "tied_row_count": len(tied_rows),
        "tied_rows": [row_idx for row_idx, _, _ in tied_rows],
        "associated": {
            "associated_column": canonical_associated,
            "associated_rows": associated_entries,
        } if associated_entries else None,
        "extreme_cells": [_cell_ref(col_idx, row_idx) for row_idx, _, _ in tied_rows],
    }


# ---------------------------------------------------------------------------
# Overview computation
# ---------------------------------------------------------------------------

def _compute_overview(headers, data_rows, file_type, file_path, sheet_name=None):
    """Return table-level and per-column bounded statistics without LLM insight."""
    data_row_count = sum(1 for row in data_rows if _row_has_any_nonblank(row))
    blank_row_count = len(data_rows) - data_row_count
    warnings = []

    if _has_duplicate_normalized_headers(headers):
        warnings.append("Duplicate headers detected; column references use the original names.")

    columns = []
    for col_idx, col_name in enumerate(headers):
        col_letter = _column_letter(col_idx + 1)
        numeric_values = []
        blank_count = 0
        formula_count = 0
        unsupported_count = 0
        text_count = 0
        distinct_text_values = set()

        for row_idx, row in enumerate(data_rows, start=2):
            raw_value = row[col_idx] if col_idx < len(row) else None
            parsed, kind = _parse_numeric(raw_value, file_type=file_type)
            if parsed is not None:
                numeric_values.append((parsed, kind, row_idx))
            elif kind == "blank":
                blank_count += 1
            elif kind == "formula_cell_present":
                formula_count += 1
            elif kind == "non_numeric_value_present":
                text_count += 1
                if raw_value is not None:
                    distinct_text_values.add(_truncate_text(raw_value))
            else:
                unsupported_count += 1

        total_cells = len(data_rows)
        nonblank_count = total_cells - blank_count
        col_info = {
            "column_name": col_name,
            "column_ref": col_letter,
            "blank_count": blank_count,
            "nonblank_count": nonblank_count,
        }

        if formula_count > 0:
            col_info["classification"] = "formula-containing"
            col_info["formula_count"] = formula_count
            col_info["warning"] = "Formula cells detected but were not executed."
        elif unsupported_count > 0 or (numeric_values and text_count > 0):
            col_info["classification"] = "mixed" if (numeric_values or text_count > 0) else "unsupported"
            col_info["warning"] = "Mixed or unsupported value types detected; numeric statistics omitted."
        elif numeric_values and text_count == 0:
            # Pure numeric column
            min_value = min((v for v, _, _ in numeric_values))
            max_value = max((v for v, _, _ in numeric_values))
            min_cells = [
                _cell_ref(col_idx + 1, row_idx)
                for v, _, row_idx in numeric_values
                if v == min_value
            ][:MAX_TIED_ROWS]
            max_cells = [
                _cell_ref(col_idx + 1, row_idx)
                for v, _, row_idx in numeric_values
                if v == max_value
            ][:MAX_TIED_ROWS]
            total = sum((v for v, _, _ in numeric_values))
            value_kind = "integer" if all(kind == "integer" for _, kind, _ in numeric_values) else "decimal"
            avg_stats = _compute_average_stats(numeric_values)
            end_row = 1 + len(data_rows)
            col_info["classification"] = "numeric"
            col_info["numeric_count"] = len(numeric_values)
            col_info["min"] = _decimal_to_serializable(min_value)
            col_info["max"] = _decimal_to_serializable(max_value)
            col_info["min_cells"] = min_cells
            col_info["max_cells"] = max_cells
            col_info["sum"] = _decimal_to_serializable(total)
            col_info["average"] = avg_stats["value"]
            col_info["average_value_kind"] = avg_stats["value_kind"]
            col_info["average_rounded"] = avg_stats["rounded"]
            col_info["average_precision"] = avg_stats["precision"]
            col_info["average_rounding_mode"] = avg_stats["rounding_mode"]
            col_info["contributing_range"] = _collect_cell_refs(2, end_row, col_idx + 1)
        elif text_count > 0:
            col_info["classification"] = "text"
            col_info["distinct_count"] = len(distinct_text_values)
        elif total_cells == 0 or blank_count == total_cells:
            col_info["classification"] = "empty"
        else:
            col_info["classification"] = "unknown"

        columns.append(col_info)

    return {
        "file_path": file_path,
        "file_type": file_type,
        "sheet_name": sheet_name,
        "data_row_count": data_row_count,
        "blank_row_count": blank_row_count,
        "column_count": len(headers),
        "column_names": list(headers),
        "columns": columns,
        "warnings": warnings,
    }


def _build_overview_answer_text(overview):
    """Generate a concise deterministic answer_text from the overview result."""
    data_row_count = overview["data_row_count"]
    column_count = overview["column_count"]
    text = f"The table contains {data_row_count} data rows and {column_count} columns."
    if overview["blank_row_count"] > 0:
        text += f" {overview['blank_row_count']} fully blank row(s) were excluded."

    first_numeric = next((c for c in overview["columns"] if c["classification"] == "numeric"), None)
    if first_numeric:
        qualifier = "approximately " if first_numeric.get("average_rounded") else ""
        text += (
            f" {first_numeric['column_name']} is numeric, ranging from {first_numeric['min']} to"
            f" {first_numeric['max']}, with a total of {first_numeric['sum']} and an average of"
            f" {qualifier}{first_numeric['average']}."
        )
    else:
        text += " No numeric columns were found."

    text += " See Details / Evidence for the complete column overview."
    return text


def _build_overview_result(file_path, file_type, sheet_name, headers, data_rows, overview):
    """Assemble the structured success result for the overview operation."""
    answer_text = _build_overview_answer_text(overview)
    result = {
        "status": "success",
        "status_reason": None,
        "operation": "overview",
        "input_file": file_path,
        "file_type": file_type,
        "sheet_name": sheet_name if file_type == "xlsx" else None,
        "data_row_count": overview["data_row_count"],
        "blank_row_count": overview["blank_row_count"],
        "column_count": overview["column_count"],
        "column_names": overview["column_names"],
        "columns": overview["columns"],
        "column_refs": [f"column:{c['column_name']}" for c in overview["columns"]],
        "row_refs": [],
        "cell_refs": [],
        "contributing_cell_ranges": [],
        "warnings": overview["warnings"],
        "limitations": [],
        "answer_text": answer_text,
    }
    for col in overview["columns"]:
        if col["classification"] == "numeric":
            result["cell_refs"].extend(col.get("min_cells", []))
            result["cell_refs"].extend(col.get("max_cells", []))
            if col.get("contributing_range"):
                result["contributing_cell_ranges"].append(col["contributing_range"])
    return result


# ---------------------------------------------------------------------------
# Result assembly
# ---------------------------------------------------------------------------

def _build_error_result(status, status_reason, file_type, file_path, sheet_name=None, detail=None):
    payload = {
        "status": status,
        "status_reason": status_reason,
        "operation": None,
        "input_file": file_path,
        "file_type": file_type,
        "sheet_name": sheet_name,
        "column_refs": [],
        "row_refs": [],
        "cell_refs": [],
        "warnings": [],
        "limitations": [],
    }
    if detail:
        payload["detail"] = detail
    return payload


def _build_success_result(operation, file_path, file_type, sheet_name, headers, target_column, computed, header_row=1):
    computed_operation = computed["operation"]
    value = computed["value"]
    value_kind = computed["value_kind"]
    rows_evaluated = computed["rows_evaluated"]
    numeric_cells = computed["numeric_cells"]
    blank_cells = computed["blank_cells"]

    column_refs = []
    if operation != "count_rows" and target_column:
        column_refs.append(f"column:{target_column}")

    associated = computed.get("associated")
    if associated and associated.get("associated_column"):
        column_refs.append(f"column:{associated['associated_column']}")

    row_refs = []
    cell_refs = []
    contributing_cell_ranges = []

    start_data_row = header_row + 1
    end_data_row = header_row + rows_evaluated

    if operation in ("max", "min"):
        extreme_cells = computed.get("extreme_cells", [])
        cell_refs.extend(extreme_cells)
        if associated:
            for entry in associated["associated_rows"]:
                cell_refs.append(entry["associated_cell"])
        row_refs.extend(computed.get("tied_rows", []))
        if target_column:
            # Locate canonical target column in headers for evidence range.
            target_idx, _, _ = _resolve_column(headers, target_column)
            if target_idx is not None:
                contributing_cell_ranges.append(
                    _collect_cell_refs(start_data_row, end_data_row, target_idx)
                )

    rounded = computed.get("rounded", False)
    answer_text = _build_answer_text(operation, target_column, value, value_kind, associated, rounded=rounded)

    limitations = []
    if computed.get("tied_row_count", 0) > 1:
        limitations.append(f"{computed['tied_row_count']} rows tied for the {operation}imum value.")
    if operation == "average" and rounded:
        limitations.append(
            f"Average rounded to {computed['precision']} significant digits using {computed['rounding_mode']}."
        )

    result = {
        "status": "success",
        "status_reason": None,
        "operation": computed_operation,
        "input_file": file_path,
        "file_type": file_type,
        "sheet_name": sheet_name if file_type == "xlsx" else None,
        "column_refs": column_refs,
        "row_refs": row_refs,
        "cell_refs": cell_refs,
        "contributing_cell_ranges": contributing_cell_ranges,
        "computed_value": value,
        "value_kind": value_kind,
        "rows_evaluated": rows_evaluated,
        "numeric_cells": numeric_cells,
        "blank_cells": blank_cells,
        "answer_text": answer_text,
        "associated": associated,
        "warnings": [],
        "limitations": limitations,
    }
    if operation == "average":
        result["computed_sum"] = computed.get("sum")
        result["computed_count"] = computed.get("count")
        result["precision"] = computed.get("precision")
        result["rounding_mode"] = computed.get("rounding_mode")
        result["rounded"] = computed.get("rounded", False)
    if operation in ("max", "min"):
        result["extreme_cells"] = computed.get("extreme_cells", [])
        result["tied_rows"] = computed.get("tied_rows", [])
        result["tied_row_count"] = computed.get("tied_row_count", 0)
    return result


def _build_answer_text(operation, target_column, value, value_kind, associated, rounded=False):
    if operation == "count_rows":
        return f"There are {value} data rows in the table."

    label = target_column or "value"
    if operation == "max":
        base = f"The highest {label} is {value}."
    elif operation == "min":
        base = f"The lowest {label} is {value}."
    elif operation == "sum":
        base = f"The sum of {label} is {value}."
    elif operation == "average":
        qualifier = "approximately " if rounded else ""
        base = f"The average of {label} is {qualifier}{value}."
    else:
        base = f"The {operation} of {label} is {value}."

    if associated and associated.get("associated_rows"):
        assoc_values = [entry.get("associated_value", "") for entry in associated["associated_rows"]]
        if len(assoc_values) == 1:
            base += f" This corresponds to {assoc_values[0]}."
        else:
            base += f" This corresponds to: {', '.join(assoc_values)}."

    return base


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _analyze_table_impl(
    path,
    operation,
    target_column=None,
    sheet_name=None,
    associated_column=None,
):
    """
    Raw bounded deterministic aggregate analysis implementation.

    Returns the structured payload dict directly (status may be
    success/not_found/ambiguous/unsupported/blocked/failed).
    """
    if not isinstance(path, str) or not path.strip():
        return _build_error_result("unsupported", "missing_path", None, None)

    operation = (operation or "").strip().lower()
    if operation not in _ALLOWED_OPERATIONS:
        return _build_error_result("unsupported", "unsupported_operation", None, path)

    file_type = _file_type_from_path(path)
    if file_type == "unsupported_legacy":
        return _build_error_result("unsupported", "unsupported_file_type", file_type, path)
    if file_type == "unsupported":
        return _build_error_result("unsupported", "unsupported_file_type", file_type, path)

    validation = _validate_file_path(path)
    if validation.get("status") == "failure":
        return _build_error_result("blocked", validation.get("reason", "path_safety_blocked"), file_type, path)

    full_path = validation["resolved_path"]

    if not os.path.exists(full_path):
        return _build_error_result("not_found", "file_not_found", file_type, path)

    try:
        file_size = os.path.getsize(full_path)
    except OSError:
        return _build_error_result("failed", "file_stat_error", file_type, path)

    if file_size > MAX_FILE_SIZE_BYTES:
        return _build_error_result("unsupported", "analysis_bounds_exceeded", file_type, path)

    if file_type == "csv":
        headers, data_rows, status, reason = _scan_csv(full_path)
        resolved_sheet = None
    else:
        headers, data_rows, status, reason_or_sheet = _scan_xlsx(full_path, sheet_name)
        if status is not None:
            reason = reason_or_sheet
            resolved_sheet = None
        else:
            reason = None
            resolved_sheet = reason_or_sheet

    if status is not None:
        return _build_error_result(status, reason, file_type, path, resolved_sheet)

    if not headers:
        return _build_error_result("unsupported", "empty_table", file_type, path, resolved_sheet)

    if operation != "overview" and _has_duplicate_normalized_headers(headers):
        return _build_error_result("ambiguous", "duplicate_column_header", file_type, path, resolved_sheet)

    if operation == "overview":
        overview = _compute_overview(
            headers, data_rows, file_type, path, sheet_name=resolved_sheet
        )
        return _build_overview_result(
            path, file_type, resolved_sheet, headers, data_rows, overview
        )

    if operation == "count_rows":
        computed = _compute_count_rows(data_rows)
    else:
        if target_column is None or str(target_column).strip() == "":
            return _build_error_result("unsupported", "missing_target_column", file_type, path, resolved_sheet)
        computed = _compute_numeric_aggregate(
            headers,
            data_rows,
            operation,
            target_column,
            associated_column=associated_column,
            file_type=file_type,
        )
        if computed.get("status") in ("not_found", "ambiguous", "unsupported"):
            result_payload = _build_error_result(
                computed["status"],
                computed["status_reason"],
                file_type,
                path,
                resolved_sheet,
            )
            if "offending_cells" in computed:
                result_payload["offending_cells"] = computed["offending_cells"]
            return result_payload

    return _build_success_result(
        operation,
        path,
        file_type,
        resolved_sheet,
        headers,
        target_column if operation != "count_rows" else None,
        computed,
    )


def run(
    path,
    operation,
    target_column=None,
    sheet_name=None,
    associated_column=None,
):
    """
    Public entry point used by system_entry.

    Returns:
        - success: {"status": "success", "result": <structured payload>}
        - non-success: {"status": "failure", "reason": <status_reason>,
                        "observation": <structured payload>}
    """
    payload = _analyze_table_impl(
        path,
        operation,
        target_column=target_column,
        sheet_name=sheet_name,
        associated_column=associated_column,
    )
    if payload.get("status") == "success":
        return {"status": "success", "result": payload}
    return {
        "status": "failure",
        "reason": payload.get("status_reason") or payload.get("status"),
        "observation": payload,
    }

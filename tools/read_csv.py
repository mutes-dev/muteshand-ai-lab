INPUT_SPEC = {
    "path": "string"
}

import csv
import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

_DEFAULT_MAX_ROWS = 100


def _is_extensionless_or_csv(path: str) -> bool:
    """Return True if path ends with .csv or resolver confirms CSV content."""
    lower = path.lower()
    if lower.endswith(".csv"):
        return True
    # Only probe if there is truly no extension
    basename = os.path.basename(path)
    if "." in basename:
        return False
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from system.orchestrator.capabilities.document_intake_resolver import is_extensionless_acceptable
    return is_extensionless_acceptable("read_csv", path)


_DEFAULT_MAX_COLUMNS = 50
_DEFAULT_MAX_CELL_CHARS = 500


def _truncate_cell(value, max_chars):
    """Truncate a cell value to max_chars with a controlled note."""
    text = str(value) if value is not None else ""
    if len(text) > max_chars:
        return text[:max_chars] + " [additional cell content omitted]"
    return text


def _detect_delimiter(sample):
    """Detect delimiter using csv.Sniffer with comma fallback."""
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        return dialect.delimiter
    except Exception:
        return ","


def run(path, max_rows=None, max_columns=None, max_cell_chars=None):
    """
    Extract a bounded structured preview from a local CSV file.

    Returns structured dict for all cases.
    """
    _max_rows = max_rows if isinstance(max_rows, int) and max_rows > 0 else _DEFAULT_MAX_ROWS
    _max_columns = max_columns if isinstance(max_columns, int) and max_columns > 0 else _DEFAULT_MAX_COLUMNS
    _max_cell_chars = max_cell_chars if isinstance(max_cell_chars, int) and max_cell_chars > 0 else _DEFAULT_MAX_CELL_CHARS

    try:
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from system.security.path_validator import validate_path

        validation = validate_path(path, BASE_PATH)
        if validation.get("status") == "failure":
            return validation

        full_path = validation["resolved_path"]

        if not os.path.exists(full_path):
            return {"status": "failure", "reason": "file_not_found"}

        if not _is_extensionless_or_csv(full_path):
            return {"status": "failure", "reason": "unsupported_format"}

        with open(full_path, "r", encoding="utf-8") as f:
            sample = f.read(4096)
            f.seek(0)
            delimiter = _detect_delimiter(sample)

            reader = csv.reader(f, delimiter=delimiter)

            headers = None
            data_rows = []
            column_count = None
            total_rows_read = 0
            rows_omitted = False
            columns_omitted = False
            cells_truncated = False

            for i, row in enumerate(reader):
                total_rows_read += 1

                if i == 0:
                    raw_headers = [_truncate_cell(c, _max_cell_chars) for c in row]
                    column_count = len(row)
                    headers = []
                    for idx, h in enumerate(raw_headers):
                        h_str = str(h) if h is not None else ""
                        if h_str.strip() == "":
                            headers.append(f"Column {idx + 1}")
                        else:
                            headers.append(h_str)
                    continue

                if len(data_rows) >= _max_rows:
                    rows_omitted = True
                    continue

                truncated_row = []
                for idx, cell in enumerate(row):
                    if idx >= _max_columns:
                        columns_omitted = True
                        break
                    val = _truncate_cell(cell, _max_cell_chars)
                    if val != str(cell) if cell is not None else False:
                        cells_truncated = True
                    truncated_row.append(val)

                data_rows.append(truncated_row)

        header_detected = bool(headers)

        # Build sectioned output
        lines = []
        lines.append(f"CSV file: {os.path.basename(full_path)}")
        lines.append("Format: CSV")
        lines.append(f"Delimiter: {delimiter if delimiter != ' ' else 'space'} ({delimiter})")
        lines.append(f"Total rows scanned: {total_rows_read}")
        if column_count is not None:
            lines.append(f"Columns detected: {column_count}")
        if header_detected:
            lines.append(f"Headers detected: {' | '.join(headers)}")
        else:
            lines.append("Headers detected: none")
        lines.append(f"Preview rows shown: {len(data_rows)}")

        if rows_omitted:
            lines.append(f"Additional rows omitted due to preview limit (max {_max_rows}).")
        if columns_omitted:
            lines.append(f"Additional columns omitted due to preview limit (max {_max_columns}).")
        if cells_truncated:
            lines.append(f"Some cell values shortened to {_max_cell_chars} characters.")
        if total_rows_read > len(data_rows) + 1:
            lines.append("Additional rows may exist beyond the preview.")

        lines.append("")
        lines.append("Preview:")

        if headers:
            header_line = "| Row | " + " | ".join(headers) + " |"
            lines.append(header_line)
            for idx, row in enumerate(data_rows):
                padded = row + [""] * (len(headers) - len(row))
                lines.append(f"| {idx + 1} | " + " | ".join(padded) + " |")
        else:
            lines.append("| Row | Data |")
            for idx, row in enumerate(data_rows):
                lines.append(f"| {idx + 1} | " + " | ".join(row) + " |")

        lines.append("")
        lines.append("Limits:")
        lines.append(f"- Max preview rows: {_max_rows}")
        lines.append(f"- Max columns: {_max_columns}")
        lines.append(f"- Max cell characters: {_max_cell_chars}")

        lines.append("")
        lines.append("Notes:")
        lines.append("- This is a bounded preview, not full spreadsheet/data analysis.")
        lines.append("- Additional rows/columns/cell content may be omitted when limits are reached.")

        result_text = "\n".join(lines)

        return {
            "status": "success",
            "result": result_text,
            "metadata": {
                "source_path": full_path,
                "format": "csv",
                "delimiter": delimiter,
                "preview_rows": len(data_rows),
                "column_count": column_count,
                "header_detected": header_detected,
                "rows_omitted": rows_omitted,
                "columns_omitted": columns_omitted,
                "cells_truncated": cells_truncated,
            },
        }

    except Exception:
        return {"status": "failure", "reason": "read_error"}

"""Tests for preview_table_schema tool."""

import csv
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from tools.preview_table_schema import run as preview_table_schema


def _project_tmp():
    return os.path.join(os.path.dirname(__file__), "..", "..", "..", "tmp")


def _make_csv(rows, headers=None):
    fd, path = tempfile.mkstemp(dir=_project_tmp(), suffix=".csv")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if headers:
            writer.writerow(headers)
        writer.writerows(rows)
    return path


def _make_xlsx(rows, headers=None, sheet_name="Sheet1"):
    from openpyxl import Workbook

    fd, path = tempfile.mkstemp(dir=_project_tmp(), suffix=".xlsx")
    os.close(fd)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    if headers:
        ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()
    return path


class TestPreviewTableSchema:
    def test_csv_preview_success(self):
        headers = ["Name", "Age", "City"]
        rows = [["Alice", "30", "NYC"], ["Bob", "25", "LA"], ["Carol", "35", "Chicago"]]
        path = _make_csv(rows, headers=headers)
        try:
            rel = os.path.relpath(path, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            result = preview_table_schema(rel)
            assert result["status"] == "success"
            assert result["file_type"] == "csv"
            assert result["headers"] == headers
            assert result["header_map"] == {"Name": 1, "Age": 2, "City": 3}
            assert len(result["sample_rows"]) == 3
            assert result["sample_rows"][0]["row_number"] == 2
            assert result["sample_rows"][0]["values"] == ["Alice", "30", "NYC"]
            assert result["column_count_observed"] == 3
        finally:
            os.unlink(path)

    def test_xlsx_preview_success(self):
        headers = ["Product", "Price", "Quantity"]
        rows = [["Apple", "1.50", "10"], ["Banana", "0.75", "20"], ["Cherry", "2.00", "15"]]
        path = _make_xlsx(rows, headers=headers, sheet_name="Sales")
        try:
            rel = os.path.relpath(path, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            result = preview_table_schema(rel, sheet_name="Sales")
            assert result["status"] == "success"
            assert result["file_type"] == "xlsx"
            assert result["sheet_name"] == "Sales"
            assert "Sales" in result["sheets"]
            assert result["headers"] == headers
            assert result["header_map"] == {"Product": 1, "Price": 2, "Quantity": 3}
            assert len(result["sample_rows"]) == 3
            assert result["column_count_observed"] == 3
        finally:
            os.unlink(path)

    def test_missing_file_error(self):
        result = preview_table_schema("tmp/nonexistent_file_for_preview_12345.csv")
        assert result["status"] == "error"
        assert result["error_code"] == "file_not_found"

    def test_unsupported_extension_error(self):
        fd, path = tempfile.mkstemp(dir=_project_tmp(), suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("not a table\n")
        try:
            rel = os.path.relpath(path, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            result = preview_table_schema(rel)
            assert result["status"] == "error"
            assert result["error_code"] == "unsupported_format"
        finally:
            os.unlink(path)

    def test_xlsm_rejected(self):
        fd, path = tempfile.mkstemp(dir=_project_tmp(), suffix=".xlsm")
        with os.fdopen(fd, "wb") as f:
            f.write(b"fake xlsm")
        try:
            rel = os.path.relpath(path, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            result = preview_table_schema(rel)
            assert result["status"] == "error"
            assert result["error_code"] == "unsupported_format"
        finally:
            os.unlink(path)

    def test_header_map(self):
        headers = ["A", "B", "C"]
        rows = [["1", "2", "3"], ["4", "5", "6"]]
        path = _make_csv(rows, headers=headers)
        try:
            rel = os.path.relpath(path, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            result = preview_table_schema(rel)
            assert result["header_map"] == {"A": 1, "B": 2, "C": 3}
            assert result["headers"] == headers
        finally:
            os.unlink(path)

    def test_bounds_applied(self):
        headers = ["Name", "Age"]
        rows = [[f"Person{i}", str(i)] for i in range(1, 10)]
        path = _make_csv(rows, headers=headers)
        try:
            rel = os.path.relpath(path, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            result = preview_table_schema(rel, max_rows=2, max_columns=1, max_cell_chars=5)
            assert result["status"] == "success"
            assert len(result["sample_rows"]) == 2
            assert result["rows_omitted"] is True
            assert result["columns_omitted"] is True
            assert result["bounds_applied"]["max_rows"] == 2
            assert result["bounds_applied"]["max_columns"] == 1
            assert result["bounds_applied"]["max_cell_chars"] == 5
            assert "[additional cell content omitted]" in result["sample_rows"][0]["values"][0]
            assert result["column_count_observed"] == 1
        finally:
            os.unlink(path)

    def test_no_analysis_output(self):
        headers = ["Name", "Score"]
        rows = [["Alice", "90"], ["Bob", "80"], ["Carol", "100"]]
        path = _make_csv(rows, headers=headers)
        try:
            rel = os.path.relpath(path, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            result = preview_table_schema(rel)
            assert result["status"] == "success"
            # Result must contain only reference metadata, no computed analysis fields
            assert "sum" not in result
            assert "average" not in result
            assert "max" not in result
            assert "min" not in result
            assert "highest" not in result
            assert "analysis" not in result
            assert "answer" not in result
            assert len(result["sample_rows"]) == 3
        finally:
            os.unlink(path)

    def test_has_header_false(self):
        rows = [["Alice", "30"], ["Bob", "25"]]
        path = _make_csv(rows)
        try:
            rel = os.path.relpath(path, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
            result = preview_table_schema(rel, has_header=False)
            assert result["status"] == "success"
            assert result["headers"] == []
            assert result["header_map"] == {}
            assert len(result["sample_rows"]) == 2
        finally:
            os.unlink(path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

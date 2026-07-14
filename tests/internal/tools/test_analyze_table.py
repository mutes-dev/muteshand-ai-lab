"""Tests for tools/analyze_table.py — F5A bounded deterministic table analysis."""

import csv
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from tools import analyze_table


# Test the raw payload implementation directly (not the system_entry wrapper).
def _call(*args, **kwargs):
    return analyze_table._analyze_table_impl(*args, **kwargs)


BASE_PATH = os.path.abspath("E:/MutesHand")


@pytest.fixture
def table_tmp_path():
    """Create a temporary directory inside the project root for safe file tests."""
    with tempfile.TemporaryDirectory(dir=BASE_PATH) as d:
        yield d


def _write_csv(file_path: str, rows: list[list]):
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)


def _rel(path: str) -> str:
    return os.path.relpath(path, BASE_PATH)


class TestAnalyzeTableCsvSuccess:
    def test_count_rows(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "scores.csv")
        _write_csv(p, [["Name", "Score"], ["Alice", "10"], ["Bob", "20"], ["", ""]])
        result = _call(_rel(p), "count_rows")
        assert result["status"] == "success"
        assert result["operation"] == "count_rows"
        assert result["computed_value"] == 2
        assert result["rows_evaluated"] == 3
        assert result["column_refs"] == []

    def test_max_integer(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "scores.csv")
        _write_csv(p, [["Name", "Score"], ["Alice", "85"], ["Bob", "91"], ["Cara", "78"]])
        result = _call(_rel(p), "max", "Score")
        assert result["status"] == "success"
        assert result["computed_value"] == "91"
        assert result["value_kind"] == "integer"
        assert result["extreme_cells"] == ["B3"]

    def test_min_with_explicit_associated_column(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "scores.csv")
        _write_csv(p, [["Name", "Score"], ["Alice", "85"], ["Bob", "91"], ["Cara", "78"]])
        result = _call(_rel(p), "min", "Score", associated_column="Name")
        assert result["status"] == "success"
        assert result["computed_value"] == "78"
        assert result["associated"]["associated_column"] == "Name"
        assert result["answer_text"].endswith("Cara.")

    def test_auto_name_like_associated_column(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "people.csv")
        _write_csv(p, [["Full Name", "Score"], ["Bob", "50"], ["Alice", "90"]])
        result = _call(_rel(p), "max", "Score", associated_column="__AUTO_NAME_LIKE__")
        assert result["status"] == "success"
        assert result["associated"]["associated_column"] == "Full Name"
        assert "Alice" in result["answer_text"]

    def test_sum_decimal(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "amounts.csv")
        _write_csv(p, [["Amount"], ["10.5"], ["2.25"], ["3"]])
        result = _call(_rel(p), "sum", "Amount")
        assert result["status"] == "success"
        assert result["computed_value"] == "15.75"
        assert result["value_kind"] == "decimal"

    def test_average_terminating_exact(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "vals.csv")
        _write_csv(p, [["Val"], ["10"], ["20"], ["30"]])
        result = _call(_rel(p), "average", "Val")
        assert result["status"] == "success"
        assert result["computed_value"] == "20"
        assert result["value_kind"] == "integer"
        assert result["rounded"] is False
        assert result["computed_sum"] == "60"
        assert result["computed_count"] == 3
        assert result["rounding_mode"] == "ROUND_HALF_EVEN"

    def test_average_repeating_decimal_is_rounded(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "vals.csv")
        _write_csv(p, [["Val"], ["10"], ["20"], ["31"]])
        result = _call(_rel(p), "average", "Val")
        assert result["status"] == "success"
        assert result["value_kind"] == "decimal"
        assert result["rounded"] is True
        assert result["precision"] == 12
        # 61/3 = 20.3333333333...; 12 significant digits => "20.3333333333".
        assert result["computed_value"].startswith("20.3333333333")
        assert "approximately" in result["answer_text"]
        assert result["computed_sum"] == "61"
        assert result["computed_count"] == 3

    def test_tied_rows_reported(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "tied.csv")
        _write_csv(p, [["Name", "Score"], ["A", "10"], ["B", "10"], ["C", "5"]])
        result = _call(_rel(p), "max", "Score", associated_column="Name")
        assert result["status"] == "success"
        assert result["tied_row_count"] == 2
        assert sorted(result["tied_rows"]) == [2, 3]
        assert "A, B" in result["answer_text"] or "B, A" in result["answer_text"]

    def test_blank_cells_excluded(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "blanks.csv")
        _write_csv(p, [["Score"], ["10"], [""], ["20"]])
        result = _call(_rel(p), "sum", "Score")
        assert result["status"] == "success"
        assert result["computed_value"] == "30"
        assert result["blank_cells"] == 1
        assert result["numeric_cells"] == 2


class TestAnalyzeTableXlsxSuccess:
    def test_max_xlsx(self, table_tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        p = os.path.join(table_tmp_path, "scores.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["Name", "Score"])
        ws.append(["Alice", 85])
        ws.append(["Bob", 91])
        wb.save(p)

        result = _call(_rel(p), "max", "Score")
        assert result["status"] == "success"
        assert result["computed_value"] == "91"
        assert result["sheet_name"] == "Sheet1"

    def test_sheet_name_extraction(self, table_tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        p = os.path.join(table_tmp_path, "multi.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.title = "Grades"
        ws.append(["Score"])
        ws.append([95])
        wb.create_sheet("Other")
        wb.save(p)

        result = _call(_rel(p), "max", "Score", sheet_name="Grades")
        assert result["status"] == "success"
        assert result["computed_value"] == "95"
        assert result["sheet_name"] == "Grades"

    def test_formula_cell_is_blocked(self, table_tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        p = os.path.join(table_tmp_path, "formula.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.append(["Score"])
        ws.append(["=SUM(1,2)"])
        wb.save(p)

        result = _call(_rel(p), "sum", "Score")
        assert result["status"] == "unsupported"
        assert result["status_reason"] == "formula_cell_present"


class TestAnalyzeTableErrors:
    def test_missing_file(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "missing.csv")
        result = _call(_rel(p), "count_rows")
        assert result["status"] == "not_found"
        assert result["status_reason"] == "file_not_found"

    def test_unsupported_file_type(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "legacy.xls")
        with open(p, "w") as f:
            f.write("dummy")
        result = _call(_rel(p), "count_rows")
        assert result["status"] == "unsupported"
        assert result["status_reason"] == "unsupported_file_type"

    def test_missing_column(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "scores.csv")
        _write_csv(p, [["Name", "Score"], ["A", "10"]])
        result = _call(_rel(p), "max", "Grade")
        assert result["status"] == "not_found"
        assert result["status_reason"] == "column_not_found"

    def test_duplicate_column_header(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "dup.csv")
        _write_csv(p, [["Score", "Score"], ["A", "10"]])
        result = _call(_rel(p), "max", "Score")
        assert result["status"] == "ambiguous"
        assert result["status_reason"] == "duplicate_column_header"

    def test_non_numeric_value(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "bad.csv")
        _write_csv(p, [["Score"], ["ten"]])
        result = _call(_rel(p), "max", "Score")
        assert result["status"] == "unsupported"
        assert result["status_reason"] == "non_numeric_value_present"

    def test_no_numeric_values(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "empty.csv")
        _write_csv(p, [["Score"], [""]])
        result = _call(_rel(p), "max", "Score")
        assert result["status"] == "not_found"
        assert result["status_reason"] == "no_numeric_values"

    def test_multiple_sheets_requires_selection(self, table_tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        p = os.path.join(table_tmp_path, "multi.xlsx")
        wb = Workbook()
        wb.active.title = "A"
        wb.create_sheet("B")
        wb.save(p)

        result = _call(_rel(p), "count_rows")
        assert result["status"] == "ambiguous"
        assert result["status_reason"] == "multiple_sheets_require_selection"

    def test_missing_sheet(self, table_tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        p = os.path.join(table_tmp_path, "book.xlsx")
        wb = Workbook()
        wb.active.title = "Sheet1"
        wb.save(p)

        result = _call(_rel(p), "count_rows", sheet_name="Missing")
        assert result["status"] == "not_found"
        assert result["status_reason"] == "sheet_not_found"

    def test_analysis_bounds_exceeded_rows(self, table_tmp_path, monkeypatch):
        p = os.path.join(table_tmp_path, "big.csv")
        _write_csv(p, [["Score"], ["1"], ["2"], ["3"]])
        monkeypatch.setattr(analyze_table, "MAX_DATA_ROWS", 1)
        result = _call(_rel(p), "sum", "Score")
        assert result["status"] == "unsupported"
        assert result["status_reason"] == "analysis_bounds_exceeded"

    def test_analysis_bounds_exceeded_columns(self, table_tmp_path, monkeypatch):
        p = os.path.join(table_tmp_path, "wide.csv")
        headers = [f"Col{i}" for i in range(101)]
        _write_csv(p, [headers, ["1"] * 101])
        result = _call(_rel(p), "sum", "Col0")
        assert result["status"] == "unsupported"
        assert result["status_reason"] == "analysis_bounds_exceeded"

    def test_path_traversal_blocked(self, table_tmp_path):
        result = _call("../outside.csv", "count_rows")
        assert result["status"] == "blocked"
        assert result["status_reason"] == "path_safety_blocked"

    def test_unsupported_operation(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "scores.csv")
        _write_csv(p, [["Score"], ["10"]])
        result = _call(_rel(p), "median", "Score")
        assert result["status"] == "unsupported"
        assert result["status_reason"] == "unsupported_operation"

    def test_missing_target_column(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "scores.csv")
        _write_csv(p, [["Score"], ["10"]])
        result = _call(_rel(p), "max")
        assert result["status"] == "unsupported"
        assert result["status_reason"] == "missing_target_column"

    def test_auto_name_like_ambiguous(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "ambig.csv")
        _write_csv(p, [["First Name", "Last Name", "Score"], ["A", "B", "10"]])
        result = _call(_rel(p), "max", "Score", associated_column="__AUTO_NAME_LIKE__")
        assert result["status"] == "ambiguous"
        assert result["status_reason"] == "associated_column_ambiguous"

class TestAnalyzeTableOverview:
    def test_overview_returns_table_and_numeric_column_stats(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "overview.csv")
        _write_csv(p, [["Name", "Score"], ["Alice", "84"], ["Bob", "91"], ["Cara", "87"]])
        result = _call(_rel(p), "overview")
        assert result["status"] == "success"
        assert result["operation"] == "overview"
        assert result["data_row_count"] == 3
        assert result["blank_row_count"] == 0
        assert result["column_count"] == 2
        assert result["column_names"] == ["Name", "Score"]
        assert result["answer_text"].startswith("The table contains 3 data rows and 2 columns.")
        assert "See Details / Evidence" in result["answer_text"]

        score_col = next(c for c in result["columns"] if c["column_name"] == "Score")
        assert score_col["classification"] == "numeric"
        assert score_col["numeric_count"] == 3
        assert score_col["min"] == "84"
        assert score_col["max"] == "91"
        assert score_col["sum"] == "262"
        assert score_col["average"] == "87.3333333333"
        assert score_col["average_rounded"] is True
        assert "B2:B4" in score_col["contributing_range"]

    def test_overview_text_column_counts(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "text_col.csv")
        _write_csv(p, [["Name", "Score"], ["Alice", "10"], ["", "20"], ["Bob", ""]])
        result = _call(_rel(p), "overview")
        assert result["status"] == "success"
        name_col = next(c for c in result["columns"] if c["column_name"] == "Name")
        assert name_col["classification"] == "text"
        assert name_col["nonblank_count"] == 2
        assert name_col["blank_count"] == 1
        assert name_col["distinct_count"] == 2

    def test_overview_mixed_column_is_warned(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "mixed.csv")
        _write_csv(p, [["Val"], ["10"], ["bad"], ["20"]])
        result = _call(_rel(p), "overview")
        assert result["status"] == "success"
        col = result["columns"][0]
        assert col["classification"] == "mixed"
        assert "numeric statistics omitted" in col["warning"]

    def test_overview_formula_column_is_classified_not_executed(self, table_tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        p = os.path.join(table_tmp_path, "formula_overview.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["Score"])
        ws.append(["=SUM(1,2)"])
        wb.save(p)

        result = _call(_rel(p), "overview")
        assert result["status"] == "success"
        col = result["columns"][0]
        assert col["classification"] == "formula-containing"
        assert col.get("formula_count") == 1
        assert "not executed" in col["warning"]

    def test_overview_empty_column(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "empty_col.csv")
        _write_csv(p, [["A", "B"], ["1", ""], ["2", ""]])
        result = _call(_rel(p), "overview")
        b_col = next(c for c in result["columns"] if c["column_name"] == "B")
        assert b_col["classification"] == "empty"

    def test_overview_multi_sheet_requires_selection(self, table_tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        p = os.path.join(table_tmp_path, "multi_sheet_overview.xlsx")
        wb = Workbook()
        wb.active.title = "A"
        wb.create_sheet("B")
        wb.save(p)

        result = _call(_rel(p), "overview")
        assert result["status"] == "ambiguous"
        assert result["status_reason"] == "multiple_sheets_require_selection"

    def test_overview_preserves_existing_operations(self, table_tmp_path):
        p = os.path.join(table_tmp_path, "scores.csv")
        _write_csv(p, [["Score"], ["10"], ["20"], ["30"]])
        sum_result = _call(_rel(p), "sum", "Score")
        assert sum_result["status"] == "success"
        assert sum_result["computed_value"] == "60"
        max_result = _call(_rel(p), "max", "Score")
        assert max_result["status"] == "success"
        assert max_result["computed_value"] == "30"

    def test_overview_xlsx_single_sheet(self, table_tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        p = os.path.join(table_tmp_path, "overview.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.title = "Grades"
        ws.append(["Name", "Score"])
        ws.append(["Alice", 84])
        ws.append(["Bob", 91])
        wb.save(p)

        result = _call(_rel(p), "overview")
        assert result["status"] == "success"
        assert result["sheet_name"] == "Grades"
        assert result["data_row_count"] == 2


    def test_date_cell_is_non_numeric(self, table_tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook
        from datetime import datetime

        p = os.path.join(table_tmp_path, "dates.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.append(["When"])
        ws.append([datetime(2026, 1, 1)])
        wb.save(p)

        result = _call(_rel(p), "max", "When")
        assert result["status"] == "unsupported"
        assert result["status_reason"] == "non_numeric_value_present"

    def test_boolean_cell_is_non_numeric(self, table_tmp_path):
        pytest.importorskip("openpyxl")
        from openpyxl import Workbook

        p = os.path.join(table_tmp_path, "bool.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.append(["Flag"])
        ws.append([True])
        wb.save(p)

        result = _call(_rel(p), "max", "Flag")
        assert result["status"] == "unsupported"
        assert result["status_reason"] == "non_numeric_value_present"

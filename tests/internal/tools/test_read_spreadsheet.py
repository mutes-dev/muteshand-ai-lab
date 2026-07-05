"""Tests for read_spreadsheet bounded structured preview tool."""

import os
import tempfile
import unittest

from tools import read_spreadsheet


try:
    from openpyxl import Workbook
    HAS_OPENPYXL = True
except Exception:
    HAS_OPENPYXL = False


class TestReadSpreadsheet(unittest.TestCase):

    def setUp(self):
        self.tmpdir = os.path.join("e:/MutesHand/tmp", "test_spreadsheet")
        os.makedirs(self.tmpdir, exist_ok=True)

    def tearDown(self):
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def _make_xlsx(self, name, sheets_data):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        path = os.path.join(self.tmpdir, name)
        wb = Workbook()
        # Remove default sheet if not needed
        if sheets_data:
            wb.remove(wb.active)
        for sheet_name, rows in sheets_data.items():
            ws = wb.create_sheet(title=sheet_name)
            for row in rows:
                ws.append(row)
        wb.save(path)
        wb.close()
        return path

    # --- Basic behavior ---

    def test_simple_xlsx(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        path = self._make_xlsx("simple.xlsx", {
            "Sheet1": [
                ["Name", "Age", "City"],
                ["Alice", 30, "New York"],
                ["Bob", 25, "Los Angeles"],
            ]
        })
        result = read_spreadsheet.run(path)
        self.assertEqual(result["status"], "success")
        self.assertIn("Workbook: simple.xlsx", result["result"])
        self.assertIn("Format: XLSX", result["result"])
        self.assertIn("Total sheets: 1", result["result"])
        self.assertIn("Sheet names: Sheet1", result["result"])
        self.assertIn("Sheets previewed: 1 of 1", result["result"])
        self.assertIn("Preview:", result["result"])
        self.assertIn("| Row | Name | Age | City |", result["result"])
        self.assertIn("| 1 | Alice | 30 | New York |", result["result"])
        self.assertIn("Formula handling:", result["result"])
        self.assertEqual(result["metadata"]["format"], "xlsx")

    def test_multiple_sheets(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        path = self._make_xlsx("multi.xlsx", {
            "Sheet1": [["A", "B"], [1, 2]],
            "Sheet2": [["C", "D"], [3, 4]],
        })
        result = read_spreadsheet.run(path)
        self.assertEqual(result["status"], "success")
        self.assertIn("Total sheets: 2", result["result"])
        self.assertIn("Sheets previewed: 2 of 2", result["result"])
        self.assertIn("Sheet1", result["result"])
        self.assertIn("Sheet2", result["result"])

    # --- Failure modes ---

    def test_missing_file(self):
        result = read_spreadsheet.run(os.path.join(self.tmpdir, "missing.xlsx"))
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "file_not_found")

    def test_non_xlsx_extension(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        path = self._make_xlsx("data.txt", {"Sheet1": [["A"]]})
        # Rename to .txt to test extension guard
        txt_path = os.path.join(self.tmpdir, "data.txt")
        os.rename(path, txt_path)
        result = read_spreadsheet.run(txt_path)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "unsupported_format")

    def test_xls_rejected(self):
        path = os.path.join(self.tmpdir, "legacy.xls")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not a real xls")
        result = read_spreadsheet.run(path)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "unsupported_format")

    def test_xlsm_rejected(self):
        path = os.path.join(self.tmpdir, "macro.xlsm")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not a real xlsm")
        result = read_spreadsheet.run(path)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "unsupported_format")

    def test_invalid_xlsx(self):
        path = os.path.join(self.tmpdir, "bad.xlsx")
        with open(path, "w", encoding="utf-8") as f:
            f.write("this is not a valid xlsx")
        result = read_spreadsheet.run(path)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "read_error")

    # --- Bounding ---

    def test_sheet_cap_enforced(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        path = self._make_xlsx("many_sheets.xlsx", {
            f"Sheet{i}": [[f"Data{i}"]] for i in range(1, 6)
        })
        result = read_spreadsheet.run(path, max_sheets=2)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["metadata"]["sheets_omitted"])
        self.assertIn("Total sheets: 5", result["result"])
        self.assertIn("Sheets previewed: 2 of 5", result["result"])
        self.assertIn("Additional sheets omitted due to preview limit (max 2).", result["result"])
        self.assertNotIn("[truncated]", result["result"])

    def test_row_cap_per_sheet(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        rows = [[f"Col{i}"] for i in range(1, 2)] + [[i] for i in range(200)]
        path = self._make_xlsx("many_rows.xlsx", {"Sheet1": rows})
        result = read_spreadsheet.run(path, max_rows_per_sheet=10)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["metadata"]["rows_omitted"])
        self.assertIn("Additional rows omitted due to preview limit (max 10).", result["result"])
        self.assertNotIn("[truncated]", result["result"])

    def test_column_cap(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        rows = [list(range(60)), list(range(60))]
        path = self._make_xlsx("many_cols.xlsx", {"Sheet1": rows})
        result = read_spreadsheet.run(path, max_columns=10)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["metadata"]["columns_omitted"])
        self.assertIn("Additional columns omitted due to preview limit (max 10).", result["result"])

    def test_cell_length_cap(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        rows = [["A", "B"], ["short", "A" * 600]]
        path = self._make_xlsx("long_cell.xlsx", {"Sheet1": rows})
        result = read_spreadsheet.run(path, max_cell_chars=50)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["metadata"]["cells_truncated"])
        self.assertIn("Some cell values shortened to 50 characters.", result["result"])
        self.assertIn("additional cell content omitted", result["result"])

    def test_no_literal_truncated(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        rows = [["A", "B"]] + [[i, i] for i in range(200)]
        path = self._make_xlsx("no_truncated.xlsx", {"Sheet1": rows})
        result = read_spreadsheet.run(path, max_rows_per_sheet=5)
        self.assertNotIn("[truncated]", result["result"])

    # --- Formula posture ---

    def test_formula_note_present(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        path = self._make_xlsx("formula.xlsx", {"Sheet1": [["A", "B"], [1, 2]]})
        result = read_spreadsheet.run(path)
        self.assertEqual(result["status"], "success")
        self.assertIn("Formula handling:", result["result"])
        self.assertIn("- Formulas are read but not executed.", result["result"])
        self.assertIn("- Cached formula values are shown only if saved in the workbook.", result["result"])
        self.assertIn('- Formula cells without cached values show "cached value unavailable".', result["result"])
        self.assertEqual(result["metadata"]["formula_note"], "Formulas are read but not executed. Cached formula values are shown only if saved in the workbook.")

    def test_formula_text_visible(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        path = self._make_xlsx("formula_text.xlsx", {
            "Sheet1": [
                ["A", "B", "Sum"],
                [10, 20, "=A2+B2"],
            ]
        })
        result = read_spreadsheet.run(path)
        self.assertEqual(result["status"], "success")
        # Formula text should be visible in the preview
        self.assertIn("Formula: =A2+B2", result["result"])
        # No cached value was saved by openpyxl, so it should show unavailable
        self.assertIn("Cached value: unavailable", result["result"])
        # Ensure posture is "read but not executed" rather than positive execution claim
        self.assertIn("Formulas are read but not executed", result["result"])

    def test_sheet_count_distinct_from_preview_row_count(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        rows = [["A", "B"]] + [[i, i] for i in range(20)]
        path = self._make_xlsx("one_sheet_many_rows.xlsx", {"Sheet1": rows})
        result = read_spreadsheet.run(path, max_rows_per_sheet=5)
        self.assertEqual(result["status"], "success")
        # Total sheets should be 1; preview rows should be 5
        self.assertIn("Total sheets: 1", result["result"])
        self.assertIn("Sheets previewed: 1 of 1", result["result"])
        self.assertIn("Preview rows shown: 5", result["result"])
        # Ensure these appear on separate lines
        self.assertIn("Total sheets: 1\nSheet names:", result["result"])

    # --- Result shape ---

    def test_result_shape(self):
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        path = self._make_xlsx("shape.xlsx", {"Sheet1": [["A"], [1]]})
        result = read_spreadsheet.run(path)
        self.assertIn("status", result)
        self.assertIn("result", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["status"], "success")
        meta = result["metadata"]
        self.assertIn("source_path", meta)
        self.assertIn("format", meta)
        self.assertIn("sheet_names", meta)
        self.assertIn("previewed_sheets", meta)

    def test_extensionless_xlsx_executes(self):
        """Extensionless XLSX executes when resolver confirms content."""
        if not HAS_OPENPYXL:
            self.skipTest("openpyxl not available")
        path = self._make_xlsx("extless_xlsx", {"Sheet1": [["Header"], ["Value"]]})
        # Rename to remove extension
        extless_path = os.path.join(self.tmpdir, "extless_xlsx_no_ext")
        os.rename(path, extless_path)
        try:
            result = read_spreadsheet.run(extless_path)
            self.assertEqual(result["status"], "success")
            self.assertIn("Header", result["result"])
            self.assertIn("Value", result["result"])
        finally:
            if os.path.exists(extless_path):
                os.remove(extless_path)

    def test_extensionless_non_xlsx_returns_unsupported(self):
        """Extensionless non-XLSX returns unsupported_format."""
        temp_path = os.path.join(self.tmpdir, "not_xlsx")
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("not a spreadsheet")
        try:
            result = read_spreadsheet.run(temp_path)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "unsupported_format")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()

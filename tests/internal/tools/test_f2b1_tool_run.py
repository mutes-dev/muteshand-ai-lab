"""F2B-1-FIX2: direct tool run tests for has_header string normalization and execution.

Covers:
- preview_table_schema accepts string "1" for has_header and empty sheet_name
- resolve_table_reference accepts string "0" for has_header and empty sheet_name
- Both tools execute successfully against CSV and XLSX
- Both tools return a top-level non-None result key satisfying the output contract
"""

import json
import os
import sys
import csv
import unittest
import tempfile

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from system.entry.system_entry import system_entry
from tools.preview_table_schema import run as preview_table_schema
from tools.resolve_table_reference import run as resolve_table_reference

try:
    import openpyxl
except Exception as exc:  # pragma: no cover
    raise ImportError("openpyxl is required for XLSX tool-run tests") from exc


class TestF2B1ToolRun(unittest.TestCase):
    """Direct execution of preview_table_schema and resolve_table_reference."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(dir=_PROJECT_ROOT)
        self.csv_path = os.path.join(self.tmp_dir, "f2b1.csv")
        self.xlsx_path = os.path.join(self.tmp_dir, "f2b1.xlsx")
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "Price"])
            writer.writerow(["Alice", "10"])
            writer.writerow(["Bob", "20"])

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["Name", "Price"])
        ws.append(["Alice", 10])
        ws.append(["Bob", 20])
        wb.save(self.xlsx_path)

        self.rel_csv = os.path.relpath(self.csv_path, _PROJECT_ROOT)
        self.rel_xlsx = os.path.relpath(self.xlsx_path, _PROJECT_ROOT)

    def tearDown(self):
        for p in (self.csv_path, self.xlsx_path):
            if os.path.exists(p):
                os.remove(p)
        if os.path.exists(self.tmp_dir):
            os.rmdir(self.tmp_dir)

    def test_preview_csv_string_has_header(self):
        result = preview_table_schema(self.rel_csv, "", "1", 1, 0, 0, 0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["headers"], ["Name", "Price"])

    def test_preview_xlsx_empty_sheet_name(self):
        result = preview_table_schema(self.rel_xlsx, "", "1", 1, 0, 0, 0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["headers"], ["Name", "Price"])

    def test_resolve_csv_cell_string_has_header(self):
        result = resolve_table_reference(
            self.rel_csv, "cell", "", "1", 1, 0, "B2", "", 0, "", 0, 0, 0
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["value"], "10")
        self.assertEqual(result["cell_address"], "B2")

    def test_resolve_xlsx_cell_string_has_header(self):
        result = resolve_table_reference(
            self.rel_xlsx, "cell", "", "1", 1, 0, "B2", "", 0, "", 0, 0, 0
        )
        self.assertEqual(result["status"], "success")
        self.assertIn(str(result["value"]), {"10", "10.0"})

    def test_resolve_csv_no_header_string_zero(self):
        result = resolve_table_reference(
            self.rel_csv, "cell", "", "0", 1, 0, "B2", "", 0, "", 0, 0, 0
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["value"], "10")

    def test_resolve_entity_from_row_xlsx(self):
        result = resolve_table_reference(
            self.rel_xlsx, "entity_from_row", "", "1", 1, 2, "", "", 0, "Name", 0, 0, 0
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["entity"], "Alice")

    def test_preview_result_contract(self):
        result = preview_table_schema(self.rel_csv, "", "1", 1, 0, 0, 0)
        self.assertEqual(result["status"], "success")
        self.assertIn("result", result)
        self.assertIsNotNone(result["result"])
        self.assertEqual(result["result"]["headers"], ["Name", "Price"])

    def test_resolve_result_contract(self):
        result = resolve_table_reference(
            self.rel_csv, "cell", "", "1", 1, 0, "B2", "", 0, "", 0, 0, 0
        )
        self.assertEqual(result["status"], "success")
        self.assertIn("result", result)
        self.assertIsNotNone(result["result"])
        self.assertEqual(result["result"]["value"], "10")

    def test_preview_system_entry_result_not_none(self):
        tool_call = f'preview_table_schema "{self.rel_csv}" "" "1" 1 0 0 0'
        result = system_entry(tool_call)
        self.assertEqual(result["status"], "success")
        self.assertIn("result", result)
        self.assertIsNotNone(result["result"])
        self.assertEqual(result["result"]["headers"], ["Name", "Price"])

    def test_resolve_system_entry_result_not_none(self):
        tool_call = f'resolve_table_reference "{self.rel_csv}" "cell" "" "1" 1 0 "B2" "" 0 "" 0 0 0'
        result = system_entry(tool_call)
        self.assertEqual(result["status"], "success")
        self.assertIn("result", result)
        self.assertIsNotNone(result["result"])
        self.assertEqual(result["result"]["value"], "10")

    def test_result_is_json_serializable(self):
        preview_result = preview_table_schema(self.rel_csv, "", "1", 1, 0, 0, 0)
        resolve_result = resolve_table_reference(
            self.rel_csv, "cell", "", "1", 1, 0, "B2", "", 0, "", 0, 0, 0
        )
        for expected_tool, result in (
            ("preview_table_schema", preview_result),
            ("resolve_table_reference", resolve_result),
        ):
            self.assertEqual(result["status"], "success")
            serialized = json.dumps(result)
            deserialized = json.loads(serialized)
            self.assertIsNotNone(deserialized["result"])
            self.assertEqual(deserialized["result"]["tool"], expected_tool)
            self.assertEqual(deserialized["status"], "success")


if __name__ == "__main__":
    unittest.main()

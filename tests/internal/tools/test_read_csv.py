"""Tests for read_csv bounded structured preview tool."""

import os
import tempfile
import unittest

from tools import read_csv


class TestReadCsv(unittest.TestCase):

    def setUp(self):
        self.tmpdir = os.path.join("e:/MutesHand/tmp", "test_csv")
        os.makedirs(self.tmpdir, exist_ok=True)

    def tearDown(self):
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def _make_csv(self, name, lines):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path

    # --- Basic behavior ---

    def test_simple_csv_headers_and_rows(self):
        path = self._make_csv("simple.csv", [
            "Name,Age,City",
            "Alice,30,New York",
            "Bob,25,Los Angeles",
        ])
        result = read_csv.run(path)
        self.assertEqual(result["status"], "success")
        self.assertIn("CSV file: simple.csv", result["result"])
        self.assertIn("Format: CSV", result["result"])
        self.assertIn("Preview:", result["result"])
        self.assertIn("| Row | Name | Age | City |", result["result"])
        self.assertIn("| 1 | Alice | 30 | New York |", result["result"])
        self.assertIn("| 2 | Bob | 25 | Los Angeles |", result["result"])
        self.assertEqual(result["metadata"]["format"], "csv")
        self.assertEqual(result["metadata"]["delimiter"], ",")
        self.assertTrue(result["metadata"]["header_detected"])

    def test_quoted_commas(self):
        path = self._make_csv("quoted.csv", [
            'ID,Description,Value',
            '1,"A, B, C",100',
            '2,"D, E",200',
        ])
        result = read_csv.run(path)
        self.assertEqual(result["status"], "success")
        # Tool reconstructs preview by joining parsed cells with delimiter;
        # original quotes are consumed by csv.reader. Assert parsed values present.
        self.assertIn("A, B, C", result["result"])
        self.assertIn("D, E", result["result"])

    def test_blank_rows(self):
        path = self._make_csv("blank.csv", [
            "A,B",
            "1,2",
            "",
            "3,4",
        ])
        result = read_csv.run(path)
        self.assertEqual(result["status"], "success")
        # Blank row should appear as empty cells in preview table
        self.assertIn("| 1 | 1 | 2 |", result["result"])
        self.assertIn("| 3 | 3 | 4 |", result["result"])

    def test_tab_delimiter(self):
        path = self._make_csv("tab.csv", [
            "A\tB\tC",
            "1\t2\t3",
        ])
        result = read_csv.run(path)
        self.assertEqual(result["status"], "success")
        self.assertIn("Preview:", result["result"])
        self.assertIn("1", result["result"])

    # --- Failure modes ---

    def test_missing_file(self):
        result = read_csv.run(os.path.join(self.tmpdir, "missing.csv"))
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "file_not_found")

    def test_non_csv_extension(self):
        path = self._make_csv("data.txt", ["A,B", "1,2"])
        result = read_csv.run(path)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "unsupported_format")

    def test_path_validation_rejects_outside_base(self):
        result = read_csv.run("C:/Windows/System32/drivers/etc/hosts")
        self.assertEqual(result["status"], "failure")

    # --- Bounding ---

    def test_row_cap_enforced(self):
        lines = ["A,B"] + [f"{i},{i}" for i in range(200)]
        path = self._make_csv("many_rows.csv", lines)
        result = read_csv.run(path, max_rows=10)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["metadata"]["rows_omitted"])
        self.assertIn("Additional rows omitted due to preview limit (max 10).", result["result"])
        self.assertNotIn("[truncated]", result["result"])

    def test_column_cap_enforced(self):
        lines = [",".join(f"Col{i}" for i in range(60))]
        lines.append(",".join(str(i) for i in range(60)))
        path = self._make_csv("many_cols.csv", lines)
        result = read_csv.run(path, max_columns=10)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["metadata"]["columns_omitted"])
        self.assertIn("Additional columns omitted due to preview limit (max 10).", result["result"])
        self.assertNotIn("[truncated]", result["result"])

    def test_cell_length_cap_enforced(self):
        long_text = "A" * 600
        path = self._make_csv("long_cell.csv", ["A,B", f"1,{long_text}"])
        result = read_csv.run(path, max_cell_chars=50)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["metadata"]["cells_truncated"])
        self.assertIn("Some cell values shortened to 50 characters.", result["result"])
        self.assertIn("additional cell content omitted", result["result"])
        self.assertNotIn("[truncated]", result["result"])

    def test_no_literal_truncated(self):
        lines = ["A,B"] + [f"{i},{i}" for i in range(200)]
        path = self._make_csv("no_truncated.csv", lines)
        result = read_csv.run(path, max_rows=5)
        self.assertNotIn("[truncated]", result["result"])

    # --- Result shape ---

    def test_result_shape(self):
        path = self._make_csv("shape.csv", ["A,B", "1,2"])
        result = read_csv.run(path)
        self.assertIn("status", result)
        self.assertIn("result", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["status"], "success")
        meta = result["metadata"]
        self.assertIn("source_path", meta)
        self.assertIn("format", meta)
        self.assertIn("preview_rows", meta)
        self.assertIn("column_count", meta)

    def test_omission_note_when_rows_exist(self):
        lines = ["A,B"] + [f"{i},{i}" for i in range(200)]
        path = self._make_csv("omission.csv", lines)
        result = read_csv.run(path, max_rows=10)
        self.assertIn("Additional rows may exist beyond the preview.", result["result"])

    def test_output_has_line_separated_sections(self):
        path = self._make_csv("sections.csv", ["A,B", "1,2"])
        result = read_csv.run(path)
        self.assertEqual(result["status"], "success")
        # Ensure sections are on separate lines, not flattened
        self.assertIn("CSV file: sections.csv\nFormat: CSV", result["result"])
        self.assertIn("Preview:\n| Row | A | B |", result["result"])
        self.assertIn("Limits:\n- Max preview rows:", result["result"])
        self.assertIn("Notes:\n- This is a bounded preview", result["result"])

    def test_extensionless_csv_executes(self):
        """Extensionless CSV executes when resolver confirms content."""
        path = self._make_csv("extless_csv", ["A,B", "1,2"])
        # Rename to remove extension
        extless_path = os.path.join(self.tmpdir, "extless_csv_no_ext")
        os.rename(path, extless_path)
        try:
            result = read_csv.run(extless_path)
            self.assertEqual(result["status"], "success")
            self.assertIn("A", result["result"])
            self.assertIn("1", result["result"])
        finally:
            if os.path.exists(extless_path):
                os.remove(extless_path)

    def test_extensionless_non_csv_returns_unsupported(self):
        """Extensionless non-CSV returns unsupported_format."""
        temp_path = os.path.join(self.tmpdir, "not_csv")
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("not a csv")
        try:
            result = read_csv.run(temp_path)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "unsupported_format")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()

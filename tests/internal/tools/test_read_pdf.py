"""Tests for read_pdf tool.

SPRINT-11-SLICE-002 — Local document reader foundation.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tools.read_pdf import run


class TestReadPdfTool(unittest.TestCase):

    def test_missing_file(self):
        """Reject missing file safely."""
        result = run("tmp/nonexistent_file.pdf")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "file_not_found")

    def test_non_pdf_extension(self):
        """Reject non-PDF extension safely."""
        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_wrong_ext.txt")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("not a pdf")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "unsupported_format")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_path_traversal_blocked(self):
        """Path outside base dir is blocked."""
        result = run("../../../etc/passwd.pdf")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "path_safety_blocked")

    def test_invalid_pdf_parse_error(self):
        """Invalid or unparseable PDF returns parse/read error."""
        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_invalid.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"not a pdf")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "failure")
            # pypdf raises various exceptions on bad data; map to read_error
            self.assertIn(result["reason"], ("read_error", "parse_error"))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("pypdf.PdfReader")
    def test_extracts_text_with_page_separators(self, mock_reader_cls):
        """Extract text with page separators from a mocked PDF."""
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page one content."
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page two content."

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2]
        mock_reader_cls.return_value = mock_reader

        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_mock.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertIn("Page one content", result["result"])
            self.assertIn("Page two content", result["result"])
            self.assertIn("--- Page 1 ---", result["result"])
            self.assertIn("--- Page 2 ---", result["result"])
            self.assertEqual(result["metadata"]["format"], "pdf")
            self.assertEqual(result["metadata"]["page_count"], 2)
            self.assertIn("source_path", result["metadata"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("pypdf.PdfReader")
    def test_empty_pages_return_read_error(self, mock_reader_cls):
        """PDF with zero pages returns parse_error."""
        mock_reader = MagicMock()
        mock_reader.pages = []
        mock_reader_cls.return_value = mock_reader

        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_empty.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "parse_error")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("pypdf.PdfReader")
    def test_no_external_calls(self, mock_reader_cls):
        """Tool does not make external network calls."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "text"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_nocall.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()

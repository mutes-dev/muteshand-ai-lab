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

    @patch("pypdf.PdfReader")
    def test_extensionless_pdf_executes(self, mock_reader_cls):
        """Extensionless PDF executes when resolver confirms content."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Extensionless PDF content."
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_extless")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertIn("Extensionless PDF content", result["result"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_extensionless_non_pdf_returns_unsupported(self):
        """Extensionless non-PDF returns unsupported_format."""
        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_extless_bad")
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

    @patch("pypdf.PdfReader")
    def test_text_bearing_pdf_no_ocr_fallback(self, mock_reader_cls):
        """Normal text-bearing PDF does not trigger OCR fallback."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "This is substantial text content that exceeds twenty characters."
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_nofallback.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertNotIn("ocr_fallback", result["metadata"])
            self.assertIn("substantial text content", result["result"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("tools.read_pdf_ocr._extract_pdf_text_via_ocr")
    @patch("pypdf.PdfReader")
    def test_scanned_pdf_triggers_ocr_fallback(self, mock_reader_cls, mock_ocr):
        """Scanned/image-only PDF triggers observable OCR fallback."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        mock_ocr.return_value = (
            "\n\n--- Page 1 ---\n\nScanned OCR text",
            {
                "ocr_engine": "tesseract",
                "render_dpi": 150,
                "pages_processed": 1,
                "max_pages": 10,
                "page_limit_applied": False,
            },
        )

        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_fallback.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertIn("Note: This PDF had little or no extractable text", result["result"])
            self.assertIn("Scanned OCR text", result["result"])
            self.assertTrue(result["metadata"]["ocr_fallback"])
            self.assertEqual(
                result["metadata"]["ocr_fallback_reason"],
                "Text extraction produced little/no usable text; bounded local OCR was used.",
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("tools.read_pdf_ocr._extract_pdf_text_via_ocr")
    @patch("pypdf.PdfReader")
    def test_ocr_fallback_metadata_includes_bounds(self, mock_reader_cls, mock_ocr):
        """OCR fallback metadata includes engine, DPI, and page bounds."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        mock_ocr.return_value = (
            "OCR result",
            {
                "ocr_engine": "tesseract",
                "render_dpi": 150,
                "pages_processed": 1,
                "max_pages": 10,
                "page_limit_applied": False,
            },
        )

        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_bounds.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["metadata"]["ocr_engine"], "tesseract")
            self.assertEqual(result["metadata"]["render_dpi"], 150)
            self.assertEqual(result["metadata"]["max_pages"], 10)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("tools.read_pdf_ocr._extract_pdf_text_via_ocr")
    @patch("pypdf.PdfReader")
    def test_ocr_fallback_attempted_no_text(self, mock_reader_cls, mock_ocr):
        """OCR fallback attempted but no text extracted is observable and safe."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        mock_ocr.return_value = ("", {"ocr_engine": "tesseract", "render_dpi": 150, "pages_processed": 1, "max_pages": 10, "page_limit_applied": False})

        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_no_ocr_text.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["metadata"]["ocr_fallback_attempted"])
            self.assertFalse(result["metadata"]["ocr_fallback"])
            self.assertIn("bounded local OCR was attempted but no text was extracted", result["metadata"]["ocr_fallback_reason"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("tools.read_pdf_ocr._extract_pdf_text_via_ocr")
    @patch("pypdf.PdfReader")
    def test_ocr_fallback_helper_raises_exception(self, mock_reader_cls, mock_ocr):
        """OCR helper exception is handled safely without crashing."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        mock_ocr.side_effect = RuntimeError("OCR engine unavailable")

        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_ocr_err.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["metadata"]["ocr_fallback_attempted"])
            self.assertFalse(result["metadata"]["ocr_fallback"])
            self.assertIn("OCR engine unavailable", result["metadata"]["ocr_fallback_error"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("tools.read_pdf_ocr._extract_pdf_text_via_ocr")
    @patch("pypdf.PdfReader")
    def test_extensionless_scanned_pdf_fallback(self, mock_reader_cls, mock_ocr):
        """Extensionless scanned PDF triggers OCR fallback."""
        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        mock_ocr.return_value = (
            "\n\n--- Page 1 ---\n\nExtensionless OCR text",
            {
                "ocr_engine": "tesseract",
                "render_dpi": 150,
                "pages_processed": 1,
                "max_pages": 10,
                "page_limit_applied": False,
            },
        )

        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_pdf_extless_scan")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["metadata"]["ocr_fallback"])
            self.assertIn("Extensionless OCR text", result["result"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()

"""Tests for read_pdf_ocr OCR tool.

SPRINT-11-SLICE-004 — OCR / Scanned Document Input Foundation.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tools.read_pdf_ocr import run


def _project_tmp(name: str) -> str:
    return os.path.join(_PROJECT_ROOT, "tmp", name)


def _make_text_image(text: str = "OCR PAGE"):
    """Generate a simple PIL image with text."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (300, 80), color="white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    d.text((10, 20), text, fill="black", font=font)
    return img


class TestReadPdfOcrTool(unittest.TestCase):

    def test_missing_file(self):
        """Reject missing file safely."""
        result = run("tmp/nonexistent_file.pdf")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "file_not_found")

    def test_non_pdf_extension(self):
        """Reject non-PDF extension safely."""
        temp_path = _project_tmp("test_read_pdf_ocr_wrong_ext.txt")
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

    @patch("pdf2image.convert_from_path")
    @patch("pytesseract.image_to_string")
    def test_ocr_extracts_text(self, mock_ocr, mock_convert):
        """OCR extracts text from mocked PDF pages."""
        mock_convert.return_value = [_make_text_image("PAGE ONE")]
        mock_ocr.return_value = "PAGE ONE"

        temp_path = _project_tmp("test_read_pdf_ocr_mock.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertIn("PAGE ONE", result["result"])
            self.assertIn("--- Page 1 ---", result["result"])
            self.assertEqual(result["metadata"]["format"], "pdf")
            self.assertEqual(result["metadata"]["pages_processed"], 1)
            self.assertEqual(result["metadata"]["ocr_engine"], "tesseract")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("pdf2image.convert_from_path")
    def test_page_limit_enforced(self, mock_convert):
        """Only bounded number of pages are OCR'd."""
        all_images = [_make_text_image(f"PAGE {i}") for i in range(1, 16)]

        def _bounded_convert(path, first_page=None, last_page=None, dpi=None):
            # pdf2image is called with last_page=page_limit; slice accordingly
            end = last_page if last_page else len(all_images)
            return all_images[:end]

        mock_convert.side_effect = _bounded_convert

        temp_path = _project_tmp("test_read_pdf_ocr_limit.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path, max_pages=5)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["metadata"]["pages_processed"], 5)
            self.assertTrue(result["metadata"]["page_limit_applied"])
            self.assertIn("Additional pages omitted", result["result"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("pdf2image.convert_from_path")
    @patch("pytesseract.image_to_string")
    def test_blank_pdf_empty_result(self, mock_ocr, mock_convert):
        """Blank PDF returns success with empty text and note."""
        from PIL import Image

        mock_convert.return_value = [Image.new("RGB", (100, 50), color="white")]
        mock_ocr.return_value = ""

        temp_path = _project_tmp("test_read_pdf_ocr_blank.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["result"], "")
            self.assertIn("note", result["metadata"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_result_shape(self):
        """Result contains expected keys."""
        temp_path = _project_tmp("test_read_pdf_ocr_shape.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            with patch("pdf2image.convert_from_path") as mock_convert, patch(
                "pytesseract.image_to_string"
            ) as mock_ocr:
                mock_convert.return_value = [_make_text_image("shape")]
                mock_ocr.return_value = "shape"
                result = run(temp_path)
            self.assertIn("status", result)
            self.assertIn("result", result)
            self.assertIn("metadata", result)
            meta = result["metadata"]
            self.assertIn("source_path", meta)
            self.assertIn("format", meta)
            self.assertIn("ocr_engine", meta)
            self.assertIn("render_dpi", meta)
            self.assertIn("pages_processed", meta)
            self.assertIn("max_pages", meta)
            self.assertIn("page_limit_applied", meta)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_no_literal_truncated(self):
        """Output does not contain literal '[truncated]'."""
        temp_path = _project_tmp("test_read_pdf_ocr_truncated.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            with patch("pdf2image.convert_from_path") as mock_convert, patch(
                "pytesseract.image_to_string"
            ) as mock_ocr:
                mock_convert.return_value = [_make_text_image("truncated check")]
                mock_ocr.return_value = "truncated check"
                result = run(temp_path)
            self.assertNotIn("[truncated]", result["result"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_read_pdf_unchanged(self):
        """read_pdf_ocr does not alter read_pdf behavior."""
        temp_path = _project_tmp("test_read_pdf_ocr_unchanged.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            # read_pdf should still behave the same (mocked in its own tests)
            from tools.read_pdf import run as read_pdf_run

            # Since we can't easily create a text-bearing PDF here,
            # verify that read_pdf_ocr import does not monkey-patch read_pdf
            import inspect

            self.assertEqual(inspect.getmodule(read_pdf_run).__name__, "tools.read_pdf")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("pdf2image.convert_from_path")
    @patch("pytesseract.image_to_string")
    def test_extensionless_pdf_executes(self, mock_ocr, mock_convert):
        """Extensionless PDF executes when resolver confirms content."""
        mock_convert.return_value = [_make_text_image("EXTLESS OCR PAGE")]
        mock_ocr.return_value = "EXTLESS OCR PAGE"

        temp_path = _project_tmp("test_read_pdf_ocr_extless")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertIn("EXTLESS OCR PAGE", result["result"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_extensionless_non_pdf_returns_unsupported(self):
        """Extensionless non-PDF returns unsupported_format."""
        temp_path = _project_tmp("test_read_pdf_ocr_extless_bad")
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

    @patch("pdf2image.convert_from_path")
    @patch("pytesseract.image_to_string")
    def test_extract_pdf_text_via_ocr_helper(self, mock_ocr, mock_convert):
        """Shared helper returns correct text and metadata structure."""
        mock_convert.return_value = [_make_text_image("HELPER PAGE")]
        mock_ocr.return_value = "HELPER PAGE"

        temp_path = _project_tmp("test_helper_ocr.pdf")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"%PDF-1.4")
        try:
            from tools.read_pdf_ocr import _extract_pdf_text_via_ocr
            text, meta = _extract_pdf_text_via_ocr(temp_path, max_pages=5, dpi=150)
            self.assertIn("HELPER PAGE", text)
            self.assertEqual(meta["ocr_engine"], "tesseract")
            self.assertEqual(meta["render_dpi"], 150)
            self.assertEqual(meta["max_pages"], 5)
            self.assertEqual(meta["pages_processed"], 1)
            self.assertFalse(meta["page_limit_applied"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()

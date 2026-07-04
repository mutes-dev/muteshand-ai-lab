"""Tests for read_image_text OCR tool.

SPRINT-11-SLICE-004 — OCR / Scanned Document Input Foundation.
"""

import os
import sys
import unittest
from unittest.mock import patch

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tools.read_image_text import run


def _project_tmp(name: str) -> str:
    return os.path.join(_PROJECT_ROOT, "tmp", name)


def _make_text_image(path: str, text: str = "Hello OCR"):
    """Generate a simple image with text for OCR testing."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (300, 80), color="white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    d.text((10, 20), text, fill="black", font=font)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)


class TestReadImageTextTool(unittest.TestCase):

    def test_missing_file(self):
        """Reject missing file safely."""
        result = run("tmp/nonexistent_file.png")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "file_not_found")

    def test_non_image_extension(self):
        """Reject non-image extension safely."""
        temp_path = _project_tmp("test_read_image_text_wrong_ext.txt")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("not an image")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "unsupported_format")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_path_traversal_blocked(self):
        """Path outside base dir is blocked."""
        result = run("../../../etc/passwd.png")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "path_safety_blocked")

    def test_extracts_text_from_png(self):
        """OCR extracts text from a generated PNG."""
        temp_path = _project_tmp("test_read_image_text_ocr.png")
        try:
            _make_text_image(temp_path, "OCR TEST")
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            # OCR may not be perfect; assert approximate content
            self.assertIn("OCR", result["result"])
            self.assertIn("TEST", result["result"])
            self.assertEqual(result["metadata"]["format"], "png")
            self.assertIn("source_path", result["metadata"])
            self.assertIn("ocr_engine", result["metadata"])
            self.assertEqual(result["metadata"]["ocr_engine"], "tesseract")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_extracts_text_from_jpg(self):
        """OCR extracts text from a generated JPEG."""
        temp_path = _project_tmp("test_read_image_text_ocr.jpg")
        try:
            _make_text_image(temp_path, "JPEG OCR")
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertIn("JPEG", result["result"])
            self.assertIn("OCR", result["result"])
            self.assertEqual(result["metadata"]["format"], "jpg")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_blank_image_returns_safe_empty(self):
        """Blank image returns success with empty result and note."""
        temp_path = _project_tmp("test_read_image_text_blank.png")
        try:
            from PIL import Image

            img = Image.new("RGB", (100, 50), color="white")
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            img.save(temp_path)
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["result"], "")
            self.assertIn("note", result["metadata"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_large_image_downscale(self):
        """Large image is downscaled before OCR."""
        temp_path = _project_tmp("test_read_image_text_large.png")
        try:
            from PIL import Image

            # Create a large image (exceeds 4096 bound)
            img = Image.new("RGB", (5000, 5000), color="white")
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            img.save(temp_path)
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["metadata"]["resized"])
            # Should still have reasonable dimensions in metadata
            self.assertEqual(result["metadata"]["width"], 5000)
            self.assertEqual(result["metadata"]["height"], 5000)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_result_shape(self):
        """Result contains expected keys."""
        temp_path = _project_tmp("test_read_image_text_shape.png")
        try:
            _make_text_image(temp_path, "shape")
            result = run(temp_path)
            self.assertIn("status", result)
            self.assertIn("result", result)
            self.assertIn("metadata", result)
            meta = result["metadata"]
            self.assertIn("source_path", meta)
            self.assertIn("format", meta)
            self.assertIn("width", meta)
            self.assertIn("height", meta)
            self.assertIn("resized", meta)
            self.assertIn("ocr_engine", meta)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_no_literal_truncated(self):
        """Output does not contain literal '[truncated]'."""
        temp_path = _project_tmp("test_read_image_text_truncated.png")
        try:
            _make_text_image(temp_path, "truncated check")
            result = run(temp_path)
            self.assertNotIn("[truncated]", result["result"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @patch("pytesseract.image_to_string")
    def test_no_external_calls(self, mock_ocr):
        """Tool does not make external network calls."""
        mock_ocr.return_value = "local text"
        temp_path = _project_tmp("test_read_image_text_nocall.png")
        try:
            from PIL import Image

            img = Image.new("RGB", (100, 50), color="white")
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            img.save(temp_path)
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()

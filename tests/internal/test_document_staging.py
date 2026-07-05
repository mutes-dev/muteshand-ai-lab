"""Tests for SPRINT-11-SLICE-006 — Document Staging Endpoint.

Run:
    cd E:\MutesHand
    python -m pytest tests\internal\test_document_staging.py -v --tb=short
"""

import os
import sys
import tempfile
import unittest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if os.path.join(_PROJECT_ROOT, "ai_lab_gui", "backend") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "ai_lab_gui", "backend"))

from fastapi.testclient import TestClient
from api import app, _sanitize_filename, _STAGING_DIR

client = TestClient(app)


def _staged_abs_path(staged_path: str) -> str:
    """Resolve a relative staged path under project root."""
    return os.path.join(_PROJECT_ROOT, staged_path.replace("/", os.sep))


def _cleanup_staged(staged_path: str):
    """Remove a staged file if it exists."""
    p = _staged_abs_path(staged_path)
    if os.path.exists(p):
        os.remove(p)


class TestSanitizeFilename(unittest.TestCase):

    def test_basic_name(self):
        self.assertEqual(_sanitize_filename("report.pdf"), "report.pdf")

    def test_spaces_preserved(self):
        self.assertEqual(_sanitize_filename("My Report.pdf"), "My Report.pdf")

    def test_path_traversal_basename(self):
        # basename of ../../etc/passwd is passwd; sanitize keeps only safe chars
        self.assertEqual(_sanitize_filename("../../etc/passwd"), "passwd")

    def test_null_bytes_rejected(self):
        with self.assertRaises(Exception):
            _sanitize_filename("file\x00.txt")

    def test_unsafe_chars_replaced(self):
        self.assertEqual(_sanitize_filename("file<name>.pdf"), "file_name_.pdf")

    def test_empty_name(self):
        self.assertEqual(_sanitize_filename(""), "unnamed")

    def test_long_name_truncated(self):
        long_name = "a" * 250 + ".pdf"
        result = _sanitize_filename(long_name)
        self.assertLessEqual(len(result), 200)
        self.assertTrue(result.endswith(".pdf"))


class TestStageEndpoint(unittest.TestCase):

    def test_stage_pdf_like_file(self):
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>"
        response = client.post(
            "/documents/stage",
            files={"file": ("test_report.pdf", pdf_bytes, "application/pdf")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("tmp/gui_stage/", data["staged_path"])
        self.assertEqual(data["filename"], "test_report.pdf")
        self.assertEqual(data["size_bytes"], len(pdf_bytes))
        self.assertEqual(data["detected_type"], "pdf")
        # Verify file exists
        abs_path = _staged_abs_path(data["staged_path"])
        self.assertTrue(os.path.exists(abs_path))
        _cleanup_staged(data["staged_path"])

    def test_stage_csv_like_file(self):
        csv_bytes = b"name,age\nAlice,30\nBob,25\n"
        response = client.post(
            "/documents/stage",
            files={"file": ("sample.csv", csv_bytes, "text/csv")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("tmp/gui_stage/", data["staged_path"])
        self.assertEqual(data["detected_type"], "csv")
        abs_path = _staged_abs_path(data["staged_path"])
        self.assertTrue(os.path.exists(abs_path))
        _cleanup_staged(data["staged_path"])

    def test_stage_image_like_file(self):
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        response = client.post(
            "/documents/stage",
            files={"file": ("image.png", png_bytes, "image/png")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["detected_type"], "png")
        abs_path = _staged_abs_path(data["staged_path"])
        self.assertTrue(os.path.exists(abs_path))
        _cleanup_staged(data["staged_path"])

    def test_stage_extensionless_file(self):
        extless_bytes = b"Hello, this is a plain text file without extension."
        response = client.post(
            "/documents/stage",
            files={"file": ("plainfile", extless_bytes, "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("tmp/gui_stage/", data["staged_path"])
        self.assertTrue("plainfile" in data["staged_path"])
        abs_path = _staged_abs_path(data["staged_path"])
        self.assertTrue(os.path.exists(abs_path))
        _cleanup_staged(data["staged_path"])

    def test_staged_file_under_controlled_directory(self):
        pdf_bytes = b"%PDF-1.4\n1 0 obj"
        response = client.post(
            "/documents/stage",
            files={"file": ("dir_test.pdf", pdf_bytes, "application/pdf")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        abs_path = _staged_abs_path(data["staged_path"])
        real_staging = os.path.realpath(_STAGING_DIR)
        real_staged = os.path.realpath(abs_path)
        self.assertTrue(
            real_staged == real_staging or real_staged.startswith(real_staging + os.sep)
        )
        _cleanup_staged(data["staged_path"])

    def test_path_traversal_filename_rejected(self):
        response = client.post(
            "/documents/stage",
            files={"file": ("../../../etc/passwd", b"bad", "text/plain")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        abs_path = _staged_abs_path(data["staged_path"])
        real_staging = os.path.realpath(_STAGING_DIR)
        real_staged = os.path.realpath(abs_path)
        self.assertTrue(
            real_staged == real_staging or real_staged.startswith(real_staging + os.sep)
        )
        _cleanup_staged(data["staged_path"])

    def test_duplicate_filenames_no_overwrite(self):
        pdf_bytes = b"%PDF-1.4\n1 0 obj"
        resp1 = client.post(
            "/documents/stage",
            files={"file": ("same.pdf", pdf_bytes, "application/pdf")},
        )
        resp2 = client.post(
            "/documents/stage",
            files={"file": ("same.pdf", pdf_bytes, "application/pdf")},
        )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        data1 = resp1.json()
        data2 = resp2.json()
        self.assertNotEqual(data1["staged_path"], data2["staged_path"])
        _cleanup_staged(data1["staged_path"])
        _cleanup_staged(data2["staged_path"])

    def test_max_file_size_enforced(self):
        big_bytes = b"x" * (50 * 1024 * 1024 + 1)
        response = client.post(
            "/documents/stage",
            files={"file": ("big.bin", big_bytes, "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 413)
        data = response.json()
        self.assertIn("50 MB", data.get("detail", ""))

    def test_unknown_binary_staged_safely(self):
        binary_bytes = b"\x00\x01\x02\x03\x04\x05"
        response = client.post(
            "/documents/stage",
            files={"file": ("unknown.bin", binary_bytes, "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["detected_type"], "unknown")
        abs_path = _staged_abs_path(data["staged_path"])
        self.assertTrue(os.path.exists(abs_path))
        _cleanup_staged(data["staged_path"])

    def test_missing_file_rejected(self):
        response = client.post("/documents/stage")
        self.assertEqual(response.status_code, 422)

    def test_staged_path_usable_by_document_local_read(self):
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>"
        resp = client.post(
            "/documents/stage",
            files={"file": ("routing_test.pdf", pdf_bytes, "application/pdf")},
        )
        data = resp.json()
        staged_path = data["staged_path"]

        from system.orchestrator.capabilities.document_local_read_capability import (
            compile_document_local_read_workflow,
        )
        wf = compile_document_local_read_workflow(f'Read the file "{staged_path}"')
        self.assertIsNotNone(wf)
        self.assertEqual(len(wf["steps"]), 2)
        self.assertEqual(wf["steps"][0]["capability_metadata"]["allowed_tool"], "read_pdf")
        _cleanup_staged(staged_path)

    def test_staged_pdf_routes_to_read_pdf(self):
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>"
        resp = client.post(
            "/documents/stage",
            files={"file": ("pdf_route.pdf", pdf_bytes, "application/pdf")},
        )
        data = resp.json()
        staged_path = data["staged_path"]
        abs_path = _staged_abs_path(staged_path)

        from system.orchestrator.capabilities.document_intake_resolver import resolve_document_tool
        result = resolve_document_tool(abs_path)
        self.assertEqual(result.get("tool"), "read_pdf")
        _cleanup_staged(staged_path)

    def test_staged_image_routes_to_read_image_text(self):
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        resp = client.post(
            "/documents/stage",
            files={"file": ("img_route.png", png_bytes, "image/png")},
        )
        data = resp.json()
        staged_path = data["staged_path"]
        abs_path = _staged_abs_path(staged_path)

        from system.orchestrator.capabilities.document_intake_resolver import resolve_document_tool
        result = resolve_document_tool(abs_path)
        self.assertEqual(result.get("tool"), "read_image_text")
        _cleanup_staged(staged_path)

    def test_staged_scanned_pdf_routes_via_read_pdf(self):
        # Low-text PDF bytes (no actual pages, but magic bytes make it a PDF)
        scanned_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>"
        resp = client.post(
            "/documents/stage",
            files={"file": ("scanned.pdf", scanned_pdf, "application/pdf")},
        )
        data = resp.json()
        staged_path = data["staged_path"]
        abs_path = _staged_abs_path(staged_path)

        from system.orchestrator.capabilities.document_intake_resolver import resolve_document_tool
        result = resolve_document_tool(abs_path)
        self.assertEqual(result.get("tool"), "read_pdf")
        _cleanup_staged(staged_path)


if __name__ == "__main__":
    unittest.main()

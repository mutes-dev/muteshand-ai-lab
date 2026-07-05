"""Tests for read_file tool.

SPRINT-11-SLICE-005-FIX2 — Safe unsupported handling for binary files.
"""

import os
import sys
import unittest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tools.read_file import run


class TestReadFileTool(unittest.TestCase):

    def test_missing_file(self):
        """Reject missing file safely."""
        result = run("tmp/nonexistent_file_12345.txt")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "file_not_found")

    def test_path_traversal_blocked(self):
        """Path outside base dir is blocked."""
        result = run("../../../etc/passwd")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "path_safety_blocked")

    def test_binary_file_returns_unsupported_format(self):
        """Binary file with null bytes returns unsupported_format, not read_error."""
        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_file_binary")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"\x00\x01\x02\xff\xfe")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "unsupported_format")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_invalid_utf8_returns_unsupported_format(self):
        """Invalid UTF-8 without null bytes returns unsupported_format via UnicodeDecodeError."""
        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_file_bad_utf8")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        # 0xff 0xfe is a valid UTF-16 BOM but invalid as standalone UTF-8 bytes (no null)
        with open(temp_path, "wb") as f:
            f.write(b"\xff\xfe")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "unsupported_format")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_normal_text_file_succeeds(self):
        """Normal UTF-8 text file reads successfully."""
        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_file_text.txt")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("Hello world\nLine two\n")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["result"], "Hello world\nLine two\n")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_empty_text_file_succeeds(self):
        """Empty text file returns success with empty string."""
        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_file_empty.txt")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("")
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["result"], "")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_no_binary_dump_in_result(self):
        """Binary file must not leak content into result."""
        temp_path = os.path.join(_PROJECT_ROOT, "tmp", "test_read_file_no_leak")
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        with open(temp_path, "wb") as f:
            f.write(b"\x00" + b"A" * 1000)
        try:
            result = run(temp_path)
            self.assertEqual(result["status"], "failure")
            self.assertNotIn("result", result) or result.get("result") is None
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()

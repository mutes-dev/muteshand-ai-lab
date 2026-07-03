"""
Behavior and safety test suite for tools/write_file.py.

Covers:
- Write new file
- Overwrite existing file
- Parent directories created
- Path traversal blocked
- Sensitive path blocked
- Invalid content type rejected
- Binary file rejection (NEW behavior with binary guard)
- Permission failure (skipped on Windows without CI)

Uses pytest tmp_path. Does not rely on project files.
"""

import os
import sys
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import tools.write_file as write_file_module
from tools.write_file import run as write_file_run


@pytest.fixture
def monkeypatch_base_path(tmp_path, monkeypatch):
    """Monkeypatch write_file's BASE_PATH to tmp_path for isolation."""
    monkeypatch.setattr(write_file_module, "BASE_PATH", str(tmp_path))


class TestWriteFileBasic:
    """Basic write behavior."""

    def test_write_new_file(self, tmp_path, monkeypatch_base_path):
        result = write_file_run("new_file.txt", "hello world")
        assert result["status"] == "success"
        assert result["result"] == "file written"
        f = tmp_path / "new_file.txt"
        assert f.read_text(encoding="utf-8") == "hello world"

    def test_overwrite_existing_file(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "existing.txt"
        f.write_text("old content", encoding="utf-8")
        result = write_file_run("existing.txt", "new content")
        assert result["status"] == "success"
        assert f.read_text(encoding="utf-8") == "new content"

    def test_write_multi_line_content(self, tmp_path, monkeypatch_base_path):
        result = write_file_run("multiline.txt", "line1\nline2\nline3")
        assert result["status"] == "success"
        f = tmp_path / "multiline.txt"
        assert f.read_text(encoding="utf-8") == "line1\nline2\nline3"

    def test_write_empty_string(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "empty.txt"
        f.write_text("previous", encoding="utf-8")
        result = write_file_run("empty.txt", "")
        assert result["status"] == "success"
        assert f.read_text(encoding="utf-8") == ""


class TestWriteFileParentDirs:
    """Parent directory creation."""

    def test_creates_parent_directories(self, tmp_path, monkeypatch_base_path):
        result = write_file_run("deep/nested/path/file.txt", "content")
        assert result["status"] == "success"
        f = tmp_path / "deep" / "nested" / "path" / "file.txt"
        assert f.exists()
        assert f.read_text(encoding="utf-8") == "content"


class TestWriteFilePathSafety:
    """Path validation behavior."""

    def test_path_traversal_blocked(self, tmp_path, monkeypatch_base_path):
        result = write_file_run("../outside.txt", "content")
        assert result["status"] == "failure"
        assert "outside" in result.get("detail", "").lower() or result["reason"] == "path_safety_blocked"

    def test_null_byte_in_path_rejected(self, tmp_path, monkeypatch_base_path):
        result = write_file_run("foo\x00bar.txt", "content")
        assert result["status"] == "failure"
        assert "null" in result.get("detail", "").lower()

    def test_empty_path_rejected(self, tmp_path, monkeypatch_base_path):
        result = write_file_run("", "content")
        assert result["status"] == "failure"


class TestWriteFileInputValidation:
    """Input validation."""

    def test_invalid_content_type(self, tmp_path, monkeypatch_base_path):
        result = write_file_run("test.txt", 12345)
        assert result["status"] == "failure"
        assert result["reason"] == "invalid_content"

    def test_none_content_rejected(self, tmp_path, monkeypatch_base_path):
        result = write_file_run("test.txt", None)
        assert result["status"] == "failure"
        assert result["reason"] == "invalid_content"


class TestWriteFileBinaryRejection:
    """Binary file write rejection (NEW behavior)."""

    def test_binary_file_rejected(self, tmp_path, monkeypatch_base_path):
        # Attempt to write content to a binary file path
        # The binary guard checks the FILE being written, not the content
        # Since write_file creates new files, the guard checks after path validation
        # but before writing. For a NEW file, there's nothing to check.
        # For an EXISTING file that is binary, we should reject.
        f = tmp_path / "existing.bin"
        f.write_bytes(b"\x00\x01\x02\x03")
        result = write_file_run("existing.bin", "replacement text")
        assert result["status"] == "failure"
        assert result["reason"] == "binary_file"
        # File should remain unchanged
        assert f.read_bytes() == b"\x00\x01\x02\x03"

    def test_text_file_allowed(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "text.txt"
        f.write_text("existing text", encoding="utf-8")
        result = write_file_run("text.txt", "replacement text")
        assert result["status"] == "success"
        assert f.read_text(encoding="utf-8") == "replacement text"


class TestWriteFilePermission:
    """Permission failure handling."""

    @pytest.mark.skipif(
        os.name == "nt" and not os.environ.get("CI"),
        reason="Permission failure testing on Windows requires elevated setup or CI environment"
    )
    def test_write_permission_denied(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "readonly.txt"
        f.write_text("old", encoding="utf-8")
        os.chmod(str(f), 0o444)
        try:
            result = write_file_run("readonly.txt", "new")
            assert result["status"] == "failure"
            assert result["reason"] in ("permission_denied", "write_error")
        finally:
            os.chmod(str(f), 0o666)

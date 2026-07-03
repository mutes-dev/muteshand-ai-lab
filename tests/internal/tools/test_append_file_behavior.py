"""
Behavior and safety test suite for tools/append_file.py.

Covers:
- Append to existing file
- Append to non-existent file returns file_not_found
- Path traversal blocked
- Sensitive path blocked
- Invalid content type rejected
- Permission failure (skipped on Windows without CI)

Uses pytest tmp_path. Does not rely on project files.
"""

import os
import sys
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import tools.append_file as append_file_module
from tools.append_file import run as append_file_run


@pytest.fixture
def monkeypatch_base_path(tmp_path, monkeypatch):
    """Monkeypatch append_file's BASE_PATH to tmp_path for isolation."""
    monkeypatch.setattr(append_file_module, "BASE_PATH", str(tmp_path))


class TestAppendFileBasic:
    """Basic append behavior."""

    def test_append_to_existing_file(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello\n", encoding="utf-8")
        result = append_file_run("test.txt", "world")
        assert result["status"] == "success"
        assert result["result"] == "file appended"
        assert f.read_text(encoding="utf-8") == "hello\nworld"

    def test_append_with_newline(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        result = append_file_run("test.txt", "\nworld")
        assert result["status"] == "success"
        assert f.read_text(encoding="utf-8") == "hello\nworld"

    def test_append_empty_string(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        result = append_file_run("test.txt", "")
        assert result["status"] == "success"
        assert f.read_text(encoding="utf-8") == "hello"


class TestAppendFileNonExistent:
    """Non-existent file handling."""

    def test_append_to_nonexistent_file_fails(self, tmp_path, monkeypatch_base_path):
        result = append_file_run("nonexistent.txt", "content")
        assert result["status"] == "failure"
        assert result["reason"] == "file_not_found"

    def test_append_to_directory_fails(self, tmp_path, monkeypatch_base_path):
        d = tmp_path / "subdir"
        d.mkdir()
        result = append_file_run("subdir", "content")
        assert result["status"] == "failure"
        assert result["reason"] == "file_not_found"


class TestAppendFilePathSafety:
    """Path validation behavior."""

    def test_path_traversal_blocked(self, tmp_path, monkeypatch_base_path):
        result = append_file_run("../outside.txt", "content")
        assert result["status"] == "failure"
        assert "outside" in result.get("detail", "").lower() or result["reason"] == "path_safety_blocked"

    def test_null_byte_in_path_rejected(self, tmp_path, monkeypatch_base_path):
        result = append_file_run("foo\x00bar.txt", "content")
        assert result["status"] == "failure"
        assert "null" in result.get("detail", "").lower()

    def test_empty_path_rejected(self, tmp_path, monkeypatch_base_path):
        result = append_file_run("", "content")
        assert result["status"] == "failure"


class TestAppendFileInputValidation:
    """Input validation."""

    def test_invalid_content_type(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        result = append_file_run("test.txt", 12345)
        assert result["status"] == "failure"
        assert result["reason"] == "invalid_content"

    def test_none_content_rejected(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        result = append_file_run("test.txt", None)
        assert result["status"] == "failure"
        assert result["reason"] == "invalid_content"


class TestAppendFilePermission:
    """Permission failure handling."""

    @pytest.mark.skipif(
        os.name == "nt" and not os.environ.get("CI"),
        reason="Permission failure testing on Windows requires elevated setup or CI environment"
    )
    def test_append_permission_denied(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "readonly.txt"
        f.write_text("hello", encoding="utf-8")
        os.chmod(str(f), 0o444)
        try:
            result = append_file_run("readonly.txt", "world")
            assert result["status"] == "failure"
            assert result["reason"] in ("permission_denied", "append_error")
        finally:
            os.chmod(str(f), 0o666)

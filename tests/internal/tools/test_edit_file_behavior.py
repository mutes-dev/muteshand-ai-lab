"""
Behavior and safety test suite for tools/edit_file.py.

Covers:
- Exact match replacement
- replace_all=1 replaces multiple occurrences
- Ambiguous match rejection when count>1 and replace_all=0
- Missing old_text returns old_text_not_found
- Empty old_text rejected
- Binary file rejected
- dry_run does not write to disk
- dry_run returns preview / replacements count / result shape
- Non-existent file failure
- Invalid path failure
- Preview truncation / first changed line behavior
- Write permission failure (skipped on Windows without CI)

Uses pytest tmp_path. Does not rely on project files.
"""

import os
import sys
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import tools.edit_file as edit_file_module
from tools.edit_file import run as edit_file_run


@pytest.fixture
def monkeypatch_base_path(tmp_path, monkeypatch):
    """Monkeypatch edit_file's BASE_PATH to tmp_path for isolation."""
    monkeypatch.setattr(edit_file_module, "BASE_PATH", str(tmp_path))


class TestEditFileExactMatch:
    """Exact string replacement behavior."""

    def test_single_occurrence_replaced(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\n", encoding="utf-8")
        result = edit_file_run("test.txt", "world", "universe")
        assert result["status"] == "success"
        assert result["result"]["replacements"] == 1
        assert "universe" in f.read_text(encoding="utf-8")

    def test_single_occurrence_replaced_explicit_replace_all_zero(self, tmp_path, monkeypatch_base_path):
        """replace_all=0 with count==1 succeeds (only ambiguous when count>1)."""
        f = tmp_path / "test.txt"
        f.write_text("hello world\n", encoding="utf-8")
        result = edit_file_run("test.txt", "world", "universe", replace_all=0)
        assert result["status"] == "success"
        assert result["result"]["replacements"] == 1
        assert "universe" in f.read_text(encoding="utf-8")

    def test_replace_all_replaces_multiple(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello hello hello\n", encoding="utf-8")
        result = edit_file_run("test.txt", "hello", "hi", replace_all=1)
        assert result["status"] == "success"
        assert result["result"]["replacements"] == 3
        assert f.read_text(encoding="utf-8") == "hi hi hi\n"

    def test_replace_first_only_by_default_rejects_ambiguous(self, tmp_path, monkeypatch_base_path):
        """replace_all=0 with count>1 returns ambiguous_match, not first-only replacement."""
        f = tmp_path / "test.txt"
        f.write_text("hello hello hello\n", encoding="utf-8")
        result = edit_file_run("test.txt", "hello", "hi", replace_all=0)
        assert result["status"] == "failure"
        assert result["reason"] == "ambiguous_match"
        # File must remain unchanged
        assert f.read_text(encoding="utf-8") == "hello hello hello\n"


class TestEditFileAmbiguousMatch:
    """Ambiguous match rejection."""

    def test_ambiguous_match_rejected(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("foo bar foo\n", encoding="utf-8")
        result = edit_file_run("test.txt", "foo", "baz", replace_all=0)
        assert result["status"] == "failure"
        assert result["reason"] == "ambiguous_match"
        assert "2 occurrences" in result["detail"]
        # File should NOT be modified
        assert f.read_text(encoding="utf-8") == "foo bar foo\n"

    def test_ambiguous_match_allowed_with_replace_all(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("foo bar foo\n", encoding="utf-8")
        result = edit_file_run("test.txt", "foo", "baz", replace_all=1)
        assert result["status"] == "success"
        assert result["result"]["replacements"] == 2
        assert f.read_text(encoding="utf-8") == "baz bar baz\n"


class TestEditFileMissingOldText:
    """Missing or empty old_text handling."""

    def test_missing_old_text_returns_failure(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\n", encoding="utf-8")
        result = edit_file_run("test.txt", "notfound", "replacement")
        assert result["status"] == "failure"
        assert result["reason"] == "old_text_not_found"

    def test_empty_old_text_rejected(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\n", encoding="utf-8")
        result = edit_file_run("test.txt", "", "replacement")
        assert result["status"] == "failure"
        assert result["reason"] == "empty_old_text"


class TestEditFileBinaryRejection:
    """Binary file editing rejection."""

    def test_binary_file_rejected(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"\x00\x01\x02\x03")
        result = edit_file_run("test.bin", "\x00", "x")
        assert result["status"] == "failure"
        assert result["reason"] == "binary_file"


class TestEditFileDryRun:
    """dry_run preview behavior."""

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        original = "hello world\n"
        f.write_text(original, encoding="utf-8")
        result = edit_file_run("test.txt", "world", "universe", dry_run=1)
        assert result["status"] == "success"
        assert result["result"]["dry_run"] is True
        # File must NOT be modified
        assert f.read_text(encoding="utf-8") == original

    def test_dry_run_returns_replacements_count(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("foo foo\n", encoding="utf-8")
        result = edit_file_run("test.txt", "foo", "bar", replace_all=1, dry_run=1)
        assert result["status"] == "success"
        assert result["result"]["replacements"] == 2
        assert "dry run" in result["result"]["message"].lower()

    def test_dry_run_returns_preview(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\n", encoding="utf-8")
        result = edit_file_run("test.txt", "world", "universe", dry_run=1)
        assert result["status"] == "success"
        assert "preview" in result["result"]
        assert "universe" in result["result"]["preview"]

    def test_dry_run_returns_path(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world\n", encoding="utf-8")
        result = edit_file_run("test.txt", "world", "universe", dry_run=1)
        assert result["status"] == "success"
        assert result["result"]["path"] == "test.txt"


class TestEditFileInputValidation:
    """Input validation and edge cases."""

    def test_nonexistent_file_fails(self, tmp_path, monkeypatch_base_path):
        result = edit_file_run("nonexistent.txt", "old", "new")
        assert result["status"] == "failure"
        assert result["reason"] == "file_not_found"

    def test_invalid_path_empty_string(self, tmp_path, monkeypatch_base_path):
        result = edit_file_run("", "old", "new")
        assert result["status"] == "failure"
        assert result["reason"] == "invalid_path"

    def test_invalid_path_none(self, tmp_path, monkeypatch_base_path):
        result = edit_file_run(None, "old", "new")
        assert result["status"] == "failure"
        assert result["reason"] == "invalid_path"

    def test_path_traversal_blocked(self, tmp_path, monkeypatch_base_path):
        result = edit_file_run("../outside.txt", "old", "new")
        assert result["status"] == "failure"
        # Should be blocked by path_validator
        assert "outside" in result.get("detail", "").lower() or result["reason"] == "path_safety_blocked"

    def test_old_text_not_string(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("hello\n", encoding="utf-8")
        result = edit_file_run("test.txt", 123, "new")
        assert result["status"] == "failure"
        assert result["reason"] == "invalid_old_text"


class TestEditFilePreview:
    """Preview generation behavior."""

    def test_preview_shows_first_changed_line(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = edit_file_run("test.txt", "line2", "modified", dry_run=1)
        assert result["status"] == "success"
        assert result["result"]["preview"] == "modified"

    def test_preview_truncated_to_200_chars(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        long_line = "a" * 300
        f.write_text(f"first\n{long_line}\n", encoding="utf-8")
        result = edit_file_run("test.txt", long_line, "b" * 300, dry_run=1)
        assert result["status"] == "success"
        assert len(result["result"]["preview"]) <= 200

    def test_preview_on_insertion(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\n", encoding="utf-8")
        result = edit_file_run("test.txt", "line1\n", "line1\nnew_line\n", dry_run=1)
        assert result["status"] == "success"
        # Preview should show the first new line after the changed content
        preview = result["result"]["preview"]
        assert preview != "(no visible change)"


class TestEditFilePermission:
    """Permission failure handling."""

    @pytest.mark.skipif(
        os.name == "nt" and not os.environ.get("CI"),
        reason="Permission failure testing on Windows requires elevated setup or CI environment"
    )
    def test_write_permission_denied(self, tmp_path, monkeypatch_base_path):
        f = tmp_path / "readonly.txt"
        f.write_text("hello\n", encoding="utf-8")
        # Make file read-only
        os.chmod(str(f), 0o444)
        try:
            result = edit_file_run("readonly.txt", "hello", "goodbye")
            assert result["status"] == "failure"
            assert result["reason"] in ("write_error", "permission_denied")
        finally:
            os.chmod(str(f), 0o666)

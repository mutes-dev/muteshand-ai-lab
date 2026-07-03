"""
Security test suite for system/security/path_validator.py.

Covers:
- Null byte rejection
- Non-string input rejection
- Empty path rejection
- Traversal outside base_dir blocked
- Traversal inside base_dir allowed
- Symlink escape blocked (with Windows skip)
- Sensitive subpath blocking
- Sensitive filename blocking
- allow_base_dir flag behavior
- Quote stripping
- Path normalization
"""

import os
import sys
import pytest

# Ensure project root on path
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from system.security.path_validator import validate_path


class TestPathValidatorInputSanity:
    """Basic input validation."""

    def test_null_byte_rejected(self, tmp_path):
        base = str(tmp_path)
        result = validate_path("foo\x00bar.txt", base)
        assert result["status"] == "failure"
        assert "null" in result["detail"].lower()

    def test_non_string_rejected(self, tmp_path):
        base = str(tmp_path)
        result = validate_path(12345, base)
        assert result["status"] == "failure"
        assert "string" in result["detail"].lower()

    def test_none_rejected(self, tmp_path):
        base = str(tmp_path)
        result = validate_path(None, base)
        assert result["status"] == "failure"

    def test_empty_path_rejected(self, tmp_path):
        base = str(tmp_path)
        result = validate_path("", base)
        assert result["status"] == "failure"
        assert "required" in result["detail"].lower()

    def test_whitespace_only_rejected(self, tmp_path):
        base = str(tmp_path)
        result = validate_path("   ", base)
        assert result["status"] == "failure"


class TestPathValidatorTraversal:
    """Directory traversal containment."""

    def test_traversal_inside_base_dir_allowed(self, tmp_path):
        base = str(tmp_path)
        sub = tmp_path / "subdir" / "file.txt"
        sub.parent.mkdir(parents=True)
        sub.write_text("hello")
        result = validate_path("subdir/file.txt", base)
        assert result["status"] == "success"
        assert result["resolved_path"] == str(sub)

    def test_traversal_outside_base_dir_rejected(self, tmp_path):
        base = str(tmp_path)
        result = validate_path("../outside.txt", base)
        assert result["status"] == "failure"
        assert "outside" in result["detail"].lower()

    def test_deep_traversal_rejected(self, tmp_path):
        base = str(tmp_path)
        result = validate_path("foo/../../outside.txt", base)
        assert result["status"] == "failure"
        assert "outside" in result["detail"].lower()

    def test_absolute_outside_rejected(self, tmp_path):
        base = str(tmp_path)
        result = validate_path("/etc/passwd", base)
        assert result["status"] == "failure"


class TestPathValidatorSymlinkEscape:
    """Symlink escape prevention."""

    @pytest.mark.skipif(
        os.name == "nt" and not os.environ.get("CI"),
        reason="Symlink creation often requires admin on Windows unless Developer Mode is on"
    )
    def test_symlink_escape_rejected(self, tmp_path):
        base = str(tmp_path)
        outside = tmp_path / ".." / "outside_target.txt"
        outside.write_text("secret")
        link = tmp_path / "escaped.txt"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"Cannot create symlink in this environment: {exc}")
        result = validate_path("escaped.txt", base)
        assert result["status"] == "failure"
        assert "outside" in result["detail"].lower()


class TestPathValidatorSensitivePaths:
    """Sensitive subpath and filename blocking."""

    def test_sensitive_subpath_ssh_blocked(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / ".ssh").mkdir()
        (tmp_path / ".ssh" / "config").write_text("")
        result = validate_path(".ssh/config", base)
        assert result["status"] == "failure"
        assert ".ssh/" in result["detail"].lower()

    def test_sensitive_subpath_etc_blocked(self, tmp_path):
        base = str(tmp_path)
        # /etc/ is in the sensitive list; create a path containing it
        evil = tmp_path / "fake_etc" / "passwd"
        evil.parent.mkdir(parents=True)
        evil.write_text("")
        result = validate_path("fake_etc/passwd", base)
        # /etc/ is a substring match — "fake_etc" does not contain "/etc/"
        # The path resolution will produce something like C:\...\fake_etc\passwd
        # which does not contain "/etc/". This test should actually pass
        # because "fake_etc" doesn't match "/etc/". Let me test with an actual
        # directory named "etc" inside base_dir.
        etc_dir = tmp_path / "etc"
        etc_dir.mkdir()
        (etc_dir / "hosts").write_text("")
        result2 = validate_path("etc/hosts", base)
        assert result2["status"] == "failure"
        assert "/etc/" in result2["detail"].lower()

    def test_sensitive_subpath_system32_blocked(self, tmp_path):
        base = str(tmp_path)
        sys32 = tmp_path / "system32"
        sys32.mkdir()
        (sys32 / "calc.exe").write_text("")
        result = validate_path("system32/calc.exe", base)
        assert result["status"] == "failure"
        assert "system32/" in result["detail"].lower()

    def test_sensitive_filename_id_rsa_blocked(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / "id_rsa").write_text("")
        result = validate_path("id_rsa", base)
        assert result["status"] == "failure"
        assert "id_rsa" in result["detail"].lower()

    def test_sensitive_filename_env_blocked(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / ".env").write_text("")
        result = validate_path(".env", base)
        assert result["status"] == "failure"
        assert ".env" in result["detail"].lower()

    def test_sensitive_filename_netrc_blocked(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / ".netrc").write_text("")
        result = validate_path(".netrc", base)
        assert result["status"] == "failure"
        assert ".netrc" in result["detail"].lower()


class TestPathValidatorBaseDirFlag:
    """allow_base_dir behavior."""

    def test_allow_base_dir_true_allows_root(self, tmp_path):
        base = str(tmp_path)
        result = validate_path(".", base, allow_base_dir=True)
        assert result["status"] == "success"
        assert result["resolved_path"] == os.path.realpath(base)

    def test_allow_base_dir_false_blocks_root(self, tmp_path):
        base = str(tmp_path)
        result = validate_path(".", base, allow_base_dir=False)
        assert result["status"] == "failure"
        assert "root itself" in result["detail"].lower()


class TestPathValidatorQuoteStripping:
    """LLM-output quote stripping."""

    def test_double_quotes_stripped(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / "file.txt").write_text("")
        result = validate_path('"file.txt"', base)
        assert result["status"] == "success"
        assert result["resolved_path"] == str(tmp_path / "file.txt")

    def test_single_quotes_stripped(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / "file.txt").write_text("")
        result = validate_path("'file.txt'", base)
        assert result["status"] == "success"
        assert result["resolved_path"] == str(tmp_path / "file.txt")


class TestPathValidatorNormalization:
    """Path normalization edge cases."""

    def test_double_slashes_normalized(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / "dir").mkdir()
        (tmp_path / "dir" / "file.txt").write_text("")
        result = validate_path("dir//file.txt", base)
        assert result["status"] == "success"
        assert result["resolved_path"] == str(tmp_path / "dir" / "file.txt")

    def test_dot_segment_allowed(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / "file.txt").write_text("")
        result = validate_path("./file.txt", base)
        assert result["status"] == "success"
        assert result["resolved_path"] == str(tmp_path / "file.txt")

    def test_dotdot_segment_inside_allowed(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / "outside.txt").write_text("")
        result = validate_path("foo/../outside.txt", base)
        # foo/../outside.txt normalizes to outside.txt inside base_dir
        assert result["status"] == "success"

    def test_resolved_path_returned_on_success(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / "dir").mkdir()
        (tmp_path / "dir" / "file.txt").write_text("")
        result = validate_path("dir/file.txt", base)
        assert result["status"] == "success"
        assert "resolved_path" in result
        assert os.path.isabs(result["resolved_path"])

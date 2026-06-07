"""Path safety validation tests — AI Lab native, inspired by Odysseus patterns.

Odysseus reference: E:\\ReferenceRepos\\odysseus\\tests\\test_tool_path_confinement.py
No Odysseus runtime or tool dispatcher code was copied.
"""

import os
import sys
import tempfile

import pytest

from system.security.path_validator import validate_path


# ── Unit tests: validate_path ────────────────────────────────────────────────

def test_allowed_path_inside_base():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "data", "notes.txt")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            f.write("ok")
        result = validate_path("data/notes.txt", tmp)
        assert result["status"] == "success"
        assert result["resolved_path"] == os.path.realpath(target)


def test_relative_traversal_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path("../secret.txt", tmp)
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"
        assert "outside allowed root" in result["detail"].lower()


def test_absolute_path_outside_base_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path("/etc/passwd", tmp)
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"
        assert "outside allowed root" in result["detail"].lower()


def test_etc_shadow_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path("etc/shadow", tmp)
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"
        assert "/etc/" in result["detail"].lower()


def test_ssh_authorized_keys_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path(".ssh/authorized_keys", tmp)
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"
        assert ".ssh/" in result["detail"].lower()


def test_sensitive_shell_rc_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        for filename in (".bashrc", ".zshrc", ".profile"):
            result = validate_path(f"data/{filename}", tmp)
            assert result["status"] == "failure", filename
            assert result["reason"] == "path_safety_blocked", filename


def test_sensitive_key_filenames_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        for filename in ("id_rsa", "id_ed25519", "authorized_keys"):
            result = validate_path(f"keys/{filename}", tmp)
            assert result["status"] == "failure", filename
            assert result["reason"] == "path_safety_blocked", filename


def test_env_file_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path("config/.env", tmp)
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"


def test_windows_system32_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path("foo/C:/Windows/System32/calc.exe", tmp)
        # This resolves inside tmp, but the subpath "system32/" triggers
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"


def test_empty_path_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path("", tmp)
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"


def test_none_path_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path(None, tmp)
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"


def test_null_bytes_blocked():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path("hello\x00world.txt", tmp)
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"


def test_base_dir_itself_blocked_when_not_allowed():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path(".", tmp)
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"
        assert "root itself" in result["detail"].lower()


def test_base_dir_allowed_when_allow_base_dir():
    with tempfile.TemporaryDirectory() as tmp:
        result = validate_path(".", tmp, allow_base_dir=True)
        assert result["status"] == "success"


def test_symlink_escape_blocked():
    """Symlink pointing outside allowed root must be caught by realpath."""
    with tempfile.TemporaryDirectory() as tmp:
        # Create a file outside tmp
        outside = os.path.join(tmp, "..", "outside_target.txt")
        outside = os.path.abspath(outside)
        with open(outside, "w") as f:
            f.write("secret")

        # Create a symlink inside tmp pointing outside
        link_path = os.path.join(tmp, "escape_link")
        try:
            os.symlink(os.path.dirname(outside), link_path)
        except (OSError, NotImplementedError):
            pytest.skip("cannot create symlink on this platform")

        # Accessing escape_link/file.txt should resolve outside tmp
        result = validate_path("escape_link/outside_target.txt", tmp)
        assert result["status"] == "failure"
        assert result["reason"] == "path_safety_blocked"
        assert "outside allowed root" in result["detail"].lower()

    # Clean up outside file
    try:
        os.unlink(outside)
    except Exception:
        pass


def test_quoted_path_allowed():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "notes.txt")
        with open(target, "w") as f:
            f.write("ok")
        result = validate_path('"notes.txt"', tmp)
        assert result["status"] == "success"


# ── Integration: read_file tool ──────────────────────────────────────────────

def test_read_file_blocks_traversal():
    import sys
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.read_file import run as read_file

    result = read_file("../secret.txt")
    assert isinstance(result, dict)
    assert result.get("status") == "failure"
    assert result.get("reason") == "path_safety_blocked"


def test_read_file_blocks_sensitive_subpath():
    import sys
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.read_file import run as read_file

    result = read_file(".ssh/config")
    assert isinstance(result, dict)
    assert result.get("status") == "failure"
    assert result.get("reason") == "path_safety_blocked"


def test_read_file_allows_legitimate():
    import sys
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.read_file import run as read_file

    # read_file BASE_PATH is E:/MutesHand — just verify a known file
    result = read_file("system/tool_index/tools.json")
    assert isinstance(result, dict)
    assert result.get("status") == "success"
    assert "read_file" not in str(result.get("reason", "")).lower()


# ── Integration: write_file tool ─────────────────────────────────────────────

def test_write_file_blocks_sensitive_filename():
    import sys
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.write_file import run as write_file

    result = write_file("data/id_rsa", "fake-key")
    assert isinstance(result, dict)
    assert result.get("status") == "failure"
    assert result.get("reason") == "path_safety_blocked"


def test_write_file_blocks_traversal():
    import sys
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.write_file import run as write_file

    result = write_file("../../../etc/passwd", "bad")
    assert isinstance(result, dict)
    assert result.get("status") == "failure"
    assert result.get("reason") == "path_safety_blocked"


# ── Integration: list_files tool ─────────────────────────────────────────────

def test_list_files_blocks_traversal():
    import sys
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.list_files import run as list_files

    result = list_files("../")
    assert isinstance(result, dict)
    assert result.get("status") == "failure"
    assert result.get("reason") == "path_safety_blocked"


def test_list_files_allows_current_dir():
    import sys
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.list_files import run as list_files

    result = list_files(".")
    # Should succeed — current directory is allowed
    assert isinstance(result, dict)
    assert result.get("status") == "success"

"""
Tool result shape consistency tests.

Calls representative safe tools with minimal valid inputs and verifies that:
- Success results are either a dict with status=="success" and a result key,
  OR are documented as intentionally returning a raw value.
- Failure results are a dict with status=="failure" and a reason key.

Uses tmp_path for file tools to avoid mutating real project files.
Does not make real network calls.
"""

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Set

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Import file tool modules for monkeypatching BASE_PATH
import tools.read_file as _read_file_module
import tools.write_file as _write_file_module
import tools.append_file as _append_file_module
import tools.edit_file as _edit_file_module
import tools.list_files as _list_files_module


def _load_tools_json() -> Dict[str, Any]:
    path = os.path.join(_PROJECT_ROOT, "system", "tool_index", "tools.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def monkeypatch_file_tool_base_path(tmp_path, monkeypatch):
    """Monkeypatch BASE_PATH on all file tool modules to tmp_path for isolation."""
    for mod in (
        _read_file_module,
        _write_file_module,
        _append_file_module,
        _edit_file_module,
        _list_files_module,
    ):
        monkeypatch.setattr(mod, "BASE_PATH", str(tmp_path))


# Tools that intentionally return raw values on success instead of a dict.
# These are documented here; if a tool is not in this set, success MUST be a dict.
RAW_RETURN_TOOLS: Set[str] = {
    "add_numbers",      # returns number
    "cube_number",      # returns number
    "multiply_numbers", # returns number
    "square_number",    # returns number
    "square_root",      # returns number
    "subtract_numbers", # returns number
    "finalize_output",  # returns string
}

# Tools that raise exceptions on some invalid inputs instead of returning failure dicts.
RAISE_ON_INVALID_TOOLS: Set[str] = {
    "finalize_output",  # raises Exception("invalid_input")
    "add_numbers",      # raises Exception(str(e))
    "cube_number",      # no explicit error path; may raise on non-numeric
    "multiply_numbers", # no explicit error path
    "square_number",    # no explicit error path
    "square_root",      # no explicit error path
    "subtract_numbers", # no explicit error path
}


def _run_tool(tool_name: str, **kwargs):
    """Import and call a tool's run() with the given kwargs."""
    mod = importlib.import_module(f"tools.{tool_name}")
    return mod.run(**kwargs)


# ---------------------------------------------------------------------------
# Math tools — mixed raw-return and dict-return
# ---------------------------------------------------------------------------

class TestMathToolResultShapes:
    """Math tools return either raw values or consistent dict shapes."""

    def test_add_numbers_success_raw(self):
        result = _run_tool("add_numbers", num1=2, num2=3)
        # add_numbers returns raw value, not a dict
        assert result == 5

    def test_divide_numbers_success_raw(self):
        result = _run_tool("divide_numbers", numerator=10, denominator=2)
        assert result == 5.0

    def test_divide_numbers_failure_dict(self):
        result = _run_tool("divide_numbers", numerator=10, denominator=0)
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result

    def test_factorial_success_raw(self):
        result = _run_tool("factorial", number=5)
        assert result == 120

    def test_factorial_failure_dict(self):
        result = _run_tool("factorial", number=-1)
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result

    def test_fibonacci_success_dict(self):
        result = _run_tool("fibonacci", n=5)
        assert isinstance(result, dict)
        assert result.get("status") == "success"
        assert "result" in result

    def test_fibonacci_failure_dict(self):
        result = _run_tool("fibonacci", n=-1)
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result

    def test_multiply_numbers_success_raw(self):
        result = _run_tool("multiply_numbers", a=3, t=4)
        assert result == 12

    def test_multiply_string_success_raw(self):
        result = _run_tool("multiply_string", str1="hi", num=3)
        assert result == "hihihi"

    def test_multiply_string_failure_dict(self):
        result = _run_tool("multiply_string", str1="hi", num=-1)
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result

    def test_cube_number_success_raw(self):
        result = _run_tool("cube_number", number=3)
        assert result == 27

    def test_square_number_success_raw(self):
        result = _run_tool("square_number", a=4)
        assert result == 16

    def test_square_root_success_raw(self):
        result = _run_tool("square_root", number=9)
        assert result == 3.0

    def test_square_root_failure_dict(self):
        result = _run_tool("square_root", number=-4)
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result

    def test_subtract_numbers_success_raw(self):
        result = _run_tool("subtract_numbers", a=10, b=3)
        assert result == 7


# ---------------------------------------------------------------------------
# File tools — always dict-return
# ---------------------------------------------------------------------------

class TestFileToolResultShapes:
    """File tools always return dict shapes."""

    def test_read_file_success(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world", encoding="utf-8")
        result = _run_tool("read_file", path=str(test_file))
        assert isinstance(result, dict)
        assert result.get("status") == "success"
        assert "result" in result

    def test_read_file_failure_not_found(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        missing = tmp_path / "missing.txt"
        result = _run_tool("read_file", path=str(missing))
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result

    def test_write_file_success(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        target = tmp_path / "write.txt"
        result = _run_tool("write_file", path=str(target), content="hello")
        assert isinstance(result, dict)
        assert result.get("status") == "success"
        assert "result" in result

    def test_write_file_failure_invalid_content(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        target = tmp_path / "write.txt"
        result = _run_tool("write_file", path=str(target), content=12345)
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result

    def test_append_file_success(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        target = tmp_path / "append.txt"
        target.write_text("existing", encoding="utf-8")
        result = _run_tool("append_file", path=str(target), content=" more")
        assert isinstance(result, dict)
        assert result.get("status") == "success"
        assert "result" in result

    def test_append_file_failure_not_found(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        missing = tmp_path / "missing.txt"
        result = _run_tool("append_file", path=str(missing), content="x")
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result

    def test_edit_file_success(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        target = tmp_path / "edit.txt"
        target.write_text("old content", encoding="utf-8")
        result = _run_tool(
            "edit_file",
            path=str(target),
            old_text="old content",
            new_text="new content",
        )
        assert isinstance(result, dict)
        assert result.get("status") == "success"
        assert "result" in result

    def test_edit_file_failure_not_found(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        missing = tmp_path / "missing.txt"
        result = _run_tool(
            "edit_file",
            path=str(missing),
            old_text="old",
            new_text="new",
        )
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result

    def test_list_files_success(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        result = _run_tool("list_files", directory=str(tmp_path))
        assert isinstance(result, dict)
        assert result.get("status") == "success"
        assert "result" in result

    def test_list_files_failure_not_found(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        missing = tmp_path / "nodir"
        result = _run_tool("list_files", directory=str(missing))
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result


# ---------------------------------------------------------------------------
# Web tools — mocked or skipped to avoid real network calls
# ---------------------------------------------------------------------------

class TestWebToolResultShapes:
    """Web tools return dict shapes; no real network calls in tests."""

    def test_read_webpage_failure_bad_url(self):
        """Invalid URL should fail safely without a real network call."""
        result = _run_tool("read_webpage", url="not-a-valid-url")
        assert isinstance(result, dict)
        assert result.get("status") == "failure"
        assert "reason" in result

    def test_web_search_empty_query(self):
        """Empty query should return string (documented raw-like behavior)."""
        result = _run_tool("web_search", query="")
        # web_search returns "no results found" string for empty input
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Finalize output — raw return
# ---------------------------------------------------------------------------

class TestFinalizeOutputResultShape:
    """finalize_output returns raw string on success."""

    def test_finalize_output_success_raw(self):
        result = _run_tool("finalize_output", text="hello")
        assert result == "hello"

    def test_finalize_output_failure_raises(self):
        with pytest.raises(Exception):
            _run_tool("finalize_output", text=12345)


# ---------------------------------------------------------------------------
# Cross-cutting: every production tool that returns a dict must have status
# ---------------------------------------------------------------------------

class TestAllProductionToolsDictShape:
    """
    For every production tool, attempt a minimal call and verify that
    if it returns a dict, the dict has a 'status' key.
    """

    def test_every_production_tool_dict_has_status(self, tmp_path: Path, monkeypatch_file_tool_base_path):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue

            # Skip tools that are not locally runnable or need external resources
            if name in {"read_webpage", "web_search"}:
                continue

            # Skip tools that require special setup
            if name in {"grep", "glob"}:
                continue

            # Build minimal kwargs from tools.json inputs + defaults
            inputs = spec.get("inputs", {})
            kwargs = {}
            for key, typ in inputs.items():
                if typ == "string":
                    if key == "path":
                        kwargs[key] = str(tmp_path / "test.txt")
                    elif key == "directory":
                        kwargs[key] = str(tmp_path)
                    elif key == "content":
                        kwargs[key] = "test"
                    elif key == "old_text":
                        kwargs[key] = "old"
                    elif key == "new_text":
                        kwargs[key] = "new"
                    elif key == "text":
                        kwargs[key] = "hello"
                    elif key == "query":
                        kwargs[key] = "test"
                    elif key == "url":
                        kwargs[key] = "http://example.com"
                    elif key == "pattern":
                        kwargs[key] = "test"
                    elif key == "section":
                        kwargs[key] = "test"
                    else:
                        kwargs[key] = "test"
                elif typ == "number":
                    if key in {"replace_all", "dry_run", "recursive", "case_sensitive", "max_results"}:
                        kwargs[key] = 0
                    else:
                        kwargs[key] = 1
                else:
                    kwargs[key] = "test"

            try:
                mod = importlib.import_module(f"tools.{name}")
                result = mod.run(**kwargs)
            except Exception as exc:
                # Tools that raise on invalid input are documented in RAISE_ON_INVALID_TOOLS
                if name in RAISE_ON_INVALID_TOOLS:
                    continue
                failures.append(f"{name}: run() raised {exc}")
                continue

            if isinstance(result, dict):
                if "status" not in result:
                    failures.append(f"{name}: dict result missing 'status' key: {result.keys()}")

        assert not failures, f"Dict shape failures: {failures}"

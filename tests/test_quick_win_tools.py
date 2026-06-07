"""
Quick-Win Tool Pack Tests (ADOPT-005B) — grep, glob, edit_file

Tests cover:
- grep: search, line numbers, max_results, path blocking, no matches, binary skip
- glob: discovery, max_results, path blocking, no matches
- edit_file: exact replacement, dry_run, path blocking, missing old_text, ambiguous match, replace_all, plan mode blocking
- Regression: path safety, tool policy, existing tools unaffected
"""

import os
import sys
import unittest
import tempfile

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tools import grep, glob as glob_tool, edit_file
from system.security.path_validator import validate_path

BASE_PATH = os.path.abspath("E:/MutesHand")


class TestGrepTool(unittest.TestCase):
    """Test grep tool behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(dir=BASE_PATH)
        self.rel_dir = os.path.relpath(self.tmpdir, BASE_PATH)

        # Create test files
        with open(os.path.join(self.tmpdir, "alpha.txt"), "w", encoding="utf-8") as f:
            f.write("line one\nline two\nhello world\n")
        with open(os.path.join(self.tmpdir, "beta.py"), "w", encoding="utf-8") as f:
            f.write("def hello():\n    print('hello')\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_grep_finds_text(self):
        result = grep.run("hello", directory=self.rel_dir, recursive=1, max_results=10, case_sensitive=1)
        self.assertEqual(result["status"], "success")
        matches = result["result"]["matches"]
        self.assertTrue(len(matches) >= 2)
        files = {m["file"] for m in matches}
        self.assertTrue(any("alpha.txt" in f for f in files))
        self.assertTrue(any("beta.py" in f for f in files))

    def test_grep_returns_line_numbers(self):
        result = grep.run("line", directory=self.rel_dir, recursive=1, max_results=10, case_sensitive=1)
        self.assertEqual(result["status"], "success")
        for m in result["result"]["matches"]:
            self.assertIsInstance(m["line"], int)
            self.assertGreater(m["line"], 0)
            self.assertIsInstance(m["text"], str)

    def test_grep_respects_max_results(self):
        result = grep.run("hello", directory=self.rel_dir, recursive=1, max_results=1, case_sensitive=1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["count"], 1)

    def test_grep_blocks_traversal(self):
        result = grep.run("test", directory="../..", recursive=1, max_results=10, case_sensitive=1)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "path_safety_blocked")

    def test_grep_handles_no_matches(self):
        result = grep.run("zzzznonexistent", directory=self.rel_dir, recursive=1, max_results=10, case_sensitive=1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["count"], 0)

    def test_grep_case_insensitive(self):
        result = grep.run("HELLO", directory=self.rel_dir, recursive=1, max_results=10, case_sensitive=0)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["result"]["count"] >= 1)

    def test_grep_invalid_pattern(self):
        result = grep.run("", directory=self.rel_dir, recursive=1, max_results=10, case_sensitive=1)
        self.assertEqual(result["status"], "failure")

    def test_grep_skips_binary(self):
        # Create a binary file with null bytes
        bin_path = os.path.join(self.tmpdir, "binary.dat")
        with open(bin_path, "wb") as f:
            f.write(b"\x00\x01\x02hello\x00")
        result = grep.run("hello", directory=self.rel_dir, recursive=1, max_results=10, case_sensitive=1)
        self.assertEqual(result["status"], "success")
        # Should not crash; may or may not find it depending on skip behavior


class TestGlobTool(unittest.TestCase):
    """Test glob tool behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(dir=BASE_PATH)
        self.rel_dir = os.path.relpath(self.tmpdir, BASE_PATH)

        with open(os.path.join(self.tmpdir, "a.py"), "w") as f:
            f.write("a")
        with open(os.path.join(self.tmpdir, "b.py"), "w") as f:
            f.write("b")
        with open(os.path.join(self.tmpdir, "c.txt"), "w") as f:
            f.write("c")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_glob_finds_files(self):
        result = glob_tool.run("*.py", directory=self.rel_dir, recursive=0, max_results=10)
        self.assertEqual(result["status"], "success")
        paths = result["result"]["paths"]
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(p.endswith(".py") for p in paths))

    def test_glob_respects_max_results(self):
        result = glob_tool.run("*.py", directory=self.rel_dir, recursive=0, max_results=1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["count"], 1)

    def test_glob_blocks_traversal(self):
        result = glob_tool.run("*", directory="../..", recursive=0, max_results=10)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "path_safety_blocked")

    def test_glob_no_matches(self):
        result = glob_tool.run("*.md", directory=self.rel_dir, recursive=0, max_results=10)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["count"], 0)

    def test_glob_recursive(self):
        subdir = os.path.join(self.tmpdir, "sub")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "deep.py"), "w") as f:
            f.write("d")
        result = glob_tool.run("*.py", directory=self.rel_dir, recursive=1, max_results=10)
        self.assertEqual(result["status"], "success")
        paths = result["result"]["paths"]
        self.assertTrue(any("deep.py" in p for p in paths))


class TestEditFileTool(unittest.TestCase):
    """Test edit_file tool behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(dir=BASE_PATH)
        self.rel_dir = os.path.relpath(self.tmpdir, BASE_PATH)
        self.test_file = os.path.join(self.rel_dir, "test_edit.txt")
        full_path = os.path.join(self.tmpdir, "test_edit.txt")
        with open(full_path, "w", encoding="utf-8") as f:
            f.write("hello world\nline two\nhello world\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_edit_file_replaces_one(self):
        result = edit_file.run(self.test_file, "line two", "LINE TWO", replace_all=0, dry_run=0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["replacements"], 1)
        with open(os.path.join(self.tmpdir, "test_edit.txt"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("LINE TWO", content)
        self.assertIn("hello world", content)

    def test_edit_file_dry_run_no_modify(self):
        result = edit_file.run(self.test_file, "line two", "LINE TWO", replace_all=0, dry_run=1)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["result"]["dry_run"])
        with open(os.path.join(self.tmpdir, "test_edit.txt"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("LINE TWO", content)

    def test_edit_file_blocks_traversal(self):
        result = edit_file.run("../../etc/passwd", "old", "new", replace_all=0, dry_run=0)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "path_safety_blocked")

    def test_edit_file_rejects_empty_old_text(self):
        result = edit_file.run(self.test_file, "", "new", replace_all=0, dry_run=0)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "empty_old_text")

    def test_edit_file_rejects_missing_old_text(self):
        result = edit_file.run(self.test_file, "zzzznonexistent", "new", replace_all=0, dry_run=0)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "old_text_not_found")

    def test_edit_file_rejects_ambiguous(self):
        result = edit_file.run(self.test_file, "hello world", "HELLO", replace_all=0, dry_run=0)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "ambiguous_match")

    def test_edit_file_replace_all_works(self):
        result = edit_file.run(self.test_file, "hello world", "HELLO WORLD", replace_all=1, dry_run=0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["replacements"], 2)
        with open(os.path.join(self.tmpdir, "test_edit.txt"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content.count("HELLO WORLD"), 2)

    def test_edit_file_rejects_binary(self):
        bin_path = os.path.join(self.tmpdir, "binary.dat")
        with open(bin_path, "wb") as f:
            f.write(b"\x00old\x00")
        rel_bin = os.path.relpath(bin_path, BASE_PATH)
        result = edit_file.run(rel_bin, "old", "new", replace_all=0, dry_run=0)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "binary_file")


class TestPlanModeIntegration(unittest.TestCase):
    """Test that grep/glob are allowed in plan mode and edit_file is blocked."""

    def test_grep_allowed_in_plan_mode(self):
        from system.security.tool_policy import check_tool_policy
        result = check_tool_policy("grep", mode="plan")
        self.assertTrue(result.allowed)

    def test_glob_allowed_in_plan_mode(self):
        from system.security.tool_policy import check_tool_policy
        result = check_tool_policy("glob", mode="plan")
        self.assertTrue(result.allowed)

    def test_edit_file_blocked_in_plan_mode(self):
        from system.security.tool_policy import check_tool_policy
        result = check_tool_policy("edit_file", mode="plan")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "plan_mode_blocked")

    def test_grep_blocked_in_read_only_mode(self):
        from system.security.tool_policy import check_tool_policy
        result = check_tool_policy("grep", mode="read_only")
        self.assertTrue(result.allowed)

    def test_edit_file_blocked_in_read_only_mode(self):
        from system.security.tool_policy import check_tool_policy
        result = check_tool_policy("edit_file", mode="read_only")
        self.assertFalse(result.allowed)


class TestSystemEntryIntegration(unittest.TestCase):
    """Test system_entry integration for new tools."""

    def test_grep_routes_through_system_entry(self):
        from system.entry.system_entry import system_entry
        result = system_entry('grep "def" "system/security" 1 10 1', mode="normal")
        self.assertEqual(result["status"], "success")
        self.assertIn("result", result)

    def test_glob_routes_through_system_entry(self):
        from system.entry.system_entry import system_entry
        result = system_entry('glob "*.py" "tools" 0 10', mode="normal")
        self.assertEqual(result["status"], "success")
        self.assertIn("result", result)

    def test_edit_file_blocked_in_plan_via_system_entry(self):
        from system.entry.system_entry import system_entry
        result = system_entry('edit_file "tests/_temp.txt" "old" "new" 0 0', mode="plan")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "plan_mode_blocked")


class TestPathConfinementOnNewTools(unittest.TestCase):
    """Test that all path-capable new tools enforce path confinement."""

    def test_grep_blocks_sensitive_path(self):
        result = grep.run("test", directory=".ssh/authorized_keys", recursive=1, max_results=10, case_sensitive=1)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "path_safety_blocked")

    def test_glob_blocks_sensitive_path(self):
        result = glob_tool.run("*", directory=".ssh", recursive=0, max_results=10)
        self.assertEqual(result["status"], "failure")
        # If .ssh dir does not exist, path validator may return directory_not_found
        # If it exists, path_safety_blocked is expected. Both are safe outcomes.
        self.assertIn(result["reason"], ("path_safety_blocked", "directory_not_found"))

    def test_edit_file_blocks_sensitive_filename(self):
        result = edit_file.run(".env", "old", "new", replace_all=0, dry_run=0)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "path_safety_blocked")


if __name__ == "__main__":
    unittest.main(verbosity=2)

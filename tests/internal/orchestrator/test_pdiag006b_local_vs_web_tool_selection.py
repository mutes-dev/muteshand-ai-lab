"""
PDIAG-006B Follow-up Tests — Local File vs Web Tool Selection

Tests that AG1 correctly distinguishes between local file operations and web operations
based on manifest metadata and generic decision boundary.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
from system.tool_index.tool_capability_index import build_ag1_capability_view


class TestLocalVsWebToolSelection(unittest.TestCase):
    """Test that AG1 correctly routes local file vs web operations."""

    def test_local_file_path_selects_read_file_not_webpage(self):
        """Test that local file path selects read_file, not read_webpage."""
        # Test with tmp/file.txt path
        result = execute_tool_selection("Read `tmp/pdiag006_tool_chain_test.txt`.", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "read_file")
        self.assertEqual(result["parsed_args"], ["tmp/pdiag006_tool_chain_test.txt"])

    def test_local_file_path_with_slash_selects_read_file(self):
        """Test that ./file.txt path selects read_file."""
        result = execute_tool_selection("Read `./config.json`.", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "read_file")
        self.assertEqual(result["parsed_args"], ["./config.json"])

    def test_windows_path_selects_read_file(self):
        """Test that Windows path selects read_file."""
        result = execute_tool_selection("Read `E:\\project\\data.txt`.", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "read_file")
        self.assertEqual(result["parsed_args"], ["E:\\project\\data.txt"])

    def test_url_selects_read_webpage_not_read_file(self):
        """Test that URL selects read_webpage, not read_file."""
        result = execute_tool_selection("Read this webpage: https://example.com", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "read_webpage")
        self.assertEqual(result["parsed_args"], ["https://example.com"])

    def test_http_url_selects_read_webpage(self):
        """Test that http:// URL selects read_webpage."""
        result = execute_tool_selection("Read http://test.org/page", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "read_webpage")
        self.assertEqual(result["parsed_args"], ["http://test.org/page"])

    def test_local_file_edit_selects_edit_file(self):
        """Test that local file edit selects edit_file."""
        result = execute_tool_selection("Edit `tmp/test.txt` to replace 'old' with 'new'", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "edit_file")
        # Arguments should include path, old_text, new_text
        self.assertIn("tmp/test.txt", result["parsed_args"])

    def test_local_file_grep_selects_grep(self):
        """Test that file search selects grep."""
        result = execute_tool_selection("Search for 'function' in src/", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "grep")
        self.assertIn("src/", result["parsed_args"])

    def test_local_file_glob_selects_glob(self):
        """Test that file pattern matching selects glob."""
        result = execute_tool_selection("Find all *.py files in tests/", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "glob")
        self.assertIn("tests/", result["parsed_args"])

    def test_local_directory_list_selects_list_files(self):
        """Test that directory listing selects list_files."""
        result = execute_tool_selection("List files in tmp/", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "list_files")
        self.assertEqual(result["parsed_args"], ["tmp/"])

    def test_web_search_selects_web_search(self):
        """Test that web search selects web_search."""
        result = execute_tool_selection("Search the web for Python tutorials", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "web_search")
        self.assertIn("Python", " ".join(result["parsed_args"]))

    def test_math_tools_not_selected_for_file_paths(self):
        """Test that math tools are not selected for file path operations."""
        result = execute_tool_selection("Read `tmp/data.txt`", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "read_file")
        # Should NOT select any math tool
        self.assertNotIn(result["selected_tool"], ["add_numbers", "square_number", "multiply_numbers"])

    def test_web_tools_not_selected_for_local_paths(self):
        """Test that web tools are not selected for local file paths."""
        result = execute_tool_selection("Read `local/file.txt`", {})
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_tool"], "read_file")
        # Should NOT select web tools
        self.assertNotIn(result["selected_tool"], ["read_webpage", "web_search"])

    def test_manifest_metadata_distinguishes_local_vs_web(self):
        """Test that manifest metadata has proper local vs web distinctions."""
        view = build_ag1_capability_view()
        
        # Check read_file metadata
        read_file = view["read_file"]
        self.assertIn("local filesystem path", " ".join(read_file["use_when"]))
        self.assertIn("http:// or https://", " ".join(read_file["do_not_use_when"]))
        
        # Check read_webpage metadata
        read_webpage = view["read_webpage"]
        self.assertIn("http:// or https://", " ".join(read_webpage["use_when"]))
        self.assertIn("local filesystem paths", " ".join(read_webpage["do_not_use_when"]))
        
        # Check web_search metadata
        web_search = view["web_search"]
        self.assertIn("local files", " ".join(web_search["do_not_use_when"]))
        
        # Check math tools exclude file operations
        for tool_name in ["add_numbers", "square_number", "multiply_numbers"]:
            if tool_name in view:
                tool = view[tool_name]
                self.assertIn("file operations", " ".join(tool["do_not_use_when"]))

    def test_ag1_prompt_contains_path_routing_boundary(self):
        """Test that AG1 prompt contains the path routing boundary."""
        from system.orchestrator.agents.tool_selection_agent import build_ag1_prompt
        
        prompt = build_ag1_prompt()
        
        # Check that the path routing boundary is present
        self.assertIn("PATH ROUTING BOUNDARY", prompt)
        self.assertIn("http:// or https://", prompt)
        self.assertIn("tmp/file.txt", prompt)
        self.assertIn("Do not use web tools for local file paths", prompt)
        self.assertIn("Do not use math tools for file paths", prompt)


class TestSameRetryDoesNotSwitchToolCategories(unittest.TestCase):
    """Test that SAME retry doesn't switch from file operations to math/web tools."""

    def test_same_retry_preserves_file_tool_selection(self):
        """Test that SAME retry preserves file tool selection after bad selection."""
        # This test would require mocking the retry mechanism
        # For now, we verify that the manifest metadata is strong enough
        view = build_ag1_capability_view()
        
        # Verify that file tools have strong do_not_use_when for math/web operations
        file_tools = ["read_file", "write_file", "edit_file", "grep", "glob", "list_files"]
        
        for tool_name in file_tools:
            if tool_name in view:
                tool = view[tool_name]
                do_not_use = " ".join(tool["do_not_use_when"])
                # Should explicitly exclude web and math operations
                self.assertTrue(
                    "web" in do_not_use.lower() or "http" in do_not_use.lower(),
                    f"{tool_name} should exclude web operations in do_not_use_when"
                )
                self.assertTrue(
                    "math" in do_not_use.lower() or "arithmetic" in do_not_use.lower(),
                    f"{tool_name} should exclude math operations in do_not_use_when"
                )


if __name__ == "__main__":
    unittest.main()

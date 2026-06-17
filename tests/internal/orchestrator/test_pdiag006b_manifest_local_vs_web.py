"""
PDIAG-006B Follow-up Tests — Local vs Web Manifest Metadata Validation

Tests that manifest metadata correctly distinguishes between local file operations and web operations.
"""

import os
import sys
import unittest

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.tool_index.tool_capability_index import build_ag1_capability_view


class TestLocalVsWebManifestMetadata(unittest.TestCase):
    """Test that manifest metadata has proper local vs web distinctions."""

    def test_read_file_metadata_distinguishes_local_paths(self):
        """Test that read_file metadata explicitly distinguishes local paths from URLs."""
        view = build_ag1_capability_view()
        read_file = view["read_file"]
        
        # Should explicitly mention local paths
        use_when_text = " ".join(read_file["use_when"])
        self.assertIn("local file", use_when_text)
        self.assertIn("tmp/file.txt", use_when_text)
        
        # Should explicitly exclude web operations
        do_not_use_text = " ".join(read_file["do_not_use_when"])
        self.assertIn("webpages", do_not_use_text)
        self.assertIn("http://", do_not_use_text)
        self.assertIn("https://", do_not_use_text)

    def test_read_webpage_metadata_distinguishes_urls(self):
        """Test that read_webpage metadata explicitly distinguishes URLs from local paths."""
        view = build_ag1_capability_view()
        read_webpage = view["read_webpage"]
        
        # Should explicitly mention URLs
        use_when_text = " ".join(read_webpage["use_when"])
        self.assertIn("URL", use_when_text)
        self.assertIn("http://", use_when_text)
        self.assertIn("https://", use_when_text)
        
        # Should explicitly exclude local file operations
        do_not_use_text = " ".join(read_webpage["do_not_use_when"])
        self.assertIn("local filesystem", do_not_use_text)
        self.assertIn("tmp/file.txt", do_not_use_text)

    def test_web_search_metadata_excludes_local_files(self):
        """Test that web_search metadata excludes local file operations."""
        view = build_ag1_capability_view()
        web_search = view["web_search"]
        
        do_not_use_text = " ".join(web_search["do_not_use_when"])
        self.assertIn("local files", do_not_use_text)
        self.assertIn("local file path", do_not_use_text)

    def test_math_tools_exclude_file_and_web_operations(self):
        """Test that math tools explicitly exclude file and web operations."""
        view = build_ag1_capability_view()
        math_tools = ["add_numbers", "square_number", "multiply_numbers", "divide_numbers", 
                     "cube_number", "square_root", "factorial", "fibonacci", "subtract_numbers"]
        
        for tool_name in math_tools:
            if tool_name in view:
                tool = view[tool_name]
                do_not_use_text = " ".join(tool["do_not_use_when"])
                
                # Should exclude file operations
                self.assertIn("file operations", do_not_use_text)
                
                # Should exclude web operations
                self.assertIn("web operations", do_not_use_text)

    def test_file_tools_exclude_web_and_math_operations(self):
        """Test that all file tools exclude web and math operations."""
        view = build_ag1_capability_view()
        file_tools = ["read_file", "write_file", "edit_file", "grep", "glob", "list_files"]
        
        for tool_name in file_tools:
            if tool_name in view:
                tool = view[tool_name]
                do_not_use_text = " ".join(tool["do_not_use_when"])
                
                # Should exclude web operations
                self.assertTrue(
                    "web operations" in do_not_use_text or "http" in do_not_use_text,
                    f"{tool_name} should exclude web operations: {do_not_use_text}"
                )
                
                # Should exclude math operations
                self.assertTrue(
                    "arithmetic/math" in do_not_use_text or "math" in do_not_use_text,
                    f"{tool_name} should exclude math operations: {do_not_use_text}"
                )

    def test_specific_tool_metadata_requirements(self):
        """Test specific metadata requirements for key tools."""
        view = build_ag1_capability_view()
        
        # read_file requirements
        read_file = view["read_file"]
        self.assertEqual(read_file["category"], "file_local")
        self.assertIn("local filesystem path", " ".join(read_file["use_when"]))
        self.assertIn("http:// or https://", " ".join(read_file["do_not_use_when"]))
        
        # read_webpage requirements
        read_webpage = view["read_webpage"]
        self.assertEqual(read_webpage["category"], "web_external")
        self.assertIn("URLs beginning with http:// or https://", " ".join(read_webpage["use_when"]))
        self.assertIn("local filesystem paths", " ".join(read_webpage["do_not_use_when"]))
        
        # web_search requirements
        web_search = view["web_search"]
        self.assertEqual(web_search["category"], "web_external")
        self.assertIn("reading local files", " ".join(web_search["do_not_use_when"]))
        
        # square_number should exclude file operations
        square_number = view["square_number"]
        self.assertIn("file operations", " ".join(square_number["do_not_use_when"]))

    def test_ag1_prompt_contains_path_routing_boundary(self):
        """Test that AG1 prompt contains the path routing boundary."""
        # Read the tool_selection_agent.py file to check for the boundary
        agent_file = os.path.join(os.path.dirname(_project_root), "system", "orchestrator", "agents", "tool_selection_agent.py")
        with open(agent_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check that the path routing boundary is present
        self.assertIn("PATH ROUTING BOUNDARY", content)
        self.assertIn("http:// or https://", content)
        self.assertIn("tmp/file.txt", content)
        self.assertIn("Do not use web tools for local file paths", content)
        self.assertIn("Do not use math tools for file paths", content)


if __name__ == "__main__":
    unittest.main()

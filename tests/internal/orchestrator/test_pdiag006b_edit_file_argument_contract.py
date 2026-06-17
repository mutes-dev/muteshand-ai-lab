"""
PDIAG-006B Follow-up Tests — edit_file Argument Contract

Tests that edit_file manifest metadata and AG1 behavior correctly handle
replace-only requirement and prevent empty_old_text failures.
"""

import os
import sys
import unittest

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.tool_index.tool_capability_index import build_ag1_capability_view


class TestEditFileArgumentContract(unittest.TestCase):
    """Test that edit_file manifest metadata correctly specifies replace-only requirement."""

    def test_edit_file_manifest_specifies_replace_only(self):
        """Test that edit_file manifest clearly specifies replace-only requirement."""
        view = build_ag1_capability_view()
        edit_file = view["edit_file"]
        
        # Check that use_when emphasizes known existing text
        use_when_text = " ".join(edit_file["use_when"])
        self.assertIn("known existing text", use_when_text)
        self.assertIn("both old text and new text", use_when_text)
        self.assertIn("exact string replacement", use_when_text)
        
        # Check that do_not_use_when excludes append operations
        do_not_use_text = " ".join(edit_file["do_not_use_when"])
        self.assertIn("appending a new line without known old_text", do_not_use_text)
        self.assertIn("adding content when no existing target text is specified", do_not_use_text)

    def test_edit_file_schema_requires_old_text(self):
        """Test that edit_file schema requires old_text argument."""
        view = build_ag1_capability_view()
        edit_file = view["edit_file"]
        
        # Check that old_text is in the arguments
        args = edit_file.get("args", {})
        self.assertIn("old_text", args)
        self.assertEqual(args["old_text"], "string")
        
        # Check arg_order includes old_text as second argument
        arg_order = edit_file.get("arg_order", [])
        self.assertIn("old_text", arg_order)
        self.assertGreater(len(arg_order), 1)
        self.assertEqual(arg_order[1], "old_text")

    def test_edit_file_description_clarifies_replace_only(self):
        """Test that edit_file description clarifies replace-only behavior."""
        view = build_ag1_capability_view()
        edit_file = view["edit_file"]
        
        description = edit_file.get("description", "")
        self.assertIn("Replace exact string occurrences", description)
        self.assertIn("Safer alternative to full file overwrite", description)

    def test_ag1_prompt_contains_edit_file_requirement(self):
        """Test that AG1 prompt contains edit_file old_text requirement."""
        # Read the tool_selection_agent.py file to check for the requirement
        agent_file = os.path.join(os.path.dirname(_project_root), "system", "orchestrator", "agents", "tool_selection_agent.py")
        with open(agent_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check that the edit_file requirement is present
        self.assertIn("EDIT_FILE REQUIREMENT", content)
        self.assertIn("provide both old_text and new_text", content)
        self.assertIn("do not invent old_text", content)

    def test_edit_file_ag1_prompt_line_shows_correct_arguments(self):
        """Test that edit_file AG1 prompt line shows correct argument names."""
        from system.tool_index.tool_capability_index import format_ag1_capability_prompt_line
        
        view = build_ag1_capability_view()
        edit_file = view["edit_file"]
        prompt_line = format_ag1_capability_prompt_line(edit_file)
        
        # Should show the correct argument names
        self.assertIn("edit_file", prompt_line)
        self.assertIn('"path"', prompt_line)
        self.assertIn('"old_text"', prompt_line)
        self.assertIn('"new_text"', prompt_line)

    def test_edit_file_manifest_excludes_append_scenarios(self):
        """Test that edit_file manifest explicitly excludes append scenarios."""
        view = build_ag1_capability_view()
        edit_file = view["edit_file"]
        
        do_not_use_when = edit_file.get("do_not_use_when", [])
        
        # Should explicitly exclude append-style scenarios
        self.assertIn("appending a new line without known old_text", do_not_use_when)
        self.assertIn("adding content when no existing target text is specified", do_not_use_when)

    def test_edit_file_category_and_risk_correct(self):
        """Test that edit_file has correct category and risk markers."""
        view = build_ag1_capability_view()
        edit_file = view["edit_file"]
        
        # Should be file_mutation category
        self.assertEqual(edit_file["category"], "file_mutation")
        
        # Should be mutating and require approval
        self.assertTrue(edit_file.get("mutating", False))
        self.assertTrue(edit_file.get("requires_approval", False))


class TestEditFileArgumentValidation(unittest.TestCase):
    """Test edit_file tool argument validation behavior through manifest."""

    def test_edit_file_manifest_indicates_replace_only(self):
        """Test that edit_file manifest indicates replace-only behavior."""
        view = build_ag1_capability_view()
        edit_file = view["edit_file"]
        
        # The description should indicate replace-only behavior
        description = edit_file.get("description", "")
        self.assertIn("Replace exact string occurrences", description)
        
        # The use_when should emphasize known existing text
        use_when = edit_file.get("use_when", [])
        self.assertIn("known existing text", " ".join(use_when))
        
        # The do_not_use_when should exclude append scenarios
        do_not_use = edit_file.get("do_not_use_when", [])
        self.assertIn("appending a new line without known old_text", do_not_use)
        self.assertIn("adding content when no existing target text is specified", do_not_use)


if __name__ == "__main__":
    unittest.main()

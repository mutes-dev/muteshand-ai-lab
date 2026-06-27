"""Tests for AGENT-001D — Tool Metadata Foundation Cleanup.

Covers metadata field completeness, conservative classification,
run-time behavior safety, and authority boundary preservation.
"""

import json
import os
import sys
import unittest

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.tool_index.tool_capability_index import build_ag1_capability_view
from system.security.tool_policy import TOOL_METADATA

_TOOLS_PATH = os.path.join("system", "tool_index", "tools.json")


class TestToolMetadataFieldsPresent(unittest.TestCase):
    """Every tools.json entry must have the four AGENT-001D metadata fields."""

    @classmethod
    def setUpClass(cls):
        with open(_TOOLS_PATH, "r", encoding="utf-8") as f:
            cls.tools = json.load(f)

    def test_every_tool_has_capability_family(self):
        for name, data in self.tools.items():
            with self.subTest(tool=name):
                self.assertIn("capability_family", data, f"{name} missing capability_family")
                self.assertIsInstance(data["capability_family"], str)
                self.assertTrue(data["capability_family"], f"{name} capability_family is empty")

    def test_every_tool_has_routeable(self):
        for name, data in self.tools.items():
            with self.subTest(tool=name):
                self.assertIn("routeable", data, f"{name} missing routeable")
                self.assertIsInstance(data["routeable"], bool)

    def test_every_tool_has_requires_literal_preservation(self):
        for name, data in self.tools.items():
            with self.subTest(tool=name):
                self.assertIn("requires_literal_preservation", data, f"{name} missing requires_literal_preservation")
                self.assertIsInstance(data["requires_literal_preservation"], bool)

    def test_every_tool_has_route_prepopulation_allowed(self):
        for name, data in self.tools.items():
            with self.subTest(tool=name):
                self.assertIn("route_prepopulation_allowed", data, f"{name} missing route_prepopulation_allowed")
                self.assertIsInstance(data["route_prepopulation_allowed"], bool)


class TestToolClassificationSafety(unittest.TestCase):
    """Conservative classification per AGENT-001D guidance."""

    @classmethod
    def setUpClass(cls):
        with open(_TOOLS_PATH, "r", encoding="utf-8") as f:
            cls.tools = json.load(f)

    def test_non_production_tools_are_not_routeable(self):
        for name, data in self.tools.items():
            if not data.get("production", False):
                with self.subTest(tool=name):
                    self.assertFalse(
                        data.get("routeable", True),
                        f"non-production tool {name} must NOT be routeable"
                    )

    def test_file_mutation_tools_are_not_routeable(self):
        mutation_tools = ["write_file", "append_file", "edit_file"]
        for name in mutation_tools:
            with self.subTest(tool=name):
                data = self.tools.get(name, {})
                self.assertFalse(
                    data.get("routeable", True),
                    f"mutation tool {name} must NOT be routeable"
                )

    def test_file_tools_route_prepopulation_false(self):
        file_tools = ["read_file", "list_files", "grep", "glob",
                      "write_file", "append_file", "edit_file"]
        for name in file_tools:
            with self.subTest(tool=name):
                data = self.tools.get(name, {})
                self.assertFalse(
                    data.get("route_prepopulation_allowed", True),
                    f"file tool {name} must NOT allow route prepopulation"
                )

    def test_web_tools_route_prepopulation_false(self):
        web_tools = ["read_webpage", "web_search"]
        for name in web_tools:
            with self.subTest(tool=name):
                data = self.tools.get(name, {})
                self.assertFalse(
                    data.get("route_prepopulation_allowed", True),
                    f"web tool {name} must NOT allow route prepopulation"
                )

    def test_production_math_tools_are_routeable(self):
        math_tools = ["add_numbers", "subtract_numbers", "multiply_numbers",
                      "divide_numbers", "square_number", "cube_number",
                      "square_root", "factorial", "fibonacci"]
        for name in math_tools:
            with self.subTest(tool=name):
                data = self.tools.get(name, {})
                self.assertTrue(
                    data.get("routeable", False),
                    f"math tool {name} must be routeable"
                )

    def test_production_math_tools_route_prepopulation_allowed(self):
        math_tools = ["add_numbers", "subtract_numbers", "multiply_numbers",
                      "divide_numbers", "square_number", "cube_number",
                      "square_root", "factorial", "fibonacci"]
        for name in math_tools:
            with self.subTest(tool=name):
                data = self.tools.get(name, {})
                self.assertTrue(
                    data.get("route_prepopulation_allowed", False),
                    f"math tool {name} must allow route prepopulation"
                )

    def test_read_file_list_files_grep_glob_routeable(self):
        for name in ["read_file", "list_files", "grep", "glob"]:
            with self.subTest(tool=name):
                data = self.tools.get(name, {})
                self.assertTrue(
                    data.get("routeable", False),
                    f"file read tool {name} must be routeable"
                )
                self.assertFalse(
                    data.get("route_prepopulation_allowed", True),
                    f"file read tool {name} must NOT allow route prepopulation"
                )

    def test_read_webpage_routeable_no_prepopulation(self):
        data = self.tools.get("read_webpage", {})
        self.assertTrue(data.get("routeable", False))
        self.assertFalse(data.get("route_prepopulation_allowed", True))

    def test_web_search_not_routeable(self):
        data = self.tools.get("web_search", {})
        self.assertFalse(data.get("routeable", True))
        self.assertFalse(data.get("route_prepopulation_allowed", True))

    def test_finalize_output_descriptive_non_authoritative(self):
        data = self.tools.get("finalize_output", {})
        self.assertEqual(data.get("capability_family"), "text_finalization")
        self.assertTrue(data.get("routeable", False))
        self.assertFalse(data.get("route_prepopulation_allowed", True))

    def test_multiply_string_string_utility_conservative(self):
        data = self.tools.get("multiply_string", {})
        self.assertEqual(data.get("capability_family"), "string_utility")
        self.assertFalse(data.get("routeable", True))
        self.assertTrue(data.get("requires_literal_preservation", False))
        self.assertFalse(data.get("route_prepopulation_allowed", True))


class TestToolIndexLoadingUnchanged(unittest.TestCase):
    """Adding metadata fields must not break tool index loading or AG1 view."""

    def test_tool_index_loads_cleanly(self):
        with open(_TOOLS_PATH, "r", encoding="utf-8") as f:
            tools = json.load(f)
        self.assertIsInstance(tools, dict)
        self.assertGreater(len(tools), 0)

    def test_ag1_capability_view_still_builds(self):
        view = build_ag1_capability_view()
        self.assertIsInstance(view, dict)
        # All production tools should be present
        with open(_TOOLS_PATH, "r", encoding="utf-8") as f:
            tools = json.load(f)
        production_tools = {name for name, d in tools.items() if d.get("production", False)}
        view_tools = set(view.keys())
        self.assertEqual(production_tools, view_tools)

    def test_ag1_capability_view_fields_stable(self):
        view = build_ag1_capability_view()
        for name, cap in view.items():
            with self.subTest(tool=name):
                self.assertIn("name", cap)
                self.assertIn("category", cap)
                self.assertIn("read_only", cap)
                self.assertIn("mutating", cap)

    def test_tool_policy_metadata_unchanged(self):
        """tool_policy.py metadata must not be affected by tools.json changes."""
        for name, meta in TOOL_METADATA.items():
            with self.subTest(tool=name):
                self.assertIn("read_only", meta)
                self.assertIn("mutating", meta)
                self.assertIn("external_call", meta)


class TestNoRuntimeBehaviorChange(unittest.TestCase):
    """Metadata-only change must not alter execution, routing, or governance."""

    def test_tools_json_extra_fields_do_not_break_argument_resolver(self):
        from system.resolver.argument_resolver import _construct_args
        # add_numbers expects 2 args; should still resolve correctly
        tokens = ["add_numbers", "5", "10"]
        args = _construct_args("add_numbers", tokens)
        self.assertEqual(args, ["5", "10"])

    def test_tools_json_extra_fields_do_not_break_tool_call_converter(self):
        from system.orchestrator.tool_call_converter import convert_agent_output_to_tool_call
        tool_call, failure = convert_agent_output_to_tool_call("USE_TOOL: add_numbers 5 10")
        self.assertIsNotNone(tool_call)
        self.assertIsNone(failure)

    def test_system_entry_still_works_for_math_tool(self):
        from system.entry.system_entry import system_entry
        result = system_entry("add_numbers 2 3")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)

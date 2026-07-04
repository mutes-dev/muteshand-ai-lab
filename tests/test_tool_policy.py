"""
Tool Policy / Plan Mode / Read-Only Controls Tests (ADOPT-004)

Tests cover:
- Tool metadata classification
- Plan/read-only mode enforcement (fail-closed)
- High-risk tool blocking
- Guide-only / no-tools intent detection
- Integration with system_entry pre-gate
- Clean failure shapes
"""

import os
import sys
import unittest

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.security.tool_policy import (
    TOOL_METADATA,
    PLAN_MODE_ALLOWED_TOOLS,
    HIGH_RISK_TOOLS,
    check_tool_policy,
    detect_guide_only_intent,
    get_tool_metadata,
    is_read_only_tool,
    is_mutating_tool,
    is_high_risk_tool,
    list_plan_mode_allowed_tools,
    list_high_risk_tools,
    ToolPolicyResult,
    GuideOnlyResult,
)
from system.entry.system_entry import system_entry


class TestToolMetadata(unittest.TestCase):
    """Test tool metadata classification."""

    def test_read_only_tools_classified(self):
        """Read-only production tools must have read_only=True."""
        for name in ["add_numbers", "read_file", "list_files", "web_search", "read_webpage", "finalize_output"]:
            with self.subTest(tool=name):
                meta = get_tool_metadata(name)
                self.assertIsNotNone(meta, f"{name} missing metadata")
                self.assertTrue(meta["read_only"], f"{name} should be read_only")
                self.assertFalse(meta["mutating"], f"{name} should not be mutating")

    def test_mutating_tools_classified(self):
        """Mutating tools must have mutating=True."""
        meta = get_tool_metadata("write_file")
        self.assertIsNotNone(meta)
        self.assertFalse(meta["read_only"])
        self.assertTrue(meta["mutating"])

    def test_high_risk_tools_classified(self):
        """High-risk tools must be in HIGH_RISK_TOOLS set."""
        self.assertIn("run_python", HIGH_RISK_TOOLS)
        meta = get_tool_metadata("run_python")
        self.assertIsNotNone(meta)
        self.assertTrue(meta["high_risk"])

    def test_unknown_tool_metadata_is_none(self):
        """Unknown tools return None metadata (fail-closed basis)."""
        self.assertIsNone(get_tool_metadata("nonexistent_tool_xyz"))

    def test_is_read_only_for_known_tools(self):
        self.assertTrue(is_read_only_tool("add_numbers"))
        self.assertFalse(is_read_only_tool("write_file"))

    def test_is_read_only_unknown_is_false(self):
        """Unknown tools are NOT read-only (fail-closed)."""
        self.assertFalse(is_read_only_tool("unknown_tool"))

    def test_is_mutating_unknown_is_true(self):
        """Unknown tools are treated as mutating (fail-closed)."""
        self.assertTrue(is_mutating_tool("unknown_tool"))

    def test_external_call_tools_flagged(self):
        meta = get_tool_metadata("web_search")
        self.assertTrue(meta["external_call"])
        meta = get_tool_metadata("read_webpage")
        self.assertTrue(meta["external_call"])


class TestCheckToolPolicyNormalMode(unittest.TestCase):
    """Test policy checks in normal mode."""

    def test_read_only_allowed_in_normal(self):
        result = check_tool_policy("add_numbers", mode="normal")
        self.assertTrue(result.allowed)
        self.assertEqual(result.mode, "normal")

    def test_mutating_allowed_in_normal(self):
        result = check_tool_policy("write_file", mode="normal")
        self.assertTrue(result.allowed)

    def test_high_risk_blocked_in_normal(self):
        """High-risk tools blocked even in normal mode."""
        result = check_tool_policy("run_python", mode="normal")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "tool_policy_blocked")
        self.assertIn("high-risk", result.detail)

    def test_unknown_tool_allowed_in_normal(self):
        """Unknown tools are allowed in normal mode (only high-risk blocked)."""
        result = check_tool_policy("unknown_tool", mode="normal")
        self.assertTrue(result.allowed)

    def test_normal_mode_default(self):
        result = check_tool_policy("add_numbers")
        self.assertTrue(result.allowed)
        self.assertEqual(result.mode, "normal")


class TestCheckToolPolicyPlanMode(unittest.TestCase):
    """Test plan/read-only mode enforcement — fail-closed."""

    def test_read_only_allowed_in_plan(self):
        for name in ["add_numbers", "read_file", "list_files", "web_search"]:
            with self.subTest(tool=name):
                result = check_tool_policy(name, mode="plan")
                self.assertTrue(result.allowed, f"{name} should be allowed in plan mode")

    def test_mutating_blocked_in_plan(self):
        result = check_tool_policy("write_file", mode="plan")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "plan_mode_blocked")
        self.assertIn("mutating", result.detail)

    def test_unknown_blocked_fail_closed_in_plan(self):
        """Unknown tools must be blocked in plan mode (fail-closed)."""
        result = check_tool_policy("nonexistent_tool", mode="plan")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "plan_mode_blocked")
        self.assertIn("unknown", result.detail)
        self.assertIn("fail-closed", result.detail)

    def test_high_risk_blocked_in_plan(self):
        result = check_tool_policy("run_python", mode="plan")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "tool_policy_blocked")

    def test_read_only_allowed_in_read_only_mode(self):
        result = check_tool_policy("read_file", mode="read_only")
        self.assertTrue(result.allowed)

    def test_mutating_blocked_in_read_only_mode(self):
        result = check_tool_policy("write_file", mode="read_only")
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "tool_policy_blocked")

    def test_guide_only_mode_blocks_mutating(self):
        result = check_tool_policy("write_file", mode="guide_only")
        self.assertFalse(result.allowed)

    def test_non_production_tool_blocked_in_plan(self):
        """Non-production mutating tools should be blocked in plan mode."""
        result = check_tool_policy("migrate_error_handling", mode="plan")
        self.assertFalse(result.allowed)


class TestHighRiskTools(unittest.TestCase):
    """Test high-risk tool blocking across all modes."""

    def test_high_risk_blocked_in_normal(self):
        result = check_tool_policy("run_python", mode="normal")
        self.assertFalse(result.allowed)

    def test_high_risk_blocked_in_plan(self):
        result = check_tool_policy("run_python", mode="plan")
        self.assertFalse(result.allowed)

    def test_high_risk_blocked_in_read_only(self):
        result = check_tool_policy("run_python", mode="read_only")
        self.assertFalse(result.allowed)

    def test_is_high_risk_tool(self):
        self.assertTrue(is_high_risk_tool("run_python"))
        self.assertFalse(is_high_risk_tool("add_numbers"))
        self.assertFalse(is_high_risk_tool("write_file"))


class TestPolicyResultShape(unittest.TestCase):
    """Test that policy results have stable, predictable shapes."""

    def test_allowed_result_dict(self):
        result = check_tool_policy("add_numbers", mode="normal")
        d = result.to_dict()
        self.assertEqual(d["status"], "success")
        self.assertTrue(d["allowed"])
        self.assertEqual(d["tool_name"], "add_numbers")
        self.assertEqual(d["mode"], "normal")

    def test_blocked_result_dict(self):
        result = check_tool_policy("write_file", mode="plan")
        d = result.to_dict()
        self.assertEqual(d["status"], "failure")
        self.assertEqual(d["reason"], "plan_mode_blocked")
        self.assertIn("detail", d)
        self.assertEqual(d["tool_name"], "write_file")
        self.assertEqual(d["mode"], "plan")

    def test_tool_policy_result_dataclass(self):
        result = ToolPolicyResult(allowed=True, tool_name="test", mode="normal")
        self.assertTrue(result.allowed)
        self.assertIsNone(result.reason)


class TestGuideOnlyDetection(unittest.TestCase):
    """Test guide-only / no-tools intent detection (advisory only)."""

    def test_detects_guide_only_mode(self):
        result = detect_guide_only_intent("Please enter guide-only mode")
        self.assertTrue(result.is_guide_only)
        self.assertIsNotNone(result.reason)

    def test_detects_no_tools(self):
        result = detect_guide_only_intent("Do not use any tools")
        self.assertTrue(result.is_guide_only)
        self.assertIn("forbade", result.reason)

    def test_detects_dont_use_tools(self):
        result = detect_guide_only_intent("Don't use tools")
        self.assertTrue(result.is_guide_only)

    def test_detects_plan_only(self):
        result = detect_guide_only_intent("plan only")
        self.assertTrue(result.is_guide_only)

    def test_detects_just_explain(self):
        result = detect_guide_only_intent("Just explain what you would do")
        self.assertTrue(result.is_guide_only)

    def test_detects_guide_me_only(self):
        result = detect_guide_only_intent("guide me only")
        self.assertTrue(result.is_guide_only)

    def test_detects_no_tool_calls(self):
        result = detect_guide_only_intent("no tool calls please")
        self.assertTrue(result.is_guide_only)

    def test_no_false_positive_on_normal_request(self):
        result = detect_guide_only_intent("What is the square root of 16?")
        self.assertFalse(result.is_guide_only)
        self.assertIsNone(result.reason)

    def test_no_false_positive_on_tool_request(self):
        result = detect_guide_only_intent("Use the web_search tool to find the answer")
        self.assertFalse(result.is_guide_only)

    def test_no_false_positive_on_explanation_with_tools(self):
        result = detect_guide_only_intent("Explain how tools work in this system")
        self.assertFalse(result.is_guide_only)

    def test_empty_string_not_guide_only(self):
        result = detect_guide_only_intent("")
        self.assertFalse(result.is_guide_only)

    def test_none_not_guide_only(self):
        result = detect_guide_only_intent(None)
        self.assertFalse(result.is_guide_only)

    def test_guide_only_result_advisory_flag(self):
        result = detect_guide_only_intent("no tools mode")
        d = result.to_dict()
        self.assertTrue(d["is_guide_only"])
        self.assertTrue(d["advisory_only"])


class TestPlanModeAllowedList(unittest.TestCase):
    """Test plan mode allowlist completeness."""

    def test_read_only_production_tools_in_allowlist(self):
        for name, meta in TOOL_METADATA.items():
            if meta.get("read_only") and meta.get("production", True):
                with self.subTest(tool=name):
                    self.assertIn(name, PLAN_MODE_ALLOWED_TOOLS, f"read-only tool {name} missing from PLAN_MODE_ALLOWED_TOOLS")

    def test_mutating_tools_not_in_allowlist(self):
        for name, meta in TOOL_METADATA.items():
            if meta.get("mutating"):
                with self.subTest(tool=name):
                    self.assertNotIn(name, PLAN_MODE_ALLOWED_TOOLS, f"mutating tool {name} should NOT be in allowlist")

    def test_high_risk_not_in_allowlist(self):
        for name in HIGH_RISK_TOOLS:
            with self.subTest(tool=name):
                self.assertNotIn(name, PLAN_MODE_ALLOWED_TOOLS)

    def test_read_file_present_in_plan_mode_allowed(self):
        """read_file must be in PLAN_MODE_ALLOWED_TOOLS (regression for typo fix)."""
        self.assertIn("read_file", PLAN_MODE_ALLOWED_TOOLS)

    def test_typo_reaf_dile_not_in_plan_mode_allowed(self):
        """The typo 'reaf_dile' must not be in PLAN_MODE_ALLOWED_TOOLS."""
        self.assertNotIn("reaf_dile", PLAN_MODE_ALLOWED_TOOLS)

    def test_list_functions_return_sorted(self):
        self.assertEqual(list_plan_mode_allowed_tools(), sorted(PLAN_MODE_ALLOWED_TOOLS))
        self.assertEqual(list_high_risk_tools(), sorted(HIGH_RISK_TOOLS))


class TestSystemEntryIntegration(unittest.TestCase):
    """Test system_entry tool policy integration — blocked tools fail cleanly."""

    def test_read_only_tool_succeeds_in_normal_mode(self):
        result = system_entry("add_numbers 2 3")
        self.assertEqual(result["status"], "success")

    def test_read_only_tool_succeeds_in_plan_mode(self):
        result = system_entry("add_numbers 2 3", mode="plan")
        self.assertEqual(result["status"], "success")

    def test_mutating_tool_blocked_in_plan_mode(self):
        """write_file must be blocked in plan mode with clean failure."""
        result = system_entry('write_file "test.txt" "hello"', mode="plan")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "plan_mode_blocked")
        self.assertIn("detail", result)
        self.assertEqual(result["tool_name"], "write_file")
        self.assertEqual(result["mode"], "plan")

    def test_unknown_tool_blocked_in_plan_mode(self):
        """Unknown tools blocked fail-closed in plan mode."""
        result = system_entry("nonexistent_tool arg1", mode="plan")
        # Unknown tool is caught by existing unknown_tool check before policy,
        # so we verify it doesn't crash and returns a clean failure.
        self.assertEqual(result["status"], "failure")

    def test_high_risk_tool_blocked_in_normal_mode(self):
        """run_python is non-production AND high-risk; blocked before execution."""
        result = system_entry("run_python print(1)", mode="normal")
        self.assertEqual(result["status"], "failure")
        # non_production_tool check runs before policy gate for non-production tools
        self.assertIn(result["reason"], ("non_production_tool", "tool_policy_blocked"))

    def test_mutating_tool_allowed_in_normal_mode(self):
        """write_file must succeed in normal mode (if path is valid)."""
        test_path = "tests/_temp_test_write.txt"
        result = system_entry(f'write_file "{test_path}" "hello world"', mode="normal")
        self.assertEqual(result["status"], "success")
        # Cleanup
        full_path = os.path.join(os.path.abspath("E:/MutesHand"), test_path)
        if os.path.exists(full_path):
            os.remove(full_path)

    def test_blocked_tool_does_not_crash(self):
        """Blocked tool must return dict, not raise."""
        result = system_entry('write_file "some.txt" "content"', mode="plan")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "failure")

    def test_read_only_tool_with_read_only_mode(self):
        result = system_entry('read_webpage "https://example.com"', mode="read_only")
        # Should be allowed (read-only external call) but may fail for network reasons;
        # we check it wasn't blocked by policy.
        if result["status"] == "failure":
            self.assertNotEqual(result.get("reason"), "plan_mode_blocked")
            self.assertNotEqual(result.get("reason"), "tool_policy_blocked")


if __name__ == "__main__":
    unittest.main(verbosity=2)

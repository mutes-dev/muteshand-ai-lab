"""
PDIAG-006 Slice 1 — AG1 Tool Capability Grounding Tests

Validates:
- Deterministic composed capability view merges tools.json + tool_policy.py
- AG1 prompt uses enriched capability metadata
- finalize_output grounding includes do_not_use_when guidance
- SAME retry enforcement remains intact
- External-call user-control behavior unchanged
- No tool execution during capability view construction
- Non-production tools excluded
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.tool_index.tool_capability_index import (
    build_ag1_capability_view,
    format_ag1_capability_prompt_line,
    build_ag1_capability_prompt,
    _read_category_from_manifest,
    _read_output_kind_from_manifest,
    _read_use_when_from_manifest,
    _read_do_not_use_when_from_manifest,
)
from system.security.tool_policy import TOOL_METADATA


class TestCapabilityViewComposition(unittest.TestCase):
    """Positive: capability view reads from manifest and merges tool_policy.py correctly."""

    def test_view_includes_all_production_tools(self):
        view = build_ag1_capability_view()
        production_tools = [
            "add_numbers", "cube_number", "divide_numbers", "factorial",
            "fibonacci", "list_files", "multiply_numbers", "multiply_string",
            "read_file", "read_webpage", "square_number", "square_root",
            "subtract_numbers", "web_search", "finalize_output", "write_file",
            "grep", "glob", "edit_file",
        ]
        for name in production_tools:
            with self.subTest(tool=name):
                self.assertIn(name, view, f"Production tool {name} missing from capability view")

    def test_capability_metadata_read_from_manifest(self):
        """Test that capability metadata is read from tools.json manifest, not inferred."""
        view = build_ag1_capability_view()
        
        # Test finalize_output reads from manifest
        finalize_cap = view["finalize_output"]
        self.assertEqual(finalize_cap["category"], "text_finalization")
        self.assertEqual(finalize_cap["output_kind"], "text")
        self.assertIn("text-only answers", finalize_cap["use_when"])
        self.assertIn("arithmetic or math operations", finalize_cap["do_not_use_when"])
        
        # Test multiply_string reads from manifest
        multiply_cap = view["multiply_string"]
        self.assertEqual(multiply_cap["category"], "string_utility")
        self.assertEqual(multiply_cap["output_kind"], "text")
        self.assertIn("repeating a provided string a specified number of times", multiply_cap["use_when"])
        self.assertIn("simple text generation", multiply_cap["do_not_use_when"])
        
        # Test math tools read from manifest
        add_cap = view["add_numbers"]
        self.assertEqual(add_cap["category"], "math")
        self.assertEqual(add_cap["output_kind"], "number")
        self.assertIn("arithmetic addition", add_cap["use_when"])
        
        # Test web tools read from manifest
        search_cap = view["web_search"]
        self.assertEqual(search_cap["category"], "web_external")
        self.assertEqual(search_cap["output_kind"], "list")
        self.assertIn("searching the web for information", search_cap["use_when"])

    def test_manifest_reading_functions_work_correctly(self):
        """Test the individual manifest reading functions."""
        # Test finalize_output
        finalize_data = {
            "category": "text_finalization",
            "output_kind": "text",
            "use_when": ["text-only answers"],
            "do_not_use_when": ["arithmetic operations"]
        }
        
        self.assertEqual(_read_category_from_manifest(finalize_data, "finalize_output"), "text_finalization")
        self.assertEqual(_read_output_kind_from_manifest(finalize_data, "finalize_output"), "text")
        self.assertEqual(_read_use_when_from_manifest(finalize_data, "finalize_output"), ["text-only answers"])
        self.assertEqual(_read_do_not_use_when_from_manifest(finalize_data, "finalize_output"), ["arithmetic operations"])
        
        # Test conservative fallback for missing metadata
        incomplete_data = {"production": True}
        
        self.assertEqual(_read_category_from_manifest(incomplete_data, "test_tool"), "utility")
        self.assertEqual(_read_output_kind_from_manifest(incomplete_data, "test_tool"), "text")
        self.assertEqual(_read_use_when_from_manifest(incomplete_data, "test_tool"), 
                        ["only when the tool description directly matches the requested action"])
        self.assertEqual(_read_do_not_use_when_from_manifest(incomplete_data, "test_tool"), 
                        ["tasks not directly described by this tool's documented purpose"])

    def test_non_production_tools_excluded(self):
        view = build_ag1_capability_view()
        non_production = [
            "bad_add", "health_check_system", "inspect_manager_section",
            "migrate_error_handling", "rebuild_tool_index", "run_python",
            "run_system_maintenance", "self_test_system",
        ]
        for name in non_production:
            with self.subTest(tool=name):
                self.assertNotIn(name, view, f"Non-production tool {name} should not be in view")

    def test_read_webpage_merges_policy_metadata(self):
        view = build_ag1_capability_view()
        cap = view["read_webpage"]
        self.assertTrue(cap["external_call"])
        self.assertTrue(cap["read_only"])
        self.assertFalse(cap["mutating"])
        self.assertFalse(cap["high_risk"])
        self.assertFalse(cap["requires_approval"])
        self.assertTrue(cap["overrideable_with_user_control"])
        self.assertEqual(cap["category"], "web_external")
        self.assertEqual(cap["provider"], "target_url_host (supplied at runtime)")

    def test_web_search_merges_policy_metadata(self):
        view = build_ag1_capability_view()
        cap = view["web_search"]
        self.assertTrue(cap["external_call"])
        self.assertTrue(cap["read_only"])
        self.assertFalse(cap["mutating"])
        self.assertFalse(cap["high_risk"])
        self.assertFalse(cap["requires_approval"])
        self.assertTrue(cap["overrideable_with_user_control"])
        self.assertEqual(cap["category"], "web_external")
        self.assertIn("DuckDuckGo", cap["provider"])

    def test_write_file_merges_policy_metadata(self):
        view = build_ag1_capability_view()
        cap = view["write_file"]
        self.assertFalse(cap["read_only"])
        self.assertTrue(cap["mutating"])
        self.assertFalse(cap["external_call"])
        self.assertTrue(cap["requires_approval"])
        self.assertFalse(cap["overrideable_with_user_control"])
        self.assertEqual(cap["category"], "file_mutation")

    def test_finalize_output_metadata(self):
        view = build_ag1_capability_view()
        cap = view["finalize_output"]
        self.assertEqual(cap["category"], "text_finalization")
        self.assertFalse(cap["external_call"])
        self.assertFalse(cap["mutating"])
        self.assertFalse(cap["high_risk"])
        self.assertFalse(cap["requires_approval"])
        self.assertTrue(cap["read_only"])
        self.assertIn("arithmetic or math operations", cap["do_not_use_when"])
        self.assertIn("file reading or writing", cap["do_not_use_when"])
        self.assertIn("webpage reading or search", cap["do_not_use_when"])
        self.assertIn("text-only answers", cap["use_when"])

    def test_math_tools_categorized_correctly(self):
        view = build_ag1_capability_view()
        for name in ["add_numbers", "subtract_numbers", "multiply_numbers", "divide_numbers", "square_number", "cube_number", "square_root", "factorial", "fibonacci"]:
            with self.subTest(tool=name):
                self.assertEqual(view[name]["category"], "math")
                self.assertTrue(view[name]["read_only"])
                self.assertFalse(view[name]["mutating"])
                self.assertFalse(view[name]["external_call"])

    def test_file_local_tools_categorized_correctly(self):
        view = build_ag1_capability_view()
        for name in ["read_file", "list_files", "grep", "glob"]:
            with self.subTest(tool=name):
                self.assertEqual(view[name]["category"], "file_local")
                self.assertTrue(view[name]["read_only"])
                self.assertFalse(view[name]["mutating"])

    def test_unknown_tool_not_in_view(self):
        view = build_ag1_capability_view()
        self.assertNotIn("nonexistent_tool_xyz", view)


class TestCapabilityPromptFormatting(unittest.TestCase):
    """Positive: AG1 prompt lines include enriched metadata."""

    def test_prompt_line_includes_category(self):
        view = build_ag1_capability_view()
        line = format_ag1_capability_prompt_line(view["add_numbers"])
        self.assertIn("category: math", line)

    def test_prompt_line_includes_risk_flags(self):
        view = build_ag1_capability_view()
        line = format_ag1_capability_prompt_line(view["write_file"])
        self.assertIn("risk: mutating, requires_approval", line)

    def test_prompt_line_includes_external_call_flag(self):
        view = build_ag1_capability_view()
        line = format_ag1_capability_prompt_line(view["web_search"])
        self.assertIn("risk: read_only, external_call", line)

    def test_prompt_line_includes_use_when(self):
        view = build_ag1_capability_view()
        line = format_ag1_capability_prompt_line(view["finalize_output"])
        self.assertIn("use when:", line)
        self.assertIn("text-only answers", line)

    def test_prompt_line_includes_do_not_use_when(self):
        view = build_ag1_capability_view()
        line = format_ag1_capability_prompt_line(view["finalize_output"])
        self.assertIn("do not use when:", line)
        self.assertIn("arithmetic or math operations", line)

    def test_full_prompt_includes_all_production_tools(self):
        prompt = build_ag1_capability_prompt()
        for name in ["add_numbers", "write_file", "web_search", "finalize_output", "read_webpage"]:
            with self.subTest(tool=name):
                self.assertIn(name, prompt)

    def test_full_prompt_includes_description(self):
        prompt = build_ag1_capability_prompt()
        self.assertIn("Adds two numbers", prompt)

    def test_prompt_preserves_arg_formatting(self):
        view = build_ag1_capability_view()
        line = format_ag1_capability_prompt_line(view["read_file"])
        self.assertIn('"path"', line)


class TestCapabilityViewDeterminism(unittest.TestCase):
    """Boundary: capability view is deterministic and read-only."""

    def test_deterministic_output(self):
        view1 = build_ag1_capability_view()
        view2 = build_ag1_capability_view()
        self.assertEqual(view1, view2)

    def test_no_tool_execution(self):
        """Building the view must not execute any tool."""
        with patch("system.tool_index.tool_capability_index.json.load") as mock_load, \
             patch("builtins.open", MagicMock()):
            mock_load.return_value = {
                "test_tool": {
                    "inputs": {"x": "number"},
                    "production": True,
                    "description": "A test tool.",
                }
            }
            view = build_ag1_capability_view()
            self.assertIn("test_tool", view)
            # No tool module should have been imported or executed

    def test_no_system_entry_bypass(self):
        """Capability view construction must not import or call system_entry."""
        import system.tool_index.tool_capability_index as tci
        self.assertFalse(
            hasattr(tci, "system_entry"),
            "tool_capability_index should not import system_entry",
        )

    def test_view_is_read_only_snapshot(self):
        view = build_ag1_capability_view()
        # Mutating the returned view should not affect future calls
        view["add_numbers"]["category"] = "hacked"
        view2 = build_ag1_capability_view()
        self.assertEqual(view2["add_numbers"]["category"], "math")


class TestAG1PromptIntegration(unittest.TestCase):
    """Integration: AG1 prompt construction uses capability view correctly."""

    def test_ag1_prompt_contains_enriched_tool_lines(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        # Mock LLM to capture the prompt
        captured_prompts = []
        def mock_execute_llm(provider, prompt, **kwargs):
            captured_prompts.append(prompt)
            return {"status": "success", "result": 'USE_TOOL: add_numbers 1 2'}

        mock_provider = MagicMock()
        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", return_value={"status": "success", "provider": mock_provider}), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", side_effect=mock_execute_llm), \
             patch("system.orchestrator.agents.tool_selection_agent.system_entry", return_value={"status": "success", "result": 3}):
            execute_tool_selection(
                agent={"name": "test", "role": "test", "scope": ["test"]},
                input_data="add 1 and 2",
            )

        self.assertTrue(captured_prompts)
        prompt = captured_prompts[0]
        # Should have enriched metadata
        self.assertIn("category: math", prompt)
        self.assertIn("risk:", prompt)
        self.assertIn("use when:", prompt)

    def test_ag1_prompt_contains_finalize_output_grounding(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        captured_prompts = []
        def mock_execute_llm(provider, prompt, **kwargs):
            captured_prompts.append(prompt)
            return {"status": "success", "result": 'USE_TOOL: finalize_output "hello"'}

        mock_provider = MagicMock()
        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", return_value={"status": "success", "provider": mock_provider}), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", side_effect=mock_execute_llm), \
             patch("system.orchestrator.agents.tool_selection_agent.system_entry", return_value={"status": "success", "result": "hello"}):
            execute_tool_selection(
                agent={"name": "test", "role": "test", "scope": ["test"]},
                input_data="say hello",
            )

        self.assertTrue(captured_prompts)
        prompt = captured_prompts[0]
        self.assertIn("do NOT use for arithmetic", prompt)
        self.assertIn("file reading/writing", prompt)
        self.assertIn("webpage reading/search", prompt)

    def test_same_retry_restricts_to_allowed_tool(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        captured_prompts = []
        def mock_execute_llm(provider, prompt, **kwargs):
            captured_prompts.append(prompt)
            return {"status": "success", "result": 'USE_TOOL: add_numbers 1 2'}

        mock_provider = MagicMock()
        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", return_value={"status": "success", "provider": mock_provider}), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", side_effect=mock_execute_llm), \
             patch("system.orchestrator.agents.tool_selection_agent.system_entry", return_value={"status": "success", "result": 3}):
            result = execute_tool_selection(
                agent={"name": "test", "role": "test", "scope": ["test"]},
                input_data="add 1 and 2",
                context={"allowed_tool": "add_numbers"},
            )

        self.assertTrue(captured_prompts)
        prompt = captured_prompts[0]
        # Should contain add_numbers but NOT write_file
        self.assertIn("add_numbers", prompt)
        self.assertNotIn("write_file", prompt)
        # SAME retry enforcement text should be present
        self.assertIn("SAME RETRY ENFORCEMENT", prompt)

    def test_same_retry_rejects_wrong_tool(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        mock_provider = MagicMock()
        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", return_value={"status": "success", "provider": mock_provider}), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", return_value={"status": "success", "result": 'USE_TOOL: write_file "x" "y"'}), \
             patch("system.orchestrator.agents.tool_selection_agent.system_entry"):
            result = execute_tool_selection(
                agent={"name": "test", "role": "test", "scope": ["test"]},
                input_data="write a file",
                context={"allowed_tool": "add_numbers"},
            )

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "same_retry_wrong_tool")


class TestSummarizationFinalizeOutputPath(unittest.TestCase):
    """PDIAG-006 GUI smoke: summarization step must route to finalize_output."""

    def test_summarization_step_routes_to_finalize_output(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        mock_provider = MagicMock()
        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", return_value={"status": "success", "provider": mock_provider}), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", return_value={"status": "success", "result": 'USE_TOOL: finalize_output "This is a summary."'}), \
             patch("system.orchestrator.agents.tool_selection_agent.system_entry", return_value={"status": "success", "result": "This is a summary."}):
            result = execute_tool_selection(
                agent={"name": "test", "role": "test", "scope": ["test"]},
                input_data="Summarize the result of step_1",
                context={
                    "workflow_id": "wf_smoke",
                    "step_id": "step_2",
                    "dependency_outputs": {
                        "step_1": {"data": "Some webpage content here."}
                    },
                },
            )

        self.assertEqual(result["status"], "success")
        self.assertIn("executed_input", result["result"])
        self.assertTrue(
            result["result"]["executed_input"].startswith("finalize_output"),
            f"Expected finalize_output, got {result['result']['executed_input']}",
        )
        self.assertEqual(result["result"]["execution_result"]["status"], "success")

    def test_plain_text_no_use_tool_wraps_finalize_output(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        mock_provider = MagicMock()
        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", return_value={"status": "success", "provider": mock_provider}), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", return_value={"status": "success", "result": "Here is a plain text summary."}), \
             patch("system.orchestrator.agents.tool_selection_agent.system_entry", return_value={"status": "success", "result": "Here is a plain text summary."}):
            result = execute_tool_selection(
                agent={"name": "test", "role": "test", "scope": ["test"]},
                input_data="Summarize the result of step_1",
                context={
                    "workflow_id": "wf_smoke",
                    "step_id": "step_2",
                    "dependency_outputs": {
                        "step_1": {"data": "Some webpage content here."}
                    },
                },
            )

        self.assertEqual(result["status"], "success")
        self.assertIn("executed_input", result["result"])
        self.assertTrue(
            result["result"]["executed_input"].startswith("USE_TOOL: finalize_output"),
            f"Expected USE_TOOL: finalize_output wrapper, got {result['result']['executed_input']}",
        )

    def test_malformed_tool_call_preserves_executed_input(self):
        """If LLM outputs a malformed USE_TOOL line, executed_input must still be present
        so step_executor can set tool_call for schema validation."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        mock_provider = MagicMock()
        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", return_value={"status": "success", "provider": mock_provider}), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", return_value={"status": "success", "result": 'USE_TOOL: finalize_output "summary" [text_finalization]'}), \
             patch("system.orchestrator.agents.tool_selection_agent.system_entry"):
            result = execute_tool_selection(
                agent={"name": "test", "role": "test", "scope": ["test"]},
                input_data="Summarize the result of step_1",
                context={"workflow_id": "wf_smoke", "step_id": "step_2"},
            )

        self.assertEqual(result["status"], "success")
        self.assertIn("executed_input", result["result"], "executed_input must be present for step_executor schema validation")
        self.assertEqual(result["result"]["execution_result"]["status"], "failure")
        self.assertEqual(result["result"]["execution_result"]["reason"], "invalid_tool_syntax")

    def test_greeting_prompt_routes_to_finalize_output_not_multiply_string(self):
        """PDIAG-006 GUI smoke: greeting should select finalize_output, not multiply_string."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        mock_provider = MagicMock()
        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", return_value={"status": "success", "provider": mock_provider}), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", return_value={"status": "success", "result": 'USE_TOOL: finalize_output "Hello Bryan!"'}), \
             patch("system.orchestrator.agents.tool_selection_agent.system_entry", return_value={"status": "success", "result": "Hello Bryan!"}):
            result = execute_tool_selection(
                agent={"name": "test", "role": "test", "scope": ["test"]},
                input_data="Write a short friendly greeting for Bryan.",
                context={"workflow_id": "wf_greet", "step_id": "step_1"},
            )

        self.assertEqual(result["status"], "success")
        self.assertIn("executed_input", result["result"])
        self.assertTrue(
            result["result"]["executed_input"].startswith("finalize_output"),
            f"Expected finalize_output, got {result['result']['executed_input']}",
        )
        self.assertEqual(result["result"]["execution_result"]["status"], "success")

    def test_multiply_string_capability_metadata_restricts_greetings(self):
        """Verify multiply_string has restrictive do_not_use_when for greetings."""
        from system.tool_index.tool_capability_index import build_ag1_capability_view

        view = build_ag1_capability_view()
        multiply_string_cap = view["multiply_string"]
        
        self.assertIn("greetings", multiply_string_cap["do_not_use_when"])
        self.assertIn("simple text generation", multiply_string_cap["do_not_use_when"])
        self.assertIn("conversational responses", multiply_string_cap["do_not_use_when"])
        self.assertEqual(multiply_string_cap["use_when"], ["repeating a provided string a specified number of times", "string duplication operations"])


class TestExternalCallUserControlUnchanged(unittest.TestCase):
    """Regression: external-call user-control behavior must remain intact."""

    def test_ag1_blocks_read_webpage_without_acceptance(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        from system.orchestrator.user_control import _user_control_registry, _user_control_registry_lock

        # Clear registry
        with _user_control_registry_lock:
            _user_control_registry.clear()

        system_entry_calls = []
        def mock_system_entry(*args, **kwargs):
            system_entry_calls.append(args)
            return {"status": "success", "result": "mocked"}

        mock_provider = MagicMock()
        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", return_value={"status": "success", "provider": mock_provider}), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", return_value={"status": "success", "result": 'USE_TOOL: read_webpage "https://example.com"'}), \
             patch("system.orchestrator.agents.tool_selection_agent.system_entry", mock_system_entry):
            result = execute_tool_selection(
                agent={"name": "test", "role": "test", "scope": ["test"]},
                input_data="read example.com",
                context={"workflow_id": "wf_test", "step_id": "step_1"},
            )

        self.assertEqual(len(system_entry_calls), 0, "system_entry should NOT be called for blocked external tool")
        self.assertEqual(result["result"]["execution_result"]["status"], "blocked")
        self.assertEqual(result["result"]["execution_result"]["reason"], "external_call_risk")

    def test_ag1_allows_read_webpage_with_acceptance(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        from system.orchestrator.user_control import (
            _user_control_registry, _user_control_registry_lock,
            create_user_control_request, get_user_control_request,
        )

        with _user_control_registry_lock:
            _user_control_registry.clear()

        # Create and accept a user control request
        req_result = create_user_control_request(
            workflow_id="wf_test2",
            step_id="step_1",
            requested_action="accept_external_call_risk",
            reason="test",
            metadata={"tool_name": "read_webpage", "destination": "https://example.com"},
        )
        req = get_user_control_request(req_result["request"]["control_id"])
        req.resolve(accepted=True)

        system_entry_calls = []
        def mock_system_entry(*args, **kwargs):
            system_entry_calls.append(args)
            return {"status": "success", "result": "mocked"}

        mock_provider = MagicMock()
        with patch("system.orchestrator.agents.tool_selection_agent.get_llm", return_value={"status": "success", "provider": mock_provider}), \
             patch("system.orchestrator.agents.tool_selection_agent.execute_llm", return_value={"status": "success", "result": 'USE_TOOL: read_webpage "https://example.com"'}), \
             patch("system.orchestrator.agents.tool_selection_agent.system_entry", mock_system_entry):
            result = execute_tool_selection(
                agent={"name": "test", "role": "test", "scope": ["test"]},
                input_data="read example.com",
                context={"workflow_id": "wf_test2", "step_id": "step_1"},
            )

        self.assertEqual(len(system_entry_calls), 1, "system_entry SHOULD be called when request is accepted")
        self.assertIsNone(result["result"].get("_user_control_blocked"))


class TestAG1RejectionPaths(unittest.TestCase):
    """Negative: AG1 still rejects unknown and non-production tools."""

    def test_ag1_rejects_unknown_tool(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "test", "role": "test", "scope": ["test"]},
            input_data='USE_TOOL: nonexistent_tool_xyz',
        )
        self.assertEqual(result["status"], "success")  # Wrapper success
        self.assertEqual(result["result"]["execution_result"]["status"], "failure")
        self.assertEqual(result["result"]["execution_result"]["reason"], "unknown_tool")

    def test_ag1_rejects_non_production_tool(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "test", "role": "test", "scope": ["test"]},
            input_data='USE_TOOL: bad_add 1 2',
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["execution_result"]["status"], "failure")
        self.assertEqual(result["result"]["execution_result"]["reason"], "non_production_tool")


if __name__ == "__main__":
    unittest.main(verbosity=2)

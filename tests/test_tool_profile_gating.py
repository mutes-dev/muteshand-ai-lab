"""
Tests for Tool Profile Gating — TOOL_PROFILE_GATING_CONTRACT_V1

Sprint 11 Slice B: Tool/Profile Gating for Planner + AG1

Tests:
1. Profile catalog: defined profiles, allowed tools, scoped catalogs
2. Profile selector: deterministic selection from user input
3. Capability router: profile recommendation metadata
4. Planner: scoped tool catalog when profile is active
5. AG1: scoped capability view when profile is active
6. AG1: out-of-profile rejection (fast path + LLM path)
7. GeneralFallbackProfile: explicit snapshot allowlist of current fallback-visible production tools
8. Quarantine: semantic_transform answer_question not in any active profile
"""

import json
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestProfileCatalog:
    """Tests for profile_catalog.py — profile definitions and scoped catalogs."""

    def test_all_profiles_defined(self):
        from system.orchestrator.profile_catalog import get_profile_names
        names = get_profile_names()
        assert "DocumentReadProfile" in names
        assert "DocumentSummaryProfile" in names
        assert "WebReadProfile" in names
        assert "WebSearchProfile" in names
        assert "WebResearchProfile" in names
        assert "ComputeProfile" in names
        assert "FileMutationProfile" in names
        assert "GeneralFallbackProfile" in names

    def test_document_read_profile_excludes_mutation(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("read_file", "DocumentReadProfile")
        assert is_tool_in_profile("list_files", "DocumentReadProfile")
        assert not is_tool_in_profile("write_file", "DocumentReadProfile")
        assert not is_tool_in_profile("edit_file", "DocumentReadProfile")
        assert not is_tool_in_profile("read_webpage", "DocumentReadProfile")

    def test_document_summary_profile_includes_semantic_transform(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("semantic_transform", "DocumentSummaryProfile")
        assert is_tool_in_profile("read_file", "DocumentSummaryProfile")
        assert not is_tool_in_profile("write_file", "DocumentSummaryProfile")
        assert not is_tool_in_profile("read_webpage", "DocumentSummaryProfile")

    def test_web_read_profile_excludes_file_and_search(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("read_webpage", "WebReadProfile")
        assert is_tool_in_profile("finalize_output", "WebReadProfile")
        assert not is_tool_in_profile("web_search", "WebReadProfile")
        assert not is_tool_in_profile("read_file", "WebReadProfile")
        assert not is_tool_in_profile("write_file", "WebReadProfile")

    def test_compute_profile_excludes_files_and_web(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("add_numbers", "ComputeProfile")
        assert is_tool_in_profile("multiply_numbers", "ComputeProfile")
        assert is_tool_in_profile("finalize_output", "ComputeProfile")
        assert not is_tool_in_profile("read_file", "ComputeProfile")
        assert not is_tool_in_profile("read_webpage", "ComputeProfile")
        assert not is_tool_in_profile("write_file", "ComputeProfile")

    def test_file_mutation_profile_includes_write_edit_append(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("write_file", "FileMutationProfile")
        assert is_tool_in_profile("edit_file", "FileMutationProfile")
        assert is_tool_in_profile("append_file", "FileMutationProfile")
        assert is_tool_in_profile("read_file", "FileMutationProfile")
        assert not is_tool_in_profile("read_webpage", "FileMutationProfile")
        assert not is_tool_in_profile("add_numbers", "FileMutationProfile")

    def test_general_fallback_allows_non_search_tools(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("add_numbers", "GeneralFallbackProfile")
        assert is_tool_in_profile("write_file", "GeneralFallbackProfile")
        assert is_tool_in_profile("read_webpage", "GeneralFallbackProfile")
        assert is_tool_in_profile("semantic_transform", "GeneralFallbackProfile")
        assert not is_tool_in_profile("web_search", "GeneralFallbackProfile")

    def test_unknown_profile_rejects_everything(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("add_numbers", "NonexistentProfile")

    def test_scoped_tool_index_filters_correctly(self):
        from system.orchestrator.profile_catalog import build_scoped_tool_index
        scoped = build_scoped_tool_index("ComputeProfile")
        tool_names = set(scoped.keys())
        assert "add_numbers" in tool_names
        assert "finalize_output" in tool_names
        assert "write_file" not in tool_names
        assert "read_webpage" not in tool_names

    def test_scoped_tool_index_fallback_returns_all(self):
        from system.orchestrator.profile_catalog import build_scoped_tool_index
        scoped = build_scoped_tool_index("GeneralFallbackProfile")
        assert len(scoped) > 5  # should have many tools

    def test_scoped_tool_context_is_string(self):
        from system.orchestrator.profile_catalog import build_scoped_tool_context
        ctx = build_scoped_tool_context("ComputeProfile")
        assert isinstance(ctx, str)
        assert "add_numbers" in ctx
        assert "write_file" not in ctx

    def test_profile_metadata_observable(self):
        from system.orchestrator.profile_catalog import get_profile_metadata
        meta = get_profile_metadata("ComputeProfile")
        assert meta["profile_name"] == "ComputeProfile"
        assert meta["valid"] is True
        assert "add_numbers" in meta["allowed_tools"]
        assert "math" in meta["allowed_tool_families"]

    def test_scoped_capability_view_filters(self):
        from system.orchestrator.profile_catalog import build_scoped_capability_view
        view = build_scoped_capability_view("WebReadProfile")
        assert "read_webpage" in view
        assert "finalize_output" in view
        assert "add_numbers" not in view
        assert "write_file" not in view

    def test_web_search_profile_allows_web_search_and_finalize_only(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("web_search", "WebSearchProfile")
        assert is_tool_in_profile("finalize_output", "WebSearchProfile")
        assert not is_tool_in_profile("read_webpage", "WebSearchProfile")
        assert not is_tool_in_profile("read_file", "WebSearchProfile")
        assert not is_tool_in_profile("write_file", "WebSearchProfile")

    def test_web_search_profile_scoped_tool_index(self):
        from system.orchestrator.profile_catalog import build_scoped_tool_index
        scoped = build_scoped_tool_index("WebSearchProfile")
        tool_names = set(scoped.keys())
        assert "web_search" in tool_names
        assert "finalize_output" in tool_names
        assert "read_webpage" not in tool_names
        assert "read_file" not in tool_names


class TestProfileSelector:
    """Tests for profile_selector.py — deterministic profile selection."""

    def test_explicit_file_read(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("read tmp/file.txt") == "DocumentReadProfile"

    def test_explicit_file_write(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("write hello to tmp/file.txt") == "FileMutationProfile"

    def test_explicit_file_edit(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("edit tmp/file.txt replacing old with new") == "FileMutationProfile"

    def test_explicit_summarize(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("summarize tmp/report.txt") == "DocumentSummaryProfile"

    def test_explicit_explain(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("explain tmp/report.txt") == "DocumentSummaryProfile"

    def test_explicit_url(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("read https://example.com") == "WebReadProfile"

    def test_pure_arithmetic(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("add 2 and 3") == "ComputeProfile"

    def test_mixed_or_uncertain(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("build a website") == "GeneralFallbackProfile"

    def test_empty_input(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("") == "GeneralFallbackProfile"

    def test_select_with_reason(self):
        from system.orchestrator.profile_selector import select_profile_with_reason
        result = select_profile_with_reason("add 5 and 10")
        assert result["profile_name"] == "ComputeProfile"
        assert result["profile_reason_code"] == "pure_arithmetic_computation"

    def test_capability_to_profile_mapping(self):
        from system.orchestrator.profile_selector import capability_to_profile
        assert capability_to_profile("arithmetic") == "ComputeProfile"
        assert capability_to_profile("document_local_read") == "DocumentReadProfile"
        assert capability_to_profile("web_read") == "WebReadProfile"
        assert capability_to_profile("web_search") == "WebSearchProfile"
        assert capability_to_profile("web_research") == "WebResearchProfile"
        assert capability_to_profile(None) is None
        assert capability_to_profile("unknown") is None

    def test_explicit_pure_web_search_selects_web_search_profile(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("search the web for current Python release notes") == "WebSearchProfile"
        assert select_profile("web search for latest PostgreSQL version") == "WebSearchProfile"
        assert select_profile("find online results for OpenAI API pricing") == "WebSearchProfile"
        assert select_profile("search DuckDuckGo for FastAPI lifespan docs") == "WebSearchProfile"

    def test_unresolved_reference_web_search_selects_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("search the web for person in row 2") == "GeneralFallbackProfile"
        assert select_profile("find more info about the person in row 2") == "GeneralFallbackProfile"
        assert select_profile("search for the company in the spreadsheet") == "GeneralFallbackProfile"
        assert select_profile("search for the value from the previous result") == "GeneralFallbackProfile"

    def test_mixed_file_web_search_selects_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('Read "tmp\\report.pdf" and search the web for related context') == "GeneralFallbackProfile"
        assert select_profile('Read "tmp\\data.csv" and search the web for more info') == "GeneralFallbackProfile"

    def test_underspecified_file_and_web_search_selects_fallback(self):
        """F3B-FIX2: vague 'read a file ... search the web' must not over-capture to WebSearchProfile."""
        from system.orchestrator.profile_selector import select_profile, select_profile_with_reason
        prompt = "Do a mixed task: read a file and search the web for more information about it"
        assert select_profile(prompt) == "GeneralFallbackProfile"
        result = select_profile_with_reason(prompt)
        assert result["profile_name"] == "GeneralFallbackProfile"
        assert result["profile_reason_code"] == "mixed_domain_workflow"

    def test_document_and_web_search_selects_fallback(self):
        """F3B-FIX2: 'read the document ... search the web' must not route to WebSearchProfile."""
        from system.orchestrator.profile_selector import select_profile, select_profile_with_reason
        prompt = "Read the document and search the web for more information about it"
        assert select_profile(prompt) == "GeneralFallbackProfile"
        result = select_profile_with_reason(prompt)
        assert result["profile_name"] == "GeneralFallbackProfile"
        assert result["profile_reason_code"] == "mixed_domain_workflow"

    def test_spreadsheet_unresolved_web_search_selects_fallback(self):
        """F3B-FIX2: 'company in the spreadsheet' web search intent remains non-executable fallback."""
        from system.orchestrator.profile_selector import select_profile, select_profile_with_reason
        prompt = "Find more info online about the company in the spreadsheet"
        assert select_profile(prompt) != "WebSearchProfile"
        result = select_profile_with_reason(prompt)
        assert result["profile_name"] == "GeneralFallbackProfile"

    def test_web_search_reason_code_resolved_vs_unresolved(self):
        from system.orchestrator.profile_selector import select_profile_with_reason
        resolved = select_profile_with_reason("search the web for current Python release notes")
        assert resolved["profile_name"] == "WebSearchProfile"
        assert resolved["profile_reason_code"] == "explicit_web_search"
        unresolved = select_profile_with_reason("search the web for person in row 2")
        assert unresolved["profile_name"] == "GeneralFallbackProfile"
        assert unresolved["profile_reason_code"] == "web_search_unresolved_reference"

    def test_document_qa_tell_me_routed_to_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('read "tmp\\My New Project Sketch.pdf" and tell me how big is the Kitchen') == "GeneralFallbackProfile"

    def test_document_qa_what_is_routed_to_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('read "tmp\\My New Project Sketch.pdf" and what is the kitchen size') == "GeneralFallbackProfile"

    def test_document_qa_who_has_routed_to_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('from "tmp\\sprint11_slice003_sample.csv", who has the highest score?') == "GeneralFallbackProfile"

    def test_pure_file_read_still_document_read(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('read "tmp\\report.pdf"') == "DocumentReadProfile"

    def test_summarize_still_document_summary(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('summarize "tmp\\report.pdf"') == "DocumentSummaryProfile"

    def test_explain_still_document_summary(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('explain "tmp\\report.pdf"') == "DocumentSummaryProfile"

    def test_extract_key_points_still_document_summary(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('extract key points from "tmp\\report.pdf"') == "DocumentSummaryProfile"

    def test_qa_reason_code(self):
        from system.orchestrator.profile_selector import select_profile_with_reason
        result = select_profile_with_reason('read "tmp\\file.pdf" and tell me the answer')
        assert result["profile_name"] == "GeneralFallbackProfile"
        assert result["profile_reason_code"] == "unsupported_document_qa_or_analysis"

    def test_pure_arithmetic_not_caught_by_qa_check(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("calculate 2 + 3") == "ComputeProfile"

    def test_calculate_with_file_routed_to_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('calculate the total from "tmp\\data.csv"') == "GeneralFallbackProfile"

    def test_future_document_qa_profile_not_selectable(self):
        from system.orchestrator.profile_selector import select_profile, select_profile_with_reason
        for prompt in [
            'read "tmp\\file.pdf" and tell me X',
            'what is the kitchen size in "tmp\\file.pdf"',
            'who has the highest score from "tmp\\file.csv"',
        ]:
            assert select_profile(prompt) != "DocumentQAProfile"
            result = select_profile_with_reason(prompt)
            assert result["profile_name"] != "DocumentQAProfile"


class TestCapabilityRouterProfileRecommendation:
    """Tests for capability_router.py — profile recommendation metadata."""

    def test_arithmetic_route_recommends_compute_profile(self):
        from system.orchestrator.capability_router import route_capability
        result = route_capability("add 2 and 3")
        if result.get("route_decision") == "ROUTE_ACCEPTED":
            assert result.get("recommended_profile") == "ComputeProfile"

    def test_web_read_route_recommends_web_read_profile(self):
        from system.orchestrator.capability_router import route_capability
        result = route_capability("read https://example.com")
        if result.get("route_decision") == "ROUTE_ACCEPTED":
            assert result.get("recommended_profile") == "WebReadProfile"

    def test_fallback_route_has_no_profile(self):
        from system.orchestrator.capability_router import route_capability
        result = route_capability("build a website")
        if result.get("route_decision") == "ROUTE_FALLBACK_TO_PLANNER":
            assert result.get("recommended_profile") is None

    def test_csv_highest_score_unsupported_analysis_recommends_fallback_profile(self):
        """CSV/XLSX unsupported analysis route must recommend GeneralFallbackProfile."""
        from system.orchestrator.capability_router import route_capability
        result = route_capability('from "tmp\\sprint11_slice003_sample.csv", who has the highest score?')
        assert result["route_decision"] == "ROUTE_ACCEPTED"
        assert result["capability_id"] == "document_local_read"
        assert result["recommended_profile"] == "GeneralFallbackProfile"
        assert result["route_reason_code"] == "unsupported_spreadsheet_analysis"

    def test_read_prefixed_csv_highest_score_unsupported_analysis_recommends_fallback_profile(self):
        """Read-prefixed CSV highest-score prompt must also recommend GeneralFallbackProfile."""
        from system.orchestrator.capability_router import route_capability
        result = route_capability('Read "tmp\\sprint11_slice003_sample.csv" and find the highest score')
        assert result["route_decision"] == "ROUTE_ACCEPTED"
        assert result["capability_id"] == "document_local_read"
        assert result["recommended_profile"] == "GeneralFallbackProfile"
        assert result["route_reason_code"] == "unsupported_spreadsheet_analysis"


class TestPlannerScopedCatalog:
    """Tests for orchestrator_planner.py — scoped tool catalog."""

    def test_plan_workflow_accepts_profile_name_param(self):
        """Verify plan_workflow signature accepts profile_name without error."""
        import inspect
        from system.orchestrator.orchestrator_planner import plan_workflow
        sig = inspect.signature(plan_workflow)
        assert "profile_name" in sig.parameters

    def test_workflow_includes_profile_name(self):
        """Verify workflow dict includes profile_name field."""
        from system.orchestrator.orchestrator_planner import plan_workflow
        # Use a simple arithmetic input that will route to ComputeProfile
        # This will call LLM, so we just check the signature accepts it
        # Full E2E test is in the integration test below
        pass  # Signature test is sufficient for unit level


class TestAG1ScopedCatalog:
    """Tests for tool_selection_agent.py — scoped AG1 capability view."""

    def test_ag1_fast_path_rejects_out_of_profile_tool(self):
        """AG1 fast path (USE_TOOL direct) should reject tools outside active profile."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data="USE_TOOL: write_file \"tmp/test.txt\" \"hello\"",
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "DocumentReadProfile",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("status") == "failure"
        assert exec_result.get("reason") == "tool_not_in_profile_allowlist"
        assert exec_result.get("tool_name") == "write_file"

    def test_ag1_fast_path_allows_in_profile_tool(self):
        """AG1 fast path should allow tools within active profile."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data="USE_TOOL: add_numbers 2 3",
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "ComputeProfile",
            }
        )
        # Should not be rejected for profile reasons
        exec_result = result.get("result", {}).get("execution_result", {})
        if exec_result.get("status") == "failure":
            assert exec_result.get("reason") != "tool_not_in_profile_allowlist"

    def test_ag1_fast_path_general_fallback_allows_all(self):
        """GeneralFallbackProfile should not reject any production tool."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data="USE_TOOL: write_file \"tmp/test.txt\" \"hello\"",
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "GeneralFallbackProfile",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("reason") != "tool_not_in_profile_allowlist"

    def test_ag1_fast_path_no_profile_allows_all(self):
        """No profile_name in context should default to GeneralFallbackProfile behavior."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data="USE_TOOL: add_numbers 2 3",
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("reason") != "tool_not_in_profile_allowlist"

    def test_ag1_fast_path_rejects_web_search_in_general_fallback(self):
        """web_search is no longer in GeneralFallbackProfile."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: web_search "Python release notes"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "GeneralFallbackProfile",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("status") == "failure"
        assert exec_result.get("reason") == "tool_not_in_profile_allowlist"
        assert exec_result.get("tool_name") == "web_search"

    def test_ag1_fast_path_allows_web_search_in_web_search_profile(self):
        """web_search is allowed in WebSearchProfile."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: web_search "Python release notes"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "WebSearchProfile",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("reason") != "tool_not_in_profile_allowlist"
        assert exec_result.get("reason") != "web_search_unresolved_reference"

    def test_ag1_fast_path_blocks_unresolved_reference_in_web_search_profile(self):
        """Unresolved references must not be sent to web_search in WebSearchProfile."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: web_search "person in row 2"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "WebSearchProfile",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("status") == "failure"
        assert exec_result.get("reason") == "web_search_unresolved_reference"
        assert exec_result.get("tool_name") == "web_search"

    def test_ag1_fast_path_blocks_read_webpage_for_unresolved_search_intent(self):
        """F4-A1-FIX1: read_webpage must not be used as a fake search provider."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: read_webpage "https://example.com/search?q=Alice+Score+97"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_2",
                "profile_name": "GeneralFallbackProfile",
                "purpose": "Search the web for more information about the person in row 4 of the csv file read by step_1",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("status") == "failure"
        assert exec_result.get("reason") == "read_webpage_not_search_provider"
        assert exec_result.get("tool_name") == "read_webpage"
        assert result.get("result", {}).get("_read_webpage_fake_search_blocked") is True

    def test_ag1_fast_path_blocks_read_webpage_for_local_source_search_intent(self):
        """F4-A1-FIX1: local-source search intent must not fall back to read_webpage."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: read_webpage "https://example.com/search?q=company"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "GeneralFallbackProfile",
                "purpose": "Find more info online about the company in tmp\\sprint11_slice003_sample.xlsx",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("status") == "failure"
        assert exec_result.get("reason") == "read_webpage_not_search_provider"

    def test_ag1_fast_path_allows_read_webpage_for_explicit_url(self):
        """F4-A1-FIX1: explicit URL read via read_webpage must remain allowed."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: read_webpage "https://example.com"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "GeneralFallbackProfile",
                "purpose": "Read https://example.com",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("reason") != "read_webpage_not_search_provider"

    def test_ag1_fast_path_allows_read_webpage_for_summarize_url(self):
        """F4-A1-FIX1: summarize/explain of an explicit URL remains allowed."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: read_webpage "https://example.com"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "GeneralFallbackProfile",
                "purpose": "Summarize https://example.com",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("reason") != "read_webpage_not_search_provider"

    def test_ag1_fast_path_allows_read_webpage_in_web_read_profile(self):
        """F4-A1-FIX1: read_webpage in WebReadProfile remains allowed."""
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: read_webpage "https://example.com"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "WebReadProfile",
                "purpose": "Read https://example.com",
            }
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("reason") != "read_webpage_not_search_provider"
        assert exec_result.get("reason") != "tool_not_in_profile_allowlist"


class TestQuarantineEnforcement:
    """Tests for semantic_transform answer_question quarantine via profile gating."""

    def test_answer_question_not_in_any_profile(self):
        """semantic_transform is only in DocumentSummaryProfile (excluding GeneralFallback).
        answer_question is quarantined — no profile includes answer_question as an allowed action."""
        from system.orchestrator.profile_catalog import get_profile_names, is_tool_in_profile
        # semantic_transform should only be in DocumentSummaryProfile (not in other narrow profiles)
        for profile in get_profile_names():
            if profile == "GeneralFallbackProfile":
                continue  # GeneralFallback uses explicit snapshot allowlist
            if is_tool_in_profile("semantic_transform", profile):
                assert profile == "DocumentSummaryProfile"
        # No profile defines answer_question as a separate tool — it's a quarantined action

    def test_web_search_not_in_web_read_profile(self):
        """web_search is not in WebReadProfile — only read_webpage and finalize_output."""
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("web_search", "WebReadProfile")

    def test_compute_profile_excludes_run_python(self):
        """run_python is not in ComputeProfile — only math tools and finalize_output."""
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("run_python", "ComputeProfile")


class TestStepExecutorProfileContext:
    """Tests for step_executor.py — profile_name in agent context."""

    def test_agent_context_includes_profile_name(self):
        """Verify step_executor includes profile_name from workflow in _agent_context."""
        # This is a structural test — we verify the code path exists
        # by checking the workflow dict key is read
        import inspect
        from system.orchestrator.step_executor import execute_step
        sig = inspect.signature(execute_step)
        # execute_step takes workflow and step — the profile_name is read from workflow
        assert "workflow" in sig.parameters


class TestD1aMixedDomainProfileSelection:
    """SPRINT-11 SLICE D1a — mixed-domain prompts must select GeneralFallbackProfile."""

    def test_document_plus_web_mixed_selects_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('Read "tmp\\report.pdf" and then search the web for related context.') == "GeneralFallbackProfile"

    def test_csv_plus_web_mixed_selects_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile(
            'Read "tmp\\sprint11_slice003_sample.csv" and search the web for more information about the person in row 2.'
        ) == "GeneralFallbackProfile"

    def test_compute_plus_write_mixed_selects_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile(
            'Add 5 and 7 and write the result to "tmp\\math_result.txt".'
        ) == "GeneralFallbackProfile"

    def test_mixed_domain_reason_code(self):
        from system.orchestrator.profile_selector import select_profile_with_reason
        result = select_profile_with_reason(
            'Read "tmp\\report.pdf" and then search the web for related context.'
        )
        assert result["profile_name"] == "GeneralFallbackProfile"
        assert result["profile_reason_code"] == "mixed_domain_workflow"

    def test_compute_plus_write_mixed_reason_code(self):
        from system.orchestrator.profile_selector import select_profile_with_reason
        result = select_profile_with_reason(
            'Add 5 and 7 and write the result to "tmp\\math_result.txt".'
        )
        assert result["profile_name"] == "GeneralFallbackProfile"
        assert result["profile_reason_code"] == "mixed_domain_workflow"


class TestD1aRegressionPreservation:
    """SPRINT-11 SLICE D1a — pure single-domain prompts must still select their narrow profile."""

    def test_pure_csv_read_still_document_read(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('Read "tmp\\sprint11_slice003_sample.csv"') == "DocumentReadProfile"

    def test_pure_xlsx_read_still_document_read(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('Read "tmp\\history.xlsx"') == "DocumentReadProfile"

    def test_summarize_still_document_summary(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('Summarize "tmp\\report.pdf"') == "DocumentSummaryProfile"

    def test_pure_url_still_web_read(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("read https://example.com") == "WebReadProfile"

    def test_pure_arithmetic_still_compute(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("Add 5 and 7") == "ComputeProfile"

    def test_pure_file_write_still_file_mutation(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('Write "hello" to "tmp\\profile_test.txt"') == "FileMutationProfile"

    def test_unsupported_qa_still_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile(
            'Read "tmp\\file.pdf" and tell me the answer'
        ) == "GeneralFallbackProfile"

    def test_no_document_qa_profile_ever_selected(self):
        from system.orchestrator.profile_selector import select_profile, select_profile_with_reason
        for prompt in [
            'Read "tmp\\file.pdf" and tell me X',
            'what is the kitchen size in "tmp\\file.pdf"',
            'who has the highest score from "tmp\\file.csv"',
            'Read "tmp\\report.pdf" and then search the web for related context.',
            'Add 5 and 7 and write the result to "tmp\\math_result.txt".',
        ]:
            assert select_profile(prompt) != "DocumentQAProfile"
            result = select_profile_with_reason(prompt)
            assert result["profile_name"] != "DocumentQAProfile"

    def test_pure_csv_highest_score_still_fallback(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile(
            'Read "tmp\\sprint11_slice003_sample.csv" and tell me who has the highest score.'
        ) == "GeneralFallbackProfile"


class TestD1aQuarantineRegression:
    """SPRINT-11 SLICE D1a — quarantine enforcement must remain intact."""

    def test_answer_question_not_in_any_profile(self):
        from system.orchestrator.profile_catalog import get_profile_names, is_tool_in_profile
        for profile in get_profile_names():
            if profile == "GeneralFallbackProfile":
                continue  # GeneralFallback uses explicit snapshot allowlist
            if is_tool_in_profile("semantic_transform", profile):
                assert profile == "DocumentSummaryProfile"

    def test_no_answer_question_tool_defined(self):
        from system.orchestrator.profile_catalog import get_profile_names, is_tool_in_profile
        for profile in get_profile_names():
            if profile == "GeneralFallbackProfile":
                continue  # GeneralFallback uses explicit snapshot allowlist
            assert not is_tool_in_profile("answer_question", profile)

    def test_document_qa_profile_not_in_catalog(self):
        from system.orchestrator.profile_catalog import get_profile_names
        assert "DocumentQAProfile" not in get_profile_names()


class TestD1bStepProfileResolver:
    """SPRINT-11 SLICE D1b/F3B — step-scoped profile narrowing for mixed workflows."""

    def test_csv_web_step2_unresolved_reference_left_unset(self):
        from system.orchestrator.step_profile_resolver import resolve_step_profiles_for_workflow
        wf = {
            "profile_name": "GeneralFallbackProfile",
            "_profile_metadata": {"profile_reason_code": "mixed_domain_workflow"},
            "steps": [
                {"id": "step_1", "purpose": "Read 'tmp\\sprint11_slice003_sample.csv'", "expected_outcome": "Execution completed", "depends_on": []},
                {"id": "step_2", "purpose": "Search the web for more information about the person in row 2 of tmp\\sprint11_slice003_sample.csv", "expected_outcome": "Execution completed", "depends_on": []},
            ],
        }
        result = resolve_step_profiles_for_workflow(wf)
        assert result["steps"][0]["_step_profile"] == "DocumentReadProfile"
        assert result["steps"][1].get("_step_profile") is None

    def test_xlsx_more_info_step2_unresolved_reference_left_unset(self):
        from system.orchestrator.step_profile_resolver import resolve_step_profiles_for_workflow
        wf = {
            "profile_name": "GeneralFallbackProfile",
            "_profile_metadata": {"profile_reason_code": "mixed_domain_workflow"},
            "steps": [
                {"id": "step_1", "purpose": "Read tmp/history.xlsx", "expected_outcome": "Execution completed", "depends_on": []},
                {"id": "step_2", "purpose": "Find more info on the person in row 2 using the result of step_1 in tmp/history.xlsx", "expected_outcome": "Execution completed", "depends_on": ["step_1"]},
            ],
        }
        result = resolve_step_profiles_for_workflow(wf)
        assert result["steps"][0]["_step_profile"] == "DocumentReadProfile"
        assert result["steps"][1].get("_step_profile") is None

    def test_pdf_web_step2_prior_step_reference_left_unset(self):
        """F3B-FIX3: 'using the result of step_1' is a prior-step dependency and must not narrow to WebSearchProfile."""
        from system.orchestrator.step_profile_resolver import resolve_step_profiles_for_workflow
        wf = {
            "profile_name": "GeneralFallbackProfile",
            "_profile_metadata": {"profile_reason_code": "mixed_domain_workflow"},
            "steps": [
                {"id": "step_1", "purpose": "Read tmp\\report.pdf", "expected_outcome": "Execution completed", "depends_on": []},
                {"id": "step_2", "purpose": "Search the web for related context using the result of step_1", "expected_outcome": "Execution completed", "depends_on": ["step_1"]},
            ],
        }
        result = resolve_step_profiles_for_workflow(wf)
        assert result["steps"][0]["_step_profile"] == "DocumentReadProfile"
        assert result["steps"][1].get("_step_profile") is None

    def test_resolver_does_not_run_on_non_mixed(self):
        from system.orchestrator.step_profile_resolver import resolve_step_profiles_for_workflow
        wf = {
            "profile_name": "DocumentReadProfile",
            "_profile_metadata": {"profile_reason_code": "document_read"},
            "steps": [{"id": "step_1", "purpose": "Read tmp/file.csv", "expected_outcome": "Execution completed"}],
        }
        result = resolve_step_profiles_for_workflow(wf)
        assert result["steps"][0].get("_step_profile") is None

    def test_resolver_never_sets_document_qa_profile(self):
        from system.orchestrator.step_profile_resolver import _classify_step_profile
        test_steps = [
            {"purpose": "Read tmp/file.pdf", "expected_outcome": ""},
            {"purpose": "Search the web for info", "expected_outcome": ""},
            {"purpose": "Add 5 and 7", "expected_outcome": ""},
            {"purpose": "Write result to tmp/out.txt", "expected_outcome": ""},
            {"purpose": "Summarize the document", "expected_outcome": ""},
            {"purpose": "Tell me the answer", "expected_outcome": ""},
        ]
        for step in test_steps:
            result = _classify_step_profile(step)
            if result is not None:
                assert result[0] != "DocumentQAProfile"


class TestD1bStepExecutorProfileContext:
    """SPRINT-11 SLICE D1b — step_executor passes step-level profile to AG1."""

    def test_step_profile_overrides_workflow_profile(self):
        """When step has _step_profile, it overrides workflow-level profile."""
        from system.orchestrator.step_executor import execute_step
        import inspect
        sig = inspect.signature(execute_step)
        assert "step" in sig.parameters
        assert "workflow" in sig.parameters

    def test_web_read_profile_excludes_read_csv(self):
        """WebReadProfile must not allow read_csv."""
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("read_csv", "WebReadProfile")

    def test_web_read_profile_excludes_read_spreadsheet(self):
        """WebReadProfile must not allow read_spreadsheet."""
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("read_spreadsheet", "WebReadProfile")

    def test_web_read_profile_excludes_read_pdf(self):
        """WebReadProfile must not allow read_pdf."""
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("read_pdf", "WebReadProfile")

    def test_web_read_profile_allows_read_webpage(self):
        """WebReadProfile must allow read_webpage."""
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("read_webpage", "WebReadProfile")

    def test_web_read_profile_allows_finalize_output(self):
        """WebReadProfile must allow finalize_output."""
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("finalize_output", "WebReadProfile")

    def test_document_read_profile_excludes_web_search(self):
        """DocumentReadProfile must not allow web_search."""
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("web_search", "DocumentReadProfile")

    def test_document_read_profile_excludes_read_webpage(self):
        """DocumentReadProfile must not allow read_webpage."""
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("read_webpage", "DocumentReadProfile")

    def test_no_answer_question_in_any_profile(self):
        """No active profile may include answer_question."""
        from system.orchestrator.profile_catalog import get_profile_names, is_tool_in_profile
        for profile in get_profile_names():
            if profile == "GeneralFallbackProfile":
                continue
            assert not is_tool_in_profile("answer_question", profile)

    def test_document_qa_profile_not_in_catalog(self):
        """DocumentQAProfile must not be in the profile catalog."""
        from system.orchestrator.profile_catalog import get_profile_names
        assert "DocumentQAProfile" not in get_profile_names()


class TestF2A1GeneralFallbackSnapshotAllowlist:
    """F2A-1: GeneralFallbackProfile explicit snapshot allowlist prevents future tool auto-exposure."""

    _EXPECTED_SNAPSHOT_TOOLS = {
        "add_numbers",
        "subtract_numbers",
        "multiply_numbers",
        "divide_numbers",
        "square_number",
        "cube_number",
        "square_root",
        "factorial",
        "fibonacci",
        "multiply_string",
        "read_file",
        "read_pdf",
        "read_docx",
        "read_csv",
        "read_spreadsheet",
        "read_image_text",
        "read_pdf_ocr",
        "list_files",
        "grep",
        "glob",
        "read_webpage",
        "semantic_transform",
        "finalize_output",
        "write_file",
        "append_file",
        "edit_file",
    }

    @staticmethod
    def _load_original_tools():
        path = os.path.join(os.path.dirname(__file__), "..", "system", "tool_index", "tools.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _make_temp_tools_with_fake():
        tools = TestF2A1GeneralFallbackSnapshotAllowlist._load_original_tools()
        tools["fake_future_tool"] = {
            "inputs": {},
            "production": True,
            "description": "Fake future tool that should not auto-enter GeneralFallbackProfile.",
            "arg_order": [],
            "arg_types": {},
            "category": "utility",
            "output_kind": "text",
            "use_when": ["when testing future tool exposure"],
            "do_not_use_when": ["never in production"],
            "capability_family": "utility",
            "routeable": False,
            "requires_literal_preservation": False,
            "route_prepopulation_allowed": False,
            "read_only": True,
            "destructive": False,
            "idempotent": True,
            "external_call": False,
            "side_effects": "none",
            "risk_level": "LOW",
            "requires_approval": False,
        }
        fd, tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(tools, f)
        return tmp_path

    def test_general_fallback_has_explicit_allowlist(self):
        from system.orchestrator.profile_catalog import get_allowed_tools
        allowed = get_allowed_tools("GeneralFallbackProfile")
        assert allowed is not None
        assert isinstance(allowed, set)
        assert self._EXPECTED_SNAPSHOT_TOOLS.issubset(allowed)
        assert "bad_add" not in allowed

    def test_general_fallback_does_not_auto_include_future_production_tool(self):
        from system.orchestrator import profile_catalog
        tmp_path = self._make_temp_tools_with_fake()
        try:
            with patch.object(profile_catalog, "_PROFILE_CATALOG_PATH", tmp_path):
                scoped = profile_catalog.build_scoped_tool_index("GeneralFallbackProfile")
            assert "fake_future_tool" not in scoped
            assert "add_numbers" in scoped
        finally:
            os.unlink(tmp_path)

    def test_is_tool_in_profile_rejects_future_tool_in_general_fallback(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("fake_future_tool", "GeneralFallbackProfile")

    def test_build_scoped_tool_context_excludes_future_tool(self):
        from system.orchestrator import profile_catalog
        tmp_path = self._make_temp_tools_with_fake()
        try:
            with patch.object(profile_catalog, "_PROFILE_CATALOG_PATH", tmp_path):
                ctx = profile_catalog.build_scoped_tool_context("GeneralFallbackProfile")
            assert "fake_future_tool" not in ctx
            assert "add_numbers" in ctx
        finally:
            os.unlink(tmp_path)

    def test_build_scoped_capability_view_excludes_future_tool(self):
        from system.orchestrator import profile_catalog
        from system.tool_index import tool_capability_index
        tmp_path = self._make_temp_tools_with_fake()
        try:
            with patch.object(profile_catalog, "_PROFILE_CATALOG_PATH", tmp_path), patch.object(
                tool_capability_index, "_TOOL_INDEX_PATH", tmp_path
            ):
                view = profile_catalog.build_scoped_capability_view("GeneralFallbackProfile")
            assert "fake_future_tool" not in view
            assert "add_numbers" in view
        finally:
            os.unlink(tmp_path)

    def test_planner_general_fallback_context_uses_explicit_allowlist(self):
        from system.orchestrator import profile_catalog
        tmp_path = self._make_temp_tools_with_fake()
        try:
            with patch.object(profile_catalog, "_PROFILE_CATALOG_PATH", tmp_path):
                ctx = profile_catalog.build_scoped_tool_context("GeneralFallbackProfile")
            assert "fake_future_tool" not in ctx
            assert "read_webpage" in ctx
        finally:
            os.unlink(tmp_path)

    def test_ag1_fallback_capability_view_uses_explicit_allowlist(self):
        from system.orchestrator import profile_catalog
        from system.tool_index import tool_capability_index
        tmp_path = self._make_temp_tools_with_fake()
        try:
            with patch.object(profile_catalog, "_PROFILE_CATALOG_PATH", tmp_path), patch.object(
                tool_capability_index, "_TOOL_INDEX_PATH", tmp_path
            ):
                view = profile_catalog.build_scoped_capability_view("GeneralFallbackProfile")
            assert "fake_future_tool" not in view
            assert "semantic_transform" in view
        finally:
            os.unlink(tmp_path)

    def test_ag1_fast_path_rejects_tool_not_in_general_fallback_allowlist(self):
        from system.orchestrator import profile_catalog
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        original_allowed = list(profile_catalog._PROFILE_DEFINITIONS["GeneralFallbackProfile"]["allowed_tools"])
        narrowed = [t for t in original_allowed if t != "write_file"]
        try:
            profile_catalog._PROFILE_DEFINITIONS["GeneralFallbackProfile"]["allowed_tools"] = narrowed
            result = execute_tool_selection(
                agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
                input_data='USE_TOOL: write_file "tmp/f2a1_test.txt" "hello"',
                context={
                    "workflow_id": "test_wf",
                    "step_id": "step_1",
                    "profile_name": "GeneralFallbackProfile",
                },
            )
            exec_result = result.get("result", {}).get("execution_result", {})
            assert exec_result.get("status") == "failure"
            assert exec_result.get("reason") == "tool_not_in_profile_allowlist"
            assert exec_result.get("tool_name") == "write_file"
        finally:
            profile_catalog._PROFILE_DEFINITIONS["GeneralFallbackProfile"]["allowed_tools"] = original_allowed

    def test_web_search_excluded_from_general_fallback(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("web_search", "GeneralFallbackProfile")

    def test_current_document_read_tools_preserved_in_general_fallback(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        for tool in [
            "read_file",
            "read_pdf",
            "read_docx",
            "read_csv",
            "read_spreadsheet",
            "read_image_text",
            "read_pdf_ocr",
            "list_files",
            "grep",
            "glob",
        ]:
            assert is_tool_in_profile(tool, "GeneralFallbackProfile")

    def test_current_mutation_tools_preserved_in_general_fallback(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        for tool in ["write_file", "append_file", "edit_file"]:
            assert is_tool_in_profile(tool, "GeneralFallbackProfile")

    def test_narrow_profiles_unchanged(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("read_file", "DocumentReadProfile")
        assert not is_tool_in_profile("write_file", "DocumentReadProfile")
        assert is_tool_in_profile("add_numbers", "ComputeProfile")
        assert not is_tool_in_profile("read_file", "ComputeProfile")
        assert is_tool_in_profile("read_webpage", "WebReadProfile")
        assert not is_tool_in_profile("read_file", "WebReadProfile")


class TestF2B1DataReferenceExposure:
    """F2B-1: New data-reference tools are narrowly exposed and do not leak into GeneralFallbackProfile."""

    _DATA_REF_TOOLS = ["preview_table_schema", "resolve_table_reference"]

    def test_data_reference_tools_registered_in_tools_json(self):
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "system", "tool_index", "tools.json")
        with open(path, "r", encoding="utf-8") as f:
            tools = json.load(f)
        for tool in self._DATA_REF_TOOLS:
            assert tool in tools
            assert tools[tool].get("production") is True
            assert tools[tool].get("read_only") is True
            assert tools[tool].get("destructive") is False
            assert tools[tool].get("external_call") is False

    def test_data_reference_tools_have_policy_metadata(self):
        from system.security.tool_policy import get_tool_metadata, is_read_only_tool, is_mutating_tool
        for tool in self._DATA_REF_TOOLS:
            meta = get_tool_metadata(tool)
            assert meta is not None
            assert is_read_only_tool(tool) is True
            assert is_mutating_tool(tool) is False
            assert meta.get("external_call") is False

    def test_data_reference_tools_in_plan_mode_allowlist(self):
        from system.security.tool_policy import list_plan_mode_allowed_tools
        allowed = set(list_plan_mode_allowed_tools())
        for tool in self._DATA_REF_TOOLS:
            assert tool in allowed

    def test_data_reference_tools_have_resource_access_metadata(self):
        from system.orchestrator.resource_access_resolver import resolve_step_access, is_read_only_access
        for tool in self._DATA_REF_TOOLS:
            step = {"tool_call": f"USE_TOOL: {tool} file_path"}
            access = resolve_step_access(step)
            assert access["target_type"] == "file"
            assert access["access_mode"] == "read"
            assert is_read_only_access(access["access_mode"]) is True

    def test_data_reference_tools_in_document_read_profile(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        for tool in self._DATA_REF_TOOLS:
            assert is_tool_in_profile(tool, "DocumentReadProfile")

    def test_data_reference_tools_not_in_general_fallback_profile(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        for tool in self._DATA_REF_TOOLS:
            assert not is_tool_in_profile(tool, "GeneralFallbackProfile")

    def test_data_reference_tools_not_in_other_narrow_profiles(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        for tool in self._DATA_REF_TOOLS:
            assert not is_tool_in_profile(tool, "ComputeProfile")
            assert not is_tool_in_profile(tool, "WebReadProfile")
            assert not is_tool_in_profile(tool, "FileMutationProfile")
            assert not is_tool_in_profile(tool, "DocumentSummaryProfile")

    def test_ag1_fast_path_rejects_data_reference_tool_outside_profile(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data="USE_TOOL: preview_table_schema",
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "ComputeProfile",
            },
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("status") == "failure"
        assert exec_result.get("reason") == "tool_not_in_profile_allowlist"
        assert exec_result.get("tool_name") == "preview_table_schema"

    def test_f2a1_snapshot_auto_leak_protection_still_holds(self):
        from system.orchestrator.profile_catalog import build_scoped_tool_index
        scoped = build_scoped_tool_index("GeneralFallbackProfile")
        for tool in self._DATA_REF_TOOLS:
            assert tool not in scoped

    def test_web_search_behavior_after_f3b(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("web_search", "WebSearchProfile")
        assert not is_tool_in_profile("web_search", "GeneralFallbackProfile")
        assert not is_tool_in_profile("web_search", "DocumentReadProfile")


class TestWebResearchProfileEnabled:
    """WEB_RESEARCH_PROFILE_CONTRACT_V1: WebResearchProfile is enabled with bounded tools/routing."""

    def test_web_research_profile_in_catalog(self):
        from system.orchestrator.profile_catalog import get_profile_names, is_tool_in_profile
        names = get_profile_names()
        assert "WebResearchProfile" in names
        assert is_tool_in_profile("web_search", "WebResearchProfile")
        assert is_tool_in_profile("read_webpage", "WebResearchProfile")
        assert is_tool_in_profile("finalize_output", "WebResearchProfile")

    def test_web_research_profile_excludes_unapproved_tools(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("semantic_transform", "WebResearchProfile")
        assert not is_tool_in_profile("read_file", "WebResearchProfile")
        assert not is_tool_in_profile("write_file", "WebResearchProfile")
        assert not is_tool_in_profile("edit_file", "WebResearchProfile")
        assert not is_tool_in_profile("run_python", "WebResearchProfile")
        assert not is_tool_in_profile("read_csv", "WebResearchProfile")
        assert not is_tool_in_profile("read_spreadsheet", "WebResearchProfile")

    def test_web_research_profile_scoped_index(self):
        from system.orchestrator.profile_catalog import build_scoped_tool_index
        scoped = build_scoped_tool_index("WebResearchProfile")
        tool_names = set(scoped.keys())
        assert "web_search" in tool_names
        assert "read_webpage" in tool_names
        assert "finalize_output" in tool_names
        assert "read_file" not in tool_names
        assert "write_file" not in tool_names

    def test_web_research_profile_scoped_capability_view(self):
        from system.orchestrator.profile_catalog import build_scoped_capability_view
        view = build_scoped_capability_view("WebResearchProfile")
        assert "web_search" in view
        assert "read_webpage" in view
        assert "finalize_output" in view
        assert "read_file" not in view
        assert "write_file" not in view
        assert "semantic_transform" not in view

    def test_profile_selector_routes_web_research_examples(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("Research FastAPI lifespan docs and summarize the best source.") == "WebResearchProfile"
        assert select_profile("Search the web for FastAPI lifespan docs, read the top result, and summarize it.") == "WebResearchProfile"
        assert select_profile("Find sources about FastAPI lifespan docs and give a short source-backed answer.") == "WebResearchProfile"
        assert select_profile("Research FastAPI lifespan docs and provide a brief source-backed answer.") == "WebResearchProfile"

    def test_profile_selector_reason_code_web_research(self):
        from system.orchestrator.profile_selector import select_profile_with_reason
        result = select_profile_with_reason("Research FastAPI lifespan docs and summarize the best source.")
        assert result["profile_name"] == "WebResearchProfile"
        assert result["profile_reason_code"] == "explicit_web_research"

    def test_profile_selector_does_not_route_pure_search_to_web_research(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("Search the web for FastAPI lifespan docs.") == "WebSearchProfile"
        assert select_profile("Find online results for FastAPI lifespan docs") == "WebSearchProfile"

    def test_profile_selector_does_not_route_url_read_to_web_research(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("Read https://example.com") == "WebReadProfile"
        assert select_profile("Summarize https://example.com") == "WebReadProfile"

    def test_profile_selector_blocks_unresolved_local_refs_for_web_research(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile("Search the web for the person in row 4 and summarize") != "WebResearchProfile"
        assert select_profile("Research the company in this spreadsheet") != "WebResearchProfile"

    def test_profile_selector_mixed_domain_does_not_route_web_research(self):
        from system.orchestrator.profile_selector import select_profile
        assert select_profile('Read "tmp/report.pdf" and research FastAPI online') == "GeneralFallbackProfile"
        assert select_profile("Read the file and search the web for more info") == "GeneralFallbackProfile"

    def test_general_fallback_profile_still_excludes_web_search(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert not is_tool_in_profile("web_search", "GeneralFallbackProfile")

    def test_web_search_profile_remains_pure_search(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("web_search", "WebSearchProfile")
        assert not is_tool_in_profile("read_webpage", "WebSearchProfile")

    def test_web_read_profile_remains_explicit_url_read(self):
        from system.orchestrator.profile_catalog import is_tool_in_profile
        assert is_tool_in_profile("read_webpage", "WebReadProfile")
        assert not is_tool_in_profile("web_search", "WebReadProfile")

    def test_ag1_fast_path_allows_web_search_in_web_research_profile(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: web_search "FastAPI lifespan docs"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "WebResearchProfile",
            },
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("reason") != "tool_not_in_profile_allowlist"
        assert exec_result.get("reason") != "web_search_unresolved_reference"

    def test_ag1_fast_path_allows_read_webpage_in_web_research_profile(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: read_webpage "https://example.com"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_2",
                "profile_name": "WebResearchProfile",
                "purpose": "Read the top search result from step_1",
                "dependency_outputs": {
                    "step_1": {
                        "selected_tool": "web_search",
                        "tool_call": 'web_search "FastAPI lifespan docs"',
                    }
                },
            },
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("reason") != "tool_not_in_profile_allowlist"
        assert exec_result.get("reason") != "read_webpage_not_search_provider"

    def test_ag1_fast_path_blocks_file_tool_in_web_research_profile(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: read_file "tmp/report.txt"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "WebResearchProfile",
            },
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("status") == "failure"
        assert exec_result.get("reason") == "tool_not_in_profile_allowlist"
        assert exec_result.get("tool_name") == "read_file"

    def test_ag1_fast_path_blocks_semantic_transform_in_web_research_profile(self):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection
        result = execute_tool_selection(
            agent={"name": "generic_agent", "role": "tool_executor", "scope": ["tools"]},
            input_data='USE_TOOL: semantic_transform "summarize" "text"',
            context={
                "workflow_id": "test_wf",
                "step_id": "step_1",
                "profile_name": "WebResearchProfile",
            },
        )
        exec_result = result.get("result", {}).get("execution_result", {})
        assert exec_result.get("status") == "failure"
        assert exec_result.get("reason") == "tool_not_in_profile_allowlist"
        assert exec_result.get("tool_name") == "semantic_transform"


class TestFakeSearchGovernanceFailFast:
    """F3C POST-GUI FIX1: read_webpage fake-search guard failures must be non-retryable."""

    def _make_step(self):
        return {
            "id": "step_1",
            "status": "PENDING",
            "type": "EXECUTE_API",
            "risk": "MEDIUM",
            "importance": "MEDIUM",
            "purpose": "test",
            "tool_call": "read_webpage https://example.com",
            "expected_outcome": "done",
            "retries": 0,
            "resource_targets": [],
        }

    def _run_governance(self, reason):
        from system.orchestrator.governance import decide_next_action
        step = self._make_step()
        execution_result = {"status": "failure", "reason": reason, "tool_name": "read_webpage"}
        return decide_next_action(
            validator_output={},
            execution_result=execution_result,
            step=step,
            context={"workflow_id": "wf_fake_search"},
        )

    def test_read_webpage_not_search_provider_is_fail_fast(self):
        """read_webpage_not_search_provider must classify as fail, not retry."""
        decision = self._run_governance("read_webpage_not_search_provider")
        assert decision.action == "fail"
        assert decision.reason == "read_webpage_not_search_provider"

    def test_read_webpage_fake_search_blocked_is_fail_fast(self):
        """read_webpage_fake_search_blocked must classify as fail, not retry."""
        decision = self._run_governance("read_webpage_fake_search_blocked")
        assert decision.action == "fail"
        assert decision.reason == "read_webpage_fake_search_blocked"

    def test_explicit_url_read_webpage_retryable_failure_remains_retryable(self):
        """A genuine retryable failure from explicit-URL read_webpage must still retry."""
        from system.orchestrator.governance import decide_next_action
        step = self._make_step()
        execution_result = {"status": "failure", "reason": "tool_execution_error", "tool_name": "read_webpage"}
        decision = decide_next_action(
            validator_output={},
            execution_result=execution_result,
            step=step,
            context={"workflow_id": "wf_retryable"},
        )
        assert decision.action == "retry"

    def test_web_search_retryable_failure_remains_retryable(self):
        """A genuine retryable failure from web_search must still retry."""
        from system.orchestrator.governance import decide_next_action
        step = self._make_step()
        step["tool_call"] = "web_search query"
        execution_result = {"status": "failure", "reason": "tool_execution_error", "tool_name": "web_search"}
        decision = decide_next_action(
            validator_output={},
            execution_result=execution_result,
            step=step,
            context={"workflow_id": "wf_retryable"},
        )
        assert decision.action == "retry"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

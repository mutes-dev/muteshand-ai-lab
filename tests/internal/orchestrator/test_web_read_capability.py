"""
AGENT-001G-IMPL1 — Web Read Capability Compiler Tests

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 10B:
- Explicit http/https URLs only
- Exact literal preservation
- Deterministic read_webpage -> finalize_output DAG
- Fallback on ambiguous, search, mutation, mixed-domain, multi-URL
"""

import os
import sys

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.orchestrator.capabilities.web_read_capability import (
    compile_web_read_workflow,
    detect_web_read_fallback_reason,
    is_web_prompt,
)


class TestWebReadCapabilityAccept:
    """High-confidence explicit-URL prompts should produce the deterministic DAG."""

    def test_http_url(self):
        wf = compile_web_read_workflow("Read http://example.com")
        assert wf is not None
        assert wf["name"] == "web_read_workflow"
        assert len(wf["steps"]) == 2
        assert wf["steps"][0]["capability_metadata"]["allowed_tool"] == "read_webpage"
        assert wf["steps"][1]["capability_metadata"]["allowed_tool"] == "finalize_output"
        print("  [PASS] http URL accepted")

    def test_https_url(self):
        wf = compile_web_read_workflow("Read https://example.com")
        assert wf is not None
        assert wf["steps"][0]["purpose"] == "Read the webpage at https://example.com"
        print("  [PASS] https URL accepted")

    def test_quoted_url(self):
        wf = compile_web_read_workflow('Read the webpage at "https://example.com/quoted"')
        assert wf is not None
        assert wf["steps"][0]["purpose"] == "Read the webpage at https://example.com/quoted"
        print("  [PASS] quoted URL accepted")

    def test_various_read_verbs(self):
        for verb in ["Read", "Show", "Open", "Display", "View", "Fetch", "Get"]:
            wf = compile_web_read_workflow(f"{verb} https://example.com")
            assert wf is not None, f"verb {verb} should be accepted"
        print("  [PASS] recognized web-read verbs")

    def test_final_action_is_present(self):
        wf = compile_web_read_workflow("Read https://example.com")
        step_2_meta = wf["steps"][1]["capability_metadata"]
        assert step_2_meta.get("final_action") == "present"
        assert step_2_meta.get("intent_mode") == "present"
        print("  [PASS] final_action/intent_mode are present")

    def test_step_2_purpose_is_explicit_present(self):
        wf = compile_web_read_workflow("Read https://example.com")
        purpose = wf["steps"][1]["purpose"]
        assert "or" not in purpose.lower()
        assert "Present the webpage contents" in purpose
        print("  [PASS] step_2 purpose is explicit present")

    def test_url_with_query_and_fragment(self):
        url = "https://example.com/path?a=1&b=2#section"
        wf = compile_web_read_workflow(f"Read {url}")
        assert wf is not None
        assert wf["steps"][0]["purpose"] == f"Read the webpage at {url}"
        print("  [PASS] URL query string and fragment preserved")

    def test_url_encoded_characters(self):
        url = "https://example.com/search?q=hello%20world"
        wf = compile_web_read_workflow(f"Read {url}")
        assert wf is not None
        assert url in wf["steps"][0]["purpose"]
        print("  [PASS] URL-encoded characters preserved")

    def test_dag_shape(self):
        wf = compile_web_read_workflow("Read https://example.com")
        step_1, step_2 = wf["steps"]
        assert step_1["id"] == "step_1"
        assert step_2["id"] == "step_2"
        assert step_2["depends_on"] == ["step_1"]
        assert step_1["depends_on"] == []
        assert step_1["type"] == "EXECUTE_API"
        assert step_2["type"] == "EXECUTE_API"
        print("  [PASS] deterministic DAG shape")

    def test_capability_metadata(self):
        wf = compile_web_read_workflow("Read https://example.com")
        step_1_meta = wf["steps"][0]["capability_metadata"]
        step_2_meta = wf["steps"][1]["capability_metadata"]
        assert step_1_meta["capability_id"] == "web_read"
        assert step_1_meta["allowed_tool_family"] == "web_read"
        assert step_1_meta["allowed_tool"] == "read_webpage"
        assert step_1_meta["route_reason_code"] == "accepted_explicit_url_read"
        assert step_2_meta["allowed_tool_family"] == "text_finalization"
        assert step_2_meta["allowed_tool"] == "finalize_output"
        print("  [PASS] capability metadata attached")

    def test_no_tool_call_prepopulation(self):
        wf = compile_web_read_workflow("Read https://example.com")
        assert "tool_call" not in wf["steps"][0]
        print("  [PASS] read_webpage step is not prepopulated")


class TestWebReadCapabilityLiteralPreservation:
    """Exact URL literal must be preserved without rewriting."""

    def test_preserves_exact_url(self):
        url = "https://example.com:8080/path?query=1&other=2#frag"
        wf = compile_web_read_workflow(f"Read {url}")
        assert wf["steps"][0]["purpose"] == f"Read the webpage at {url}"
        print("  [PASS] exact URL literal preserved")

    def test_preserves_case_and_encoding(self):
        url = "https://Example.COM/%20path?Q=%C3%A9"
        wf = compile_web_read_workflow(f"Read {url}")
        assert wf["steps"][0]["purpose"] == f"Read the webpage at {url}"
        print("  [PASS] URL case and percent-encoding preserved")


class TestWebReadCapabilityFallback:
    """Disallowed or ambiguous cases must fall back to the planner."""

    def test_missing_url(self):
        assert compile_web_read_workflow("Read the webpage") is None
        print("  [PASS] missing URL falls back")

    def test_ambiguous_reference(self):
        for prompt in ["Read the website", "Show that page", "Open the article"]:
            assert compile_web_read_workflow(prompt) is None, prompt
        print("  [PASS] ambiguous web references fall back")

    def test_web_search_request(self):
        for prompt in [
            "Search the web for example.com",
            "Find online https://example.com",
            "Google example.com",
        ]:
            assert compile_web_read_workflow(prompt) is None, prompt
        print("  [PASS] web search requests fall back")

    def test_search_then_read_first_result(self):
        assert compile_web_read_workflow("Search then read the first result for example.com") is None
        print("  [PASS] search-then-read falls back")

    def test_mutation_intents(self):
        for prompt in [
            "Download https://example.com",
            "Save https://example.com to tmp/page.txt",
            "Write https://example.com content to file",
        ]:
            assert compile_web_read_workflow(prompt) is None, prompt
        print("  [PASS] mutation intents fall back")

    def test_mixed_web_and_file(self):
        assert compile_web_read_workflow("Read https://example.com and read tmp/file.txt") is None
        assert compile_web_read_workflow("Read https://example.com and list files in tmp") is None
        print("  [PASS] mixed web + file falls back")

    def test_mixed_web_and_arithmetic(self):
        assert compile_web_read_workflow("Read https://example.com and add 5") is None
        print("  [PASS] mixed web + arithmetic falls back")

    def test_multiple_urls(self):
        assert compile_web_read_workflow("Read https://a.com and https://b.com") is None
        print("  [PASS] multiple URLs fall back")

    def test_no_read_verb(self):
        assert compile_web_read_workflow("https://example.com") is None
        print("  [PASS] bare URL without read intent falls back")

    def test_unsupported_scheme(self):
        assert compile_web_read_workflow("Read file:///etc/passwd") is None
        print("  [PASS] unsupported URL scheme falls back")

    def test_summarize_url_supported(self):
        wf = compile_web_read_workflow("Summarize https://example.com")
        assert wf is not None
        meta = wf["steps"][1]["capability_metadata"]
        assert meta["final_action"] == "summarize"
        assert meta["intent_mode"] == "summarize"
        assert meta["transform_required"] is True
        assert wf["steps"][1]["purpose"] == "Summarize the webpage contents from step_1"

    def test_explain_url_supported(self):
        wf = compile_web_read_workflow("Explain https://example.com")
        assert wf is not None
        meta = wf["steps"][1]["capability_metadata"]
        assert meta["final_action"] == "explain"
        assert meta["intent_mode"] == "explain"
        assert meta["transform_required"] is True
        assert wf["steps"][1]["purpose"] == "Explain the webpage contents from step_1"

    def test_extract_key_points_url_supported(self):
        wf = compile_web_read_workflow("Extract key points from https://example.com")
        assert wf is not None
        meta = wf["steps"][1]["capability_metadata"]
        assert meta["final_action"] == "extract_key_points"
        assert meta["intent_mode"] == "extract_key_points"
        assert meta["transform_required"] is True
        assert wf["steps"][1]["purpose"] == "Extract key points from the webpage contents from step_1"

    def test_summary_of_url_supported(self):
        wf = compile_web_read_workflow("Give me a summary of https://example.com")
        assert wf is not None
        assert wf["steps"][1]["capability_metadata"]["final_action"] == "summarize"

    def test_compare_url_not_supported(self):
        assert compile_web_read_workflow("Compare https://example.com and https://other.com") is None
        print("  [PASS] compare URL falls back")


class TestWebReadFallbackReasons:
    """Advisory fallback reason codes are correct for web-related prompts."""

    def test_web_search_reason(self):
        assert detect_web_read_fallback_reason("Search the web for example.com") == "fallback_web_search_requested"

    def test_ambiguous_reason(self):
        assert detect_web_read_fallback_reason("Read the website") == "fallback_ambiguous_web_reference"

    def test_missing_url_reason(self):
        assert detect_web_read_fallback_reason("Read the webpage") == "fallback_missing_explicit_url"

    def test_mixed_domain_reason(self):
        assert detect_web_read_fallback_reason("Read https://example.com and add 5") == "fallback_mixed_domain"

    def test_unsupported_operation_reason(self):
        assert detect_web_read_fallback_reason("Download https://example.com") == "fallback_unsupported_operation"

    def test_summarize_missing_url_reason(self):
        # Summarize is now supported for explicit URLs; missing-URL phrasing falls back.
        assert detect_web_read_fallback_reason("Summarize the webpage") == "fallback_missing_explicit_url"
        assert detect_web_read_fallback_reason("Summarize the website") == "fallback_ambiguous_web_reference"

    def test_explain_missing_url_reason(self):
        # Explain is now supported for explicit URLs; missing-URL phrasing falls back.
        assert detect_web_read_fallback_reason("Explain the webpage") == "fallback_missing_explicit_url"
        assert detect_web_read_fallback_reason("Explain the website") == "fallback_ambiguous_web_reference"

    def test_extract_key_points_missing_url_reason(self):
        # Extract key points is now supported for explicit URLs; missing-URL phrasing falls back.
        assert detect_web_read_fallback_reason("Extract key points from the webpage") == "fallback_missing_explicit_url"
        assert detect_web_read_fallback_reason("Extract key points from the website") == "fallback_ambiguous_web_reference"

    def test_compare_unsupported_final_action_reason(self):
        assert detect_web_read_fallback_reason("Compare https://example.com and https://other.com") == "fallback_unsupported_final_action"


class TestWebReadPromptHeuristic:
    """is_web_prompt distinguishes web-related prompts from generic prompts."""

    def test_web_prompt_true(self):
        assert is_web_prompt("Read https://example.com")
        assert is_web_prompt("Search the web for example.com")
        assert is_web_prompt("Read the webpage")

    def test_web_prompt_false(self):
        assert not is_web_prompt("Tell me a joke")
        assert not is_web_prompt("Add 5 and 10")
        assert not is_web_prompt("List files in tmp")

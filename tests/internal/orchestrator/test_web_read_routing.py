"""
AGENT-001G-IMPL1 — Web Read Capability Router Tests

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 9/10B:
- Router evaluates web_read after arithmetic and document_local_read
- Route accepted with metadata and candidate workflow
- Fallback to planner with correct advisory reason codes
- Mandatory planning compiler -> workflow validator handoff succeeds
"""

import os
import sys

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.orchestrator.capability_router import route_capability
from system.orchestrator.planning_compiler import compile_candidate_workflow
from system.orchestrator.workflow_validator import validate_workflow
from system.orchestrator.projection_schema import build_workflow_projection


class TestWebReadRouting:
    """Route-level behavior for web_read."""

    def test_route_accepted_for_explicit_url(self):
        result = route_capability("Read https://example.com")
        assert result["route_decision"] == "ROUTE_ACCEPTED"
        assert result["capability_id"] == "web_read"
        assert result["route_reason_code"] == "accepted_explicit_url_read"
        assert result["route_confidence"] == 1.0
        assert result["fallback_reason"] is None
        assert result["candidate_workflow"] is not None
        print("  [PASS] web_read route accepted for explicit URL")

    def test_route_metadata_emitted(self):
        result = route_capability("Read https://example.com")
        meta = result["route_metadata"]
        assert meta["route_decision"] == "ROUTE_ACCEPTED"
        assert meta["capability_id"] == "web_read"
        assert meta["route_confidence"] == 1.0
        assert meta["route_reason_code"] == "accepted_explicit_url_read"
        assert meta["candidate_workflow_emitted"] is True
        print("  [PASS] route metadata emitted")

    def test_candidate_workflow_tool_narrowing(self):
        result = route_capability("Read https://example.com")
        steps = result["candidate_workflow"]["steps"]
        allowed = [s["capability_metadata"]["allowed_tool"] for s in steps]
        assert allowed == ["read_webpage", "finalize_output"]
        for s in steps:
            assert s["capability_metadata"]["capability_id"] == "web_read"
        print("  [PASS] candidate workflow narrows to allowed tools")

    def test_precedence_arithmetic_first(self):
        result = route_capability("Add 5 and 10")
        assert result["capability_id"] == "arithmetic"
        print("  [PASS] arithmetic takes precedence over web_read")

    def test_precedence_document_local_read_second(self):
        result = route_capability("Read tmp/file.txt")
        assert result["capability_id"] == "document_local_read"
        print("  [PASS] document_local_read takes precedence over web_read")

    def test_compiler_and_validator_handoff(self):
        result = route_capability("Read https://example.com")
        workflow = compile_candidate_workflow(result["candidate_workflow"], user_input="Read https://example.com")
        validation = validate_workflow(workflow)
        assert validation["status"] == "success"
        print("  [PASS] planning compiler -> workflow validator handoff succeeds")

    def test_fallback_missing_url(self):
        result = route_capability("Read the webpage")
        assert result["route_decision"] == "ROUTE_FALLBACK_TO_PLANNER"
        assert result["route_reason_code"] == "fallback_missing_explicit_url"
        print("  [PASS] missing URL fallback reason code")

    def test_fallback_ambiguous_reference(self):
        result = route_capability("Show that website")
        assert result["route_decision"] == "ROUTE_FALLBACK_TO_PLANNER"
        assert result["route_reason_code"] == "fallback_ambiguous_web_reference"
        print("  [PASS] ambiguous reference fallback reason code")

    def test_fallback_web_search(self):
        result = route_capability("Search the web for example.com")
        assert result["route_decision"] == "ROUTE_FALLBACK_TO_PLANNER"
        assert result["route_reason_code"] == "fallback_web_search_requested"
        print("  [PASS] web search fallback reason code")

    def test_fallback_search_then_read(self):
        result = route_capability("Search then read the first result for example.com")
        assert result["route_decision"] == "ROUTE_FALLBACK_TO_PLANNER"
        assert result["route_reason_code"] == "fallback_web_search_requested"
        print("  [PASS] search-then-read fallback reason code")

    def test_fallback_mixed_domain(self):
        result = route_capability("Read https://example.com and add 5")
        assert result["route_decision"] == "ROUTE_FALLBACK_TO_PLANNER"
        assert result["route_reason_code"] == "fallback_mixed_domain"
        print("  [PASS] mixed web + arithmetic fallback reason code")

    def test_fallback_mutation(self):
        result = route_capability("Download https://example.com")
        assert result["route_decision"] == "ROUTE_FALLBACK_TO_PLANNER"
        assert result["route_reason_code"] == "fallback_unsupported_operation"
        print("  [PASS] mutation fallback reason code")

    def test_route_accepted_for_summarize_url(self):
        result = route_capability("Summarize https://example.com")
        assert result["route_decision"] == "ROUTE_ACCEPTED"
        assert result["capability_id"] == "web_read"
        assert result["route_reason_code"] == "accepted_explicit_url_summarize"
        assert result["candidate_workflow"]["steps"][1]["capability_metadata"]["transform_required"] is True
        print("  [PASS] web_read route accepted for summarize URL")

    def test_route_accepted_for_explain_url(self):
        result = route_capability("Explain https://example.com")
        assert result["route_decision"] == "ROUTE_ACCEPTED"
        assert result["capability_id"] == "web_read"
        assert result["route_reason_code"] == "accepted_explicit_url_explain"
        assert result["candidate_workflow"]["steps"][1]["capability_metadata"]["transform_required"] is True
        print("  [PASS] web_read route accepted for explain URL")

    def test_route_accepted_for_extract_key_points_url(self):
        result = route_capability("Extract key points from https://example.com")
        assert result["route_decision"] == "ROUTE_ACCEPTED"
        assert result["capability_id"] == "web_read"
        assert result["route_reason_code"] == "accepted_explicit_url_extract_key_points"
        assert result["candidate_workflow"]["steps"][1]["capability_metadata"]["transform_required"] is True
        print("  [PASS] web_read route accepted for extract key points URL")

    def test_non_web_prompt_fallback_generic(self):
        result = route_capability("Tell me a joke")
        assert result["route_decision"] == "ROUTE_FALLBACK_TO_PLANNER"
        assert result["route_reason_code"] == "no_matching_capability"
        print("  [PASS] non-web prompt falls back generically")


class TestWebReadProjection:
    """Capability metadata flows through projection."""

    def _make_workflow(self):
        result = route_capability("Read https://example.com")
        wf = compile_candidate_workflow(result["candidate_workflow"], user_input="Read https://example.com")
        wf["id"] = "wf-web-read"
        return wf

    def test_projection_capability_metadata(self):
        wf = self._make_workflow()
        projection = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="QUEUED",
        )
        for step_proj in projection["steps"]:
            assert step_proj["capability_metadata"] is not None
            assert step_proj["capability_metadata"]["capability_id"] == "web_read"
        assert projection["steps"][0]["capability_metadata"]["allowed_tool"] == "read_webpage"
        assert projection["steps"][1]["capability_metadata"]["allowed_tool"] == "finalize_output"
        print("  [PASS] projection exposes capability metadata")

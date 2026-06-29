"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - Parser escape-sequence handling for quoted strings
  - Deterministic read_webpage -> finalize_output path for arbitrary payloads
ENTRYPOINT: system_entry
DIRECT_INTERNAL_CALLS: system.parser, system.orchestrator.agents.tool_selection_agent
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: REGRESSION
ARCHITECTURAL_SCOPE: Presentation path only
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from system.parser.parser import parse_arguments, QuotedString
from system.orchestrator.agents.tool_selection_agent import _try_single_dependency_presentation


def test_parser_escaped_quote_inside_quoted_string():
    result = parse_arguments('finalize_output "He said \\"hello\\""')
    assert isinstance(result, list), result
    assert result[0] == "finalize_output"
    assert result[1] == 'He said "hello"'
    assert isinstance(result[1], QuotedString)


def test_parser_preserves_literal_backslash_inside_quoted_string():
    result = parse_arguments('finalize_output "path\\to\\file"')
    assert isinstance(result, list), result
    assert result[1] == "path\\to\\file"


def test_parser_mixed_escaped_quote_and_literal_backslashes():
    result = parse_arguments('finalize_output "Line: \\\"a\\b\\\""')
    assert isinstance(result, list), result
    assert result[1] == 'Line: "a\\b"'


def test_deterministic_webpage_presentation_preserves_arbitrary_content():
    payload = 'Text with "quotes", \\backslashes\\ and \nnewlines.'
    context = {
        "workflow_id": "wf_test",
        "step_id": "step_2",
        "allowed_tool": "finalize_output",
        "dependency_outputs": {
            "step_1": {
                "status": "success",
                "data": payload,
                "purpose": "Read the webpage at https://example.com",
                "selected_tool": "read_webpage",
                "resource_targets": ["https://example.com"],
            }
        },
    }
    result = _try_single_dependency_presentation(
        {"name": "tool_selection_agent", "role": "tool_selection"},
        "Present the webpage contents from step_1",
        context,
    )
    assert result["status"] == "success"
    assert result["result"]["execution_result"]["status"] == "success"
    assert result["result"]["output"] == payload
    assert result["result"]["executed_input"].startswith("finalize_output ")


def test_deterministic_webpage_presentation_real_system_entry():
    """End-to-end: deterministic path round-trips a webpage-like payload through system_entry."""
    payload = "  <div class=\"section\">\n    \"Quoted\" and \\escaped\\ text.\n  </div>\n"
    context = {
        "workflow_id": "wf_test",
        "step_id": "step_2",
        "allowed_tool": "finalize_output",
        "dependency_outputs": {
            "step_1": {
                "status": "success",
                "data": payload,
                "purpose": "Read the webpage at https://docs.python.org/",
                "selected_tool": "read_webpage",
                "resource_targets": ["https://docs.python.org/"],
            }
        },
    }
    result = _try_single_dependency_presentation(
        {"name": "tool_selection_agent", "role": "tool_selection"},
        "Present the summary of the webpage from step_1",
        context,
    )
    assert result["status"] == "success"
    assert result["result"]["execution_result"]["status"] == "success"
    assert result["result"]["output"] == payload


if __name__ == "__main__":
    test_parser_escaped_quote_inside_quoted_string()
    test_parser_preserves_literal_backslash_inside_quoted_string()
    test_parser_mixed_escaped_quote_and_literal_backslashes()
    test_deterministic_webpage_presentation_preserves_arbitrary_content()
    test_deterministic_webpage_presentation_real_system_entry()
    print("All web_read presentation escaping tests passed.")

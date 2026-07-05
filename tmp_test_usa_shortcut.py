"""Temporary validation script for tool selection agent unsupported spreadsheet shortcut."""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from system.orchestrator.agents.tool_selection_agent import _try_unsupported_spreadsheet_analysis
from system.orchestrator.capabilities.document_local_read_capability import (
    _UNSUPPORTED_SPREADSHEET_ANALYSIS_MESSAGE,
)

context = {
    "capability_metadata": {
        "capability_id": "document_local_read",
        "allowed_tool": "finalize_output",
        "final_action": "unsupported_spreadsheet_analysis",
        "intent_mode": "unsupported_spreadsheet_analysis",
        "transform_required": False,
        "static_message": _UNSUPPORTED_SPREADSHEET_ANALYSIS_MESSAGE,
    },
    "dependency_outputs": {},
}

result = _try_unsupported_spreadsheet_analysis(
    agent={"name": "test", "role": "tool_executor"},
    input_data="ignore",
    context=context,
)
assert result is not None, "shortcut should fire"
assert result["status"] == "success"
assert _UNSUPPORTED_SPREADSHEET_ANALYSIS_MESSAGE in result["result"]["output"]
print("OK: tool selection agent shortcut returns deterministic unsupported message.")

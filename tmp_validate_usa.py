"""Temporary validation script for unsupported spreadsheet analysis route."""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from system.orchestrator.capabilities.document_local_read_capability import (
    compile_document_local_read_workflow,
)
from system.orchestrator.workflow_validator import validate_workflow
from system.orchestrator.planning_compiler import compile_candidate_workflow

user_input = 'from "tmp/sprint11_slice003_sample.csv", who has the highest score?'
wf = compile_document_local_read_workflow(user_input)
assert wf is not None, "workflow should be compiled"
assert len(wf["steps"]) == 1, "single step workflow"
meta = wf["steps"][0]["capability_metadata"]
assert meta["final_action"] == "unsupported_spreadsheet_analysis"
assert meta["allowed_tool"] == "finalize_output"

compiled = compile_candidate_workflow(wf)
result = validate_workflow(compiled)
assert result["status"] == "success", f"validation failed: {result}"
print("OK: unsupported spreadsheet analysis workflow compiles and validates.")

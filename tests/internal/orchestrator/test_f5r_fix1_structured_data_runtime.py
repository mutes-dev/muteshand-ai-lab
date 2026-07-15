"""F5R-FIX1/FIX2 integration tests: plan-mode runtime reachability and ownership.

Covers:
- Plan-mode execution authority inside analyze_table.run() / system_entry.
- Path, sheet, and positional conflict rejection.
- Oversized / malformed / invalid-version plan rejection.
- Simple capability path convergence: every simple operation routes through
  run_plan() and produces verified trust metadata.
- Planner/AG1 ownership of composed multi-filter + optional sort interpretation.
- Capability validation/lowerer for Planner-produced TableAnalysisPlanV1.
- Missing-source ambiguity deterministic runtime guidance.
- Intermediate-filter truncation regression.
- Trust metadata and advisory blocker semantics.
"""

import csv
import json
import os
import shlex
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

BASE_PATH = os.path.abspath("E:/MutesHand")

import system.entry.system_entry as _system_entry_module
from system.entry.system_entry import system_entry
from system.orchestrator.capabilities.structured_data_analysis_capability import (
    compile_structured_data_analysis_workflow,
    is_structured_data_analysis_intent,
    validate_and_build_structured_data_workflow,
)
from system.orchestrator.capabilities.document_local_read_capability import (
    compile_document_local_read_workflow,
)
from system.orchestrator.orchestrator_planner import plan_workflow
from system.orchestrator.agents.tool_selection_agent import execute_tool_selection


# The module object used by system_entry's execution registry is the one loaded by
# system.registry.registry_builder, not the 'tools.analyze_table' package import.
def _analyze_table_globals():
    return _system_entry_module._execution_registry["analyze_table"].__globals__


@pytest.fixture
def table_tmp_path():
    """Create a temporary directory inside the project root for safe file tests."""
    with tempfile.TemporaryDirectory(dir=BASE_PATH) as d:
        yield d


def _write_csv(file_path: str, rows: list[list]):
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)


def _rel(path: str) -> str:
    return os.path.relpath(path, BASE_PATH).replace("\\", "/")


def _strip_use_tool(tool_call: str) -> str:
    if tool_call.startswith("USE_TOOL:"):
        return tool_call.split(":", 1)[1].strip()
    return tool_call


def _build_tool_call_for_plan(plan: dict) -> str:
    """Use the capability lowering for any plan dict (for test-only authority checks)."""
    from system.orchestrator.capabilities.structured_data_analysis_capability import (
        _build_tool_call as _cap_build_tool_call,
    )
    return _strip_use_tool(_cap_build_tool_call(plan["source"]["path"], plan))


def _build_default_bounds() -> dict:
    return {
        "max_operations": 8,
        "max_predicates": 6,
        "max_rows_scanned": 10000,
        "max_rows_returned": 1000,
    }


def _mock_llm_table_plan_response(proposal: dict) -> dict:
    """Return the shape execute_llm produces when the Planner emits a proposal."""
    planner_output = {
        "steps": [
            {
                "name": "structured_data_analysis",
                "purpose": "Placeholder planner step; structured proposal is authoritative.",
                "agent": "structured_data_analysis",
                "estimated_complexity": "low",
            }
        ],
        "table_analysis_plan_v1_proposal": proposal,
    }
    return {"status": "success", "result": json.dumps(planner_output)}


# ── Plan-mode execution authority ────────────────────────────────────────────


class TestPlanModeExecutionAuthority:
    """Validate the serialized plan as the sole authority for execution."""

    def test_valid_plan_roundtrip_through_system_entry(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(os.path.join(BASE_PATH, rel), [["Name", "Score"], ["A", "10"], ["B", "20"]])
        prompt = f'Which Name has the highest Score in "{rel}"?'
        wf = compile_structured_data_analysis_workflow(prompt)
        assert wf is not None
        tc = _strip_use_tool(wf["steps"][0]["tool_call"])
        result = system_entry(tc)
        assert result["status"] == "success"
        payload = result["result"]
        assert payload["trust_metadata"]["trust_class"] == "verified"
        assert payload["trust_metadata"]["operation_coverage_complete"] is True
        assert payload["answer_text"] == "The highest Score is 20. This corresponds to B."

    def test_source_path_mismatch_is_rejected(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(os.path.join(BASE_PATH, rel), [["Name", "Score"], ["A", "10"]])
        prompt = f'What is the highest Score in "{rel}"?'
        wf = compile_structured_data_analysis_workflow(prompt)
        tc = wf["steps"][0]["tool_call"]
        # Tamper with the explicit path while preserving the plan payload.
        tc_tampered = tc.replace(rel, "other/path.csv", 1)
        result = system_entry(_strip_use_tool(tc_tampered))
        assert result["status"] == "failure"
        assert "plan_source_path_mismatch" in result["reason"]

    def test_filter_value_conflict_is_rejected(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(os.path.join(BASE_PATH, rel), [["Name", "Score"], ["A", "10"], ["B", "20"]])
        prompt = f'Show rows where Score is greater than 5 in "{rel}"'
        wf = compile_structured_data_analysis_workflow(prompt)
        tc = wf["steps"][0]["tool_call"]
        # shlex-split to get the eight positional arguments.  The plan payload is at
        # index 4, the legacy filter_value at index 7.
        parts = shlex.split(tc)
        assert parts[0] == "USE_TOOL:"
        assert parts[1] == "analyze_table"
        # Tamper with the legacy filter_value while preserving the plan payload.
        parts[8] = "9999"
        # Re-escape the plan payload so it survives re-quoting.
        parts[4] = parts[4].replace("\\", "\\\\").replace('"', '\\"')
        quoted_args = " ".join(f'"{a}"' for a in parts[2:])
        tc_tampered = f"USE_TOOL: analyze_table {quoted_args}"
        result = system_entry(_strip_use_tool(tc_tampered))
        assert result["status"] == "failure"
        assert "plan_positional_conflict" in result["reason"]

    def test_malformed_plan_payload_rejected(self):
        # Syntactically valid quoted argument, but not valid JSON.
        tc = 'USE_TOOL: analyze_table "tmp/data.csv" "__table_analysis_plan_v1__" "not json" "" "" "" "" ""'
        result = system_entry(_strip_use_tool(tc))
        assert result["status"] == "failure"
        assert "plan_payload_not_valid_json" in result["reason"]

    def test_invalid_plan_version_rejected(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(os.path.join(BASE_PATH, rel), [["Name", "Score"], ["A", "10"]])
        from system.orchestrator.structured_data.table_analysis_plan import (
            build_single_op_plan,
            MAX_OPERATIONS,
            MAX_PREDICATES,
            MAX_ROWS_SCANNED,
            MAX_ROWS_RETURNED,
        )

        plan = build_single_op_plan(
            source_path=rel,
            operation_type="max",
            operation_id="op_max",
            column="Score",
        )
        plan["version"] = "BadVersion"
        tc = _build_tool_call_for_plan(plan)
        result = system_entry(tc)
        assert result["status"] == "failure"
        assert "plan_version_mismatch" in result["reason"]

    def test_oversized_plan_payload_rejected(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(os.path.join(BASE_PATH, rel), [["Name", "Score"], ["A", "10"]])
        from system.orchestrator.structured_data.table_analysis_plan import (
            build_single_op_plan,
            MAX_OPERATIONS,
            MAX_PREDICATES,
            MAX_ROWS_SCANNED,
            MAX_ROWS_RETURNED,
        )

        plan = build_single_op_plan(
            source_path=rel,
            operation_type="max",
            operation_id="op_max",
            column="Score",
        )
        # Inflate the plan with a huge column name to exceed 8192 bytes.
        plan["operations"][0]["column"] = "x" * 9000
        tc = _build_tool_call_for_plan(plan)
        result = system_entry(tc)
        assert result["status"] == "failure"
        assert "plan_payload_oversized" in result["reason"]


# ── Simple capability path convergence ───────────────────────────────────────


class TestSimpleCapabilityPathConvergence:
    """Every simple F5A/F5B-1 operation must execute through run_plan()."""

    def _run_and_verify(self, table_tmp_path, prompt, expected_op_id, expected_answer=None):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(
            os.path.join(BASE_PATH, rel),
            [["Name", "Score", "Age"], ["Alice", "85", "30"], ["Bob", "91", "25"], ["Cara", "78", "35"]],
        )
        wf = compile_structured_data_analysis_workflow(prompt)
        assert wf is not None, f"prompt not accepted: {prompt}"
        tc = _strip_use_tool(wf["steps"][0]["tool_call"])

        calls = []
        _mod_globals = _analyze_table_globals()
        original_run_plan = _mod_globals["run_plan"]

        def _spy(plan):
            calls.append(plan)
            return original_run_plan(plan)

        with mock.patch.dict(_mod_globals, run_plan=_spy):
            result = system_entry(tc)

        assert result["status"] == "success", result
        assert len(calls) == 1, "run_plan() was not called for capability tool_call"
        payload = result["result"]
        tm = payload["trust_metadata"]
        assert tm["trust_class"] == "verified"
        assert tm["operation_coverage_complete"] is True
        assert tm["requested_operations"] == [expected_op_id]
        assert tm["executed_operations"] == [expected_op_id]
        assert tm["omitted_operations"] == []
        assert tm["learning_eligible"] is False
        assert tm["operator_acceptance_status"] == "unreviewed"
        if expected_answer:
            assert expected_answer in payload["answer_text"]
        return payload

    def test_count_rows_runs_plan(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = f'How many rows are in "{rel}"?'
        self._run_and_verify(table_tmp_path, prompt, "op_count_rows", "There are 3 data rows")

    def test_max_runs_plan(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = f'What is the highest Score in "{rel}"?'
        self._run_and_verify(table_tmp_path, prompt, "op_max", "The highest Score is 91")

    def test_min_runs_plan(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = f'What is the lowest Score in "{rel}"?'
        self._run_and_verify(table_tmp_path, prompt, "op_min", "The lowest Score is 78")

    def test_sum_runs_plan(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = f'Sum the Score column in "{rel}"'
        self._run_and_verify(table_tmp_path, prompt, "op_sum", "The sum of Score is 254")

    def test_average_runs_plan(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = f'What is the average Score in "{rel}"?'
        self._run_and_verify(table_tmp_path, prompt, "op_average", "84.6666666667")

    def test_overview_runs_plan(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = f'Analyze "{rel}".'
        self._run_and_verify(table_tmp_path, prompt, "op_overview")

    def test_associated_row_runs_plan(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = f'Which Name has the highest Score in "{rel}"?'
        payload = self._run_and_verify(table_tmp_path, prompt, "op_max", "Bob")
        assert payload["associated"]["associated_rows"][0]["associated_value"] == "Bob"

    def test_single_filter_runs_plan(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = f'Show rows where Score is greater than 80 in "{rel}"'
        payload = self._run_and_verify(table_tmp_path, prompt, "op_filter")
        rows = payload["rows"]
        assert len(rows) == 2
        names = {
            next(c["value"] for c in r["cells"] if c["column_name"] == "Name")
            for r in rows
        }
        assert names == {"Alice", "Bob"}


# ── Real Planner/LLM TableAnalysisPlanV1 production ─────────────────────────


class TestRealPlannerTablePlanProduction:
    """F5R-FIX3: Planner/LLM owns non-trivial natural-language interpretation.

    The deterministic parser only validates the Planner's structured proposal and
    lowers it through the capability boundary; it does not author the plan from raw text.
    """

    def _valid_proposal(self, rel: str, include_sort: bool = True) -> dict:
        ops = [
            {
                "operation_id": "op_filter_1",
                "type": "filter",
                "column": "Score",
                "operator": "gt",
                "value": "80",
            },
            {
                "operation_id": "op_filter_2",
                "type": "filter",
                "column": "Age",
                "operator": "lt",
                "value": "35",
            },
        ]
        requested = ["op_filter_1", "op_filter_2"]
        result_op = "op_filter_2"
        if include_sort:
            ops.append(
                {
                    "operation_id": "op_sort_1",
                    "type": "sort",
                    "column": "Name",
                    "direction": "asc",
                }
            )
            requested.append("op_sort_1")
            result_op = "op_sort_1"
        return {
            "version": "TableAnalysisPlanV1",
            "source": {"path": rel, "sheet": None},
            "operations": ops,
            "requested_operations": requested,
            "result_operation": result_op,
            "bounds": _build_default_bounds(),
        }

    def _run_prompt_with_proposal(self, prompt: str, proposal: dict):
        with mock.patch(
            "system.orchestrator.orchestrator_planner.execute_llm",
            return_value=_mock_llm_table_plan_response(proposal),
        ) as mock_llm:
            result = plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")
            mock_llm.assert_called_once()
        return result

    def test_multi_filter_and_sort_planner_proposal_runs_end_to_end(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(
            os.path.join(BASE_PATH, rel),
            [
                ["Name", "Score", "Age"],
                ["Alice", "85", "30"],
                ["Bob", "91", "25"],
                ["Cara", "78", "35"],
                ["Dan", "88", "40"],
            ],
        )
        prompt = (
            f'Show rows where Score is greater than 80 and Age is less than 35 '
            f'in "{rel}" sorted by Name ascending'
        )
        proposal = self._valid_proposal(rel)

        # 1. Simple capability path declines composed parsing.
        assert compile_structured_data_analysis_workflow(prompt) is None
        assert is_structured_data_analysis_intent(prompt) is True

        # 2. Router chooses Planner fallback with StructuredDataAnalysisProfile.
        from system.orchestrator.capability_router import route_capability
        route = route_capability(prompt)
        assert route["route_decision"] == "ROUTE_FALLBACK_TO_PLANNER"
        assert route["recommended_profile"] == "StructuredDataAnalysisProfile"
        assert route["route_reason_code"] == "structured_data_analysis_requires_planner"
        assert route["candidate_workflow"] is None

        # 3-6. Planner is invoked, returns proposal, parser validates it, capability lowers it.
        result = self._run_prompt_with_proposal(prompt, proposal)
        assert result["status"] == "success"
        wf = result["workflow"]
        assert len(wf["steps"]) == 1
        step = wf["steps"][0]
        assert step["agent"] == "structured_data_analysis"
        cm = step["capability_metadata"]
        assert cm["route_reason_code"] == "planner_owned_composed_plan"
        assert cm["allowed_tool"] == "analyze_table"
        plan = cm["table_analysis_plan"]
        assert plan["version"] == "TableAnalysisPlanV1"
        assert [op["operation_id"] for op in plan["operations"]] == [
            "op_filter_1",
            "op_filter_2",
            "op_sort_1",
        ]
        assert plan["result_operation"] == "op_sort_1"
        assert step["tool_call"].startswith("USE_TOOL:")

        # 7-13. Execute the pre-validated analyze_table call through the runtime.
        from system.orchestrator.step_executor import execute_step
        exec_result = execute_step(step, wf)
        assert exec_result["execution_result"]["status"] == "success"
        payload = exec_result["last_result"]
        assert payload is not None

        # 14. Trust metadata proves complete-request coverage.
        tm = payload["trust_metadata"]
        assert tm["trust_class"] == "verified"
        assert tm["requested_operations"] == ["op_filter_1", "op_filter_2", "op_sort_1"]
        assert tm["executed_operations"] == ["op_filter_1", "op_filter_2", "op_sort_1"]
        assert tm["omitted_operations"] == []
        assert tm["operation_coverage_complete"] is True
        assert tm["result_complete"] is True
        assert tm["learning_eligible"] is False
        names = [
            next(c["value"] for c in r["cells"] if c["column_name"] == "Name")
            for r in payload["rows"]
        ]
        assert names == ["Alice", "Bob"]

    def test_capability_validator_rejects_incomplete_planner_plan(self):
        """Capability validation must reject a plan with missing requested operations."""
        from system.orchestrator.structured_data.table_analysis_plan import (
            build_multi_filter_sort_plan,
        )

        plan = build_multi_filter_sort_plan(
            source_path="tmp/data.csv",
            filters=[{"column": "Score", "filter_op": "gt", "filter_value": "80"}],
        )
        # Tamper: claim a second requested operation that does not exist.
        plan["requested_operations"].append("op_filter_ghost")
        assert validate_and_build_structured_data_workflow("test prompt", plan) is None

    def test_capability_validator_rejects_unsupported_operation_type(self):
        from system.orchestrator.structured_data.table_analysis_plan import (
            build_multi_filter_sort_plan,
        )
        plan = build_multi_filter_sort_plan(
            source_path="tmp/data.csv",
            filters=[{"column": "Score", "filter_op": "gt", "filter_value": "80"}],
        )
        plan["operations"][0]["type"] = "group_by"
        assert validate_and_build_structured_data_workflow("test prompt", plan) is None

    def test_capability_still_accepts_simple_filter(self, table_tmp_path):
        """Simple deterministic fast paths remain capability-owned."""
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(
            os.path.join(BASE_PATH, rel),
            [["Name", "Score"], ["Alice", "85"], ["Bob", "91"], ["Cara", "78"]],
        )
        prompt = f'Show rows where Score is greater than 80 in "{rel}"'
        wf = compile_structured_data_analysis_workflow(prompt)
        assert wf is not None
        cm = wf["steps"][0]["capability_metadata"]
        assert cm["route_reason_code"] == "accepted_structured_data_analysis"
        assert cm["table_analysis_plan"]["operations"][0]["type"] == "filter"


# ── Planner proposal failure handling ───────────────────────────────────────


class TestPlannerTablePlanProposalFailures:
    """Invalid or partial Planner proposals must not produce verified execution."""

    def _base_prompt(self, rel: str) -> str:
        return (
            f'Show rows where Score is greater than 80 and Age is less than 35 '
            f'in "{rel}" sorted by Name ascending'
        )

    def _base_proposal(self, rel: str) -> dict:
        return {
            "version": "TableAnalysisPlanV1",
            "source": {"path": rel, "sheet": None},
            "operations": [
                {
                    "operation_id": "op_filter_1",
                    "type": "filter",
                    "column": "Score",
                    "operator": "gt",
                    "value": "80",
                },
                {
                    "operation_id": "op_filter_2",
                    "type": "filter",
                    "column": "Age",
                    "operator": "lt",
                    "value": "35",
                },
                {
                    "operation_id": "op_sort_1",
                    "type": "sort",
                    "column": "Name",
                    "direction": "asc",
                },
            ],
            "requested_operations": ["op_filter_1", "op_filter_2", "op_sort_1"],
            "result_operation": "op_sort_1",
            "bounds": _build_default_bounds(),
        }

    def _run_with_proposal(self, prompt: str, proposal: dict):
        with mock.patch(
            "system.orchestrator.orchestrator_planner.execute_llm",
            return_value=_mock_llm_table_plan_response(proposal),
        ):
            return plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")

    def test_omits_second_filter(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        proposal = self._base_proposal(rel)
        proposal["operations"] = [op for op in proposal["operations"] if op["operation_id"] != "op_filter_2"]
        proposal["requested_operations"] = ["op_filter_1", "op_sort_1"]
        result = self._run_with_proposal(prompt, proposal)
        assert result["status"] != "success"

    def test_omits_sort(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        proposal = self._base_proposal(rel)
        proposal["operations"] = [op for op in proposal["operations"] if op["type"] != "sort"]
        proposal["requested_operations"] = ["op_filter_1", "op_filter_2"]
        proposal["result_operation"] = "op_filter_2"
        result = self._run_with_proposal(prompt, proposal)
        assert result["status"] != "success"

    def test_contains_unsupported_or(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel).replace("and", "or")
        proposal = self._base_proposal(rel)
        # The prompt uses 'or', but the proposal still claims AND semantics.
        result = self._run_with_proposal(prompt, proposal)
        assert result["status"] != "success"

    def test_unknown_operation_type(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        proposal = self._base_proposal(rel)
        proposal["operations"][0]["type"] = "group_by"
        result = self._run_with_proposal(prompt, proposal)
        assert result["status"] != "success"

    def test_malformed_json(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        with mock.patch(
            "system.orchestrator.orchestrator_planner.execute_llm",
            return_value={"status": "success", "result": "not valid json"},
        ):
            result = plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")
        assert result["status"] != "success"

    def test_exceeds_bounds(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        proposal = self._base_proposal(rel)
        proposal["operations"] = [
            {"operation_id": f"op_filter_{i}", "type": "filter", "column": "Score", "operator": "gt", "value": str(i)}
            for i in range(9)
        ] + [{
            "operation_id": "op_sort_1",
            "type": "sort",
            "column": "Name",
            "direction": "asc",
        }]
        proposal["requested_operations"] = [op["operation_id"] for op in proposal["operations"]]
        proposal["result_operation"] = "op_sort_1"
        result = self._run_with_proposal(prompt, proposal)
        assert result["status"] != "success"

    def test_unknown_requested_operation_id(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        proposal = self._base_proposal(rel)
        proposal["requested_operations"].append("op_ghost")
        result = self._run_with_proposal(prompt, proposal)
        assert result["status"] != "success"

    def test_wrong_source(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        proposal = self._base_proposal(rel)
        proposal["source"]["path"] = "other/path.csv"
        result = self._run_with_proposal(prompt, proposal)
        assert result["status"] != "success"

    def test_invalid_result_operation(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        proposal = self._base_proposal(rel)
        proposal["result_operation"] = "op_nonexistent"
        result = self._run_with_proposal(prompt, proposal)
        assert result["status"] != "success"


# ── Missing-source full workflow runtime ──────────────────────────────────────


class TestMissingSourceFullWorkflowRuntime:
    """Missing-source structured-data prompts must complete deterministically
    through the normal workflow path without calling analyze_table or retrying."""

    def test_missing_path_filter_guidance_executes_in_workflow(self):
        prompt = 'Show rows where Score is greater than 85'
        wf = compile_document_local_read_workflow(prompt)
        assert wf is not None
        step = wf["steps"][0]
        cm = step["capability_metadata"]
        assert cm["allowed_tool"] == "finalize_output"
        assert cm["route_reason_code"] == "missing_path_filter_guidance"
        tm = cm["trust_metadata"]
        assert tm["trust_class"] == "ambiguous"
        assert tm["ambiguity_reason"] == "missing_source_path"
        assert tm["clarification_needed"] is True
        assert tm["executed_operations"] == []
        assert tm["omitted_operations"] == ["op_filter"]

        from system.orchestrator import llm_executor
        from system.orchestrator.step_executor import execute_step
        with mock.patch.object(
            llm_executor,
            "execute_llm",
            side_effect=AssertionError("AG1 LLM must not be called for missing-source guidance"),
        ):
            result = execute_step(step, wf)

        assert result["execution_result"]["status"] == "success"
        result_payload = result["execution_result"]["result"]
        assert isinstance(result_payload, dict)
        assert "path" in result_payload["answer_text"].lower()
        tm = result_payload["trust_metadata"]
        assert tm["trust_class"] == "ambiguous"
        assert tm["ambiguity_reason"] == "missing_source_path"
        assert tm["clarification_needed"] is True
        assert tm["learning_eligible"] is False
        assert step.get("status") != "BLOCKED"


# ── Intermediate-filter truncation regression ───────────────────────────────


class TestIntermediateFilterTruncation:
    """Intermediate filter results must not be prematurely truncated.

    Regression: an earlier implementation capped each intermediate filter stage
    to max_rows_returned, silently dropping rows before later predicates could be
    applied. The final result must include all rows matching every predicate.
    """

    def test_second_predicate_keeps_rows_beyond_1000(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/large.csv"
        rows = [["Index", "Score", "Age"]]
        target_names = set()
        for i in range(1002):
            name = f"Name{i:04d}"
            score = str(i + 1)
            age = "30" if i in (900, 1100) else "25"
            if i in (900, 1100):
                target_names.add(name)
            rows.append([name, score, age])
        _write_csv(os.path.join(BASE_PATH, rel), rows)

        prompt = f'Show rows where Score is greater than 0 and Age is 30 in "{rel}" sorted by Index ascending'
        proposal = {
            "version": "TableAnalysisPlanV1",
            "source": {"path": rel, "sheet": None},
            "operations": [
                {
                    "operation_id": "op_filter_1",
                    "type": "filter",
                    "column": "Score",
                    "operator": "gt",
                    "value": "0",
                },
                {
                    "operation_id": "op_filter_2",
                    "type": "filter",
                    "column": "Age",
                    "operator": "eq",
                    "value": "30",
                },
                {
                    "operation_id": "op_sort_1",
                    "type": "sort",
                    "column": "Index",
                    "direction": "asc",
                },
            ],
            "requested_operations": ["op_filter_1", "op_filter_2", "op_sort_1"],
            "result_operation": "op_sort_1",
            "bounds": _build_default_bounds(),
        }

        with mock.patch(
            "system.orchestrator.orchestrator_planner.execute_llm",
            return_value=_mock_llm_table_plan_response(proposal),
        ) as mock_llm:
            result = plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")
            mock_llm.assert_called_once()

        assert result["status"] == "success"
        step = result["workflow"]["steps"][0]
        from system.orchestrator.step_executor import execute_step
        exec_result = execute_step(step, result["workflow"])
        assert exec_result["execution_result"]["status"] == "success"
        payload = exec_result["last_result"]
        assert payload["trust_metadata"]["trust_class"] == "verified"
        names = [
            next(c["value"] for c in r["cells"] if c["column_name"] == "Index")
            for r in payload["rows"]
        ]
        assert names == sorted(target_names)


# ── Trust metadata and advisory blocker ──────────────────────────────────────


class TestTrustMetadataAndAdvisoryBlocker:
    """Trust metadata semantics survive the full execution pipeline."""

    def test_trust_metadata_fields_present_after_system_entry(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(os.path.join(BASE_PATH, rel), [["Name", "Score"], ["A", "10"]])
        wf = compile_structured_data_analysis_workflow(f'Count rows in "{rel}"')
        tc = _strip_use_tool(wf["steps"][0]["tool_call"])
        result = system_entry(tc)
        tm = result["result"]["trust_metadata"]
        required = {
            "trust_class",
            "verification_status",
            "plan_version",
            "plan_source_path",
            "requested_operations",
            "executed_operations",
            "omitted_operations",
            "operation_coverage_complete",
            "result_complete",
            "evidence_refs",
            "source_context_refs",
            "context_scope",
            "context_complete",
            "advisory_disclaimer",
            "unsupported_reason",
            "ambiguity_reason",
            "clarification_needed",
            "limitations",
            "warnings",
            "learning_eligible",
            "operator_acceptance_status",
        }
        assert required.issubset(tm.keys())
        assert tm["trust_class"] == "verified"
        assert tm["verification_status"] == "verified"
        assert tm["learning_eligible"] is False
        assert tm["operator_acceptance_status"] == "unreviewed"

    def test_unsupported_operation_produces_unsupported_trust_class(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(os.path.join(BASE_PATH, rel), [["Name", "Score"], ["A", "10"]])
        from system.orchestrator.structured_data.table_analysis_plan import (
            build_single_op_plan,
            MAX_OPERATIONS,
            MAX_PREDICATES,
            MAX_ROWS_SCANNED,
            MAX_ROWS_RETURNED,
        )

        plan = build_single_op_plan(
            source_path=rel,
            operation_type="correlate",
            operation_id="op_correlate",
            column="Score",
        )
        tc = _build_tool_call_for_plan(plan)
        result = system_entry(tc)
        assert result["status"] == "failure"
        assert "plan_validation_failed" in result["reason"]


# ── Profile boundaries / legacy path non-usage ───────────────────────────────


class TestProfileBoundariesAndLegacyPath:
    """Capability-produced calls must not fall through to the legacy flat path."""

    def test_legacy_positional_args_alone_still_work(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(os.path.join(BASE_PATH, rel), [["Name", "Score"], ["A", "10"]])
        tc = f'analyze_table "{rel}" "max" "Score" "" "" "" "" ""'
        result = system_entry(tc)
        assert result["status"] == "success"
        assert "The highest Score is 10" in result["result"]["answer_text"]

    def test_capability_tool_call_does_not_use_legacy_run(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(os.path.join(BASE_PATH, rel), [["Name", "Score"], ["A", "10"]])
        wf = compile_structured_data_analysis_workflow(f'What is the highest Score in "{rel}"?')
        tc = _strip_use_tool(wf["steps"][0]["tool_call"])

        _mod_globals = _analyze_table_globals()
        legacy_calls = []
        original_impl = _mod_globals["_analyze_table_impl"]

        def _spy_legacy(*args, **kwargs):
            legacy_calls.append((args, kwargs))
            return original_impl(*args, **kwargs)

        with mock.patch.dict(_mod_globals, _analyze_table_impl=_spy_legacy):
            result = system_entry(tc)

        assert result["status"] == "success"
        # Single-op plans still invoke _analyze_table_impl for the actual numeric
        # computation, but the entry point must be run() with plan-mode token and
        # return TableAnalysisPlanV1 trust metadata.
        assert result["result"]["trust_metadata"]["plan_version"] == "TableAnalysisPlanV1"


# ── F5R-FIX4: dedicated structured-data Planner contract ────────────────────


class TestDedicatedStructuredDataPlannerContract:
    """The dedicated StructuredDataAnalysisProfile route must reject prose,
    reject ordinary workflows, accept valid plan-only responses, and bound retries."""

    def _base_prompt(self, rel: str) -> str:
        return (
            f'Show rows where Score is greater than 80 and Age is less than 35 '
            f'in "{rel}" sorted by Name ascending'
        )

    def _base_plan(self, rel: str) -> dict:
        return {
            "version": "TableAnalysisPlanV1",
            "source": {"path": rel, "sheet": None},
            "operations": [
                {
                    "operation_id": "op_filter_1",
                    "type": "filter",
                    "column": "Score",
                    "operator": "gt",
                    "value": "80",
                },
                {
                    "operation_id": "op_filter_2",
                    "type": "filter",
                    "column": "Age",
                    "operator": "lt",
                    "value": "35",
                },
                {
                    "operation_id": "op_sort_1",
                    "type": "sort",
                    "column": "Name",
                    "direction": "asc",
                },
            ],
            "requested_operations": ["op_filter_1", "op_filter_2", "op_sort_1"],
            "result_operation": "op_sort_1",
            "bounds": _build_default_bounds(),
        }

    def _direct_response(self, plan: dict):
        return {"status": "success", "result": json.dumps(plan)}

    def test_prose_response_rejected_after_bounded_retry(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        prose = (
            "Based on the provided text, it appears that you want me to generate a JSON output "
            "for a series of steps based on user inputs. Please provide the user input."
        )
        with mock.patch(
            "system.orchestrator.orchestrator_planner.execute_llm",
            return_value={"status": "success", "result": prose},
        ) as mock_llm:
            result = plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")
            assert mock_llm.call_count == 2

        assert result["status"] == "failure"
        assert result["reason"].startswith("structured_data")

    def test_steps_only_workflow_rejected(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        steps_only = json.dumps({
            "steps": [
                {"name": "Read csv file", "purpose": f"Read csv file at {rel}", "agent": "file_executor", "estimated_complexity": "low"},
                {"name": "Filter rows", "purpose": "Filter rows", "agent": "general_agent", "estimated_complexity": "medium"},
                {"name": "Sort rows", "purpose": "Sort rows", "agent": "general_agent", "estimated_complexity": "low"},
            ]
        })
        with mock.patch(
            "system.orchestrator.orchestrator_planner.execute_llm",
            return_value={"status": "success", "result": steps_only},
        ) as mock_llm:
            result = plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")
            assert mock_llm.call_count == 2

        assert result["status"] == "failure"

    def test_valid_plan_only_response_accepted(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(
            os.path.join(BASE_PATH, rel),
            [["Name", "Score", "Age"], ["Alice", "85", "30"], ["Bob", "91", "25"], ["Cara", "78", "35"]],
        )
        prompt = self._base_prompt(rel)
        plan = self._base_plan(rel)
        with mock.patch(
            "system.orchestrator.orchestrator_planner.execute_llm",
            return_value=self._direct_response(plan),
        ) as mock_llm:
            result = plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")
            mock_llm.assert_called_once()

        assert result["status"] == "success"
        step = result["workflow"]["steps"][0]
        assert step["agent"] == "structured_data_analysis"
        from system.orchestrator.step_executor import execute_step
        exec_result = execute_step(step, result["workflow"])
        assert exec_result["execution_result"]["status"] == "success"
        payload = exec_result["last_result"]
        assert payload["trust_metadata"]["trust_class"] == "verified"
        names = [next(c["value"] for c in r["cells"] if c["column_name"] == "Name") for r in payload["rows"]]
        assert names == ["Alice", "Bob"]

    def test_first_invalid_then_valid_plan(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        plan = self._base_plan(rel)
        prose = "I cannot do that. Please clarify."
        with mock.patch(
            "system.orchestrator.orchestrator_planner.execute_llm",
            side_effect=[
                {"status": "success", "result": prose},
                self._direct_response(plan),
            ],
        ) as mock_llm:
            result = plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")
            assert mock_llm.call_count == 2

        assert result["status"] == "success"

    def test_two_invalid_responses_fail_explicitly(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        prose = "I cannot do that."
        steps_only = json.dumps({"steps": []})
        with mock.patch(
            "system.orchestrator.orchestrator_planner.execute_llm",
            side_effect=[
                {"status": "success", "result": prose},
                {"status": "success", "result": steps_only},
            ],
        ) as mock_llm:
            result = plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")
            assert mock_llm.call_count == 2

        assert result["status"] == "failure"
        assert result["reason"].startswith("structured_data")

    def test_wrapped_proposal_still_accepted(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        prompt = self._base_prompt(rel)
        plan = self._base_plan(rel)
        with mock.patch(
            "system.orchestrator.orchestrator_planner.execute_llm",
            return_value=_mock_llm_table_plan_response(plan),
        ) as mock_llm:
            result = plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")
            mock_llm.assert_called_once()

        assert result["status"] == "success"


# ── F5R-FIX4: associated-row coverage ─────────────────────────────────────────


class TestAssociatedRowCoverage:
    """Who requests must preserve the associated-column requirement through the plan."""

    def test_who_highest_score_returns_associated_name(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/scores.csv"
        _write_csv(
            os.path.join(BASE_PATH, rel),
            [["Name", "Score"], ["Alice", "85"], ["Bob", "91"], ["Cara", "78"]],
        )
        prompt = f'Who has the highest Score in "{rel}"?'
        wf = compile_structured_data_analysis_workflow(prompt)
        assert wf is not None
        step = wf["steps"][0]
        plan = step["capability_metadata"]["table_analysis_plan"]
        assert plan["operations"][0].get("associated_column") == "__AUTO_NAME_LIKE__"

        from system.orchestrator.step_executor import execute_step
        result = execute_step(step, wf)
        payload = result["last_result"]
        assert payload["trust_metadata"]["trust_class"] == "verified"
        assert payload["answer_text"] == "The highest Score is 91. This corresponds to Bob."
        assert payload["associated"]["associated_rows"][0]["associated_value"] == "Bob"

    def test_who_without_name_like_column_is_ambiguous(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/data.csv"
        _write_csv(
            os.path.join(BASE_PATH, rel),
            [["A", "B"], ["x", "10"], ["y", "20"]],
        )
        prompt = f'Who has the highest B in "{rel}"?'
        wf = compile_structured_data_analysis_workflow(prompt)
        assert wf is not None
        step = wf["steps"][0]
        from system.orchestrator.step_executor import execute_step
        result = execute_step(step, wf)
        payload = result["last_result"]
        assert payload["trust_metadata"]["trust_class"] == "ambiguous"

    def test_who_with_multiple_name_like_columns_is_ambiguous(self, table_tmp_path):
        rel = _rel(table_tmp_path) + "/data.csv"
        _write_csv(
            os.path.join(BASE_PATH, rel),
            [["FirstName", "LastName", "Score"], ["A", "X", "10"], ["B", "Y", "20"]],
        )
        prompt = f'Who has the highest Score in "{rel}"?'
        wf = compile_structured_data_analysis_workflow(prompt)
        assert wf is not None
        step = wf["steps"][0]
        from system.orchestrator.step_executor import execute_step
        result = execute_step(step, wf)
        payload = result["last_result"]
        assert payload["trust_metadata"]["trust_class"] == "ambiguous"


# ── F5R-FIX4: live local-Planner smoke ─────────────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM") != "1",
    reason="Live LLM smoke test; set RUN_LIVE_LLM=1 to run",
)
def test_live_local_planner_composed_request_smoke():
    """One non-automated live Planner smoke for the real composed prompt."""
    rel = "tmp/f5r_gui_composed.csv"
    prompt = (
        f'Find rows where Score is greater than 5 and Department is Engineering, '
        f'then sort by Name ascending in "{rel}".'
    )
    result = plan_workflow(prompt, profile_name="StructuredDataAnalysisProfile")
    assert result["status"] == "success", f"Planning failed: {result}"
    step = result["workflow"]["steps"][0]
    from system.orchestrator.step_executor import execute_step
    exec_result = execute_step(step, result["workflow"])
    assert exec_result["execution_result"]["status"] == "success"
    payload = exec_result["last_result"]
    assert payload["trust_metadata"]["trust_class"] == "verified"
    names = [next(c["value"] for c in r["cells"] if c["column_name"] == "Name") for r in payload["rows"]]
    assert names == ["Alice", "Zoe"]

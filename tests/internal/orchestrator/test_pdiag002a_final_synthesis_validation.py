"""
CATEGORY: INTERNAL_RUNTIME
AUTHORITY_LAYER: Runtime Behavioral Truth
VALIDATES:
  - ISSUE-PDIAG-002A Final Synthesis Step Dependency Validation
  - Final synthesis steps must declare dependencies on all prior source steps
  - Non-synthesis steps and single-step workflows are unaffected
  - Prior synthesis steps are not blindly required as source dependencies
ENTRYPOINT: validate_workflow
DIRECT_INTERNAL_CALLS:
  - workflow_validator.validate_workflow
  - workflow_validator._is_synthesis_step
  - workflow_validator._is_all_prior_synthesis_step
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: DIRECT_FUNCTION_CALLS
TEST_INTENT: BEHAVIORAL_VALIDATION
ARCHITECTURAL_SCOPE: Workflow validation (pre-resolution)
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.workflow_validator import validate_workflow


class TestPdiag002aFinalSynthesisValidation:
    def _make_workflow(self, steps):
        return {
            "id": "wf_test",
            "name": "test_workflow",
            "status": "QUEUED",
            "steps": steps
        }

    def _make_step(self, step_id, purpose, depends_on=None, expected_outcome="Done"):
        return {
            "id": step_id,
            "type": "EXECUTE_API",
            "purpose": purpose,
            "expected_outcome": expected_outcome,
            "risk": "LOW",
            "importance": "MEDIUM",
            "resource_targets": [],
            "depends_on": depends_on or []
        }

    # 1. final synthesis step with "summarize all findings" and empty depends_on is rejected
    def test_summarize_all_findings_empty_deps_rejected(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "summarize all findings", expected_outcome="Combined summary")
        ])
        result = validate_workflow(wf)
        assert result["status"] == "failure"
        assert result["reason"] == "under_declared_synthesis_dependencies"
        assert result["step_id"] == "step_3"
        assert "step_1" in result["missing_dependencies"]
        assert "step_2" in result["missing_dependencies"]

    # 2. final synthesis step with "compare the results" and empty depends_on is rejected
    def test_compare_results_empty_deps_rejected(self):
        wf = self._make_workflow([
            self._make_step("step_1", "calculate value A"),
            self._make_step("step_2", "calculate value B"),
            self._make_step("step_3", "compare the results")
        ])
        result = validate_workflow(wf)
        assert result["status"] == "failure"
        assert result["reason"] == "under_declared_synthesis_dependencies"
        assert result["step_id"] == "step_3"

    # 3. final synthesis step with "write final report from the sources" and only one dependency is rejected
    def test_final_report_one_dep_rejected(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "write final report from the sources", depends_on=["step_1"])
        ])
        result = validate_workflow(wf)
        assert result["status"] == "failure"
        assert result["reason"] == "under_declared_synthesis_dependencies"
        assert "step_2" in result["missing_dependencies"]

    # 4. final synthesis step with "use all previous results" and all prior source dependencies declared is accepted
    def test_use_all_previous_results_all_deps_accepted(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "use all previous results", depends_on=["step_1", "step_2"])
        ])
        result = validate_workflow(wf)
        assert result["status"] == "success"

    # 5. final synthesis step with explicit step_1 and step_2 references and both dependencies declared remains accepted
    def test_explicit_refs_both_deps_accepted(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "combine result of step_1 and result of step_2", depends_on=["step_1", "step_2"])
        ])
        result = validate_workflow(wf)
        assert result["status"] == "success"

    # 6. final synthesis step with explicit step_1 and step_2 references but only step_1 declared remains rejected by PDIAG-001
    def test_explicit_refs_partial_deps_rejected_by_pdiag001(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "combine result of step_1 and result of step_2", depends_on=["step_1"])
        ])
        result = validate_workflow(wf)
        assert result["status"] == "failure"
        assert result["reason"] == "partial_dependency_declaration"
        assert "step_2" in result["missing_dependencies"]

    # 7. non-synthesis independent step with no depends_on remains accepted
    def test_non_synthesis_no_deps_accepted(self):
        wf = self._make_workflow([
            self._make_step("step_1", "read file foo.txt"),
            self._make_step("step_2", "calculate sum of 5 and 10")
        ])
        result = validate_workflow(wf)
        assert result["status"] == "success"

    # 8. single-step workflow is not rejected merely because it contains a synthesis-like word
    def test_single_step_synthesis_word_accepted(self):
        wf = self._make_workflow([
            self._make_step("step_1", "summarize the document")
        ])
        result = validate_workflow(wf)
        assert result["status"] == "success"

    # 9. intermediate text-producing step is not rejected unless it clearly claims final/all-prior/multi-source synthesis
    def test_intermediate_text_step_not_rejected(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "generate a note about the topic"),
            self._make_step("step_3", "read file foo.txt")
        ])
        result = validate_workflow(wf)
        assert result["status"] == "success"

    # 10. prior synthesis/final-output steps are not blindly required as source dependencies
    def test_prior_synthesis_not_blindly_required(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "summarize the initial findings"),
            self._make_step("step_3", "read file bar.txt"),
            self._make_step("step_4", "write final report from the sources", depends_on=["step_1", "step_3"])
        ])
        result = validate_workflow(wf)
        assert result["status"] == "success"
        # step_2 is a prior synthesis step and is NOT required; validation passes
        # because step_4 declares all required non-synthesis prior dependencies

    # 11. "read the report file" is not treated as synthesis
    def test_read_report_file_not_synthesis(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read the report file"),
            self._make_step("step_3", "write final report from the sources", depends_on=["step_1", "step_2"])
        ])
        result = validate_workflow(wf)
        assert result["status"] == "success"

    # 12. "generate a status report for X" is not treated as all-prior synthesis
    def test_generate_status_report_not_all_prior(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "generate a status report for project X"),
            self._make_step("step_3", "read file foo.txt")
        ])
        result = validate_workflow(wf)
        assert result["status"] == "success"

    # 13. targeted synthesis "summarize step_1" does not require unrelated step_2
    def test_targeted_synthesis_no_universal_requirement(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "summarize step_1", depends_on=["step_1"])
        ])
        result = validate_workflow(wf)
        assert result["status"] == "success"

    # 14. "summarize step_1" without depends_on is rejected by PDIAG-001, not PDIAG-002A
    def test_targeted_synthesis_missing_explicit_ref_rejected_by_pdiag001(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "summarize step_1")
        ])
        result = validate_workflow(wf)
        assert result["status"] == "failure"
        assert result["reason"] == "partial_dependency_declaration"
        assert "step_1" in result["missing_dependencies"]

    # 15. intermediate step with "all previous results" is checked even if not final
    def test_intermediate_all_previous_checked(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "write summary using all previous results"),
            self._make_step("step_4", "save the output")
        ])
        result = validate_workflow(wf)
        assert result["status"] == "failure"
        assert result["reason"] == "under_declared_synthesis_dependencies"
        assert result["step_id"] == "step_3"

    # 16. "report" with synthesis context in final step is detected
    def test_report_with_context_final_step_detected(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "generate final report from all sources")
        ])
        result = validate_workflow(wf)
        assert result["status"] == "failure"
        assert result["reason"] == "under_declared_synthesis_dependencies"

    # 17. "report" without synthesis context in final step is NOT detected
    def test_report_without_context_final_step_not_detected(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "generate status report for external client")
        ])
        result = validate_workflow(wf)
        assert result["status"] == "success"

    # 18. prior synthesis step explicitly referenced is still validated by PDIAG-001
    def test_prior_synthesis_explicitly_referenced_pdiag001(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "summarize initial findings"),
            self._make_step("step_3", "combine result of step_1 and result of step_2", depends_on=["step_1"])
        ])
        result = validate_workflow(wf)
        assert result["status"] == "failure"
        assert result["reason"] == "partial_dependency_declaration"
        assert "step_2" in result["missing_dependencies"]

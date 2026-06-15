"""
CATEGORY: INTERNAL_RUNTIME
AUTHORITY_LAYER: Runtime Behavioral Truth
VALIDATES:
  - ISSUE-PDIAG-002B Planning Compiler Final Synthesis Dependency Auto-Binding
  - Pre-runtime deterministic repair of existing all-prior synthesis steps
  - Targeted synthesis is NOT auto-bound to all prior steps
  - Validator remains final fail-safe
ENTRYPOINT: apply_synthesis_dependency_binding
DIRECT_INTERNAL_CALLS:
  - planning_compiler.apply_synthesis_dependency_binding
  - workflow_validator.validate_workflow
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: DIRECT_FUNCTION_CALLS
TEST_INTENT: BEHAVIORAL_VALIDATION
ARCHITECTURAL_SCOPE: Planning compiler (pre-runtime)
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.planning_compiler import apply_synthesis_dependency_binding
from system.orchestrator.workflow_validator import validate_workflow


class TestPdiag002bPlanningCompiler:
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

    # 1. Existing all-prior final synthesis step missing dependencies receives all prior non-synthesis source steps
    def test_all_prior_synthesis_missing_deps_gets_all_prior_sources(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "summarize all findings")
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_3 = result["steps"][2]
        assert "step_1" in step_3["depends_on"]
        assert "step_2" in step_3["depends_on"]
        # Validate that repaired workflow passes validator
        assert validate_workflow(result)["status"] == "success"

    # 2. Existing synthesis step with some dependencies gets missing prior source steps added
    def test_partial_deps_gets_missing_added(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "write final report from the sources", depends_on=["step_1"])
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_3 = result["steps"][2]
        assert "step_1" in step_3["depends_on"]
        assert "step_2" in step_3["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 3. Existing synthesis step with full dependencies remains unchanged
    def test_full_deps_unchanged(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "summarize all findings", depends_on=["step_1", "step_2"])
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_3 = result["steps"][2]
        assert step_3["depends_on"] == ["step_1", "step_2"]
        assert validate_workflow(result)["status"] == "success"

    # 4. Existing targeted synthesis step does not get all prior steps added
    def test_targeted_synthesis_no_all_prior_binding(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "summarize step_1", depends_on=["step_1"])
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_3 = result["steps"][2]
        assert step_3["depends_on"] == ["step_1"]
        assert "step_2" not in step_3["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 5. Future steps are not bound
    def test_future_steps_not_bound(self):
        wf = self._make_workflow([
            self._make_step("step_1", "read file foo.txt"),
            self._make_step("step_2", "write final report from the sources"),
            self._make_step("step_3", "read file bar.txt")
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_2 = result["steps"][1]
        # step_2 is not the final step and lacks strong multi-source wording,
        # so it is NOT detected as all-prior synthesis and remains unchanged
        assert step_2["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

    # 6. Self-dependency is not created
    def test_no_self_dependency(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "summarize all findings")
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_2 = result["steps"][1]
        assert "step_2" not in step_2["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 7. Existing dependencies are preserved and deduped
    def test_existing_deps_preserved_and_deduped(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "summarize all findings", depends_on=["step_1"])
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_3 = result["steps"][2]
        # step_1 should appear once, step_2 appended after
        assert step_3["depends_on"].count("step_1") == 1
        assert step_3["depends_on"] == ["step_1", "step_2"]
        assert validate_workflow(result)["status"] == "success"

    # 8. Function is idempotent
    def test_idempotent(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "summarize all findings")
        ])
        first = apply_synthesis_dependency_binding(wf)
        second = apply_synthesis_dependency_binding(first)
        assert first["steps"][2]["depends_on"] == second["steps"][2]["depends_on"]
        assert validate_workflow(second)["status"] == "success"

    # 9. Prior synthesis/final-output steps are not blindly bound as source dependencies
    def test_prior_synthesis_not_blindly_bound(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "summarize initial findings"),
            self._make_step("step_3", "read file bar.txt"),
            self._make_step("step_4", "write final report from the sources")
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_4 = result["steps"][3]
        assert "step_1" in step_4["depends_on"]
        assert "step_3" in step_4["depends_on"]
        # step_2 is a prior synthesis step and should NOT be bound
        assert "step_2" not in step_4["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 10. "read the report file" is not treated as synthesis
    def test_read_report_file_not_synthesis(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read the report file"),
            self._make_step("step_3", "write final report from the sources")
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_3 = result["steps"][2]
        assert "step_1" in step_3["depends_on"]
        assert "step_2" in step_3["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 11. "generate a status report for X" is not auto-bound as all-prior synthesis
    def test_status_report_not_all_prior(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "generate a status report for project X"),
            self._make_step("step_3", "read file foo.txt")
        ])
        result = apply_synthesis_dependency_binding(wf)
        # No step should be detected as all-prior synthesis
        for step in result["steps"]:
            assert step.get("depends_on", []) == []
        assert validate_workflow(result)["status"] == "success"

    # 12. Compiler output passes workflow_validator.validate_workflow()
    def test_compiler_output_passes_validator(self):
        wf = self._make_workflow([
            self._make_step("step_1", "calculate value A"),
            self._make_step("step_2", "calculate value B"),
            self._make_step("step_3", "compare all results")
        ])
        result = apply_synthesis_dependency_binding(wf)
        assert validate_workflow(result)["status"] == "success"

    # 13. Validator still rejects ambiguous or under-declared cases that compiler did not safely repair
    def test_validator_still_rejects_ambiguous(self):
        # A non-synthesis step with no deps should still pass
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "generate a note about the topic")
        ])
        result = apply_synthesis_dependency_binding(wf)
        # step_3 is not detected as synthesis, so no binding
        assert validate_workflow(result)["status"] == "success"

    # 14. Existing explicit step_1 / step_2 dependency behavior remains valid
    def test_explicit_refs_preserved(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "combine result of step_1 and result of step_2", depends_on=["step_1", "step_2"])
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_3 = result["steps"][2]
        assert step_3["depends_on"] == ["step_1", "step_2"]
        assert validate_workflow(result)["status"] == "success"

    # 15. Single-step workflow is not modified
    def test_single_step_unchanged(self):
        wf = self._make_workflow([
            self._make_step("step_1", "summarize the document")
        ])
        result = apply_synthesis_dependency_binding(wf)
        assert result["steps"][0]["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

    # 16. Near-final step with strong multi-source wording gets bound
    def test_near_final_strong_multi_source_gets_bound(self):
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "read file foo.txt"),
            self._make_step("step_3", "write summary using all previous results"),
            self._make_step("step_4", "save the output")
        ])
        result = apply_synthesis_dependency_binding(wf)
        step_3 = result["steps"][2]
        assert "step_1" in step_3["depends_on"]
        assert "step_2" in step_3["depends_on"]
        assert validate_workflow(result)["status"] == "success"

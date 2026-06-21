"""
CATEGORY: INTERNAL_RUNTIME
AUTHORITY_LAYER: Runtime Behavioral Truth
VALIDATES:
  - ISSUE-PDIAG-006-RS1 Same-Resource Sequencing Safety
  - Pre-runtime deterministic repair of missing same-resource file sequencing deps
  - Conservative: prefers no repair over broad inference
ENTRYPOINT: apply_resource_sequencing_binding
DIRECT_INTERNAL_CALLS:
  - planning_compiler.apply_resource_sequencing_binding
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

from system.orchestrator.planning_compiler import apply_resource_sequencing_binding
from system.orchestrator.workflow_validator import validate_workflow


class TestPdiag006Rs1ResourceSequencingCompiler:
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

    # 1. D.1 pattern: write -> read same file gets dependency
    def test_write_then_read_same_file_gets_dependency(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write 'hello' to C:\\temp\\test.txt"),
            self._make_step("step_2", "Read the contents of C:\\temp\\test.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 2. D.3 pattern: write -> edit -> read same file becomes ordered chain
    def test_write_edit_read_chain(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to file C:\\temp\\A.txt"),
            self._make_step("step_2", "Edit file C:\\temp\\A.txt"),
            self._make_step("step_3", "Read file C:\\temp\\A.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert "step_2" in result["steps"][2]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 3. D.4 pattern with sequence marker: read -> edit -> read gets dependency
    def test_read_edit_read_with_sequence_marker(self):
        user_input = "Read file C:\\temp\\A.txt, edit file C:\\temp\\A.txt, then read file C:\\temp\\A.txt again."
        wf = self._make_workflow([
            self._make_step("step_1", "Read file C:\\temp\\A.txt"),
            self._make_step("step_2", "Edit file C:\\temp\\A.txt"),
            self._make_step("step_3", "Read file C:\\temp\\A.txt again"),
        ])
        result = apply_resource_sequencing_binding(wf, user_input=user_input)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert "step_2" in result["steps"][2]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 4. read -> edit WITHOUT sequence marker does NOT repair
    def test_read_edit_without_marker_no_repair(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Read file C:\\temp\\A.txt"),
            self._make_step("step_2", "Edit file C:\\temp\\A.txt"),
        ])
        result = apply_resource_sequencing_binding(wf, user_input="Read file A, edit file A")
        assert result["steps"][1]["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

    # 5. D.10 pattern: write -> write same file gets dependency
    def test_two_writes_same_file_gets_dependency(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write 'X' to C:\\temp\\file.txt"),
            self._make_step("step_2", "Write 'Y' to C:\\temp\\file.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 6. edit -> edit same file gets dependency
    def test_two_edits_same_file_gets_dependency(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Edit C:\\temp\\file.txt replacing 'old' with 'new'"),
            self._make_step("step_2", "Edit C:\\temp\\file.txt replacing 'foo' with 'bar'"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 7. different file paths remain independent
    def test_different_file_paths_remain_independent(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to C:\\temp\\a.txt"),
            self._make_step("step_2", "Read C:\\temp\\b.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][1]["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

    # 8. existing dependencies are preserved
    def test_existing_dependencies_preserved(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to C:\\temp\\file.txt"),
            self._make_step("step_2", "Read C:\\temp\\file.txt", depends_on=["step_1"]),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][1]["depends_on"] == ["step_1"]
        assert validate_workflow(result)["status"] == "success"

    # 9. dependencies are deduped
    def test_dependencies_deduped(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to C:\\temp\\file.txt"),
            self._make_step("step_2", "Read C:\\temp\\file.txt", depends_on=["step_1"]),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][1]["depends_on"].count("step_1") == 1
        assert validate_workflow(result)["status"] == "success"

    # 10. repair is idempotent
    def test_repair_is_idempotent(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to C:\\temp\\file.txt"),
            self._make_step("step_2", "Read C:\\temp\\file.txt"),
        ])
        first = apply_resource_sequencing_binding(wf)
        second = apply_resource_sequencing_binding(first)
        assert first["steps"][1]["depends_on"] == second["steps"][1]["depends_on"]
        assert validate_workflow(second)["status"] == "success"

    # 11. no self or future dependencies are created
    def test_no_self_or_future_dependencies(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to C:\\temp\\file.txt"),
            self._make_step("step_2", "Read C:\\temp\\file.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_2" not in result["steps"][1]["depends_on"]
        assert "step_2" not in result["steps"][0]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 12. ambiguous paths are not repaired
    def test_ambiguous_path_no_repair(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to some file"),
            self._make_step("step_2", "Read a file"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][1]["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

    # 13. relative paths are not repaired
    def test_relative_path_no_repair(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to temp\\file.txt"),
            self._make_step("step_2", "Read temp\\file.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][1]["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

    # 14. URLs are not repaired
    def test_url_no_repair(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to https://example.com/data"),
            self._make_step("step_2", "Read https://example.com/data"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][1]["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

    # 15. path normalization is consistent (case and slash insensitive)
    def test_path_normalization_consistent(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to C:\\TEMP\\file.txt"),
            self._make_step("step_2", "Read c:/temp/file.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 16. trailing punctuation does not corrupt matching
    def test_trailing_punctuation_handled(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to C:\\temp\\file.txt."),
            self._make_step("step_2", "Read C:\\temp\\file.txt,"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 17. existing synthesis dependency binding still works alongside resource sequencing
    def test_existing_synthesis_binding_still_works(self):
        from system.orchestrator.planning_compiler import apply_synthesis_dependency_binding
        wf = self._make_workflow([
            self._make_step("step_1", "research topic A"),
            self._make_step("step_2", "Write to C:\\temp\\report.txt"),
            self._make_step("step_3", "Read C:\\temp\\report.txt"),
            self._make_step("step_4", "summarize all findings"),
        ])
        wf = apply_synthesis_dependency_binding(wf)
        wf = apply_resource_sequencing_binding(wf)
        # Synthesis binding: step_4 should depend on step_1 and step_3
        assert "step_1" in wf["steps"][3]["depends_on"]
        assert "step_3" in wf["steps"][3]["depends_on"]
        # Resource sequencing: step_3 should depend on step_2
        assert "step_2" in wf["steps"][2]["depends_on"]
        assert validate_workflow(wf)["status"] == "success"

    # 18. quoted paths are handled
    def test_quoted_paths_handled(self):
        wf = self._make_workflow([
            self._make_step("step_1", 'Write to "C:\\temp\\file.txt"'),
            self._make_step("step_2", "Read 'C:\\temp\\file.txt'"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 19. single-step workflow is not modified
    def test_single_step_unchanged(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to C:\\temp\\file.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][0]["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

    # 20. step without id is skipped
    def test_step_without_id_skipped(self):
        wf = self._make_workflow([
            {
                "purpose": "Write to C:\\temp\\file.txt",
                "type": "EXECUTE_API",
                "expected_outcome": "Done",
                "risk": "LOW",
                "importance": "MEDIUM",
                "resource_targets": [],
            },
            self._make_step("step_2", "Read C:\\temp\\file.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][1]["depends_on"] == []

    # === PDIAG-008B1: Bare filename sequencing tests ===

    # 21. live B2 failure: "named X.txt" write -> "Read X.txt" gets dependency
    def test_bare_filename_named_write_then_read_gets_dependency(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write the text alpha beta gamma to a local file named pdiag008_write.txt"),
            self._make_step("step_2", "Read pdiag008_write.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 22. "write to file X.txt" then "Read from X.txt" gets dependency
    def test_bare_filename_write_to_file_then_read_from_gets_dependency(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write 'hello' to file test.txt"),
            self._make_step("step_2", "Read from test.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 23. "create file called X.txt" then "Read X.txt" gets dependency
    def test_bare_filename_create_called_then_read_gets_dependency(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Create a file called output.txt"),
            self._make_step("step_2", "Read output.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert "step_1" in result["steps"][1]["depends_on"]
        assert validate_workflow(result)["status"] == "success"

    # 24. bare filename read alone (no prior write) does NOT create phantom dependency
    def test_bare_filename_read_alone_no_phantom_dependency(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Calculate some value"),
            self._make_step("step_2", "Read pdiag008_write.txt"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][1]["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

    # 25. non-file prose does not extract false path or create repair
    def test_non_file_prose_no_extraction(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Analyze version 1.0 results"),
            self._make_step("step_2", "Execute the next step"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][1]["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

    # 26. URL-like text does not create local file repair (example.com is a TLD, not a file ext)
    def test_url_like_text_no_local_file_repair(self):
        wf = self._make_workflow([
            self._make_step("step_1", "Write to https://example.com"),
            self._make_step("step_2", "Read example.com"),
        ])
        result = apply_resource_sequencing_binding(wf)
        assert result["steps"][1]["depends_on"] == []
        assert validate_workflow(result)["status"] == "success"

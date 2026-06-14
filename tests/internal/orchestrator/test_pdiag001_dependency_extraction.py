"""
CATEGORY: INTERNAL_RUNTIME
AUTHORITY_LAYER: Runtime Behavioral Truth
VALIDATES:
  - ISSUE-PDIAG-001 Multi-Reference Dependency Extraction
  - resolve_dependencies collects all explicit references
  - Partial dependency declarations are rejected before execution
  - Self/future/nonexistent references are rejected
  - All supported reference forms are handled
ENTRYPOINT: resolve_dependencies, validate_workflow
DIRECT_INTERNAL_CALLS:
  - orchestrator_planner.resolve_dependencies
  - workflow_validator.validate_workflow
  - workflow_validator._extract_explicit_step_references
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: DIRECT_FUNCTION_CALLS
TEST_INTENT: BEHAVIORAL_VALIDATION
ARCHITECTURAL_SCOPE: Planner dependency resolution + workflow validation

---

ISSUE-PDIAG-001 — Focused Tests
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.orchestrator_planner import resolve_dependencies
from system.orchestrator.workflow_validator import validate_workflow, _extract_explicit_step_references


# ===========================================================================
# _extract_explicit_step_references — unit tests
# ===========================================================================

class TestExtractExplicitReferences:
    def test_result_of_step_underscore(self):
        refs = _extract_explicit_step_references("combine result of step_1 and result of step_2")
        assert refs == ["step_1", "step_2"]

    def test_result_of_step_space(self):
        refs = _extract_explicit_step_references("combine result of step 1 and result of step 2")
        assert refs == ["step_1", "step_2"]

    def test_output_of_step_underscore(self):
        refs = _extract_explicit_step_references("merge output of step_1 and output of step_2")
        assert refs == ["step_1", "step_2"]

    def test_output_of_step_space(self):
        refs = _extract_explicit_step_references("merge output of step 1 and output of step 2")
        assert refs == ["step_1", "step_2"]

    def test_bare_step_underscore(self):
        refs = _extract_explicit_step_references("compare step_1 with step_2")
        assert refs == ["step_1", "step_2"]

    def test_bare_step_space(self):
        refs = _extract_explicit_step_references("compare step 1 with step 2")
        assert refs == ["step_1", "step_2"]

    def test_case_insensitive(self):
        refs = _extract_explicit_step_references("Compare Result Of Step_1 and OUTPUT OF STEP 2")
        assert refs == ["step_1", "step_2"]

    def test_dedupes_duplicates(self):
        refs = _extract_explicit_step_references("result of step_1 and result of step_1")
        assert refs == ["step_1"]

    def test_stable_first_seen_order(self):
        refs = _extract_explicit_step_references("result of step_2 then result of step_1")
        assert refs == ["step_2", "step_1"]

    def test_no_false_positive_vague_phrase(self):
        refs = _extract_explicit_step_references("the earlier result")
        assert refs == []

    def test_no_false_positive_no_digit(self):
        refs = _extract_explicit_step_references("step by step instructions")
        assert refs == []

    def test_no_false_positive_inside_word(self):
        refs = _extract_explicit_step_references("mystep_1 example")
        assert refs == []

    def test_empty_string(self):
        refs = _extract_explicit_step_references("")
        assert refs == []

    def test_none_input(self):
        refs = _extract_explicit_step_references(None)
        assert refs == []


# ===========================================================================
# resolve_dependencies — positive cases
# ===========================================================================

class TestResolveDependenciesPositive:
    def test_single_reference_preserved(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "multiply the result of step_1 by 4"}
        ]
        result = resolve_dependencies("add 2 and 3 then multiply by 4", steps)
        assert isinstance(result, list)
        assert result[0]["depends_on"] == []
        assert result[1]["depends_on"] == ["step_1"]

    def test_multi_reference_two_parents(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "multiply 4 and 5"},
            {"purpose": "combine result of step_1 and result of step_2"}
        ]
        result = resolve_dependencies("multi-parent test", steps)
        assert isinstance(result, list)
        assert result[0]["depends_on"] == []
        assert result[1]["depends_on"] == []
        assert result[2]["depends_on"] == ["step_1", "step_2"]

    def test_multi_reference_three_parents(self):
        steps = [
            {"purpose": "step a"},
            {"purpose": "step b"},
            {"purpose": "step c"},
            {"purpose": "merge result of step_1, step_2, and step_3"}
        ]
        result = resolve_dependencies("three-parent test", steps)
        assert result[3]["depends_on"] == ["step_1", "step_2", "step_3"]

    def test_duplicate_references_deduped(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "compare result of step_1 with result of step_1"}
        ]
        result = resolve_dependencies("dedup test", steps)
        assert result[1]["depends_on"] == ["step_1"]

    def test_step_space_variant(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "multiply result of step 1 by 4"}
        ]
        result = resolve_dependencies("space variant test", steps)
        assert result[1]["depends_on"] == ["step_1"]

    def test_output_of_variant(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "read output of step_1"}
        ]
        result = resolve_dependencies("output variant test", steps)
        assert result[1]["depends_on"] == ["step_1"]

    def test_output_of_space_variant(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "read output of step 1"}
        ]
        result = resolve_dependencies("output space variant test", steps)
        assert result[1]["depends_on"] == ["step_1"]

    def test_bare_step_reference(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "multiply 4 and 5"},
            {"purpose": "compare step_1 with step_2"}
        ]
        result = resolve_dependencies("bare reference test", steps)
        assert result[2]["depends_on"] == ["step_1", "step_2"]

    def test_independent_steps_no_dependency(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "multiply 4 and 5"}
        ]
        result = resolve_dependencies("independent test", steps)
        assert result[0]["depends_on"] == []
        assert result[1]["depends_on"] == []

    def test_stable_order_first_seen(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "multiply 4 and 5"},
            {"purpose": "combine result of step_2 and result of step_1"}
        ]
        result = resolve_dependencies("order test", steps)
        assert result[2]["depends_on"] == ["step_2", "step_1"]


# ===========================================================================
# resolve_dependencies — negative cases (invalid references rejected)
# ===========================================================================

class TestResolveDependenciesNegative:
    def test_self_reference_rejected(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "use result of step_2"}
        ]
        result = resolve_dependencies("self ref test", steps)
        assert isinstance(result, dict)
        assert result["status"] == "failure"
        assert result["reason"] == "self_dependency"

    def test_future_reference_rejected(self):
        steps = [
            {"purpose": "use result of step_2"},
            {"purpose": "add 2 and 3"}
        ]
        result = resolve_dependencies("future ref test", steps)
        assert isinstance(result, dict)
        assert result["status"] == "failure"
        assert result["reason"] == "future_dependency_reference"

    def test_nonexistent_reference_rejected(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "use result of step_99"}
        ]
        result = resolve_dependencies("nonexistent ref test", steps)
        assert isinstance(result, dict)
        assert result["status"] == "failure"
        assert result["reason"] == "invalid_dependency_reference"

    def test_vague_phrase_no_dependency(self):
        steps = [
            {"purpose": "add 2 and 3"},
            {"purpose": "use the earlier result"}
        ]
        result = resolve_dependencies("vague phrase test", steps)
        assert isinstance(result, list)
        assert result[1]["depends_on"] == []


# ===========================================================================
# validate_workflow — partial dependency declaration rejection
# ===========================================================================

class TestPartialDependencyValidation:
    def _make_workflow(self, steps):
        return {
            "id": "wf_test",
            "name": "test workflow",
            "status": "QUEUED",
            "steps": steps
        }

    def test_partial_dependency_rejected(self):
        workflow = self._make_workflow([
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "add 2 and 3",
                "expected_outcome": "sum is 5",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            },
            {
                "id": "step_2",
                "type": "EXECUTE_API",
                "purpose": "multiply 4 and 5",
                "expected_outcome": "product is 20",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            },
            {
                "id": "step_3",
                "type": "EXECUTE_API",
                "purpose": "combine result of step_1 and result of step_2",
                "expected_outcome": "merged output",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": ["step_1"]
            }
        ])
        result = validate_workflow(workflow)
        assert result["status"] == "failure"
        assert result["reason"] == "partial_dependency_declaration"
        assert result["step_id"] == "step_3"
        assert "step_2" in result["missing_dependencies"]

    def test_full_multi_dependency_accepted(self):
        workflow = self._make_workflow([
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "add 2 and 3",
                "expected_outcome": "sum is 5",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            },
            {
                "id": "step_2",
                "type": "EXECUTE_API",
                "purpose": "multiply 4 and 5",
                "expected_outcome": "product is 20",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            },
            {
                "id": "step_3",
                "type": "EXECUTE_API",
                "purpose": "combine result of step_1 and result of step_2",
                "expected_outcome": "merged output",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": ["step_1", "step_2"]
            }
        ])
        result = validate_workflow(workflow)
        assert result["status"] == "success"

    def test_expected_outcome_reference_checked(self):
        workflow = self._make_workflow([
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "add 2 and 3",
                "expected_outcome": "sum is 5",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            },
            {
                "id": "step_2",
                "type": "EXECUTE_API",
                "purpose": "do something",
                "expected_outcome": "result matches step_1 output",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            }
        ])
        result = validate_workflow(workflow)
        assert result["status"] == "failure"
        assert result["reason"] == "partial_dependency_declaration"
        assert "step_1" in result["missing_dependencies"]

    def test_no_dependency_workflow_passes(self):
        workflow = self._make_workflow([
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "add 2 and 3",
                "expected_outcome": "sum is 5",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            },
            {
                "id": "step_2",
                "type": "EXECUTE_API",
                "purpose": "multiply 4 and 5",
                "expected_outcome": "product is 20",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            }
        ])
        result = validate_workflow(workflow)
        assert result["status"] == "success"

    def test_single_dependency_workflow_passes(self):
        workflow = self._make_workflow([
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "add 2 and 3",
                "expected_outcome": "sum is 5",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            },
            {
                "id": "step_2",
                "type": "EXECUTE_API",
                "purpose": "multiply result of step_1 by 4",
                "expected_outcome": "product is 20",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": ["step_1"]
            }
        ])
        result = validate_workflow(workflow)
        assert result["status"] == "success"

    def test_vague_phrase_no_dependency_passes(self):
        workflow = self._make_workflow([
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "add 2 and 3",
                "expected_outcome": "sum is 5",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            },
            {
                "id": "step_2",
                "type": "EXECUTE_API",
                "purpose": "use the earlier result",
                "expected_outcome": "something",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            }
        ])
        result = validate_workflow(workflow)
        # "the earlier result" does not match explicit step patterns
        # and does not match the generic keyword list exactly,
        # so no dependency is inferred — workflow passes.
        assert result["status"] == "success"

    def test_self_dependency_rejected(self):
        workflow = self._make_workflow([
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "add 2 and 3",
                "expected_outcome": "sum is 5",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            },
            {
                "id": "step_2",
                "type": "EXECUTE_API",
                "purpose": "use result of step_2",
                "expected_outcome": "something",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": ["step_2"]
            }
        ])
        result = validate_workflow(workflow)
        assert result["status"] == "failure"
        assert result["reason"] == "self_dependency"

    def test_nonexistent_dependency_rejected(self):
        workflow = self._make_workflow([
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "add 2 and 3",
                "expected_outcome": "sum is 5",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": []
            },
            {
                "id": "step_2",
                "type": "EXECUTE_API",
                "purpose": "use result of step_99",
                "expected_outcome": "something",
                "risk": "LOW",
                "importance": "LOW",
                "resource_targets": [],
                "depends_on": ["step_99"]
            }
        ])
        result = validate_workflow(workflow)
        assert result["status"] == "failure"
        assert result["reason"] == "invalid_dependency_reference"


# ===========================================================================
# Regression: existing behavior preserved
# ===========================================================================

class TestRegressionPreserved:
    def test_existing_one_parent_still_valid(self):
        workflow = {
            "id": "wf_test",
            "name": "test",
            "status": "QUEUED",
            "steps": [
                {
                    "id": "step_1",
                    "type": "EXECUTE_API",
                    "purpose": "add 2 and 3",
                    "expected_outcome": "sum is 5",
                    "risk": "LOW",
                    "importance": "LOW",
                    "resource_targets": [],
                    "depends_on": []
                },
                {
                    "id": "step_2",
                    "type": "EXECUTE_API",
                    "purpose": "multiply result of step_1 by 4",
                    "expected_outcome": "product is 20",
                    "risk": "LOW",
                    "importance": "LOW",
                    "resource_targets": [],
                    "depends_on": ["step_1"]
                }
            ]
        }
        result = validate_workflow(workflow)
        assert result["status"] == "success"

    def test_cycle_still_rejected(self):
        workflow = {
            "id": "wf_test",
            "name": "test",
            "status": "QUEUED",
            "steps": [
                {
                    "id": "step_1",
                    "type": "EXECUTE_API",
                    "purpose": "depends on step_2",
                    "expected_outcome": "",
                    "risk": "LOW",
                    "importance": "LOW",
                    "resource_targets": [],
                    "depends_on": ["step_2"]
                },
                {
                    "id": "step_2",
                    "type": "EXECUTE_API",
                    "purpose": "depends on step_1",
                    "expected_outcome": "",
                    "risk": "LOW",
                    "importance": "LOW",
                    "resource_targets": [],
                    "depends_on": ["step_1"]
                }
            ]
        }
        result = validate_workflow(workflow)
        assert result["status"] == "failure"
        assert result["reason"] == "circular_dependency"

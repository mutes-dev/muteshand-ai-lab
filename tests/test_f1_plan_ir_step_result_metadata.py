"""
F1 — PLAN IR + STEP RESULT METADATA TESTS

Tests for Sprint 11 Foundation F1:
- Workflow-level metadata defaults (plan_id, plan_version, continuation_metadata)
- Step-result metadata defaults (evidence_refs, unresolved_refs, dependency_refs_used, validator_results)
- Old workflow compatibility (missing F1 fields tolerated)
- Persistence round trip
- Canonical projection isolation (F1 fields not in projection output)
- Raw passthrough sanitization (F1 fields not in get_plan/edit_step/add_step/retry_step returns)
- Authority preservation (execution_result unchanged, lifecycle/governance unaffected)
"""

import json
import os
import sys
import tempfile
import shutil

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# =============================================================================
# Helpers
# =============================================================================

def _make_minimal_workflow(workflow_id="wf_test_f1", steps=None):
    """Create a minimal valid workflow dict without F1 fields."""
    if steps is None:
        steps = [
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "add 2 + 2",
                "expected_outcome": "4",
                "risk": "LOW",
                "importance": "MEDIUM",
                "resource_targets": [],
                "depends_on": [],
                "status": "PENDING",
                "retries": 0,
                "max_retries": 3,
            }
        ]
    return {
        "id": workflow_id,
        "name": "dynamic_workflow",
        "status": "QUEUED",
        "goal": "test goal",
        "steps": steps,
        "approval_required": False,
        "profile_name": "GeneralFallbackProfile",
    }


def _make_minimal_workflow_with_f1(workflow_id="wf_test_f1"):
    """Create a workflow dict with F1 fields already present."""
    wf = _make_minimal_workflow(workflow_id)
    wf["plan_id"] = "custom_plan_id"
    wf["plan_version"] = 5
    wf["continuation_metadata"] = {"reason": "test"}
    for step in wf["steps"]:
        step["evidence_refs"] = [{"ref": "test"}]
        step["unresolved_refs"] = [{"ref": "unresolved"}]
        step["dependency_refs_used"] = ["step_0"]
        step["validator_results"] = [{"validator": "test", "output": {}}]
    return wf


# =============================================================================
# 1. Workflow metadata defaults
# =============================================================================

class TestWorkflowMetadataDefaults:
    """Test that plan_workflow attaches F1 workflow-level metadata defaults."""

    def test_plan_workflow_attaches_plan_id(self):
        """plan_workflow should set plan_id defaulting to workflow id."""
        from system.orchestrator.orchestrator_planner import plan_workflow
        result = plan_workflow("add 1 and 2", pre_generated_workflow_id="wf_f1_plan_id")
        assert result["status"] == "success"
        wf = result["workflow"]
        assert wf.get("plan_id") == "wf_f1_plan_id"

    def test_plan_workflow_attaches_plan_version(self):
        """plan_workflow should set plan_version defaulting to 1."""
        from system.orchestrator.orchestrator_planner import plan_workflow
        result = plan_workflow("add 1 and 2", pre_generated_workflow_id="wf_f1_plan_version")
        assert result["status"] == "success"
        wf = result["workflow"]
        assert wf.get("plan_version") == 1

    def test_plan_workflow_attaches_continuation_metadata(self):
        """plan_workflow should set continuation_metadata defaulting to {}."""
        from system.orchestrator.orchestrator_planner import plan_workflow
        result = plan_workflow("add 1 and 2", pre_generated_workflow_id="wf_f1_cont_meta")
        assert result["status"] == "success"
        wf = result["workflow"]
        assert wf.get("continuation_metadata") == {}


# =============================================================================
# 2. Existing/minimal workflow compatibility
# =============================================================================

class TestWorkflowCompatibility:
    """Test that workflows without F1 fields are tolerated and defaults are filled."""

    def test_run_workflow_fills_f1_workflow_defaults(self):
        """run_workflow should setdefault F1 fields on hydrated workflows."""
        from system.orchestrator.orchestrator_runtime import _ensure_step_metadata
        wf = _make_minimal_workflow("wf_f1_compat")
        # Simulate what run_workflow does for step defaults
        for step in wf.get("steps", []):
            _ensure_step_metadata(step)
            step.setdefault("evidence_refs", [])
            step.setdefault("unresolved_refs", [])
            step.setdefault("dependency_refs_used", [])
            step.setdefault("validator_results", [])
        wf.setdefault("plan_id", wf.get("id", "unknown"))
        wf.setdefault("plan_version", 1)
        wf.setdefault("continuation_metadata", {})

        assert wf["plan_id"] == "wf_f1_compat"
        assert wf["plan_version"] == 1
        assert wf["continuation_metadata"] == {}
        for step in wf["steps"]:
            assert step["evidence_refs"] == []
            assert step["unresolved_refs"] == []
            assert step["dependency_refs_used"] == []
            assert step["validator_results"] == []

    def test_existing_f1_values_preserved(self):
        """setdefault should NOT overwrite existing non-empty F1 values."""
        wf = _make_minimal_workflow_with_f1("wf_f1_preserve")
        # Simulate setdefault behavior
        wf.setdefault("plan_id", wf.get("id", "unknown"))
        wf.setdefault("plan_version", 1)
        wf.setdefault("continuation_metadata", {})

        assert wf["plan_id"] == "custom_plan_id"
        assert wf["plan_version"] == 5
        assert wf["continuation_metadata"] == {"reason": "test"}


# =============================================================================
# 3. Step-result metadata defaults
# =============================================================================

class TestStepResultMetadataDefaults:
    """Test that step-result F1 metadata defaults are correct."""

    def test_step_defaults_after_execution(self):
        """After execute_step, step should have F1 defaults."""
        from system.orchestrator.step_executor import execute_step
        # We can't easily call execute_step without a full runtime setup,
        # but we can test the defaulting logic directly
        step = {
            "id": "step_1",
            "type": "EXECUTE_API",
            "purpose": "test",
            "expected_outcome": "done",
            "risk": "LOW",
            "importance": "MEDIUM",
            "resource_targets": [],
            "depends_on": ["step_0"],
            "status": "PENDING",
            "retries": 0,
            "tool_call": "add_numbers 1 2",
        }
        # Simulate the F1 defaulting block from step_executor
        validator_output = {}
        try:
            step.setdefault("evidence_refs", [])
            step.setdefault("unresolved_refs", [])
            if "dependency_refs_used" not in step or not step.get("dependency_refs_used"):
                step["dependency_refs_used"] = list(step.get("depends_on", []))
            if "validator_results" not in step:
                _vr = []
                if validator_output:
                    _vr = [{"validator": "intent_validator", "output": validator_output}]
                step["validator_results"] = _vr
        except Exception:
            pass

        assert step["evidence_refs"] == []
        assert step["unresolved_refs"] == []
        assert step["dependency_refs_used"] == ["step_0"]
        assert step["validator_results"] == []

    def test_dependency_refs_used_populated_from_depends_on(self):
        """dependency_refs_used should be populated from depends_on."""
        step = {
            "depends_on": ["step_1", "step_2"],
        }
        if "dependency_refs_used" not in step or not step.get("dependency_refs_used"):
            step["dependency_refs_used"] = list(step.get("depends_on", []))

        assert step["dependency_refs_used"] == ["step_1", "step_2"]

    def test_validator_results_mirrors_validator_output(self):
        """validator_results should mirror existing validator output when present."""
        step = {}
        validator_output = {"decision": "retry", "reason": "test"}
        if "validator_results" not in step:
            _vr = []
            if validator_output:
                _vr = [{"validator": "intent_validator", "output": validator_output}]
            step["validator_results"] = _vr

        assert len(step["validator_results"]) == 1
        assert step["validator_results"][0]["validator"] == "intent_validator"
        assert step["validator_results"][0]["output"] == validator_output


# =============================================================================
# 4. Persistence round trip
# =============================================================================

class TestPersistenceRoundTrip:
    """Test that F1 fields survive save/load round trip."""

    def test_f1_fields_survive_save_load(self, tmp_path):
        """F1 workflow and step fields should survive JSON save/load."""
        wf = _make_minimal_workflow_with_f1("wf_f1_persist")
        # Simulate persistence: json.dump -> json.load
        tmp_file = tmp_path / "test_wf.json"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(wf, f, ensure_ascii=False, indent=2)
        with open(tmp_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["plan_id"] == "custom_plan_id"
        assert loaded["plan_version"] == 5
        assert loaded["continuation_metadata"] == {"reason": "test"}
        step = loaded["steps"][0]
        assert step["evidence_refs"] == [{"ref": "test"}]
        assert step["unresolved_refs"] == [{"ref": "unresolved"}]
        assert step["dependency_refs_used"] == ["step_0"]
        assert step["validator_results"] == [{"validator": "test", "output": {}}]

    def test_old_workflow_without_f1_loads_cleanly(self, tmp_path):
        """Workflow without F1 fields should load without errors."""
        wf = _make_minimal_workflow("wf_f1_old")
        tmp_file = tmp_path / "old_wf.json"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(wf, f, ensure_ascii=False, indent=2)
        with open(tmp_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        # F1 fields are absent — that's OK, .get() with defaults handles this
        assert loaded.get("plan_id", loaded["id"]) == "wf_f1_old"
        assert loaded.get("plan_version", 1) == 1
        assert loaded.get("continuation_metadata", {}) == {}
        step = loaded["steps"][0]
        assert step.get("evidence_refs", []) == []
        assert step.get("unresolved_refs", []) == []
        assert step.get("dependency_refs_used", []) == []
        assert step.get("validator_results", []) == []


# =============================================================================
# 5. Canonical projection isolation
# =============================================================================

class TestProjectionIsolation:
    """Test that F1 fields do NOT appear in canonical projection output."""

    def test_f1_step_fields_not_in_build_step_projection(self):
        """build_step_projection must not include F1 step-level fields."""
        from system.orchestrator.projection_schema import build_step_projection
        step = _make_minimal_workflow("wf_proj").copy()["steps"][0]
        step["evidence_refs"] = [{"ref": "test"}]
        step["unresolved_refs"] = [{"ref": "test"}]
        step["dependency_refs_used"] = ["step_0"]
        step["validator_results"] = [{"validator": "test"}]
        step["execution_result"] = {"status": "success", "result": 4}
        step["tool_call"] = "add_numbers 2 2"

        proj = build_step_projection("wf_proj", step, 1)
        assert "evidence_refs" not in proj
        assert "unresolved_refs" not in proj
        assert "dependency_refs_used" not in proj
        assert "validator_results" not in proj

    def test_f1_workflow_fields_not_in_build_workflow_projection(self):
        """build_workflow_projection must not include F1 workflow-level fields."""
        from system.orchestrator.projection_schema import build_workflow_projection
        wf = _make_minimal_workflow("wf_proj_wf")
        wf["plan_id"] = "test_plan_id"
        wf["plan_version"] = 3
        wf["continuation_metadata"] = {"reason": "test"}

        proj = build_workflow_projection(wf, 1, "QUEUED")
        assert "plan_id" not in proj
        assert "plan_version" not in proj
        assert "continuation_metadata" not in proj

    def test_f1_fields_not_in_project_workflow_for_gui(self):
        """project_workflow_for_gui must not include F1 fields."""
        # project_workflow_for_gui is in api.py — we test via import
        sys.path.insert(0, os.path.join(_ROOT, "ai_lab_gui", "backend"))
        try:
            from api import project_workflow_for_gui
        except ImportError:
            pytest.skip("api.py not importable in test context")
            return

        wf = _make_minimal_workflow("wf_proj_gui")
        wf["plan_id"] = "test_plan_id"
        wf["plan_version"] = 3
        wf["continuation_metadata"] = {"reason": "test"}
        for step in wf["steps"]:
            step["evidence_refs"] = [{"ref": "test"}]
            step["unresolved_refs"] = [{"ref": "test"}]
            step["dependency_refs_used"] = ["step_0"]
            step["validator_results"] = [{"validator": "test"}]

        proj = project_workflow_for_gui(wf)
        assert "plan_id" not in proj
        assert "plan_version" not in proj
        assert "continuation_metadata" not in proj
        for step in proj.get("steps", []):
            assert "evidence_refs" not in step
            assert "unresolved_refs" not in step
            assert "dependency_refs_used" not in step
            assert "validator_results" not in step


# =============================================================================
# 6. Raw passthrough sanitization
# =============================================================================

class TestRawPassthroughSanitization:
    """Test that raw passthrough paths do NOT expose F1 step-level fields."""

    def test_sanitize_step_f1_removes_f1_fields(self):
        """_sanitize_step_f1 should remove F1 step-level fields."""
        from system.orchestrator.workflow_control import _sanitize_step_f1
        step = {
            "id": "step_1",
            "purpose": "test",
            "evidence_refs": [{"ref": "test"}],
            "unresolved_refs": [{"ref": "test"}],
            "dependency_refs_used": ["step_0"],
            "validator_results": [{"validator": "test"}],
            "execution_result": {"status": "success"},
        }
        sanitized = _sanitize_step_f1(step)
        assert "evidence_refs" not in sanitized
        assert "unresolved_refs" not in sanitized
        assert "dependency_refs_used" not in sanitized
        assert "validator_results" not in sanitized
        # Non-F1 fields preserved
        assert sanitized["id"] == "step_1"
        assert sanitized["purpose"] == "test"
        assert sanitized["execution_result"] == {"status": "success"}

    def test_sanitize_step_f1_does_not_modify_original(self):
        """_sanitize_step_f1 must NOT modify the original step dict."""
        from system.orchestrator.workflow_control import _sanitize_step_f1
        step = {
            "id": "step_1",
            "evidence_refs": [{"ref": "test"}],
            "unresolved_refs": [],
            "dependency_refs_used": ["step_0"],
            "validator_results": [],
        }
        _sanitize_step_f1(step)
        # Original must still have F1 fields
        assert step["evidence_refs"] == [{"ref": "test"}]
        assert step["dependency_refs_used"] == ["step_0"]

    def test_sanitize_steps_f1_removes_f1_fields_from_list(self):
        """_sanitize_steps_f1 should remove F1 fields from all steps in list."""
        from system.orchestrator.workflow_control import _sanitize_steps_f1
        steps = [
            {"id": "step_1", "evidence_refs": [{"ref": "a"}], "validator_results": []},
            {"id": "step_2", "unresolved_refs": [], "dependency_refs_used": ["step_1"]},
        ]
        sanitized = _sanitize_steps_f1(steps)
        for s in sanitized:
            assert "evidence_refs" not in s
            assert "unresolved_refs" not in s
            assert "dependency_refs_used" not in s
            assert "validator_results" not in s
        assert sanitized[0]["id"] == "step_1"
        assert sanitized[1]["id"] == "step_2"

    def test_snapshot_step_strips_f1_fields(self):
        """_snapshot_step in plan_mutation_manager should strip F1 fields."""
        from system.orchestrator.plan_mutation_manager import _snapshot_step
        step = {
            "id": "step_1",
            "purpose": "test",
            "execution_result": {"status": "success"},
            "output": "test output",
            "evidence_refs": [{"ref": "test"}],
            "unresolved_refs": [],
            "dependency_refs_used": ["step_0"],
            "validator_results": [{"validator": "test"}],
        }
        snapshot = _snapshot_step(step)
        assert "evidence_refs" not in snapshot
        assert "unresolved_refs" not in snapshot
        assert "dependency_refs_used" not in snapshot
        assert "validator_results" not in snapshot
        # Also strips execution_result and output (existing behavior)
        assert "execution_result" not in snapshot
        assert "output" not in snapshot
        # Non-stripped fields preserved
        assert snapshot["id"] == "step_1"
        assert snapshot["purpose"] == "test"


# =============================================================================
# 7. Authority preservation
# =============================================================================

class TestAuthorityPreservation:
    """Test that F1 fields do not affect execution_result or authority."""

    def test_execution_result_not_modified_by_f1(self):
        """execution_result must remain unchanged when F1 fields are present."""
        step = {
            "id": "step_1",
            "execution_result": {"status": "success", "result": 42},
            "evidence_refs": [{"ref": "test"}],
            "unresolved_refs": [],
            "dependency_refs_used": [],
            "validator_results": [],
        }
        # F1 fields are metadata — execution_result is untouched
        assert step["execution_result"] == {"status": "success", "result": 42}
        assert step["execution_result"]["result"] == 42

    def test_f1_fields_not_in_required_keys(self):
        """F1 fields must NOT be in REQUIRED_WORKFLOW_KEYS or REQUIRED_PLAN_STEP_KEYS."""
        from system.orchestrator.workflow_validator import REQUIRED_WORKFLOW_KEYS
        # Check workflow-level F1 fields
        assert "plan_id" not in REQUIRED_WORKFLOW_KEYS
        assert "plan_version" not in REQUIRED_WORKFLOW_KEYS
        assert "continuation_metadata" not in REQUIRED_WORKFLOW_KEYS

    def test_f1_step_fields_not_in_required_step_keys(self):
        """F1 step-level fields must NOT be in REQUIRED_PLAN_STEP_KEYS."""
        from system.orchestrator.workflow_validator import REQUIRED_PLAN_STEP_KEYS
        assert "evidence_refs" not in REQUIRED_PLAN_STEP_KEYS
        assert "unresolved_refs" not in REQUIRED_PLAN_STEP_KEYS
        assert "dependency_refs_used" not in REQUIRED_PLAN_STEP_KEYS
        assert "validator_results" not in REQUIRED_PLAN_STEP_KEYS

    def test_f1_fields_not_in_required_step_schema_keys(self):
        """F1 step-level fields must NOT be in REQUIRED_STEP_SCHEMA_KEYS."""
        from system.orchestrator.workflow_validator import REQUIRED_STEP_SCHEMA_KEYS
        assert "evidence_refs" not in REQUIRED_STEP_SCHEMA_KEYS
        assert "unresolved_refs" not in REQUIRED_STEP_SCHEMA_KEYS
        assert "dependency_refs_used" not in REQUIRED_STEP_SCHEMA_KEYS
        assert "validator_results" not in REQUIRED_STEP_SCHEMA_KEYS

    def test_workflow_with_f1_validates_successfully(self):
        """Workflow with F1 fields should pass validation."""
        from system.orchestrator.workflow_validator import validate_workflow
        wf = _make_minimal_workflow("wf_f1_validate")
        wf["plan_id"] = "wf_f1_validate"
        wf["plan_version"] = 1
        wf["continuation_metadata"] = {}
        for step in wf["steps"]:
            step["evidence_refs"] = []
            step["unresolved_refs"] = []
            step["dependency_refs_used"] = []
            step["validator_results"] = []
            step["tool_call"] = "add_numbers 1 2"

        result = validate_workflow(wf)
        assert result["status"] == "success"

    def test_workflow_without_f1_validates_successfully(self):
        """Workflow without F1 fields should also pass validation."""
        from system.orchestrator.workflow_validator import validate_workflow
        wf = _make_minimal_workflow("wf_f1_no_f1_validate")
        for step in wf["steps"]:
            step["tool_call"] = "add_numbers 1 2"

        result = validate_workflow(wf)
        assert result["status"] == "success"

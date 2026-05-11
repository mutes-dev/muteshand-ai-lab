"""
Validation test for CANONICAL EXECUTION INTENT SYNCHRONIZATION.

Ensures step["input"] is synchronized with step["purpose"] when purpose is edited.
Prevents escalation/retry from using stale pre-edit input values.
"""

import pytest
from system.orchestrator.plan_mutation_manager import (
    _handle_edit_step,
    EDITABLE_STEP_FIELDS,
)
from system.orchestrator.workflow_control import edit_step


class TestInputPurposeSynchronization:
    """
    Test that purpose edit mutations synchronize step["input"] with step["purpose"].
    """

    def test_handle_edit_step_syncs_input_from_purpose(self):
        """
        _handle_edit_step must set step["input"] = updates["purpose"] when purpose is edited.
        """
        workflow = {
            "id": "wf-sync-test",
            "status": "ACTIVE",
            "steps": [
                {
                    "id": "s1",
                    "status": "FAILED",
                    "purpose": "Divide result by 0",
                    "input": "Divide result by 0",
                    "type": "EXECUTE_API",
                    "expected_outcome": "Division result",
                    "risk": "LOW",
                    "importance": "MEDIUM",
                    "depends_on": [],
                }
            ],
        }

        result = _handle_edit_step(
            workflow=workflow,
            payload={
                "step_id": "s1",
                "updates": {"purpose": "Divide result by 5"},
            },
            actor="test",
        )

        assert result["status"] == "success", f"Edit failed: {result}"

        step = workflow["steps"][0]
        # PURPOSE updated
        assert step["purpose"] == "Divide result by 5", "purpose not updated"
        # INPUT synchronized to same value
        assert step["input"] == "Divide result by 5", (
            f"input NOT synchronized with purpose: got {step['input']!r}, expected 'Divide result by 5'"
        )

    def test_handle_edit_step_no_sync_when_purpose_not_edited(self):
        """
        When purpose is NOT in updates, input should remain unchanged.
        """
        workflow = {
            "id": "wf-sync-test-2",
            "status": "ACTIVE",
            "steps": [
                {
                    "id": "s1",
                    "status": "FAILED",
                    "purpose": "Original purpose",
                    "input": "Execution base input",
                    "type": "EXECUTE_API",
                    "expected_outcome": "Result",
                    "risk": "LOW",
                    "importance": "MEDIUM",
                    "depends_on": [],
                }
            ],
        }

        result = _handle_edit_step(
            workflow=workflow,
            payload={
                "step_id": "s1",
                "updates": {"expected_outcome": "Different outcome"},
            },
            actor="test",
        )

        assert result["status"] == "success"

        step = workflow["steps"][0]
        # expected_outcome updated
        assert step["expected_outcome"] == "Different outcome"
        # input NOT changed (purpose wasn't in updates)
        assert step["input"] == "Execution base input", "input should not change when purpose not edited"
        assert step["purpose"] == "Original purpose", "purpose should not change"

    def test_workflow_control_edit_step_syncs_input(self):
        """
        Legacy edit_step path must also synchronize input from purpose.
        """
        # Setup: create workflow via persistence first
        from system.orchestrator.persistence import save_workflow, load_active_workflows

        workflow = {
            "id": "wf-legacy-sync",
            "status": "BLOCKED",
            "steps": [
                {
                    "id": "s1",
                    "status": "FAILED",
                    "purpose": "Add 2 and 3",
                    "input": "Add 2 and 3",
                    "type": "EXECUTE_API",
                    "expected_outcome": "5",
                    "risk": "LOW",
                    "importance": "MEDIUM",
                    "depends_on": [],
                }
            ],
        }
        save_workflow(workflow)

        result = edit_step(
            workflow_id="wf-legacy-sync",
            step_id="s1",
            updates={"purpose": "Multiply 4 and 5"},
        )

        assert result["status"] == "success", f"edit_step failed: {result}"

        # Reload to verify persistence
        wfs = load_active_workflows()
        wf = next((w for w in wfs if w["id"] == "wf-legacy-sync"), None)
        assert wf is not None, "workflow not found after edit"

        step = wf["steps"][0]
        assert step["purpose"] == "Multiply 4 and 5", "purpose not updated in persistence"
        assert step["input"] == "Multiply 4 and 5", (
            f"input NOT synchronized in persistence: got {step['input']!r}"
        )


class TestEscalationRetryUsesSyncedInput:
    """
    Test that escalation retry path now receives the edited input value.
    """

    def test_escalation_handle_retry_snapshots_synced_input(self):
        """
        After purpose edit → input sync, handle_retry must snapshot the synced value.
        """
        from system.orchestrator.escalation_controller import handle_retry

        # Simulate a step that was edited (input now synced with purpose)
        step = {
            "id": "s1",
            "status": "RETRY",
            "retries": 1,
            "max_retries": 3,
            "input": "Divide by 5",  # synced value after edit
            "purpose": "Divide by 5",
            "_original_input": "Divide by 0",  # stale from pre-edit execution
            "_extracted_constraints": {"format": "count"},
            "_validator_signals": {"constraint_ok": False},
        }
        wf = {"id": "wf-esc", "steps": [step]}

        # First, simulate that the edit cleared transient fields
        step.pop("_original_input", None)
        step.pop("_extracted_constraints", None)
        step.pop("_validator_signals", None)

        # Now handle_retry should snapshot the CORRECT input
        result = handle_retry(step, wf, next_decision="retry")

        assert result["action"] == "RETRY"
        # _original_input should now be the synced value
        assert step.get("_original_input") == "Divide by 5", (
            f"_original_input should snapshot 'Divide by 5', got {step.get('_original_input')!r}"
        )

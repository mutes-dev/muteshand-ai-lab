"""Step Executor Module — Handles step execution WITHOUT changing behavior.

This module extracts the execution logic from orchestrator_runtime
to create a clean separation of concerns. BEHAVIOR IS LOCKED.
"""
import json
import shlex
from system.orchestrator import signal_interpreter

from system.entry.system_entry import system_entry
from system.orchestrator.agent_executor import execute_agent
from system.orchestrator.intent_validator import evaluate_intent

_TOOL_INDEX_PATH = "system/tool_index/tools.json"
with open(_TOOL_INDEX_PATH, "r", encoding="utf-8") as _f:
    _tool_index = json.load(_f)


def execute_step(step, workflow, retry_guidance=None, debug_verbose=False):
    """
    Execute a single step.

    Args:
        step: The step dict with tool_call, input, purpose, etc.
        workflow: The parent workflow dict
        retry_guidance: Optional retry guidance string
        debug_verbose: Debug output flag

    Returns:
        dict with keys:
            - execution_result: The execution result dict
            - validator_output: The validator output dict
            - executed_input: The executed input string
            - last_result: The last result value (for chaining)
            - step_result: The raw step result from execute_agent
    """
    # === STEP TOOL_CALL EXECUTION (STEP_SCHEMA_CONTRACT_V1) ===
    # Use step's explicit tool_call — NO inference from purpose
    agent_input = step.get("tool_call")
    if not agent_input:
        # FAIL FAST: Missing tool_call is a schema violation
        return {
            "execution_result": {
                "status": "failure",
                "reason": "missing_tool_call"
            },
            "validator_output": {},
            "executed_input": None,
            "last_result": None,
            "step_result": {
                "status": "failure",
                "result": {
                    "execution_result": {
                        "status": "failure",
                        "reason": "missing_tool_call"
                    }
                }
            }
        }

    # Add USE_TOOL: prefix for agent_executor compatibility
    if not agent_input.startswith("USE_TOOL:"):
        agent_input = f"USE_TOOL: {agent_input}"

    # === USER APPROVAL GATE (Phase 1D — Governance-Aligned) ===
    # Governance is the SOLE authority for approval decisions.
    # step_executor ONLY handles the approval interaction when
    # governance has already decided BLOCK with blocked_reason=approval_required.
    # Runtime MUST NOT independently decide approval requirement.
    if step.get("status") == "BLOCKED" and step.get("blocked_reason") == "approval_required":
        from system.orchestrator.user_approval import request_approval
        approved = request_approval(step)

        if not approved:
            return {
                "execution_result": None,
                "validator_output": {},
                "executed_input": None,
                "last_result": None,
                "step_result": None,
                "blocked": True,
                "blocked_reason": "User denied approval"
            }
        # Approved — continue to execution below
        step["status"] = "ACTIVE"

    step_result = execute_agent(
        agent={
            "name": "generic_agent",
            "role": "tool_executor",
            "scope": ["tools"]
        },
        input_data=agent_input,
        retry_guidance=retry_guidance,
        context=None
    )
    # Extract execution_result for validation
    _result_val = step_result.get("result")
    executed_input = (
        (_result_val.get("executed_input") if isinstance(_result_val, dict) else None)
        or step_result.get("executed_input")
    )
    execution_result = step_result.get("result", {}).get("execution_result") if isinstance(step_result.get("result"), dict) else None
    output = step.get("output")

    # If no execution_result and no prior output, synthesize failure for governance
    if execution_result is None:
        if not (output and str(output).strip()):
            execution_result = {"status": "failure", "reason": "no_output"}

    # Perform validation if tool was executed (ADVISORY ONLY)
    validator_output = {}

    if executed_input and step_result.get("status") == "success":
        try:
            ei_parts = shlex.split(executed_input)
        except Exception:
            ei_parts = []
        ei_tool = ei_parts[0] if ei_parts else None
        ei_args = ei_parts[1:] if len(ei_parts) > 1 else []
        tool_def = _tool_index.get(ei_tool) if ei_tool else None

        if tool_def is not None:
            expected_inputs = tool_def.get("inputs", {})

            if len(ei_args) != len(expected_inputs):
                validator_output = {"decision": "retry", "reason": "invalid_argument_count"}

            if not validator_output:
                for arg, expected_type in zip(ei_args, expected_inputs.values()):
                    if expected_type == "number":
                        cleaned = arg.lstrip("-")
                        if not cleaned.isdigit():
                            validator_output = {"decision": "retry", "reason": "invalid_argument_type"}
                            break

        if not validator_output:
            _intent_output = step_result.get("result", {}).get("output", "") if isinstance(step_result.get("result"), dict) else ""
            if not _intent_output and execution_result and execution_result.get("status") == "success":
                _intent_output = execution_result.get("result", "")

            try:
                _ei_args_for_intent = shlex.split(executed_input)[1:] if executed_input else []
            except Exception:
                _ei_args_for_intent = []
            _intent_decision = evaluate_intent(
                step.get("input"),
                ei_tool,
                _ei_args_for_intent,
                _intent_output,
                step.get("purpose"),
                execution_result=execution_result,
                executed_input=executed_input
            )

            if _intent_decision.get("recommendation") == "retry":
                validator_output = _intent_decision

            # VALIDATOR OUTPUT — ADVISORY ONLY (NO CONTROL IMPACT)
            if validator_output:
                # Store advisory reason
                step["_validator_advisory"] = validator_output.get("reason", "unknown")
                # Store validator decision (for correlation tests)
                step["_validator_decision"] = validator_output.get("recommendation")
                # Store signals if present
                if validator_output.get("signals"):
                    step["_validator_signals"] = validator_output.get("signals")
                # Store extracted_constraints for retry guidance
                meta = validator_output.get("meta", {})
                if meta.get("extracted_constraints"):
                    step["_extracted_constraints"] = meta.get("extracted_constraints")

    # === SIGNAL INTERPRETATION (ADVISORY ONLY — NO CONTROL INFLUENCE) ===
    # Stored in step["_signal_analysis"] for trace/debug purposes only.
    # MUST NOT be read by governance, retry logic, or execution.
    try:
        step["_signal_analysis"] = signal_interpreter.interpret_signals(step, execution_result or {})
    except Exception:
        step["_signal_analysis"] = {"status_analysis": "error", "conflicts": [], "issues": [], "confidence": "low", "summary": "signal interpretation failed"}

    # Update last_result from execution_result (governance decides action downstream)
    last_result = None
    if execution_result and execution_result.get("status") == "success":
        try:
            last_result = execution_result.get("result", None)
        except Exception:
            last_result = None

    return {
        "execution_result": execution_result,
        "validator_output": validator_output,
        "executed_input": executed_input,
        "last_result": last_result,
        "step_result": step_result
    }

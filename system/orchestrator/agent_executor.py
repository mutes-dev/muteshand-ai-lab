import json
import os

from system.orchestrator.agent_output_validator import validate_agent_output
from system.orchestrator.tool_call_converter import convert_agent_output_to_tool_call
from system.orchestrator.persistence import get_last_workflow
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm
from system.entry.system_entry import system_entry
from system.interface import event_emitter as _agent_event_emitter


def call_llm(prompt: str) -> str:
    return f"LLM_RESPONSE: {prompt}"


def build_prompt(agent: dict, input_data) -> str:
    return f"""
ROLE: {agent['role']}
SCOPE: {', '.join(agent['scope'])}
TASK: {input_data}
"""


def escape_for_tool_call(text: str) -> str:
    if text is None:
        return ""
    return text.replace('"', "'")


def _format_tool_output(original_input: str, raw_output: str, workflow_id: str = None) -> str:
    formatter_prompt = f"""You are a response formatter.

Your job is to convert tool output into a clear, concise answer.

Rules:
- Do NOT mention tools
- Do NOT mention "USE_TOOL"
- Do NOT explain your process
- Just answer the user clearly

User request:
{original_input}

Tool output:
{raw_output}

Final answer:
"""
    provider_result = get_llm("ollama_llm")
    if provider_result.get("status") == "success":
        _fmt_provider = provider_result["provider"]
        fmt_result = execute_llm(_fmt_provider, formatter_prompt, _perf_caller="formatter", workflow_id=workflow_id)
        # === Sprint 9B: Formatter event emission (failure-isolated) ===
        if _agent_event_emitter is not None:
            try:
                _agent_event_emitter.emit_formatter_call(
                    workflow_id=workflow_id,
                    tool_name=None,
                    status="success" if fmt_result.get("status") == "success" else "failure",
                )
            except Exception:
                pass
        if fmt_result.get("status") == "success":
            return fmt_result["result"]
    return raw_output


def execute_agent(agent: dict, input_data, retry_guidance: str = None, context: dict = None):
    """
    Execute an agent with the given input.

    Args:
        agent: Agent configuration dict with name, role, scope
        input_data: Input string or data for the agent
        retry_guidance: Optional guidance for retry attempts (does not modify input_data)
        context: Optional ephemeral context from previous step (e.g., last_result)

    Returns:
        dict: Execution result with status and result data
    """
    if (
        input_data is None
        or "name" not in agent
        or "role" not in agent
        or "scope" not in agent
        or not isinstance(agent["scope"], list)
    ):
        failure_result = {
            "status": "failure",
            "reason": "invalid_input"
        }

        validation = validate_agent_output(failure_result)
        if validation["status"] == "failure":
            return {
                "status": "failure",
                "result": {
                    "output": None,
                    "execution_result": None
                }
            }

        return failure_result

    # === DELEGATION TO BOUNDED TOOL-SELECTION AGENT (ISSUE-072) ===
    # All tool-selection logic extracted to system.orchestrator.agents.tool_selection_agent
    # to create a typed, bounded specialization while preserving exact behavior.
    from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

    result = execute_tool_selection(
        agent=agent,
        input_data=input_data,
        retry_guidance=retry_guidance,
        context=context
    )

    # Validate agent output (preserved from original implementation)
    if result.get("status") == "success" and "result" in result:
        validation = validate_agent_output(result)
        if validation["status"] != "success":
            result["result"]["validation_error"] = "validation_failed"

    return result

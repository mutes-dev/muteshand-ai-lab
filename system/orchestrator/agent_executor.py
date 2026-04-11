from system.orchestrator.agent_output_validator import validate_agent_output
from system.orchestrator.tool_registry import get_tool
from system.orchestrator.tool_executor import execute_tool
from system.orchestrator.persistence import get_last_workflow
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm


def call_llm(prompt: str) -> str:
    return f"LLM_RESPONSE: {prompt}"


def build_prompt(agent: dict, input_data) -> str:
    return f"""
ROLE: {agent['role']}
SCOPE: {', '.join(agent['scope'])}
TASK: {input_data}
"""


def execute_agent(agent: dict, input_data):
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
                "reason": "invalid_agent_output"
            }

        return failure_result

    if isinstance(input_data, str) and input_data.startswith("USE_TOOL:"):
        tool_part = input_data.split(":", 1)[1].strip()
        tool_name = tool_part.split()[0]

        if not tool_name:
            return {
                "status": "failure",
                "reason": "invalid_input"
            }

        tool_lookup = get_tool(tool_name)

        if tool_lookup["status"] == "failure":
            return {
                "status": "failure",
                "reason": "tool_not_found"
            }

        tool = tool_lookup["tool"]
        tool_result = execute_tool(tool, input_data)

        if tool_result["status"] == "failure":
            return {
                "status": "failure",
                "reason": tool_result.get("reason", "tool_execution_failed")
            }

        result = {
            "status": "success",
            "result": {
                "agent": agent["name"],
                "role": agent["role"],
                "reasoning": f"Tool used: {tool_name}",
                "output": str(tool_result)
            }
        }

        validation = validate_agent_output(result)
        if validation["status"] == "failure":
            return {
                "status": "failure",
                "reason": "invalid_agent_output"
            }

        return result

    context = get_last_workflow()

    previous_output = None

    if context.get("status") == "success":
        try:
            previous_output = context["workflow"]["steps"][-1].get("output")
        except Exception:
            previous_output = None

    if previous_output is not None:
        prompt = f"""
ROLE: {agent['role']}
SCOPE: {', '.join(agent['scope'])}

CONTEXT:
{previous_output}

TASK:
{input_data}
"""
    else:
        prompt = build_prompt(agent, input_data)

    provider_result = get_llm("default_llm")

    if provider_result.get("status") == "success":
        provider = provider_result["provider"]
        llm_result = execute_llm(provider, prompt)

        if llm_result.get("status") == "success":
            llm_output = llm_result["result"]
        else:
            llm_output = "LLM_ERROR"
    else:
        llm_output = "LLM_ERROR"

    reasoning = f"Processed task using role: {agent['role']}"

    result = {
        "status": "success",
        "result": {
            "agent": agent["name"],
            "role": agent["role"],
            "reasoning": reasoning,
            "output": llm_output
        }
    }

    validation = validate_agent_output(result)
    if validation["status"] == "failure":
        return {
            "status": "failure",
            "reason": "invalid_agent_output"
        }

    return result

import json
import os

from system.orchestrator.agent_output_validator import validate_agent_output
from system.orchestrator.persistence import get_last_workflow
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm
from system.entry.system_entry import system_entry


def call_llm(prompt: str) -> str:
    print("LLM RESPONSE:", prompt)
    return f"LLM_RESPONSE: {prompt}"


def build_prompt(agent: dict, input_data) -> str:
    return f"""
ROLE: {agent['role']}
SCOPE: {', '.join(agent['scope'])}
TASK: {input_data}
"""


def _format_tool_output(original_input: str, raw_output: str) -> str:
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
        fmt_result = execute_llm(provider_result["provider"], formatter_prompt)
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
                "reason": "invalid_agent_output"
            }

        return failure_result

    if isinstance(input_data, str) and input_data.startswith("USE_TOOL:"):
        tool_call = input_data.split(":", 1)[1].strip()
        tool_name = tool_call.split()[0]

        result = system_entry(tool_call)

        if result["status"] == "failure":
            return {
                "status": "failure",
                "reason": result["reason"],
                "executed_input": tool_call
            }

        raw_output = str(result)
        formatted_output = _format_tool_output(input_data, raw_output)

        result = {
            "status": "success",
            "result": {
                "agent": agent["name"],
                "role": agent["role"],
                "reasoning": f"Tool used: {tool_name}",
                "output": formatted_output,
                "executed_input": tool_call
            }
        }

        validation = validate_agent_output(result)
        if validation["status"] == "failure":
            return {
                "status": "failure",
                "reason": "invalid_agent_output"
            }

        return result

    context_block = ""

    # Add retry guidance section if provided (does NOT modify input_data)
    retry_guidance_section = f"\n{retry_guidance}\n" if retry_guidance else ""

    # Add ephemeral context from previous step (runtime only, NOT stored)
    context_section = ""
    if context and context.get("last_result") is not None:
        context_section = f"\nPrevious result: {context['last_result']}\n"
        # DEBUG_TEMP_START
        print("[DEBUG_CONTEXT_LAST_RESULT]:", context['last_result'])
        # DEBUG_TEMP_END

    try:
        tool_index_path = os.path.join("system", "tool_index", "tools.json")
        with open(tool_index_path, "r") as f:
            tool_index = json.load(f)
        tool_lines = []
        for tool_name, tool_data in tool_index.items():
            if not tool_data.get("production", False):
                continue
            inputs = tool_data.get("inputs", {})
            arg_keys = list(inputs.keys())
            arg_names = []
            for i, arg in enumerate(arg_keys):
                if inputs[arg] == "string":
                    arg_names.append(f'"{arg}"')
                else:
                    arg_names.append(f"number{i+1}")
            args = " ".join(arg_names)
            description = tool_data.get("description", "").strip()
            if description:
                tool_lines.append(f"- {tool_name} {args}\n  use: {description}".strip())
            else:
                tool_lines.append(f"- {tool_name} {args}".strip())
        tool_list_text = "\n".join(tool_lines)
    except Exception:
        tool_list_text = ""

    prompt = f"""You are an intelligent assistant that can choose to use tools when necessary.

Available tools:
{tool_list_text}

Rules:
- If the task can be solved using a tool, respond ONLY with:
  USE_TOOL: <tool_call>
- Do NOT explain
- Do NOT add extra text
- If no tool is appropriate, respond normally.
- You may respond normally if no tool is required.
- Use a tool ONLY if it is necessary to complete the task.
- If using a tool, you MUST output EXACTLY ONE tool call.
- NEVER output more than one USE_TOOL line.
- If responding normally, DO NOT output USE_TOOL.
- DO NOT say "I don't have a tool".
- DO NOT ask for clarification if the request is clear.
- Prefer direct answers when possible.

STRICT FORMAT RULES:
- Use positional arguments ONLY
- DO NOT use named arguments (e.g. number1=, number2=)
- DO NOT use "=" anywhere in the tool call
- Correct format example:
  USE_TOOL: subtract_numbers 2026 1994
- Incorrect format examples:
  USE_TOOL: subtract_numbers number1=2026 number2=1994
  USE_TOOL: subtract_numbers (2026, 1994)

STRING TOOL RULES:
- If a tool requires text input, you MUST wrap it in double quotes
- Example:
  USE_TOOL: web_search "usa war 2026"
- DO NOT pass multiple tokens without quotes
- DO NOT omit quotes for text inputs
{context_block}
{retry_guidance_section}
{context_section}
Current step:
{input_data}
"""

    provider_result = get_llm("ollama_llm")

    if provider_result.get("status") == "success":
        provider = provider_result["provider"]
        llm_result = execute_llm(provider, prompt)

        if llm_result.get("status") == "success":
            llm_output = llm_result["result"]
        else:
            llm_output = "LLM_ERROR"
    else:
        llm_output = "LLM_ERROR"

    # DEBUG_TEMP_START
    print("[DEBUG_LLM_RAW_OUTPUT]:", llm_output)
    # DEBUG_TEMP_END

    # DEBUG_TEMP_START
    print("[DEBUG_POST_LLM_BEFORE]:", llm_output)
    # DEBUG_TEMP_END

    # ENFORCE SINGLE USE_TOOL RULE
    use_tool_count = llm_output.count("USE_TOOL:")

    if use_tool_count > 1:
        print("DEBUG_MULTI_TOOL_DETECTED:", llm_output)
        return {
            "status": "failure",
            "reason": "multiple_tool_calls_not_allowed"
        }

    # Extract only first USE_TOOL line
    lines = llm_output.splitlines()
    tool_lines = [line for line in lines if "USE_TOOL:" in line]
    if tool_lines:
        llm_output = tool_lines[0]

    # DEBUG_TEMP_START
    print("[DEBUG_POST_LLM_AFTER]:", llm_output)
    # DEBUG_TEMP_END

    if llm_output == "LLM_ERROR":
        return {
            "status": "failure",
            "reason": "llm_error"
        }

    if not isinstance(llm_output, str) or "USE_TOOL:" not in llm_output:
        return {
            "status": "success",
            "result": {
                "agent": agent["name"],
                "role": agent["role"],
                "reasoning": "No tool required",
                "output": llm_output.strip() if isinstance(llm_output, str) else str(llm_output),
                "executed_input": None,
                "execution_result": None
            }
        }

    tool_lines = [l for l in llm_output.splitlines() if "USE_TOOL:" in l]

    if not tool_lines:
        return {
            "status": "success",
            "result": {
                "agent": agent["name"],
                "role": agent["role"],
                "reasoning": "No tool required",
                "output": llm_output.strip(),
                "executed_input": None,
                "execution_result": None
            }
        }

    tool_line = tool_lines[0]
    tool_call = tool_line.split("USE_TOOL:", 1)[1].strip()

    # DEBUG_TEMP_START
    print("[DEBUG_PRE_SYSTEM_ENTRY_INPUT]:", tool_call)
    # DEBUG_TEMP_END

    execution_result = system_entry(tool_call)

    if isinstance(execution_result, dict) and execution_result.get("status") == "failure":
        failure_reason = execution_result.get("reason", "unknown error")
        formatted_output = f"Could not complete request: {failure_reason}"
    else:
        raw_output = str(execution_result)
        formatted_output = _format_tool_output(input_data, raw_output)

    result = {
        "status": "success",
        "result": {
            "agent": agent["name"],
            "role": agent["role"],
            "reasoning": llm_output.strip(),
            "output": formatted_output,
            "executed_input": tool_call,
            "execution_result": execution_result
        }
    }

    validation = validate_agent_output(result)
    if validation["status"] == "failure":
        return {
            "status": "failure",
            "reason": "invalid_agent_output"
        }

    return result

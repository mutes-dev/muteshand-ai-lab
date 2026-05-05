import json
import os

from system.orchestrator.agent_output_validator import validate_agent_output
from system.orchestrator.tool_call_converter import convert_agent_output_to_tool_call
from system.orchestrator.persistence import get_last_workflow
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm
from system.entry.system_entry import system_entry


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
                "result": {
                    "output": None,
                    "execution_result": None
                }
            }

        return failure_result

    tool_index_path = os.path.join("system", "tool_index", "tools.json")
    with open(tool_index_path, "r") as f:
        tool_index = json.load(f)

    if isinstance(input_data, str) and input_data.startswith("USE_TOOL:"):
        tool_call = input_data.split(":", 1)[1].strip()

        raw = tool_call.strip()
        if raw == "" or raw == ":":
            return {"status": "success", "result": {"output": None, "execution_result": {"status": "failure", "reason": "empty_tool_call"}}}

        parts = raw.split()
        if len(parts) == 0:
            return {"status": "success", "result": {"output": None, "execution_result": {"status": "failure", "reason": "empty_tool_call"}}}

        tool_name = parts[0]
        if not tool_name or " " in tool_name:
            return {"status": "success", "result": {"output": None, "execution_result": {"status": "failure", "reason": "invalid_tool_name"}}}

        if tool_name not in tool_index:
            return {
                "status": "success",
                "result": {
                    "output": None,
                    "execution_result": {"status": "failure", "reason": "unknown_tool"}
                }
            }

        if not tool_index[tool_name].get("production", False):
            return {
                "status": "success",
                "result": {
                    "output": None,
                    "execution_result": {"status": "failure", "reason": "non_production_tool"}
                }
            }

        execution_result = system_entry(tool_call)

        # CONTRACT-SAFE: Always return status="success" regardless of execution_result status
        # execution_result is the sole source of truth for success/failure
        raw_output = str(execution_result)
        formatted_output = _format_tool_output(input_data, raw_output)

        result = {
            "status": "success",
            "result": {
                "agent": agent["name"],
                "role": agent["role"],
                "reasoning": f"Tool used: {tool_name}",
                "output": formatted_output,
                "executed_input": tool_call,
                "execution_result": execution_result
            }
        }

        validation = validate_agent_output(result)
        if validation["status"] != "success":
            result["result"]["validation_error"] = "validation_failed"

        return result

    # === STEP IO: DEPENDENCY-ONLY CONTEXT (STEP_IO_CONTRACT_V1 Section 3) ===
    # Agent receives ONLY outputs from declared dependencies.
    # No global last_result, no implicit chaining.
    context_block = ""
    if context and isinstance(context, dict) and context.get("dependency_outputs"):
        _dep_outputs = context["dependency_outputs"]
        _dep_lines = []
        for dep_id, dep_output in _dep_outputs.items():
            _dep_lines.append(f"  {dep_id}: {dep_output.get('data')}")
        context_block = f"\nDependency outputs:\n" + "\n".join(_dep_lines) + "\n"

    # Add retry guidance section if provided (does NOT modify input_data)
    retry_guidance_section = f"\n{retry_guidance}\n" if retry_guidance else ""

    try:
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

    prompt = f"""You are a tool executor.
You do not solve problems.
You only select the correct tool and pass inputs exactly as given.

Available tools:
{tool_list_text}

TOOL USAGE CONTRACT (STRICT):

You are NOT allowed to solve problems yourself.

Your ONLY responsibility is to:
→ select the correct tool
→ pass the correct inputs

---

1. TOOL SELECTION

- You MUST choose the MOST SPECIFIC tool that directly matches the user's request.

Examples:
- "square 5" → USE_TOOL: square_number 5
- "cube 3" → USE_TOOL: cube_number 3

- DO NOT use general tools if a specific tool exists.

---

2. NO PRE-COMPUTATION

- DO NOT calculate values before calling tools.

Example:
- "cube 3" → USE_TOOL: cube_number 3
- NOT → cube_number 27

---

3. INPUT INTEGRITY

- Pass only original inputs or previous outputs
- DO NOT modify or invent values

---

4. TOOL-ONLY EXECUTION

- If a tool exists → you MUST use it
- DO NOT simulate tool behavior

---

5. OUTPUT FORMAT

If using a tool, output EXACTLY:

USE_TOOL: <tool_name> <args>

No explanation. No extra text.
You MUST output EXACTLY ONE tool call.
NEVER output more than one USE_TOOL line.
If responding normally, DO NOT output USE_TOOL.

FORMAT RULES:
- Use positional arguments ONLY
- DO NOT use named arguments (e.g. number1=, number2=)
- DO NOT use "=" anywhere in the tool call
- Correct: USE_TOOL: subtract_numbers 2026 1994
- Wrong: USE_TOOL: subtract_numbers number1=2026 number2=1994

STRING RULES:
- If a tool requires text input, wrap it in double quotes
- Example: USE_TOOL: web_search "usa war 2026"
- DO NOT pass multiple tokens without quotes

---

DECISION BOUNDARY (CRITICAL):

You MUST explicitly choose ONE of the following:

1. USE_TOOL: <tool_name> <args>
2. USE_TOOL: finalize_output "<response>"

RULES:

- If the request requires ANY external action (calculation, file, API, etc.)
  → MUST use the correct tool

- If the request does NOT require a tool
  → MUST use finalize_output

- You MUST NOT respond without a USE_TOOL line

- finalize_output is NOT fallback
  → it is the correct path for non-tool responses

Examples:

Input: "tell me a joke"
Output: USE_TOOL: finalize_output "Why don't scientists trust atoms? Because they make up everything."

Input: "what is 2+2"
Output: USE_TOOL: add_numbers 2 2

---

6. NO TOOL CASE

If no tool applies, you MUST use finalize_output.
DO NOT respond without a USE_TOOL line.
DO NOT say "I don't have a tool".
DO NOT ask for clarification if the request is clear.

---

7. STRICT TOOL MATCHING (CRITICAL)

- You MUST ONLY use a tool if it EXACTLY matches the requested operation.

- If the request is:
  "power", "raise", "exponent", or any operation NOT explicitly supported by a tool:

  → DO NOT select any tool
  → DO NOT approximate using other tools (e.g. cube, multiply, etc.)

- DO NOT transform inputs:
  Example:
  "power 2 to 4"
  ❌ cube_number 16
  ❌ multiply_numbers 2 4

- If no tool applies:
  → respond normally (NO USE_TOOL)

---

8. SINGLE TOOL ENFORCEMENT

- You MUST output EXACTLY ONE of:
  ✔ ONE valid USE_TOOL line
  OR
  ✔ normal response (no USE_TOOL)

- NEVER output multiple USE_TOOL lines
- NEVER combine tool calls

{context_block}
{retry_guidance_section}
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

    # ENFORCE SINGLE USE_TOOL RULE
    use_tool_count = llm_output.count("USE_TOOL:")

    if use_tool_count > 1:
        return {
            "status": "failure",
            "reason": "multiple_tool_calls_not_allowed",
            "result": {
                "output": None,
                "execution_result": None
            }
        }

    # Extract only first USE_TOOL line
    lines = llm_output.splitlines()
    tool_lines = [line for line in lines if "USE_TOOL:" in line]
    if tool_lines:
        llm_output = tool_lines[0]

    if llm_output == "LLM_ERROR":
        return {
            "status": "failure",
            "result": {
                "output": None,
                "execution_result": None
            }
        }

    if not isinstance(llm_output, str) or "USE_TOOL:" not in llm_output:
        # A. Extract output safely
        output = llm_output.strip() if isinstance(llm_output, str) else str(llm_output)

        # B. Escape for tool call (backslash, quotes, newlines)
        escaped_response = escape_for_tool_call(output)

        # C. Construct deterministic tool call
        tool_input = f'USE_TOOL: finalize_output "{escaped_response}"'
        tool_call = f'finalize_output "{escaped_response}"'

        # D. Execute via system_entry (SINGLE CALL)
        execution_result = system_entry(tool_call)

        # E. Return structured result
        return {
            "status": "success",
            "result": {
                "agent": agent["name"],
                "role": agent["role"],
                "reasoning": "Non-tool response routed via finalize_output",
                "output": None,
                "executed_input": tool_input,
                "execution_result": execution_result,
                "suggestions": []
            }
        }

    tool_lines = [l for l in llm_output.splitlines() if "USE_TOOL:" in l]

    if not tool_lines:
        escaped_response = escape_for_tool_call(llm_output.strip())
        tool_input = f'USE_TOOL: finalize_output "{escaped_response}"'
        tool_call_fb = f'finalize_output "{escaped_response}"'
        execution_result = system_entry(tool_call_fb)
        return {
            "status": "success",
            "result": {
                "agent": agent["name"],
                "role": agent["role"],
                "reasoning": "Non-tool response routed via finalize_output",
                "output": None,
                "executed_input": tool_input,
                "execution_result": execution_result,
                "suggestions": []
            }
        }

    tool_line = tool_lines[0]

    # --- TOOL_CALL CONVERSION (via interface module) ---
    tool_call, failure = convert_agent_output_to_tool_call(tool_line)

    if failure:
        return {
            "status": "success",
            "result": {
                "output": None,
                "execution_result": failure
            }
        }

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
    if validation["status"] != "success":
        result["result"]["validation_error"] = "validation_failed"

    return result

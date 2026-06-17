import json
import os
from typing import Any, Dict, Optional

from system.orchestrator.tool_call_converter import convert_agent_output_to_tool_call
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm
from system.entry.system_entry import system_entry
from system.tool_index.tool_capability_index import (
    build_ag1_capability_view,
    format_ag1_capability_prompt_line,
)


# ── ISSUE-095B: Advisory memory prompt bounds ──────────────────────────────

_MAX_MEMORY_PROMPT_CHARS = 1000


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
        fmt_result = execute_llm(provider_result["provider"], formatter_prompt, _perf_caller="formatter")
        if fmt_result.get("status") == "success":
            return fmt_result["result"]
    return raw_output


def execute_tool_selection(agent, input_data, retry_guidance=None, context=None):
    """
    Bounded tool-selection agent.

    Extracted from agent_executor.py as part of ISSUE-072 reduced scope.
    Preserves exact behavior while creating a typed, bounded specialization.

    Produces USE_TOOL: strings only. All execution routes through system_entry.
    """
    # === PERF036: AG1 start ===
    try:
        import time as _ag1_time, json as _ag1_json
        from datetime import datetime as _ag1_dt, timezone as _ag1_tz
        _ag1_start = _ag1_time.monotonic()
        _ag1_iso_start = _ag1_dt.now(_ag1_tz.utc).isoformat()
        _ag1_step_id = (context or {}).get("step_id", "unknown") if isinstance(context, dict) else "unknown"
        _ag1_wf_id = (context or {}).get("workflow_id", "unknown") if isinstance(context, dict) else "unknown"
        print("PERF036_BACKEND " + _ag1_json.dumps({
            "label": "ag1_tool_selection_start",
            "source_layer": "tool_selection_agent",
            "timestamp_iso": _ag1_iso_start,
            "step_id": _ag1_step_id,
            "workflow_id": _ag1_wf_id,
        }))
    except Exception:
        _ag1_start = None
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

        # === ISSUE-098KP: DYNAMIC EXTERNAL-CALL ENFORCEMENT ===
        # Enforce user-control for dynamically selected external-call tools
        # before system_entry executes them. This complements the predeclared
        # tool_call gate in orchestrator_runtime.py.
        # ISSUE-098KR FIX: step_id now included in context from step_executor.py
        _ag1_wf_id = context.get("workflow_id") if isinstance(context, dict) else None
        _ag1_step_id = context.get("step_id") if isinstance(context, dict) else None

        if _ag1_wf_id and _ag1_step_id:
            # Extract tool_args for metadata lookup
            _ag1_tool_args: Optional[Dict[str, Any]] = None
            if tool_name == "read_webpage" and len(parts) > 1:
                _ag1_url = " ".join(parts[1:]).strip('"').strip("'")
                _ag1_tool_args = {"url": _ag1_url}
            elif tool_name == "web_search" and len(parts) > 1:
                _ag1_query = " ".join(parts[1:]).strip('"').strip("'")
                _ag1_tool_args = {"query": _ag1_query}

            from system.orchestrator.user_control import enforce_external_call_user_control

            _ag1_enforcement = enforce_external_call_user_control(
                workflow_id=_ag1_wf_id,
                step_id=_ag1_step_id,
                tool_name=tool_name,
                tool_args=_ag1_tool_args,
                source="ag1_dynamic_tool_selection",
            )

            if _ag1_enforcement.get("blocked"):
                # Blocked for external_call_risk — return controlled result
                # This is NOT a tool failure; it's a user-control block
                return {
                    "status": "success",
                    "result": {
                        "agent": agent["name"],
                        "role": agent["role"],
                        "reasoning": f"External-call tool '{tool_name}' blocked pending user acceptance",
                        "output": f"User control required: accept_external_call_risk for {tool_name}",
                        "executed_input": None,
                        "execution_result": {
                            "status": "blocked",
                            "reason": "external_call_risk",
                            "control_id": _ag1_enforcement.get("control_id"),
                            "request_status": _ag1_enforcement.get("request_status"),
                        },
                        "_user_control_blocked": True,
                        "_external_call_risk": True,
                    }
                }

        _mode = (context or {}).get("mode", "normal") if isinstance(context, dict) else "normal"

        execution_result = system_entry(tool_call, mode=_mode)

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

    # ── ISSUE-095B: Operator-managed advisory memory context (AG1-only) ───
    # advisory_memory is a pre-formatted, bounded, advisory-only string from
    # system.memory.advisory_bridge. It contains only operator-managed memory_store
    # entries with source="user", eligible categories, and confidence >= 0.5.
    # Never raw memory values. Never imports global_memory or memory_adapter.
    memory_prompt_section = ""
    if context and isinstance(context, dict):
        _advisory_text = context.get("advisory_memory")
        if isinstance(_advisory_text, str) and _advisory_text.strip():
            _truncated = _advisory_text
            if len(_truncated) > _MAX_MEMORY_PROMPT_CHARS:
                _truncated = (
                    _truncated[: _MAX_MEMORY_PROMPT_CHARS - 50]
                    + "\n... [truncated]\n[/ADVISORY MEMORY CONTEXT]"
                )
            memory_prompt_section = "\n" + _truncated + "\n"

    try:
        _ag1_capability_view = build_ag1_capability_view()
        tool_lines = [
            format_ag1_capability_prompt_line(cap)
            for cap in _ag1_capability_view.values()
        ]
        tool_list_text = "\n".join(tool_lines)
    except Exception:
        # Fallback to raw tools.json construction if capability index fails
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

    # Sprint 7C ISSUE-098A: SAME retry enforcement
    _allowed_tool = None
    _same_retry_section = ""
    if context and isinstance(context, dict):
        _allowed_tool = context.get("allowed_tool")
        if _allowed_tool:
            # Restrict available tools to allowed_tool only
            _restricted_lines = []
            for _line in tool_lines:
                _tool_name = _line.split()[1] if _line.split() else None
                if _tool_name == _allowed_tool:
                    _restricted_lines.append(_line)
            if _restricted_lines:
                tool_list_text = "\n".join(_restricted_lines)
            else:
                # allowed_tool not found in production tool index
                return {
                    "status": "failure",
                    "reason": "same_retry_tool_unavailable",
                    "result": {
                        "output": None,
                        "execution_result": {
                            "status": "failure",
                            "reason": "same_retry_tool_unavailable"
                        }
                    }
                }
            _same_retry_section = (
                f"\nSAME RETRY ENFORCEMENT:\n"
                f"- This step is being retried with strategy=SAME.\n"
                f"- You MUST use ONLY the allowed tool: {_allowed_tool}\n"
                f"- DO NOT select any other tool.\n"
                f"- DO NOT use finalize_output unless it is the allowed tool.\n"
                f"- Reconstruct arguments freshly from the current step input.\n\n"
            )

    # Build conditional PATH ROUTING BOUNDARY
    if _allowed_tool:
        # During SAME retry, use simplified boundary that doesn't mention other tools
        path_routing_boundary = """PATH ROUTING BOUNDARY (CRITICAL):

Use the allowed tool only. Do not use other tools."""
    else:
        # Normal operation with full boundary
        path_routing_boundary = """PATH ROUTING BOUNDARY (CRITICAL):

If the target begins with http:// or https://, use web tools such as read_webpage/web_search as appropriate.
If the target is a local path such as tmp/file.txt, ./file.txt, E:\\..., or a project-relative path, use local file tools such as read_file/list_files/grep/glob/edit_file/write_file as appropriate.
Do not use web tools for local file paths.
Do not use math tools for file paths.

EDIT_FILE REQUIREMENT:
For edit_file, provide both old_text and new_text. If the request says "also contains" or "append" but no old_text is given, do not invent old_text."""

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
- Example: USE_TOOL: finalize_output "Hello Bryan! Hope you're having a great day."
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
  → correct for text-only answers, summarization, explanation, final synthesis
  → correct for greetings, conversational responses, and simple text generation
  → do NOT use for arithmetic, file reading/writing, webpage reading/search, or concrete utility tools
  → If the request is to write/generate text without explicit string operations, use finalize_output

Examples:

Input: "tell me a joke"
Output: USE_TOOL: finalize_output "Why don't scientists trust atoms? Because they make up everything."

Input: "Write a short friendly greeting for Bryan"
Output: USE_TOOL: finalize_output "Hello Bryan! Hope you're having a great day."

Input: "what is 2+2"
Output: USE_TOOL: add_numbers 2 2

---

{path_routing_boundary}

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
{memory_prompt_section}
{path_routing_boundary}
{_same_retry_section}Current step:
{input_data}
"""

    provider_result = get_llm("ollama_llm")

    if provider_result.get("status") == "success":
        provider = provider_result["provider"]
        _ag1_wf_id = context.get("workflow_id") if isinstance(context, dict) else None
        llm_result = execute_llm(provider, prompt, _perf_caller="ag1_tool_selection", workflow_id=_ag1_wf_id)

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
        # Sprint 7C ISSUE-098A: SAME retry must not fallback to finalize_output
        # unless allowed_tool is finalize_output
        if _allowed_tool and _allowed_tool != "finalize_output":
            return {
                "status": "failure",
                "reason": "same_retry_wrong_tool",
                "result": {
                    "output": None,
                    "execution_result": {
                        "status": "failure",
                        "reason": "same_retry_wrong_tool"
                    }
                }
            }

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
        # Sprint 7C ISSUE-098A: SAME retry must not fallback to finalize_output
        if _allowed_tool and _allowed_tool != "finalize_output":
            return {
                "status": "failure",
                "reason": "same_retry_wrong_tool",
                "result": {
                    "output": None,
                    "execution_result": {
                        "status": "failure",
                        "reason": "same_retry_wrong_tool"
                    }
                }
            }

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
                "executed_input": tool_line,
                "execution_result": failure
            }
        }

    # Sprint 7C ISSUE-098A: SAME retry selected-tool validation
    if _allowed_tool:
        _selected_tool = tool_call.strip().split()[0] if tool_call.strip().split() else None
        if _selected_tool != _allowed_tool:
            return {
                "status": "failure",
                "reason": "same_retry_wrong_tool",
                "result": {
                    "output": None,
                    "execution_result": {
                        "status": "failure",
                        "reason": "same_retry_wrong_tool"
                    }
                }
            }

    # === ISSUE-098KS: DYNAMIC TOOL SELECTION ENFORCEMENT ===
    # Enforce user-control for LLM-selected external-call tools
    # before system_entry executes them. This is the production path
    # for AG1 dynamic tool selection.
    _ag1_wf_id = context.get("workflow_id") if isinstance(context, dict) else None
    _ag1_step_id = context.get("step_id") if isinstance(context, dict) else None

    if _ag1_wf_id and _ag1_step_id:
        # Extract tool_name from tool_call
        _ag1_parts = tool_call.strip().split()
        _ag1_tool_name = _ag1_parts[0] if _ag1_parts else None

        # Extract tool_args for metadata lookup
        _ag1_tool_args: Optional[Dict[str, Any]] = None
        if _ag1_tool_name == "read_webpage" and len(_ag1_parts) > 1:
            _ag1_url = " ".join(_ag1_parts[1:]).strip('"').strip("'")
            _ag1_tool_args = {"url": _ag1_url}
        elif _ag1_tool_name == "web_search" and len(_ag1_parts) > 1:
            _ag1_query = " ".join(_ag1_parts[1:]).strip('"').strip("'")
            _ag1_tool_args = {"query": _ag1_query}

        from system.orchestrator.user_control import enforce_external_call_user_control

        _ag1_enforcement = enforce_external_call_user_control(
            workflow_id=_ag1_wf_id,
            step_id=_ag1_step_id,
            tool_name=_ag1_tool_name,
            tool_args=_ag1_tool_args,
            source="ag1_llm_tool_selection",
        )

        if _ag1_enforcement.get("blocked"):
            # Blocked for external_call_risk — return controlled result
            # Include tool_call in executed_input so step_schema validation passes
            return {
                "status": "success",
                "result": {
                    "agent": agent["name"],
                    "role": agent["role"],
                    "reasoning": f"External-call tool '{_ag1_tool_name}' blocked pending user acceptance",
                    "output": f"User control required: accept_external_call_risk for {_ag1_tool_name}",
                    "executed_input": tool_call,  # Include for step_schema validation
                    "execution_result": {
                        "status": "blocked",
                        "reason": "external_call_risk",
                        "control_id": _ag1_enforcement.get("control_id"),
                        "request_status": _ag1_enforcement.get("request_status"),
                    },
                    "_user_control_blocked": True,
                    "_external_call_risk": True,
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

    # === PERF036: AG1 end ===
    try:
        if _ag1_start is not None:
            import time as _ag1_time_end, json as _ag1_json_end
            from datetime import datetime as _ag1_dt_end, timezone as _ag1_tz_end
            _ag1_dur = round((_ag1_time_end.monotonic() - _ag1_start) * 1000, 2)
            print("PERF036_BACKEND " + _ag1_json_end.dumps({
                "label": "ag1_tool_selection_end",
                "source_layer": "tool_selection_agent",
                "timestamp_iso": _ag1_dt_end.now(_ag1_tz_end.utc).isoformat(),
                "duration_ms": _ag1_dur,
                "step_id": _ag1_step_id,
                "workflow_id": _ag1_wf_id,
            }))
    except Exception:
        pass

    return result

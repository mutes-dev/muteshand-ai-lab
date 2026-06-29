import json
import os
import re
from typing import Any, Dict, Optional

from system.orchestrator.tool_call_converter import convert_agent_output_to_tool_call
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm
from system.entry.system_entry import system_entry
from system.tool_index.tool_capability_index import (
    build_ag1_capability_view,
    format_ag1_capability_prompt_line,
)
from system.interface import event_emitter as _ag1_event_emitter


# ── ISSUE-095B: Advisory memory prompt bounds ──────────────────────────────

_MAX_MEMORY_PROMPT_CHARS = 1000

# ── PDIAG-007F: Dependency output rendering bounds ──────────────────────────

_MAX_DEPENDENCY_RESULT_CHARS = 800


def _safe_truncate(value: Any, limit: int = _MAX_DEPENDENCY_RESULT_CHARS) -> str:
    """Convert a dependency value to a compact, prompt-safe string."""
    if value is None:
        return ""
    text = str(value)
    # Normalize internal whitespace
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 50].rstrip() + " ... [truncated]"
    return text


def _extract_resource_from_tool_call(tool_call: str) -> Optional[str]:
    """Extract the first string argument from a tool_call if available."""
    if not tool_call or not isinstance(tool_call, str):
        return None
    import shlex
    try:
        parts = shlex.split(tool_call.strip())
    except ValueError:
        return None
    if len(parts) <= 1:
        return None
    # First argument after tool name
    return parts[1]


_PLACEHOLDER_PATTERN = re.compile(r"(?:\$|<<)step[_\s]?\d+\b|<step[_\s]?\d+>|<<step[_\s]?\d+>>", re.IGNORECASE)


def _contains_dependency_placeholder(text: str) -> bool:
    """Detect symbolic dependency references that should be literal values."""
    if not text or not isinstance(text, str):
        return False
    return bool(_PLACEHOLDER_PATTERN.search(text))


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
        _fmt_provider_name = _fmt_provider.get("name", "unknown") if isinstance(_fmt_provider, dict) else "unknown"
        fmt_result = execute_llm(_fmt_provider, formatter_prompt, _perf_caller="formatter", workflow_id=workflow_id)
        # === Sprint 9B: Formatter event emission (failure-isolated) ===
        if _ag1_event_emitter is not None:
            try:
                _ag1_event_emitter.emit_formatter_call(
                    workflow_id=workflow_id,
                    tool_name=None,
                    status="success" if fmt_result.get("status") == "success" else "failure",
                )
            except Exception:
                pass
        if fmt_result.get("status") == "success":
            return fmt_result["result"]
    return raw_output


def _extract_literals_from_purpose(purpose: str):
    """Extract numeric literals from step purpose text, excluding step references."""
    import re
    if not purpose:
        return []
    cleaned = re.sub(
        r"(?:result\s+of\s+|output\s+of\s+)?\bstep[_\s]?\d+\b",
        "",
        purpose,
        flags=re.IGNORECASE,
    )
    nums = re.findall(r"\b\d+\.?\d*\b", cleaned)
    result = []
    for n in nums:
        try:
            if "." in n:
                result.append(float(n))
            else:
                result.append(int(n))
        except ValueError:
            pass
    return result


def _detect_precomputation(tool_call: str, input_data: str, context: dict) -> dict:
    """
    Detect if AG1 has pre-computed a math result and passed it as a tool argument.

    Returns dict with keys:
        is_suspicious: bool
        reason: str or None
        detected_computation: str or None
        dependency_value: numeric or None
        literal_operand: numeric or None
        suspicious_argument: numeric or None
    """
    if not tool_call or not isinstance(tool_call, str):
        return {"is_suspicious": False, "reason": None, "detected_computation": None}

    parts = tool_call.strip().split()
    if len(parts) < 2:
        return {"is_suspicious": False, "reason": None, "detected_computation": None}

    tool_name = parts[0]
    math_tools = {
        "add_numbers",
        "subtract_numbers",
        "multiply_numbers",
        "divide_numbers",
        "square_number",
        "cube_number",
    }
    if tool_name not in math_tools:
        return {"is_suspicious": False, "reason": None, "detected_computation": None}

    dep_outputs = context.get("dependency_outputs") if isinstance(context, dict) else None
    if not dep_outputs:
        return {"is_suspicious": False, "reason": None, "detected_computation": None}

    numeric_args = []
    for p in parts[1:]:
        p_clean = p.strip('"').strip("'")
        try:
            if "." in p_clean:
                numeric_args.append(float(p_clean))
            else:
                numeric_args.append(int(p_clean))
        except ValueError:
            pass

    if not numeric_args:
        return {"is_suspicious": False, "reason": None, "detected_computation": None}

    dep_values = []
    for dep_output in dep_outputs.values():
        data = dep_output.get("data") if isinstance(dep_output, dict) else dep_output
        if data is None:
            continue
        try:
            if isinstance(data, (int, float)):
                dep_values.append(data)
            else:
                s = str(data).strip()
                if "." in s:
                    dep_values.append(float(s))
                else:
                    dep_values.append(int(s))
        except (ValueError, TypeError):
            pass

    if not dep_values:
        return {"is_suspicious": False, "reason": None, "detected_computation": None}

    literals = _extract_literals_from_purpose(input_data)
    if not literals:
        # For square/cube, the operation is self-referential on the dependency value
        if tool_name in ("square_number", "cube_number"):
            literals = list(dep_values)
        else:
            return {"is_suspicious": False, "reason": None, "detected_computation": None}

    for dep_val in dep_values:
        for lit in literals:
            for arg in numeric_args:
                if arg == lit or arg == dep_val:
                    continue
                try:
                    expected = None
                    if tool_name == "add_numbers":
                        expected = dep_val + lit
                    elif tool_name == "subtract_numbers":
                        expected = dep_val - lit
                    elif tool_name == "multiply_numbers":
                        expected = dep_val * lit
                    elif tool_name == "divide_numbers" and lit != 0:
                        expected = dep_val / lit
                    elif tool_name == "square_number":
                        expected = dep_val * dep_val
                    elif tool_name == "cube_number":
                        expected = dep_val * dep_val * dep_val

                    if expected is not None:
                        if isinstance(expected, float):
                            match = abs(arg - expected) < 0.001
                        else:
                            match = arg == expected
                        if match:
                            return {
                                "is_suspicious": True,
                                "reason": "ag1_precomputed_tool_argument_detected",
                                "detected_computation": (
                                    f"{tool_name} arg {arg} appears pre-computed from "
                                    f"dependency {dep_val} and literal {lit}"
                                ),
                                "dependency_value": dep_val,
                                "literal_operand": lit,
                                "suspicious_argument": arg,
                            }
                except (TypeError, ZeroDivisionError):
                    pass

    return {"is_suspicious": False, "reason": None, "detected_computation": None}


# ── PDIAG-007D: Deterministic simple-synthesis path ──────────────────────────

_SYNTHESIS_KEYWORDS = frozenset({
    "summarize", "summary", "combine", "both results", "final answer",
    "compare", "comparison", "synthesis", "synthesize", "overview",
})


def _is_scalar_value(value: Any) -> bool:
    """Check if a value is a simple scalar suitable for deterministic synthesis."""
    if value is None:
        return False
    if isinstance(value, (int, float, bool)):
        return True
    if isinstance(value, str):
        # Simple string: not too long, no newlines, no complex structure
        if len(value) > 200:
            return False
        if "\n" in value or "\r" in value:
            return False
        # Exclude JSON-like, list-like, dict-like strings
        stripped = value.strip()
        if stripped.startswith(("[", "{", "(", "<")):
            return False
        if stripped.endswith(("]", "}", ")", ">")):
            return False
        return True
    return False


def _looks_like_synthesis_purpose(purpose: str) -> bool:
    """Check if step purpose implies simple scalar dependency-output synthesis."""
    if not purpose:
        return False
    purpose_lower = purpose.lower()
    return any(kw in purpose_lower for kw in _SYNTHESIS_KEYWORDS)


def _build_deterministic_summary_text(
    dependency_outputs: dict,
    purpose: str,
) -> Optional[str]:
    """
    Construct deterministic synthesis text from scalar dependency outputs.

    Returns None if deterministic synthesis is not applicable.
    """
    if not dependency_outputs or len(dependency_outputs) < 2:
        return None

    # Extract scalar values
    dep_items = []
    for dep_id, dep_output in dependency_outputs.items():
        data = dep_output.get("data") if isinstance(dep_output, dict) else dep_output
        if not _is_scalar_value(data):
            return None
        dep_items.append((dep_id, data))

    if len(dep_items) < 2:
        return None

    # Sort by step number for determinism
    def _step_sort_key(item):
        dep_id = item[0]
        # Extract numeric suffix from step IDs like step_1, step_2
        import re
        match = re.search(r"\d+", dep_id)
        if match:
            return int(match.group())
        return dep_id

    dep_items.sort(key=_step_sort_key)

    # Build summary lines
    lines = []
    for dep_id, value in dep_items:
        lines.append(f"{dep_id} result: {value}.")

    summary_text = " ".join(lines)

    # Add comparison sentence if purpose implies comparison and all values are numeric
    purpose_lower = purpose.lower() if purpose else ""
    is_comparison = any(kw in purpose_lower for kw in (
        "compare", "comparing", "comparison",
        "which is", "which is greater", "which is larger", "which is smaller",
        "greater than", "less than",
        "compare both", "comparing both",
        "versus",
    ))

    if is_comparison:
        numeric_pairs = []  # [(original_value, float_value), ...]
        for _dep_id, value in dep_items:
            try:
                if isinstance(value, bool):
                    continue
                numeric_pairs.append((value, float(value)))
            except (ValueError, TypeError):
                pass

        if len(numeric_pairs) >= 2:
            orig_v1, cmp_v1 = numeric_pairs[0]
            orig_v2, cmp_v2 = numeric_pairs[1]

            if len(numeric_pairs) == 2:
                if cmp_v1 == cmp_v2:
                    comparison = f" Comparison: both results are equal ({orig_v1})."
                elif cmp_v1 > cmp_v2:
                    comparison = f" Comparison: {orig_v1} is greater than {orig_v2}."
                else:
                    comparison = f" Comparison: {orig_v2} is greater than {orig_v1}."
            else:
                cmp_values = [pair[1] for pair in numeric_pairs]
                max_cmp = max(cmp_values)
                min_cmp = min(cmp_values)
                # Find original values corresponding to max/min
                max_orig = next(pair[0] for pair in numeric_pairs if pair[1] == max_cmp)
                min_orig = next(pair[0] for pair in numeric_pairs if pair[1] == min_cmp)
                if max_cmp == min_cmp:
                    comparison = f" Comparison: all results are equal ({max_orig})."
                else:
                    comparison = f" Comparison: highest is {max_orig}, lowest is {min_orig}."

            summary_text = summary_text + comparison

    return summary_text


def _try_deterministic_synthesis(
    agent: dict,
    input_data: str,
    context: Optional[dict],
) -> Optional[dict]:
    """
    Attempt deterministic simple-synthesis for scalar dependency-output summaries.

    Returns a result dict compatible with execute_tool_selection if the pattern
    matches, otherwise None (caller should fall back to AG1).
    """
    if not isinstance(context, dict):
        return None

    cap = context.get("capability_metadata")
    if cap:
        if cap.get("transform_required") is True:
            return None
        if cap.get("final_action") not in (None, "present"):
            return None

    # Must have dependency outputs with >= 2 items
    dep_outputs = context.get("dependency_outputs")
    if not dep_outputs or not isinstance(dep_outputs, dict) or len(dep_outputs) < 2:
        return None

    # Purpose must imply synthesis
    purpose = input_data if isinstance(input_data, str) else ""
    if not _looks_like_synthesis_purpose(purpose):
        return None

    # Check for SAME retry enforcement — if we're retrying, let AG1 handle it
    # unless the prior tool was finalize_output
    allowed_tool = context.get("allowed_tool")
    if allowed_tool and allowed_tool != "finalize_output":
        return None

    # Build deterministic text
    summary_text = _build_deterministic_summary_text(dep_outputs, purpose)
    if not summary_text:
        return None

    # Route through finalize_output
    tool_call = f'finalize_output "{escape_for_tool_call(summary_text)}"'
    execution_result = system_entry(tool_call)

    output_value = None
    if isinstance(execution_result, dict) and execution_result.get("status") == "success":
        result_value = execution_result.get("result")
        if isinstance(result_value, str):
            output_value = result_value

    return {
        "status": "success",
        "result": {
            "agent": agent.get("name", "generic_agent"),
            "role": agent.get("role", "tool_executor"),
            "reasoning": "Deterministic simple-synthesis path (PDIAG-007D)",
            "output": output_value,
            "executed_input": tool_call,
            "execution_result": execution_result,
            "suggestions": [],
            "deterministic_synthesis": True,
            "deterministic_synthesis_reason": "simple_scalar_dependency_summary",
        }
    }


def _try_single_dependency_presentation(
    agent: dict,
    input_data: str,
    context: Optional[dict],
) -> Optional[dict]:
    """
    AGENT-001E-FIX4: Deterministic presentation for single-dependency finalize steps.

    Bypasses AG1 for narrow cases where a single prior step produced concrete
    output (e.g. list_files) and the current step's purpose is to present it.
    Prevents AG1 from emitting intro-only or tool-name-echo outputs.
    """
    if not isinstance(context, dict):
        return None

    cap = context.get("capability_metadata")
    if cap:
        if cap.get("transform_required") is True:
            return None
        if cap.get("final_action") not in (None, "present"):
            return None

    dep_outputs = context.get("dependency_outputs")
    if not dep_outputs or not isinstance(dep_outputs, dict) or len(dep_outputs) != 1:
        return None

    allowed_tool = context.get("allowed_tool")
    if allowed_tool != "finalize_output":
        return None

    purpose = input_data if isinstance(input_data, str) else ""
    purpose_lower = purpose.lower()

    # Narrow presentation keywords
    presentation_keywords = [
        "present", "show", "display", "listing", "result", "output", "contents",
    ]
    if not any(kw in purpose_lower for kw in presentation_keywords):
        return None

    dep_id, dep_output = next(iter(dep_outputs.items()))
    data = dep_output.get("data") if isinstance(dep_output, dict) else dep_output
    if not isinstance(data, str):
        return None

    # Preserve empty-string results (FIX3 contract); list_files already returns "(empty)"
    if data is None:
        return None

    # Restrict to list_files (known AG1-weak case) or explicitly listing-focused
    prior_tool = dep_output.get("selected_tool") or ""
    prior_tool_name = ""
    if isinstance(prior_tool, str):
        prior_tool_name = prior_tool.strip().split()[0] if prior_tool.strip() else ""
    else:
        prior_tool_name = str(prior_tool)

    is_list_files = prior_tool_name == "list_files"
    has_listing_purpose = "listing" in purpose_lower

    # AGENT-001G-IMPL1: read_webpage -> finalize_output source-grounded presentation
    is_read_webpage = prior_tool_name == "read_webpage"
    has_webpage_purpose = any(
        kw in purpose_lower
        for kw in ["webpage", "web page", "page", "url", "website", "site"]
    )

    if not is_list_files and not has_listing_purpose:
        if not (is_read_webpage and has_webpage_purpose):
            return None

    # Build deterministic finalize_output tool call
    _escaped = data.replace('"', '\\"')
    tool_call = f'finalize_output "{_escaped}"'
    execution_result = system_entry(tool_call)

    output_value = None
    if isinstance(execution_result, dict) and execution_result.get("status") == "success":
        result_value = execution_result.get("result")
        if isinstance(result_value, str):
            output_value = result_value

    return {
        "status": "success",
        "result": {
            "agent": agent.get("name", "generic_agent"),
            "role": agent.get("role", "tool_executor"),
            "reasoning": "Deterministic single-dependency presentation (AGENT-001E-FIX4)",
            "output": output_value,
            "executed_input": tool_call,
            "execution_result": execution_result,
            "suggestions": [],
            "deterministic_synthesis": True,
            "deterministic_synthesis_reason": "single_dependency_presentation",
        }
    }


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

    # === Sprint 9B: AG1 event emission (failure-isolated) ===
    if _ag1_event_emitter is not None:
        try:
            _ag1_event_emitter.emit_tool_selection_started(
                workflow_id=_ag1_wf_id,
                step_id=_ag1_step_id,
                input_data=input_data,
            )
        except Exception:
            pass

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

        # === PDIAG-008B8: Pre-dispatch file path grounding (USE_TOOL fast path) ===
        # Correct AG1 filename typos before system_entry executes to prevent wrong-path
        # side effects on mutating tools (write_file, edit_file, append_file).
        _b8_purpose = (context or {}).get("purpose", "") if isinstance(context, dict) else ""
        _b8_already = (context or {}).get("user_path_grounding_attempted", False) if isinstance(context, dict) else False
        _b8_grounded_meta = None
        if _b8_purpose and not _b8_already:
            try:
                from system.orchestrator.path_grounding import ground_tool_call_to_purpose_path
                _b8_corrected = ground_tool_call_to_purpose_path(tool_call, _b8_purpose, _b8_already)
                if _b8_corrected is not None:
                    _b8_grounded_meta = {
                        "user_path_grounding_attempted": True,
                        "user_path_grounding_phase": "pre_system_entry",
                        "purpose_path": _b8_purpose,
                        "original_executed_input": tool_call,
                        "grounded_executed_input": _b8_corrected,
                    }
                    tool_call = _b8_corrected
                    tool_name = tool_call.split()[0] if tool_call.split() else tool_name
            except Exception:
                pass

        execution_result = system_entry(tool_call, mode=_mode)

        if _b8_grounded_meta is not None:
            _b8_grounded_meta["grounding_result_status"] = execution_result.get("status") if isinstance(execution_result, dict) else "unknown"

        # === Sprint 9B: Tool selected event (failure-isolated) ===
        if _ag1_event_emitter is not None:
            try:
                _ag1_event_emitter.emit_tool_selected(
                    workflow_id=_ag1_wf_id,
                    step_id=_ag1_step_id,
                    selected_tool=tool_name,
                    provider=_fmt_provider_name if "_fmt_provider_name" in locals() else None,
                    model=None,
                )
            except Exception:
                pass

        raw_output = str(execution_result)
        formatted_output = _format_tool_output(input_data, raw_output, workflow_id=_ag1_wf_id)

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
        if _b8_grounded_meta is not None:
            result["result"]["_user_path_grounding_meta"] = _b8_grounded_meta

        return result

    # === AGENT-001E-FIX4: Deterministic single-dependency presentation ===
    # Bypass AG1 for narrow single-dependency presentation steps (e.g. list_files).
    _pres_result = _try_single_dependency_presentation(agent, input_data, context)
    if _pres_result is not None:
        return _pres_result

    # === PDIAG-007D: Deterministic simple-synthesis path ===
    # Bypass AG1 for narrow common scalar dependency-output summaries.
    # Preserves AG1 fallback for complex/ambiguous cases.
    _det_result = _try_deterministic_synthesis(agent, input_data, context)
    if _det_result is not None:
        return _det_result

    # === STEP IO: DEPENDENCY-ONLY CONTEXT (STEP_IO_CONTRACT_V1 Section 3) ===
    # Agent receives ONLY outputs from declared dependencies.
    # No global last_result, no implicit chaining.
    # PDIAG-006-F1: Enriched dependency context includes step purpose/label.
    # PDIAG-007F: Rich dependency context includes prior tool, resource, and result
    # so AG1 consumes the output instead of re-invoking the upstream tool.
    context_block = ""
    if context and isinstance(context, dict) and context.get("dependency_outputs"):
        _dep_outputs = context["dependency_outputs"]
        _dep_lines = ["Dependency outputs:"]
        for dep_id, dep_output in _dep_outputs.items():
            _dep_lines.append(f"  {dep_id}")
            _prior_purpose = dep_output.get("purpose")
            if _prior_purpose:
                _dep_lines.append(f"    prior purpose: {_prior_purpose}")
            _prior_tool = dep_output.get("selected_tool") or dep_output.get("tool_call")
            _tool_name = None
            if isinstance(_prior_tool, str):
                _tool_name = _prior_tool.strip().split()[0] if _prior_tool.strip() else None
            elif _prior_tool:
                _tool_name = str(_prior_tool)
            if _tool_name:
                _dep_lines.append(f"    prior tool: {_tool_name}")
            _resource = dep_output.get("resource_targets")
            if _resource and isinstance(_resource, list) and _resource:
                _resource = _resource[0]
            elif _resource:
                _resource = str(_resource)
            else:
                _resource = _extract_resource_from_tool_call(dep_output.get("tool_call"))
            if _resource:
                _dep_lines.append(f"    resource: {_resource}")
            _raw_data = dep_output.get("data")
            if _raw_data is not None:
                _data = _safe_truncate(_raw_data)
                _dep_lines.append(f"    result: {_data}")
        context_block = "\n" + "\n".join(_dep_lines) + "\n"

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
        # PDIAG-006: Fallback now includes use_when/do_not_use_when for disambiguation
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

            # Build compact fallback line
            lines = [f"- {tool_name} {args}"]

            category = tool_data.get("category")
            if category:
                lines.append(f"  category: {category}")

            description = tool_data.get("description", "").strip()
            if description:
                lines.append(f"  use: {description}")

            tool_lines.append("\n".join(lines))
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
        path_routing_boundary = """PATH ROUTING BOUNDARY:
- Use the allowed tool only. Do not use other tools."""
    else:
        # Normal operation with compact boundary
        path_routing_boundary = """PATH ROUTING BOUNDARY:
- Web targets (http/https) -> use read_webpage/web_search
- Local file paths -> use read_file/write_file/append_file/edit_file/etc
- To append to an existing local file -> use append_file, not edit_file or write_file
- Do not mix web and local tools"""

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

Dependency math example:
- Dependency output: step_1 = 30
- Current step: "Multiply the result of step_1 by 3"
- Correct: USE_TOOL: multiply_numbers 30 3
- WRONG: USE_TOOL: multiply_numbers 30 90
- Do NOT pre-compute 30 × 3 = 90. Pass the literal operand 3.

---

3. DEPENDENCY OUTPUT USAGE

- Dependency outputs are already available content. Do NOT re-read or re-fetch them.
- When dependency outputs are provided, use their literal values in arguments.
- Do NOT use symbolic references like $step_1 or placeholders like <<step_1>>.
- For summarization, explanation, final answer, or synthesis over a dependency output, use finalize_output.
- For edit_file after a read_file dependency, use the prior read result EXACTLY as old_text.
- Preserve punctuation and whitespace in old_text.
- dry_run must be 0 unless the user explicitly asks for a dry run/preview.
- When a step depends on multiple prior outputs and the purpose is to summarize, explain, report, compare, synthesize, or produce a final answer from those outputs, use finalize_output once. Do not write back to the original file. Do not re-read local files. Do not re-fetch URLs. Do not use edit_file, read_file, read_webpage, grep, or other resource tools for this synthesis step unless the user explicitly asks to perform a new resource operation.

Example: step_1: 30 → pass 30 as the argument value.

Example — read then edit:
The old_text for edit_file must be the literal dependency output value from the prior read_file step. Do not add punctuation, remove punctuation, summarize, normalize, decorate, or infer old_text from the example. Copy the dependency result exactly.

Dependency output:
  step_1
    prior tool: read_file
    resource: tmp/pdiag007_gate2_test.txt
    result: hello from gate 2
Current step: Edit tmp/pdiag007_gate2_test.txt, replacing the current content with the new text: hello from gate 2 after edit, using the result of step_1
Correct: USE_TOOL: edit_file "tmp/pdiag007_gate2_test.txt" "hello from gate 2" "hello from gate 2 after edit" 0 0
Wrong:  USE_TOOL: read_file "tmp/pdiag007_gate2_test.txt"
Wrong:  USE_TOOL: edit_file "tmp/pdiag007_gate2_test.txt" "" "hello from gate 2 after edit" 0 0
Wrong:  USE_TOOL: edit_file "tmp/pdiag007_gate2_test.txt" "hello from gate 2." "hello from gate 2 after edit" 0 0

Example — webpage then summarize:
Dependency output:
  step_1
    prior tool: read_webpage
    resource: https://example.com
    result: Example Domain ...
Current step: Summarize what the page is about using the result of step_1 at https://example.com
Correct: USE_TOOL: finalize_output "The page is Example Domain, a placeholder domain used for documentation examples."
Wrong:  USE_TOOL: read_webpage "https://example.com"
Wrong:  USE_TOOL: finalize_output "The webpage is about <<step_1>>."

Example — file + webpage then summarize both separately:
Dependency outputs:
  step_1
    prior purpose: Read the local file tmp/pdiag007_gate2_test.txt
    prior tool: read_file
    resource: tmp/pdiag007_gate2_test.txt
    result: hello from gate 2 after edit
  step_2
    prior purpose: Read https://example.com
    prior tool: read_webpage
    resource: https://example.com
    result: Example Domain ...
Current step: Summarize the result of step_1 and the result of step_2 separately.
Correct: USE_TOOL: finalize_output "Local file: The file contains 'hello from gate 2 after edit'. Webpage: The webpage is Example Domain, a placeholder domain used for documentation examples."
Wrong: USE_TOOL: edit_file "tmp/pdiag007_gate2_test.txt" ...
Wrong: USE_TOOL: read_file "tmp/pdiag007_gate2_test.txt"
Wrong: USE_TOOL: read_webpage "https://example.com"
Wrong: USE_TOOL: grep ...

---

4. INPUT INTEGRITY

- Pass only original inputs or previous outputs
- DO NOT modify or invent values

---

5. TOOL-ONLY EXECUTION

- If a tool exists → you MUST use it
- DO NOT simulate tool behavior

---

6. OUTPUT FORMAT

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

{path_routing_boundary}

---

7. DECISION BOUNDARY (CRITICAL):

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

- SUMMARIZATION BOUNDARY (CRITICAL):
  → When the task is summarization, explanation, reporting, final answer synthesis,
    or synthesis of prior/dependency outputs, use finalize_output.
  → Do NOT select math tools merely because dependency outputs contain numbers.
  → Numeric dependency outputs are data to summarize unless the current step explicitly asks for a math operation.

Examples:

Input: "tell me a joke"
Output: USE_TOOL: finalize_output "Why don't scientists trust atoms? Because they make up everything."

Input: "Write a short friendly greeting for Bryan"
Output: USE_TOOL: finalize_output "Hello Bryan! Hope you're having a great day."

Input: "what is 2+2"
Output: USE_TOOL: add_numbers 2 2

---

8. NO TOOL CASE

If no tool applies, you MUST use finalize_output.
DO NOT respond without a USE_TOOL line.
DO NOT say "I don't have a tool".
DO NOT ask for clarification if the request is clear.

---

9. STRICT TOOL MATCHING (CRITICAL)

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

10. SINGLE TOOL ENFORCEMENT

- You MUST output EXACTLY ONE of:
  ✔ ONE valid USE_TOOL line
  OR
  ✔ normal response (no USE_TOOL)

- NEVER output multiple USE_TOOL lines
- NEVER combine tool calls

{context_block}
{retry_guidance_section}
{memory_prompt_section}
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
        if _ag1_event_emitter is not None:
            try:
                _ag1_event_emitter.emit_tool_selection_failed(
                    workflow_id=_ag1_wf_id,
                    step_id=_ag1_step_id,
                    reason="multiple_tool_calls_not_allowed",
                )
            except Exception:
                pass
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
        if _ag1_event_emitter is not None:
            try:
                _ag1_event_emitter.emit_tool_selection_failed(
                    workflow_id=_ag1_wf_id,
                    step_id=_ag1_step_id,
                    reason="llm_error",
                )
            except Exception:
                pass
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

        # C. Construct canonical executable tool call
        tool_call = f'finalize_output "{escaped_response}"'

        # D. Execute via system_entry (SINGLE CALL)
        execution_result = system_entry(tool_call)

        output_value = None
        if isinstance(execution_result, dict) and execution_result.get("status") == "success":
            result_value = execution_result.get("result")
            if isinstance(result_value, str):
                output_value = result_value

        return {
            "status": "success",
            "result": {
                "agent": agent["name"],
                "role": agent["role"],
                "reasoning": "Non-tool response routed via finalize_output",
                "output": output_value,
                "executed_input": tool_call,
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
        tool_call_fb = f'finalize_output "{escaped_response}"'
        execution_result = system_entry(tool_call_fb)

        output_value = None
        if isinstance(execution_result, dict) and execution_result.get("status") == "success":
            result_value = execution_result.get("result")
            if isinstance(result_value, str):
                output_value = result_value

        return {
            "status": "success",
            "result": {
                "agent": agent["name"],
                "role": agent["role"],
                "reasoning": "Non-tool response routed via finalize_output",
                "output": output_value,
                "executed_input": tool_call_fb,
                "execution_result": execution_result,
                "suggestions": []
            }
        }

    tool_line = tool_lines[0]

    # --- TOOL_CALL CONVERSION (via interface module) ---
    tool_call, failure = convert_agent_output_to_tool_call(tool_line)

    # === PDIAG-007E: UNKNOWN TOOL ENFORCEMENT ===
    # If AG1 emits a tool name not in tools.json, retry once with explicit
    # correction guidance. Do not dispatch unknown tools to system_entry.
    _unknown_tool_metadata = {
        "original_tool_call": tool_line,
        "unknown_tool_name": None,
        "retry_attempted": False,
        "final_tool_call": None,
        "failure_reason": None,
    }

    if failure and failure.get("reason") in ("unknown_tool", "non_production_tool"):
        # Extract the unknown tool name for metadata and correction prompt
        try:
            _raw_call = tool_line.split("USE_TOOL:", 1)[1].strip()
            _unknown_tool_name = _raw_call.split()[0] if _raw_call.split() else None
        except Exception:
            _unknown_tool_name = None
        _unknown_tool_metadata["unknown_tool_name"] = _unknown_tool_name
        _unknown_tool_metadata["failure_reason"] = failure.get("reason")

        _correction_prompt = prompt + (
            "\n\nCRITICAL CORRECTION — PREVIOUS CALL REJECTED:\n"
            f"Tool '{_unknown_tool_name}' does not exist or is not available.\n"
            "You MUST ONLY use tools from the Available Tools list.\n"
            "For summarization, final answers, reporting, explanation, or synthesis of prior outputs, "
            "USE_TOOL: finalize_output \"<your response>\"\n"
            "Do NOT invent tool names. Do NOT use tools that are not in the list.\n"
        )

        _retry_llm_result = execute_llm(
            provider,
            _correction_prompt,
            _perf_caller="ag1_unknown_tool_retry",
            workflow_id=_ag1_wf_id,
        )
        _unknown_tool_metadata["retry_attempted"] = True

        if _retry_llm_result.get("status") == "success":
            _retry_output = _retry_llm_result["result"]
            _retry_tool_lines = [line for line in _retry_output.splitlines() if "USE_TOOL:" in line]

            # Enforce single USE_TOOL line on retry
            if len(_retry_tool_lines) != 1:
                _unknown_tool_metadata["final_tool_call"] = _retry_output
                if _ag1_event_emitter is not None:
                    try:
                        _ag1_event_emitter.emit_tool_selection_failed(
                            workflow_id=_ag1_wf_id,
                            step_id=_ag1_step_id,
                            reason="ag1_unknown_tool_retry_invalid",
                        )
                    except Exception:
                        pass
                return {
                    "status": "success",
                    "result": {
                        "agent": agent["name"],
                        "role": agent["role"],
                        "reasoning": _retry_output,
                        "output": None,
                        "executed_input": _retry_tool_lines[0] if _retry_tool_lines else None,
                        "execution_result": {
                            "status": "failure",
                            "reason": "ag1_unknown_tool_detected",
                        },
                        "_unknown_tool_metadata": _unknown_tool_metadata,
                    }
                }

            _retry_tool_line = _retry_tool_lines[0]
            _retry_tool_call, _retry_failure = convert_agent_output_to_tool_call(_retry_tool_line)

            if _retry_failure:
                _unknown_tool_metadata["final_tool_call"] = _retry_tool_line
                if _ag1_event_emitter is not None:
                    try:
                        _ag1_event_emitter.emit_tool_selection_failed(
                            workflow_id=_ag1_wf_id,
                            step_id=_ag1_step_id,
                            reason="ag1_unknown_tool_retry_conversion_failed",
                        )
                    except Exception:
                        pass
                return {
                    "status": "success",
                    "result": {
                        "agent": agent["name"],
                        "role": agent["role"],
                        "reasoning": _retry_tool_line,
                        "output": None,
                        "executed_input": _retry_tool_line,
                        "execution_result": {
                            "status": "failure",
                            "reason": "ag1_unknown_tool_detected",
                        },
                        "_unknown_tool_metadata": _unknown_tool_metadata,
                    }
                }

            # Retry succeeded with a known tool
            tool_call = _retry_tool_call
            llm_output = _retry_tool_line
            _unknown_tool_metadata["final_tool_call"] = tool_call
        else:
            # LLM retry call itself failed
            _unknown_tool_metadata["final_tool_call"] = None
            if _ag1_event_emitter is not None:
                try:
                    _ag1_event_emitter.emit_tool_selection_failed(
                        workflow_id=_ag1_wf_id,
                        step_id=_ag1_step_id,
                        reason="ag1_unknown_tool_retry_llm_failed",
                    )
                except Exception:
                    pass
            return {
                "status": "success",
                "result": {
                    "agent": agent["name"],
                    "role": agent["role"],
                    "reasoning": "LLM retry failed after unknown tool detection",
                    "output": None,
                    "executed_input": None,
                    "execution_result": {
                        "status": "failure",
                        "reason": "ag1_unknown_tool_detected",
                    },
                    "_unknown_tool_metadata": _unknown_tool_metadata,
                }
            }

    elif failure:
        # Sprint 10: bounded fallback for finalize_output with unescaped inner quotes
        # AG1 may produce USE_TOOL: finalize_output "text with "nested" quotes"
        # which breaks shlex.split. Fallback: extract intended text, escape, rebuild.
        if _allowed_tool == "finalize_output" and failure.get("reason") == "invalid_tool_syntax":
            _raw = tool_line.split("USE_TOOL:", 1)[1].strip() if tool_line.startswith("USE_TOOL:") else tool_line.strip()
            if _raw.startswith("finalize_output"):
                _raw = _raw[len("finalize_output"):].strip()
            if (_raw.startswith('"') and _raw.endswith('"')) or (_raw.startswith("'") and _raw.endswith("'")):
                _raw = _raw[1:-1]
            _escaped = escape_for_tool_call(_raw)
            _tool_call = f'finalize_output "{_escaped}"'
            _execution_result = system_entry(_tool_call)
            _output_value = None
            if isinstance(_execution_result, dict) and _execution_result.get("status") == "success":
                _result_value = _execution_result.get("result")
                if isinstance(_result_value, str):
                    _output_value = _result_value
            return {
                "status": "success",
                "result": {
                    "agent": agent["name"],
                    "role": agent["role"],
                    "reasoning": "finalize_output malformed quote fallback",
                    "output": _output_value,
                    "executed_input": _tool_call,
                    "execution_result": _execution_result,
                }
            }

        # Other conversion failures (invalid_tool_syntax, tool_index_unavailable):
        # keep original behavior, no retry.
        if _ag1_event_emitter is not None:
            try:
                _ag1_event_emitter.emit_tool_selection_failed(
                    workflow_id=_ag1_wf_id,
                    step_id=_ag1_step_id,
                    reason=failure.get("reason", "tool_conversion_failed"),
                )
            except Exception:
                pass
        return {
            "status": "success",
            "result": {
                "output": None,
                "executed_input": tool_line,
                "execution_result": failure,
                "_unknown_tool_metadata": _unknown_tool_metadata,
            }
        }

    # === PDIAG-007F: DEPENDENCY PLACEHOLDER ENFORCEMENT ===
    # If AG1 emits a tool call containing symbolic dependency references like
    # <<step_1>> or $step_1, retry once with explicit correction guidance.
    _placeholder_metadata = {
        "original_tool_call": tool_call,
        "placeholder_detected": False,
        "retry_attempted": False,
        "final_tool_call": tool_call,
    }
    if _contains_dependency_placeholder(tool_call):
        _placeholder_metadata["placeholder_detected"] = True
        _placeholder_correction_prompt = prompt + (
            "\n\nCRITICAL CORRECTION — PREVIOUS CALL REJECTED:\n"
            "Your previous tool call contained a symbolic dependency reference "
            "(e.g., $step_1, <<step_1>>, or <step_1>).\n"
            "Dependency outputs are already provided above. You MUST use their literal values, "
            "not symbolic references.\n"
            "For summarization, final answers, reporting, explanation, or synthesis of prior outputs, "
            "USE_TOOL: finalize_output \"<your response>\"\n"
        )
        _retry_placeholder_result = execute_llm(
            provider,
            _placeholder_correction_prompt,
            _perf_caller="ag1_placeholder_retry",
            workflow_id=_ag1_wf_id,
        )
        _placeholder_metadata["retry_attempted"] = True
        if _retry_placeholder_result.get("status") == "success":
            _retry_placeholder_output = _retry_placeholder_result["result"]
            _retry_placeholder_lines = [line for line in _retry_placeholder_output.splitlines() if "USE_TOOL:" in line]
            if len(_retry_placeholder_lines) == 1:
                _retry_placeholder_line = _retry_placeholder_lines[0]
                _retry_placeholder_call, _retry_placeholder_failure = convert_agent_output_to_tool_call(_retry_placeholder_line)
                if not _retry_placeholder_failure and not _contains_dependency_placeholder(_retry_placeholder_call):
                    tool_call = _retry_placeholder_call
                    llm_output = _retry_placeholder_line
                    _placeholder_metadata["final_tool_call"] = tool_call
                else:
                    _placeholder_metadata["final_tool_call"] = _retry_placeholder_line
                    return {
                        "status": "success",
                        "result": {
                            "agent": agent["name"],
                            "role": agent["role"],
                            "reasoning": _retry_placeholder_line,
                            "output": None,
                            "executed_input": _retry_placeholder_line,
                            "execution_result": {
                                "status": "failure",
                                "reason": "ag1_dependency_placeholder_detected",
                            },
                            "_placeholder_metadata": _placeholder_metadata,
                        },
                    }
            else:
                _placeholder_metadata["final_tool_call"] = _retry_placeholder_output
                return {
                    "status": "success",
                    "result": {
                        "agent": agent["name"],
                        "role": agent["role"],
                        "reasoning": _retry_placeholder_output,
                        "output": None,
                        "executed_input": _retry_placeholder_lines[0] if _retry_placeholder_lines else None,
                        "execution_result": {
                            "status": "failure",
                            "reason": "ag1_dependency_placeholder_detected",
                        },
                        "_placeholder_metadata": _placeholder_metadata,
                    },
                }
        else:
            _placeholder_metadata["final_tool_call"] = None
            return {
                "status": "success",
                "result": {
                    "agent": agent["name"],
                    "role": agent["role"],
                    "reasoning": "LLM retry failed after dependency placeholder detection",
                    "output": None,
                    "executed_input": None,
                    "execution_result": {
                        "status": "failure",
                        "reason": "ag1_dependency_placeholder_detected",
                    },
                    "_placeholder_metadata": _placeholder_metadata,
                },
            }

    # Sprint 7C ISSUE-098A: SAME retry selected-tool validation
    if _allowed_tool:
        _selected_tool = tool_call.strip().split()[0] if tool_call.strip().split() else None
        if _selected_tool != _allowed_tool:
            if _ag1_event_emitter is not None:
                try:
                    _ag1_event_emitter.emit_tool_selection_failed(
                        workflow_id=_ag1_wf_id,
                        step_id=_ag1_step_id,
                        reason="same_retry_wrong_tool",
                    )
                except Exception:
                    pass
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
            if _ag1_event_emitter is not None:
                try:
                    _ag1_event_emitter.emit_tool_selection_failed(
                        workflow_id=_ag1_wf_id,
                        step_id=_ag1_step_id,
                        reason="external_call_user_control_blocked",
                    )
                except Exception:
                    pass
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

    # === PDIAG-007: POST-AG1 MATH PRE-COMPUTATION GUARD ===
    _guard_result = _detect_precomputation(tool_call, input_data, context)
    _guard_metadata = {
        "original_tool_call": tool_call,
        "guard_applied": False,
        "guard_suspicious": False,
        "guard_reason": None,
        "retry_attempted": False,
        "final_tool_call": tool_call,
    }

    if _guard_result.get("is_suspicious"):
        _guard_metadata["guard_applied"] = True
        _guard_metadata["guard_suspicious"] = True
        _guard_metadata["guard_reason"] = _guard_result.get("reason")
        _guard_metadata["detected_computation"] = _guard_result.get("detected_computation")
        _guard_metadata["dependency_value"] = _guard_result.get("dependency_value")
        _guard_metadata["literal_operand"] = _guard_result.get("literal_operand")
        _guard_metadata["suspicious_argument"] = _guard_result.get("suspicious_argument")

        # Log guard detection
        print("[AG1_MATH_GUARD] " + json.dumps({
            "event": "precomputation_detected",
            "workflow_id": _ag1_wf_id,
            "step_id": _ag1_step_id,
            "original_tool_call": tool_call,
            "detected_computation": _guard_result.get("detected_computation"),
        }))

        # === BOUNDED RETRY WITH STRICTER GUIDANCE ===
        _retry_prompt = prompt + (
            "\n\nCRITICAL CORRECTION — PREVIOUS CALL REJECTED:\n"
            "Your previous tool call contained a PRE-COMPUTED result.\n"
            "You MUST NOT pass the final computed answer as a tool argument.\n"
            "Pass ONLY the dependency output value and the literal operand from the instruction.\n"
            "DO NOT compute the result yourself. The tool will compute it.\n"
            "Example correction:\n"
            "- Dependency output: 30\n"
            "- Instruction: multiply by 3\n"
            "- Correct: USE_TOOL: multiply_numbers 30 3\n"
            "- WRONG: USE_TOOL: multiply_numbers 30 90\n"
        )

        _retry_llm_result = execute_llm(provider, _retry_prompt, _perf_caller="ag1_tool_selection_guard_retry", workflow_id=_ag1_wf_id)
        _guard_metadata["retry_attempted"] = True

        if _retry_llm_result.get("status") == "success":
            _retry_output = _retry_llm_result["result"]
            # Re-parse USE_TOOL line from retry output
            _retry_lines = [line for line in _retry_output.splitlines() if "USE_TOOL:" in line]
            if _retry_lines:
                _retry_tool_line = _retry_lines[0]
                _retry_tool_call, _retry_failure = convert_agent_output_to_tool_call(_retry_tool_line)
                if not _retry_failure:
                    _retry_guard = _detect_precomputation(_retry_tool_call, input_data, context)
                    if not _retry_guard.get("is_suspicious"):
                        tool_call = _retry_tool_call
                        llm_output = _retry_tool_line
                        _guard_metadata["final_tool_call"] = tool_call
                    else:
                        # Retry still suspicious — fail step
                        print("[AG1_MATH_GUARD] " + json.dumps({
                            "event": "retry_still_suspicious",
                            "workflow_id": _ag1_wf_id,
                            "step_id": _ag1_step_id,
                            "retry_tool_call": _retry_tool_call,
                        }))
                        if _ag1_event_emitter is not None:
                            try:
                                _ag1_event_emitter.emit_tool_selection_failed(
                                    workflow_id=_ag1_wf_id,
                                    step_id=_ag1_step_id,
                                    reason="ag1_precomputed_tool_argument_detected",
                                )
                            except Exception:
                                pass
                        return {
                            "status": "success",
                            "result": {
                                "agent": agent["name"],
                                "role": agent["role"],
                                "reasoning": _retry_tool_line,
                                "output": None,
                                "executed_input": _retry_tool_call,
                                "execution_result": {
                                    "status": "failure",
                                    "reason": "ag1_precomputed_tool_argument_detected",
                                },
                                "_guard_metadata": _guard_metadata,
                            },
                        }

    # === Sprint 9B: Tool selected event before main path dispatch (failure-isolated) ===
    _ag1_selected_tool_main = tool_call.strip().split()[0] if tool_call.strip().split() else None
    if _ag1_event_emitter is not None:
        try:
            _ag1_event_emitter.emit_tool_selected(
                workflow_id=_ag1_wf_id,
                step_id=_ag1_step_id,
                selected_tool=_ag1_selected_tool_main,
                provider=provider.get("name") if isinstance(provider, dict) else None,
                model=provider.get("model") if isinstance(provider, dict) else None,
            )
        except Exception:
            pass

    # === PDIAG-008B8: Pre-dispatch file path grounding (main LLM path) ===
    # Correct AG1 filename typos before system_entry executes to prevent wrong-path
    # side effects on mutating tools (write_file, edit_file, append_file).
    _b8_purpose_main = (context or {}).get("purpose", "") if isinstance(context, dict) else ""
    _b8_already_main = (context or {}).get("user_path_grounding_attempted", False) if isinstance(context, dict) else False
    _b8_grounded_meta_main = None
    if _b8_purpose_main and not _b8_already_main:
        try:
            from system.orchestrator.path_grounding import ground_tool_call_to_purpose_path
            _b8_corrected_main = ground_tool_call_to_purpose_path(tool_call, _b8_purpose_main, _b8_already_main)
            if _b8_corrected_main is not None:
                _b8_grounded_meta_main = {
                    "user_path_grounding_attempted": True,
                    "user_path_grounding_phase": "pre_system_entry",
                    "purpose_path": _b8_purpose_main,
                    "original_executed_input": tool_call,
                    "grounded_executed_input": _b8_corrected_main,
                }
                tool_call = _b8_corrected_main
        except Exception:
            pass

    execution_result = system_entry(tool_call)

    if _b8_grounded_meta_main is not None:
        _b8_grounded_meta_main["grounding_result_status"] = execution_result.get("status") if isinstance(execution_result, dict) else "unknown"

    if isinstance(execution_result, dict) and execution_result.get("status") == "failure":
        failure_reason = execution_result.get("reason", "unknown error")
        formatted_output = f"Could not complete request: {failure_reason}"
    else:
        raw_output = str(execution_result)
        formatted_output = _format_tool_output(input_data, raw_output, workflow_id=_ag1_wf_id)

    result = {
        "status": "success",
        "result": {
            "agent": agent["name"],
            "role": agent["role"],
            "reasoning": llm_output.strip(),
            "output": formatted_output,
            "executed_input": tool_call,
            "execution_result": execution_result,
            "_guard_metadata": _guard_metadata,
            "_unknown_tool_metadata": _unknown_tool_metadata,
            "_placeholder_metadata": _placeholder_metadata,
        }
    }
    if _b8_grounded_meta_main is not None:
        result["result"]["_user_path_grounding_meta"] = _b8_grounded_meta_main

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

"""
Tool Executor Module

PURPOSE:
    Provides tool execution, input normalization, and failure detection utilities.
    Handles the actual invocation of tools with parsed arguments.

ARCHITECTURE ROLE:
    - Execution layer: Bridges planning to actual tool invocation
    - Side effects: Executes tool functions, modifies results list
    - Contains failure detection logic for repair loops

LAYER RESPONSIBILITY:
    - Normalize various input formats to executable arguments
    - Detect tool execution failures vs domain errors
    - Track tool call history to prevent duplicates
    - Execute tools with parsed arguments

USAGE:
    from core.tool_executor import execute_tool, tool_failed
    
    output, drift_counter, prompt = execute_tool(
        tool_name="add_numbers",
        tool_input="2, 3",
        TOOLS={"add_numbers": add_func},
        results=[],
        ...
    )

FAILURE DETECTION:
    Distinguishes between:
    - Execution failures (crashes) -> Trigger repair
    - Domain errors (division by zero) -> Normal result, no repair
"""

import re
from core.config import config
from core.logger import log


def normalize_tool_input(tool_input):
    """
    Normalize tool input to a standard format.
    
    Converts various input representations to a consistent format:
    - None -> {}
    - Empty string -> {}
    - String "none" -> {}
    - Other values pass through unchanged
    
    Args:
        tool_input: Raw input to normalize (may be None, str, or other types)
        
    Returns:
        Normalized input, typically a dict or the original value
    """
    if tool_input is None:
        return {}
    if tool_input == "":
        return {}
    if isinstance(tool_input, str):
        if tool_input.strip().lower() == "none":
            return {}
    return tool_input


def tool_failed(output):
    """
    Determines whether a tool execution failed.

    A failure means the tool implementation crashed or raised an exception.
    Domain errors returned by tools (like division by zero) are NOT
    considered execution failures and should NOT trigger repair.
    
    FAILURE CATEGORIES:
        Clean Domain Errors (NOT failures):
            - Division by zero
            - Math domain errors
            - Invalid numeric literals
            - Overflow/underflow
            These are expected behaviors, not implementation bugs.
        
        Execution Failures (REPAIR needed):
            - Syntax errors in tool code
            - Name errors (undefined variables)
            - Attribute errors
            - Type errors
            - Import errors
            - Tracebacks
            These indicate broken tool implementation.
    
    Args:
        output: Tool execution result to analyze
        
    Returns:
        bool: True if tool crashed (needs repair), False if result is valid
              (even if result indicates a domain error like division by zero)
    """
    if output is None:
        return True

    text = str(output).lower()

    # First: check for known clean domain-error results
    # (these should NOT trigger repair)
    clean_domain_indicators = [
        "division by zero",
        "error: division by zero",
        "cannot divide by zero",
        "zero division",
        "invalid literal for int()",
        "invalid literal for float()",
        "math domain error",
        "overflow",
        "underflow",
    ]

    if any(ind in text for ind in clean_domain_indicators):
        return False  # <- treat as normal domain result, not crash

    # Then: only real execution/crash signals
    failure_signals = [
        "tool execution error",
        "traceback",
        "syntaxerror",
        "nameerror",
        "attributeerror",
        "typeerror",
        "importerror",
        "module not found",
        "unterminated string",
        "unsupported operand",
        "invalid literal",           # keep this one — but only if not caught above
        "index out of range",
        "missing",
    ]

    return any(signal in text for signal in failure_signals)


def parse_tool_parentheses(action_line):
    """
    Converts tool_name() syntax into TOOL/INPUT format.
    
    Transforms:
        tool_name()
    Into:
        TOOL: tool_name
        INPUT: {}
    
    Used for handling legacy or shorthand tool call syntax.
    
    Args:
        action_line (str): Tool call line potentially ending with ()
        
    Returns:
        tuple: (tool_name, {}) if matched, (None, None) if not
    """
    if action_line.endswith("()"):
        tool = action_line[:-2].strip()
        return tool, {}
    return None, None


def execute_tool(
    tool_name,
    tool_input,
    TOOLS,
    results,
    steps,
    manager_prompt,
    task_state,
    drift_counter,
    tool_history,
    log
):

    tool_input = normalize_tool_input(tool_input)

    if isinstance(tool_input, dict):
        tool_input = ""

    tool_key = (tool_name, str(tool_input))

    if tool_key in tool_history:

        log(f"Skipping repeated tool call: {tool_name}({tool_input})")

        if results:
            results.append(results[-1])

        manager_prompt += "\nSYSTEM: Tool already executed with same inputs. Use previous result.\n"

        return None, drift_counter, manager_prompt

    tool_history.add(tool_key)

    steps.append(f"ACTION: {tool_name}({tool_input})")

    try:

        args = []

        pairs = re.findall(
            r'(\w+)\s*[:=]\s*"([^"]*)"|(\w+)\s*[:=]\s*\'([^\']*)\'|(\w+)\s*[:=]\s*([^,\n]+)',
            tool_input
        )

        for p in pairs:

            if p[1]:
                value = p[1]
            elif p[3]:
                value = p[3]
            else:
                value = p[5].strip()

            if isinstance(value, str) and value.startswith("result_"):

                try:
                    index = int(value.replace("result_", "")) - 1
                    args.append(results[index])
                    continue
                except:
                    pass

            try:
                if "." in value:
                    args.append(float(value))
                else:
                    args.append(int(value))
            except:
                args.append(value)

        if not args and isinstance(tool_input, str) and "," in tool_input:

            parts = [p.strip() for p in tool_input.split(",")]

            for p in parts:
                try:
                    if "." in p:
                        args.append(float(p))
                    else:
                        args.append(int(p))
                except:
                    args.append(p)

        if not args and isinstance(tool_input, str):

            parts = tool_input.strip().split()

            if not parts:
                args = []
            elif len(parts) > 1:

                for p in parts:

                    try:
                        if "." in p:
                            args.append(float(p))
                        else:
                            args.append(int(p))
                    except:
                        args.append(p)

            else:

                value = parts[0]

                try:
                    if "." in value:
                        args = [float(value)]
                    else:
                        args = [int(value)]
                except:
                    args = [value]

        if not args:

            numbers = re.findall(r'-?\d+\.?\d*', str(tool_input))

            for n in numbers:
                if "." in n:
                    args.append(float(n))
                else:
                    args.append(int(n))

        log(f"ACTION: {tool_name}{tuple(args)}")

        output = TOOLS[tool_name](*args)

        drift_counter = 0

    except Exception as e:

        output = f"Tool execution error: {e}"

    log(f"OBSERVATION: {output}")

    steps.append(f"OBSERVATION: {output}")

    results.append(output)

    failed = tool_failed(output)

    if failed:
        manager_prompt += "\nSYSTEM: The tool execution failed. You must repair the tool before continuing.\n"
    else:
        manager_prompt += "\nSYSTEM: If the goal has been satisfied, produce FINAL ANSWER now.\n"

        # Advance step only on success (this is the single source of truth)
        if task_state.get("structured_plan") and task_state["current_step"] < len(task_state["structured_plan"]):
            if task_state["current_step"] < len(task_state.get("plan", [])):
                task_state["completed_steps"].append(
                    task_state["plan"][task_state["current_step"]]
                )
            task_state["current_step"] += 1

    return output, drift_counter, manager_prompt
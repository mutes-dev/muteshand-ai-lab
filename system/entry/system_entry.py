import json
import os
import re
import shlex

from system.registry.registry_builder import build_registries

from system.parser.parser import parse
from system.resolver.argument_resolver import resolve
from system.execution.executor import execute
from system.entry.pipeline_entry import build as entry_build
from system.observability.validator import validate


# Build registries once at module load
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
TOOL_INDEX_PATH = os.path.join(_ROOT, "system", "tool_index", "tools.json")
TOOLS_PATH = os.path.join(_ROOT, "tools")

_validation_registry, _execution_registry = build_registries(TOOL_INDEX_PATH, TOOLS_PATH)

with open(TOOL_INDEX_PATH, "r", encoding="utf-8") as _f:
    _tool_index = json.load(_f)


def system_entry(input_text: str):
    """
    System Entry — Pure Execution Layer

    CONTRACT:
    - Input: "<tool_name> <arg1> <arg2> ..."
    - Output: {"status": "success", "result": <value>} OR {"status": "failure", "reason": <string>}

    RESPONSIBILITIES:
    - parse tool_call string
    - resolve arguments
    - validate structure
    - execute tool
    - normalize output

    PROHIBITIONS:
    - NO planning
    - NO normalization
    - NO input correction
    - NO fallback logic
    - NO intelligence

    ARCHITECTURE:
    - Single-step only
    - Deterministic
    - Fail-fast
    """
    
    try:
        # STEP 1: PARSE INPUT STRING
        # Convert "tool_name arg1 arg2" to structured plan
        # Fail if input is not a valid tool_call string
        
        if not isinstance(input_text, str):
            return {
                "status": "failure",
                "reason": "invalid_input_type"
            }
        
        try:
            parts = shlex.split(input_text.strip(), posix=False)
        except ValueError:
            return {
                "status": "failure",
                "reason": "invalid_tool_call_format"
            }
        
        if len(parts) == 0:
            return {
                "status": "failure",
                "reason": "invalid_tool_call_format"
            }
        
        tool_name = parts[0]
        args_str = ' '.join(parts[1:]) if len(parts) > 1 else ''
        
        # Validate tool name format
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', tool_name):
            return {
                "status": "failure",
                "reason": "invalid_tool_name"
            }
        
        # Validate tool exists
        if tool_name not in _tool_index:
            return {
                "status": "failure",
                "reason": "unknown_tool"
            }
        
        # Construct plan format for parser
        plan = [{"type": "tool", "name": tool_name, "input_text": input_text.strip(), "clean_input": args_str}]
        
        # STEP 2: PARSE PLAN
        parsed = parse(plan)
        
        # Check if parser returned a failure dict
        if isinstance(parsed, dict) and parsed.get("status") == "failure":
            return {
                "status": "failure",
                "reason": parsed.get("reason", "parse_error")
            }
        
        # STEP 3: RESOLVE ARGUMENTS
        resolved = resolve(parsed, input_text.strip())
        
        # Check if resolver returned a failure dict
        if isinstance(resolved, dict) and resolved.get("status") == "failure":
            return {
                "status": "failure",
                "reason": resolved.get("reason", "resolve_error")
            }

        # STEP 4: SINGLE-STEP ENFORCEMENT
        if len(resolved) != 1:
            return {
                "status": "failure",
                "reason": "single_step_required"
            }

        step = resolved[0]

        # Build entry data
        entry_data = entry_build([step])

        # STEP 5: VALIDATE
        validation_result = validate(entry_data, _validation_registry)

        if validation_result.get("status") != "success":
            return {
                "status": "failure",
                "reason": validation_result.get("reason", "validation_failed")
            }

        # STEP 6: EXECUTE
        raw_result = execute(entry_data, _execution_registry)

        # STEP 7: NORMALIZE OUTPUT
        result = _normalize_output(raw_result)

        return result

    except Exception:
        # EXCEPTION HANDLER (fail-safe)
        return {
            "status": "failure",
            "reason": "execution_error"
        }


def _normalize_output(raw_result):
    """
    Normalize execution output to STRICT contract.

    Contract:
    - Success: {"status": "success", "result": <value>}
    - Failure: {"status": "failure", "reason": <string>}
    """
    # CASE 1 — NONE / INVALID
    if raw_result is None:
        return {
            "status": "failure",
            "reason": "execution_returned_none"
        }

    # CASE 2 — FAILURE OBJECT
    if isinstance(raw_result, dict) and raw_result.get("status") == "failure":
        return {
            "status": "failure",
            "reason": raw_result.get("reason", "execution_failed")
        }

    # CASE 3 — SUCCESS OBJECT (WITH EXTRA FIELDS)
    if isinstance(raw_result, dict) and raw_result.get("status") == "success":
        # Extract only the result field, ignore steps and other fields
        return {
            "status": "success",
            "result": raw_result.get("result")
        }

    # CASE 4 — RAW VALUE (EXECUTION RETURN)
    # Wrap raw value in success contract
    return {
        "status": "success",
        "result": raw_result
    }

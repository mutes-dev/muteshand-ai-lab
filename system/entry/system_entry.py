from system.entry.router import route_input
from system.planner.deterministic_planner import plan as planner_plan
from system.registry.registry_builder import build_registries

from system.parser.parser import parse
from system.resolver.argument_resolver import resolve
from system.execution.executor import execute
from system.entry.pipeline_entry import build as entry_build
from system.observability.validator import validate


# Build registries once at module load
TOOL_INDEX_PATH = "memory/tool_index/tools.json"
TOOLS_PATH = "tools"

_validation_registry, _execution_registry = build_registries(TOOL_INDEX_PATH, TOOLS_PATH)


def system_entry(input_text: str):
    """
    System Entry (Execution Orchestrator)

    Responsibilities:
    - execute routing decision
    - call planner ONLY when required
    - pass plan through full pipeline
    - return STRICTLY NORMALIZED final result

    DO NOT:
    - modify plan
    - validate manually
    - inject arguments
    - return raw execution output
    """

    try:
        router_result = route_input(input_text)

        # Planner mode
        if router_result.get("mode") == "planner":
            plan = planner_plan(input_text)

        # Direct plan mode
        elif router_result.get("mode") == "direct_plan":
            plan = router_result.get("data")

        # Fail-safe
        else:
            plan = planner_plan(input_text)

        # FULL PIPELINE (MANDATORY ORDER)
        parsed = parse(plan)
        
        # Check if parser returned a failure dict (resolver would crash on this)
        if isinstance(parsed, dict) and parsed.get("status") == "failure":
            return {
                "status": "failure",
                "reason": parsed.get("reason", "unknown_error")
            }
        
        resolved = resolve(parsed)
        
        # Check if resolver returned a failure dict
        if isinstance(resolved, dict) and resolved.get("status") == "failure":
            return {
                "status": "failure",
                "reason": resolved.get("reason", "unknown_error")
            }

        entry_data = entry_build(resolved)

        validation_result = validate(entry_data, _validation_registry)

        if validation_result.get("status") != "success":
            # CASE 1 — FAILURE OBJECT: Normalize to strict contract
            return {
                "status": "failure",
                "reason": validation_result.get("reason", "unknown_error")
            }

        raw_result = execute(entry_data, _execution_registry)

        # FINAL NORMALIZATION: Enforce strict contract
        return _normalize_output(raw_result)

    except Exception:
        # CASE 5 — EXCEPTION HANDLER
        return {
            "status": "failure",
            "reason": "execution_error"
        }


def _normalize_output(raw_result):
    """
    Normalize ANY execution output to STRICT contract.

    Contract:
    - Success: {"status": "success", "result": <value>}
    - Failure: {"status": "failure", "reason": <string>}
    """
    # CASE 4 — NONE / INVALID
    if raw_result is None:
        return {
            "status": "failure",
            "reason": "unknown_error"
        }

    # CASE 1 — FAILURE OBJECT
    if isinstance(raw_result, dict) and raw_result.get("status") == "failure":
        return {
            "status": "failure",
            "reason": raw_result.get("reason", "unknown_error")
        }

    # CASE 2 — SUCCESS OBJECT (WITH EXTRA FIELDS)
    if isinstance(raw_result, dict) and raw_result.get("status") == "success":
        # Extract only the result field, ignore steps and other fields
        return {
            "status": "success",
            "result": raw_result.get("result")
        }

    # CASE 3 — RAW VALUE (EXECUTION RETURN)
    # Wrap raw value in success contract
    return {
        "status": "success",
        "result": raw_result
    }

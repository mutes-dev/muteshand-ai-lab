from system.parser.parser import parse
from system.resolver.argument_resolver import resolve
from system.entry.main import run
from system.planner.deterministic_planner import plan


def run_from_planner(planner_output, validation_registry, execution_registry):
    if isinstance(planner_output, str):
        planner_output = plan(planner_output)

    parsed = parse(planner_output)

    if isinstance(parsed, dict) and parsed.get("status") == "failure":
        return parsed

    resolved = resolve(parsed)

    print("PIPELINE → RESOLVED PLAN:", resolved)

    return run(resolved, validation_registry, execution_registry)

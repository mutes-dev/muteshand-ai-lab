from system.orchestrator.agent_registry import register_agent, get_agent
from system.orchestrator.tool_registry import register_tool, get_tool


def initialize_system() -> dict:
    agent_result = get_agent("default_agent")

    if agent_result.get("status") != "success":
        register_agent({
            "name": "default_agent",
            "role": "General assistant",
            "scope": ["general tasks"]
        })

    tool_selection_result = get_agent("tool_selection_agent")

    if tool_selection_result.get("status") != "success":
        register_agent({
            "name": "tool_selection_agent",
            "role": "Bounded tool-selection agent",
            "scope": ["tool_selection"],
            "type": "tool_selection",
            "capabilities": ["select_tool", "route_to_system_entry"],
            "version": "1.0.0"
        })

    tool_result = get_tool("test_tool")

    if tool_result.get("status") != "success":
        register_tool({
            "name": "test_tool",
            "input_schema": {},
            "output_schema": {}
        })

    return {"status": "success"}

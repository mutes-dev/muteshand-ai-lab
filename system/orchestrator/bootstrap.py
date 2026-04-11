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

    tool_result = get_tool("test_tool")

    if tool_result.get("status") != "success":
        register_tool({
            "name": "test_tool",
            "input_schema": {},
            "output_schema": {}
        })

    return {"status": "success"}

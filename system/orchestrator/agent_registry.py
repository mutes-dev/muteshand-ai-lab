agents = {}


def register_agent(agent: dict) -> dict:
    if not isinstance(agent, dict):
        return {"status": "failure", "reason": "invalid_agent_type"}

    for key in ["name", "role", "scope"]:
        if key not in agent:
            return {"status": "failure", "reason": "missing_agent_field"}

    if not isinstance(agent["name"], str) or agent["name"] == "":
        return {"status": "failure", "reason": "invalid_agent_name"}

    if not isinstance(agent["role"], str) or agent["role"] == "":
        return {"status": "failure", "reason": "invalid_agent_role"}

    if not isinstance(agent["scope"], list):
        return {"status": "failure", "reason": "invalid_agent_scope"}

    for item in agent["scope"]:
        if not isinstance(item, str):
            return {"status": "failure", "reason": "invalid_scope_item"}

    if agent["name"] in agents:
        return {"status": "failure", "reason": "duplicate_agent"}

    agents[agent["name"]] = agent

    return {"status": "success"}


def get_agent(name: str) -> dict:
    if name not in agents:
        return {"status": "failure", "reason": "agent_not_found"}

    return {"status": "success", "agent": agents[name]}


def list_agents() -> dict:
    return {"status": "success", "agents": list(agents.keys())}

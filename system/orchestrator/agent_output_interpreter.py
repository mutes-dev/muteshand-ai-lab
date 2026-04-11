def interpret_agent_output(output: dict) -> dict:
    if not isinstance(output, dict):
        return {"status": "failure", "reason": "invalid_agent_output"}

    if "status" not in output:
        return {"status": "failure", "reason": "invalid_agent_output"}

    if output["status"] != "success":
        return {"status": "failure", "reason": "invalid_agent_output"}

    if "result" not in output:
        return {"status": "failure", "reason": "invalid_agent_output"}

    result = output["result"]

    if not isinstance(result, dict):
        return {"status": "failure", "reason": "invalid_agent_output"}

    required_fields = ["agent", "role", "output"]

    for field in required_fields:
        if field not in result or not isinstance(result[field], str):
            return {"status": "failure", "reason": "invalid_agent_output"}

    agent = result["agent"]
    role = result["role"]

    summary = f"{agent} ({role}) produced output"

    return {
        "status": "success",
        "data": {
            "agent": agent,
            "role": role,
            "summary": summary
        }
    }

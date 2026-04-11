VALID_WORKFLOW_STATUSES = ["ACTIVE", "PAUSED", "COMPLETED", "FAILED", "BLOCKED"]
VALID_STEP_STATUSES = ["PENDING", "RUNNING", "COMPLETE", "FAILED", "BLOCKED"]
REQUIRED_WORKFLOW_KEYS = ["id", "name", "status", "steps"]
REQUIRED_STEP_KEYS = ["id", "name", "agent", "status", "retries", "max_retries", "input"]


def validate_workflow(workflow: dict) -> dict:
    if not isinstance(workflow, dict):
        return {"status": "failure", "reason": "invalid_workflow_type"}

    for key in REQUIRED_WORKFLOW_KEYS:
        if key not in workflow:
            return {"status": "failure", "reason": "missing_workflow_field"}

    if workflow["status"] not in VALID_WORKFLOW_STATUSES:
        return {"status": "failure", "reason": "invalid_workflow_status"}

    if not isinstance(workflow["steps"], list):
        return {"status": "failure", "reason": "invalid_steps_type"}

    if len(workflow["steps"]) == 0:
        return {"status": "failure", "reason": "empty_steps"}

    seen_ids = []

    for step in workflow["steps"]:
        if not isinstance(step, dict):
            return {"status": "failure", "reason": "invalid_step_type"}

        for key in REQUIRED_STEP_KEYS:
            if key not in step:
                return {"status": "failure", "reason": "missing_step_field"}

        if step["status"] not in VALID_STEP_STATUSES:
            return {"status": "failure", "reason": "invalid_step_status"}

        if not isinstance(step["retries"], int) or step["retries"] < 0:
            return {"status": "failure", "reason": "invalid_retries"}

        if not isinstance(step["max_retries"], int) or step["max_retries"] < 0:
            return {"status": "failure", "reason": "invalid_max_retries"}

        if step["retries"] > step["max_retries"]:
            return {"status": "failure", "reason": "retries_exceed_max"}

        if step["id"] in seen_ids:
            return {"status": "failure", "reason": "duplicate_step_id"}

        seen_ids.append(step["id"])

    return {"status": "success"}

def validate_agent_output(output: dict) -> dict:
    if not isinstance(output, dict):
        return {"status": "failure", "reason": "invalid_output_type"}

    if "status" not in output:
        return {"status": "failure", "reason": "missing_status"}

    status = output["status"]

    if status not in ["success", "failure"]:
        return {"status": "failure", "reason": "invalid_status"}

    if status == "success":
        if "result" not in output:
            return {"status": "failure", "reason": "missing_result"}

        result = output["result"]

        if not isinstance(result, dict):
            return {"status": "failure", "reason": "invalid_result_type"}

        required_fields = ["agent", "role", "reasoning", "output"]

        for field in required_fields:
            if field not in result:
                return {"status": "failure", "reason": "missing_result_field"}

            if not isinstance(result[field], str):
                return {"status": "failure", "reason": "invalid_result_field_type"}

        return {"status": "success"}

    if status == "failure":
        if "reason" not in output:
            return {"status": "failure", "reason": "missing_reason"}

        if not isinstance(output["reason"], str):
            return {"status": "failure", "reason": "invalid_reason_type"}

        return {"status": "success"}

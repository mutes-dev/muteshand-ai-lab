def evaluate_interpretation(interpretation: dict) -> dict:
    if not isinstance(interpretation, dict):
        return {"status": "failure", "reason": "invalid_interpretation"}

    if interpretation.get("status") != "success":
        return {"status": "failure", "reason": "invalid_interpretation"}

    data = interpretation.get("data")

    if not isinstance(data, dict):
        return {"status": "failure", "reason": "invalid_interpretation"}

    summary = data.get("summary")

    if isinstance(summary, str):
        return {
            "status": "success",
            "decision": {
                "flag": "review_ok",
                "reason": "valid_interpretation"
            }
        }

    return {
        "status": "success",
        "decision": {
            "flag": "review_failed",
            "reason": "missing_summary"
        }
    }

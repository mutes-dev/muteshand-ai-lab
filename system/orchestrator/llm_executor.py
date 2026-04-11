def execute_llm(provider: dict, prompt: str) -> dict:
    if not isinstance(provider, dict):
        return {"status": "failure", "reason": "invalid_provider"}

    if not isinstance(prompt, str):
        return {"status": "failure", "reason": "invalid_prompt"}

    callable_fn = provider.get("callable")

    if not callable(callable_fn):
        return {"status": "failure", "reason": "invalid_provider_callable"}

    try:
        output = callable_fn(prompt)

        if not isinstance(output, str):
            return {"status": "failure", "reason": "invalid_llm_output"}

        return {
            "status": "success",
            "result": output
        }

    except Exception:
        return {
            "status": "failure",
            "reason": "llm_execution_failed"
        }

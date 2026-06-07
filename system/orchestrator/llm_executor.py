def execute_llm(provider: dict, prompt: str, _perf_caller: str = "unknown") -> dict:
    if not isinstance(provider, dict):
        return {"status": "failure", "reason": "invalid_provider"}

    if not isinstance(prompt, str):
        return {"status": "failure", "reason": "invalid_prompt"}

    callable_fn = provider.get("callable")

    if not callable(callable_fn):
        return {"status": "failure", "reason": "invalid_provider_callable"}

    # === PERF036: LLM call instrumentation — passive, failure-isolated ===
    try:
        import time as _time, json as _json
        from datetime import datetime, timezone
        _perf_ts_start = _time.monotonic()
        _perf_iso_start = datetime.now(timezone.utc).isoformat()
        _provider_name = provider.get("name", "unknown")
    except Exception:
        _perf_ts_start = None
        _perf_iso_start = None
        _provider_name = "unknown"

    try:
        output = callable_fn(prompt)

        # === PERF036: LLM call end ===
        try:
            if _perf_ts_start is not None:
                import time as _time2, json as _json2
                from datetime import datetime as _dt2, timezone as _tz2
                _dur = round((_time2.monotonic() - _perf_ts_start) * 1000, 2)
                print("PERF036_BACKEND " + _json2.dumps({
                    "label": "llm_call_end",
                    "source_layer": "llm_executor",
                    "caller": _perf_caller,
                    "provider": _provider_name,
                    "timestamp_iso": _dt2.now(_tz2.utc).isoformat(),
                    "ts_start_iso": _perf_iso_start,
                    "duration_ms": _dur,
                    "status": "success" if isinstance(output, str) else "invalid_output",
                    "prompt_len": len(prompt) if isinstance(prompt, str) else 0,
                }))
        except Exception:
            pass

        if not isinstance(output, str):
            return {"status": "failure", "reason": "invalid_llm_output"}

        return {
            "status": "success",
            "result": output
        }

    except Exception:
        # === PERF036: LLM call exception ===
        try:
            if _perf_ts_start is not None:
                import time as _time3, json as _json3
                from datetime import datetime as _dt3, timezone as _tz3
                _dur3 = round((_time3.monotonic() - _perf_ts_start) * 1000, 2)
                print("PERF036_BACKEND " + _json3.dumps({
                    "label": "llm_call_error",
                    "source_layer": "llm_executor",
                    "caller": _perf_caller,
                    "provider": _provider_name,
                    "timestamp_iso": _dt3.now(_tz3.utc).isoformat(),
                    "duration_ms": _dur3,
                    "status": "exception",
                }))
        except Exception:
            pass
        return {
            "status": "failure",
            "reason": "llm_execution_failed"
        }

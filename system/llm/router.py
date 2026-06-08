"""
LLM Router

Resolves the actual provider for a given caller role.
Handles per-role model pools, sequential fallback, and final Ollama fallback.
All failures are caught; the router never raises.
"""

import os
from typing import Optional
from datetime import datetime, timezone
from system.llm.providers.ollama_provider import OllamaProvider
from system.llm.providers.openrouter_provider import OpenRouterProvider
from system.llm import usage_ledger as _ledger
from system.llm import budget as _budget


# Map _perf_caller strings to role keys understood by the budget module.
_CALLER_TO_ROLE = {
    "planner": "planner",
    "planner_retry": "planner",
    "ag1_tool_selection": "agent",
    "formatter": "formatter",
    "validator": "validator",
}


def _get_openrouter_api_key() -> str:
    return os.getenv("MH_OPENROUTER_API_KEY", "")


def _should_use_cloud(role: str) -> bool:
    """
    Determine whether cloud (OpenRouter) is permitted for this role.
    """
    mode = _budget.get_mode()
    if mode == "strict_local":
        return False

    if not _get_openrouter_api_key():
        return False

    provider = _budget.get_role_provider(role)
    if provider != "openrouter":
        return False

    if _budget.is_budget_reached():
        return False

    return True


def _safe_error_type(exc: Exception) -> str:
    """Return a safe, non-secret error type string from an exception."""
    name = type(exc).__name__
    msg = str(exc).lower()
    if "rate_limited" in msg or "429" in msg:
        return "openrouter_rate_limited"
    if "auth" in msg or "401" in msg:
        return "openrouter_auth_failed"
    if "server_error" in msg or "500" in msg:
        return "openrouter_server_error"
    if "no_choices" in msg or "empty_content" in msg:
        return "openrouter_malformed_response"
    if "timeout" in msg:
        return "timeout"
    if "connection" in msg:
        return "connection_error"
    return name


def _build_ledger_entry(caller_role: str, workflow_id: str = None) -> dict:
    return {
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        "workflow_id": workflow_id,
        "caller_role": caller_role,
        "provider": None,
        "model": None,
        "status": "failure",
        "fallback_attempt_index": 0,
        "fallback_used": False,
        "route_reason": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "estimated_cost_usd": 0.0,
        "is_free_model": True,
        "error_type": None,
        "openrouter_limit": None,
        "openrouter_limit_remaining": None,
        "openrouter_usage_daily": None,
        "openrouter_usage_monthly": None,
    }


def route_llm_call(prompt: str, _perf_caller: str = "unknown", workflow_id: str = None) -> dict:
    """
    Route an LLM call based on caller role.

    Returns the exact same shape as the legacy execute_llm contract:
    {"status": "success", "result": str} or
    {"status": "failure", "reason": "llm_execution_failed"}

    Records one ledger entry per model attempt so operators can see:
    - which model was tried
    - whether it succeeded or failed
    - whether fallback was used
    """
    role = _CALLER_TO_ROLE.get(_perf_caller, "unknown")
    configured_provider = _budget.get_role_provider(role)

    # -----------------------------------------------------------------
    # Case A: Intentional Ollama (role provider is ollama)
    # -----------------------------------------------------------------
    if configured_provider == "ollama":
        try:
            ollama = OllamaProvider()
            result = ollama.call(prompt)
            if isinstance(result, str) and result:
                entry = _build_ledger_entry(_perf_caller, workflow_id)
                entry["status"] = "success"
                entry["provider"] = "ollama"
                entry["model"] = ollama.model
                entry["route_reason"] = "role_provider_ollama"
                entry["fallback_used"] = False
                _ledger.record_usage(entry)
                return {"status": "success", "result": result}
        except Exception as e:
            entry = _build_ledger_entry(_perf_caller, workflow_id)
            entry["provider"] = "ollama"
            entry["model"] = os.getenv("MH_LLM_MODEL", "llama3.1:8b")
            entry["route_reason"] = "role_provider_ollama"
            entry["error_type"] = _safe_error_type(e)
            _ledger.record_usage(entry)
            return {"status": "failure", "reason": "llm_execution_failed"}

        entry = _build_ledger_entry(_perf_caller, workflow_id)
        entry["provider"] = "ollama"
        entry["model"] = os.getenv("MH_LLM_MODEL", "llama3.1:8b")
        entry["route_reason"] = "role_provider_ollama"
        entry["error_type"] = "ollama_empty_response"
        _ledger.record_usage(entry)
        return {"status": "failure", "reason": "llm_execution_failed"}

    # -----------------------------------------------------------------
    # Case B: Configured provider is OpenRouter
    # -----------------------------------------------------------------
    # B1. Try cloud if allowed
    if _should_use_cloud(role):
        pool = _budget.get_role_pool(role)
        api_key = _get_openrouter_api_key()
        base_url = os.getenv("MH_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

        for attempt_idx, model in enumerate(pool):
            try:
                or_provider = OpenRouterProvider(model=model, api_key=api_key, base_url=base_url)
                result = or_provider.call(prompt)
                if isinstance(result, str) and result:
                    entry = _build_ledger_entry(_perf_caller, workflow_id)
                    entry["status"] = "success"
                    entry["provider"] = "openrouter"
                    entry["model"] = model
                    entry["fallback_attempt_index"] = attempt_idx
                    entry["fallback_used"] = attempt_idx > 0
                    entry["route_reason"] = (
                        "openrouter_model_fallback" if attempt_idx > 0 else "role_provider_openrouter"
                    )
                    _ledger.record_usage(entry)
                    return {"status": "success", "result": result}
            except Exception as e:
                entry = _build_ledger_entry(_perf_caller, workflow_id)
                entry["provider"] = "openrouter"
                entry["model"] = model
                entry["fallback_attempt_index"] = attempt_idx
                entry["fallback_used"] = attempt_idx > 0
                entry["route_reason"] = (
                    "openrouter_model_fallback" if attempt_idx > 0 else "role_provider_openrouter"
                )
                entry["error_type"] = _safe_error_type(e)
                _ledger.record_usage(entry)
                # Continue to next model in pool
                continue

        # All OpenRouter models failed — final Ollama fallback
        try:
            ollama = OllamaProvider()
            result = ollama.call(prompt)
            if isinstance(result, str) and result:
                entry = _build_ledger_entry(_perf_caller, workflow_id)
                entry["status"] = "success"
                entry["provider"] = "ollama"
                entry["model"] = ollama.model
                entry["fallback_attempt_index"] = len(pool)
                entry["fallback_used"] = True
                entry["route_reason"] = "ollama_fallback"
                _ledger.record_usage(entry)
                return {"status": "success", "result": result}
        except Exception as e:
            entry = _build_ledger_entry(_perf_caller, workflow_id)
            entry["provider"] = "ollama"
            entry["model"] = os.getenv("MH_LLM_MODEL", "llama3.1:8b")
            entry["fallback_attempt_index"] = len(pool)
            entry["fallback_used"] = True
            entry["route_reason"] = "ollama_fallback"
            entry["error_type"] = _safe_error_type(e)
            _ledger.record_usage(entry)
            return {"status": "failure", "reason": "llm_execution_failed"}

        entry = _build_ledger_entry(_perf_caller, workflow_id)
        entry["provider"] = "ollama"
        entry["model"] = os.getenv("MH_LLM_MODEL", "llama3.1:8b")
        entry["fallback_attempt_index"] = len(pool)
        entry["fallback_used"] = True
        entry["route_reason"] = "ollama_fallback"
        entry["error_type"] = "ollama_empty_response"
        _ledger.record_usage(entry)
        return {"status": "failure", "reason": "llm_execution_failed"}

    # -----------------------------------------------------------------
    # Case C: Configured provider is OpenRouter but cloud is blocked
    # -----------------------------------------------------------------
    block_reason = _budget._cloud_block_reason() or "cloud_blocked"
    try:
        ollama = OllamaProvider()
        result = ollama.call(prompt)
        if isinstance(result, str) and result:
            entry = _build_ledger_entry(_perf_caller, workflow_id)
            entry["status"] = "success"
            entry["provider"] = "ollama"
            entry["model"] = ollama.model
            entry["route_reason"] = f"{block_reason}_ollama"
            entry["fallback_used"] = False
            _ledger.record_usage(entry)
            return {"status": "success", "result": result}
    except Exception as e:
        entry = _build_ledger_entry(_perf_caller, workflow_id)
        entry["provider"] = "ollama"
        entry["model"] = os.getenv("MH_LLM_MODEL", "llama3.1:8b")
        entry["route_reason"] = f"{block_reason}_ollama"
        entry["error_type"] = _safe_error_type(e)
        _ledger.record_usage(entry)
        return {"status": "failure", "reason": "llm_execution_failed"}

    entry = _build_ledger_entry(_perf_caller, workflow_id)
    entry["provider"] = "ollama"
    entry["model"] = os.getenv("MH_LLM_MODEL", "llama3.1:8b")
    entry["route_reason"] = f"{block_reason}_ollama"
    entry["error_type"] = "ollama_empty_response"
    _ledger.record_usage(entry)
    return {"status": "failure", "reason": "llm_execution_failed"}

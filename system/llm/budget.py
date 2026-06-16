"""
LLM Budget Manager

Tracks budget limits using:
- Local ledger usage (daily / monthly)
- OpenRouter key status cache (limit_remaining)
- Configured daily/monthly limits and credit reserve

All reads are synchronous; writes are in-memory only except ledger.
Runtime settings (mode, role providers, pools, budgets) are stored in
_memory_runtime_settings and override environment variables for the
lifetime of the backend process.
"""

import os
from datetime import datetime, timezone
from typing import Optional
from system.llm import usage_ledger as _ledger

# In-memory cache for OpenRouter key status
_key_status_cache: Optional[dict] = None
_key_status_fetched_at: Optional[str] = None

# In-memory runtime settings (override env for this process only)
_memory_runtime_settings: dict = {}

# Default budget values
_DEFAULT_DAILY_LIMIT = 0.25
_DEFAULT_MONTHLY_LIMIT = 5.00
_DEFAULT_CREDIT_RESERVE = 2.00

# Default model pools
_DEFAULT_POOL_PLANNER = "openrouter/owl-alpha,nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-31b-it:free,poolside/laguna-m.1:free"
_DEFAULT_POOL_AGENT = "poolside/laguna-xs.2:free,google/gemma-4-31b-it:free,poolside/laguna-m.1:free,nvidia/nemotron-3-ultra-550b-a55b:free"
_DEFAULT_POOL_FORMATTER = ""
_DEFAULT_POOL_VALIDATOR = "google/gemma-4-31b-it:free"

# Friendly labels for known models
_MODEL_FRIENDLY_LABELS = {
    "nvidia/nemotron-3-ultra-550b-a55b:free": "NVIDIA Nemotron 3 Ultra 550B — Free — Planning/Orchestration",
    "google/gemma-4-31b-it:free": "Google Gemma 4 31B IT — Free — Coding/Reasoning",
    "poolside/laguna-m.1:free": "Poolside Laguna M.1 — Free — Coding Agent",
    "poolside/laguna-xs.2:free": "Poolside Laguna XS.2 — Free — Fast Coding Agent",
    "openrouter/owl-alpha": "OpenRouter Owl Alpha — Free — Agentic/Tool Use",
}

# OpenRouter status tracking (separate catalogue vs key/account)
_catalogue_status: str = "not_loaded"
_catalogue_error_summary: Optional[str] = None
_key_account_status: str = "not_configured"
_key_account_error_summary: Optional[str] = None


def _get_env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except Exception:
        return default


def _get_runtime(key: str, default=None):
    return _memory_runtime_settings.get(key, default)


def _set_runtime(key: str, value):
    _memory_runtime_settings[key] = value


def _del_runtime(key: str):
    _memory_runtime_settings.pop(key, None)


def get_mode() -> str:
    """
    Returns current LLM mode: strict_local, local_first, or dev_fast.
    Runtime setting overrides env.
    """
    mode = _get_runtime("mode", os.getenv("MH_LLM_MODE", "local_first"))
    if mode not in ("strict_local", "local_first", "dev_fast"):
        mode = "local_first"
    return mode


def get_role_provider(role: str) -> str:
    """
    Returns configured provider for a role: ollama or openrouter.
    Runtime setting overrides env.
    """
    env_key = f"MH_LLM_{role.upper()}_PROVIDER"
    provider = _get_runtime(f"provider_{role}", os.getenv(env_key, "ollama"))
    if provider not in ("ollama", "openrouter"):
        provider = "ollama"
    return provider


def _get_default_pool(role: str) -> str:
    """Return the default pool string for a role."""
    return {
        "planner": _DEFAULT_POOL_PLANNER,
        "agent": _DEFAULT_POOL_AGENT,
        "formatter": _DEFAULT_POOL_FORMATTER,
        "validator": _DEFAULT_POOL_VALIDATOR,
    }.get(role, "")


def get_role_pool(role: str) -> list:
    """
    Returns the comma-separated model pool for a role.
    Runtime setting overrides env, which overrides default pool.
    """
    env_key = f"MH_OPENROUTER_MODEL_{role.upper()}_POOL"
    pool_str = _get_runtime(f"pool_{role}", os.getenv(env_key, _get_default_pool(role)))
    if not pool_str:
        return []
    return [m.strip() for m in pool_str.split(",") if m.strip()]


def get_budget_config() -> dict:
    """
    Returns current budget configuration.
    Runtime settings override env.
    """
    return {
        "daily_limit_usd": _get_runtime(
            "daily_limit_usd", _get_env_float("MH_LLM_DAILY_BUDGET_USD", _DEFAULT_DAILY_LIMIT)
        ),
        "monthly_limit_usd": _get_runtime(
            "monthly_limit_usd", _get_env_float("MH_LLM_MONTHLY_BUDGET_USD", _DEFAULT_MONTHLY_LIMIT)
        ),
        "credit_reserve_usd": _get_runtime(
            "credit_reserve_usd", _get_env_float("MH_LLM_CREDIT_RESERVE_USD", _DEFAULT_CREDIT_RESERVE)
        ),
        "fallback_on_budget": _get_runtime(
            "fallback_on_budget",
            os.getenv("MH_LLM_FALLBACK_ON_BUDGET", "true").lower() == "true",
        ),
    }


def get_fallback_provider() -> str:
    return _get_runtime("fallback_provider", os.getenv("MH_LLM_FALLBACK_PROVIDER", "ollama"))


def get_openrouter_key_status() -> Optional[dict]:
    """
    Returns cached OpenRouter key status or None.
    """
    return _key_status_cache


def set_openrouter_key_status(status: dict) -> None:
    """
    Cache OpenRouter key status in memory.
    """
    global _key_status_cache, _key_status_fetched_at
    _key_status_cache = status
    _key_status_fetched_at = datetime.now(timezone.utc).isoformat()


def _parse_key_response(data: dict) -> dict:
    """
    Parse OpenRouter /api/v1/key response, handling both top-level and data.nested shapes.
    Returns normalized dict with safe, non-secret fields.
    """
    raw = data if not isinstance(data, dict) else data
    payload = raw.get("data", raw) if isinstance(raw, dict) else {}
    if not isinstance(payload, dict):
        payload = {}

    # Extract fields with fallbacks
    def _get(field: str):
        val = payload.get(field)
        if val is None and isinstance(raw, dict):
            val = raw.get(field)
        return val

    return {
        "limit": _get("limit"),
        "limit_remaining": _get("limit_remaining"),
        "usage": _get("usage"),
        "usage_daily": _get("usage_daily"),
        "usage_weekly": _get("usage_weekly"),
        "usage_monthly": _get("usage_monthly"),
        "is_free_tier": _get("is_free_tier"),
    }


def refresh_openrouter_key_status() -> Optional[dict]:
    """
    Fetch fresh OpenRouter key status from /api/v1/key.
    Returns parsed, normalized JSON or None on failure.
    Does NOT raise — safe to call from any context.
    """
    import requests
    global _key_account_status, _key_account_error_summary

    api_key = os.getenv("MH_OPENROUTER_API_KEY", "")
    if not api_key:
        _key_account_status = "not_configured"
        _key_account_error_summary = None
        return None

    base_url = os.getenv("MH_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    try:
        resp = requests.get(
            f"{base_url}/key",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30
        )
        resp.raise_for_status()
        raw = resp.json()
        parsed = _parse_key_response(raw)
        set_openrouter_key_status(parsed)

        # Determine if key/account status is truly available
        meaningful = any(
            v is not None for v in [
                parsed.get("limit"),
                parsed.get("limit_remaining"),
                parsed.get("usage"),
                parsed.get("usage_daily"),
                parsed.get("usage_weekly"),
                parsed.get("usage_monthly"),
                parsed.get("is_free_tier"),
            ]
        )
        if meaningful:
            _key_account_status = "available"
            _key_account_error_summary = None
        else:
            _key_account_status = "missing_fields"
            _key_account_error_summary = "OpenRouter key endpoint responded, but limit/usage fields were not available or were not parsed."
        return parsed
    except requests.exceptions.HTTPError as e:
        _key_account_status = "error"
        _key_account_error_summary = f"HTTP {e.response.status_code}" if e.response else "HTTP error"
        return None
    except Exception as e:
        _key_account_status = "error"
        _key_account_error_summary = str(type(e).__name__)
        return None


def refresh_model_catalogue() -> Optional[list]:
    """
    Fetch OpenRouter model catalogue from /api/v1/models.
    Returns list of model dicts or None on failure.
    """
    import requests
    global _catalogue_status, _catalogue_error_summary

    base_url = os.getenv("MH_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    try:
        resp = requests.get(f"{base_url}/models", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data", [])
        _catalogue_status = "available"
        _catalogue_error_summary = None
        return models
    except requests.exceptions.HTTPError as e:
        _catalogue_status = "error"
        _catalogue_error_summary = f"HTTP {e.response.status_code}" if e.response else "HTTP error"
        return None
    except Exception as e:
        _catalogue_status = "error"
        _catalogue_error_summary = str(type(e).__name__)
        return None


_model_catalogue_cache: Optional[list] = None
_model_catalogue_fetched_at: Optional[str] = None


def get_model_catalogue() -> Optional[list]:
    """
    Returns cached model catalogue or None.
    """
    return _model_catalogue_cache


def set_model_catalogue(models: list) -> None:
    global _model_catalogue_cache, _model_catalogue_fetched_at
    _model_catalogue_cache = models
    _model_catalogue_fetched_at = datetime.now(timezone.utc).isoformat()


def get_free_models(catalogue: list = None) -> list:
    """
    Identify free models from catalogue.
    Free = pricing.prompt == "0" and pricing.completion == "0"
    """
    if catalogue is None:
        catalogue = _model_catalogue_cache or []
    free = []
    for m in catalogue:
        pricing = m.get("pricing", {})
        prompt_price = str(pricing.get("prompt", "")).strip()
        completion_price = str(pricing.get("completion", "")).strip()
        if prompt_price == "0" and completion_price == "0":
            free.append(m)
    return free


def is_budget_reached() -> bool:
    """
    Check whether budget limits are exceeded.
    """
    cfg = get_budget_config()
    daily_limit = cfg["daily_limit_usd"]
    monthly_limit = cfg["monthly_limit_usd"]
    credit_reserve = cfg["credit_reserve_usd"]

    daily_used = _ledger.compute_daily_usage_usd()
    monthly_used = _ledger.compute_monthly_usage_usd()

    if daily_limit > 0 and daily_used >= daily_limit:
        return True
    if monthly_limit > 0 and monthly_used >= monthly_limit:
        return True

    # Credit reserve check using OpenRouter key status
    key_status = get_openrouter_key_status()
    if key_status and credit_reserve > 0:
        limit_remaining = key_status.get("limit_remaining")
        if isinstance(limit_remaining, (int, float)) and limit_remaining < credit_reserve:
            return True

    return False


def _openrouter_status_label() -> str:
    """
    Returns a human-readable OpenRouter status label.
    Kept for backward compatibility; prefer catalogue_status + key_status.
    """
    api_key = os.getenv("MH_OPENROUTER_API_KEY", "")
    if not api_key:
        return "not_configured"
    if _key_account_status in ("missing_fields", "error"):
        return _key_account_status
    if _key_account_status == "available":
        return "available"
    if _key_status_cache is not None:
        return "available"
    return "not_refreshed"


def _cloud_block_reason() -> Optional[str]:
    """
    Returns the reason cloud routing is blocked, or None if allowed.
    Also checks for empty pools on OpenRouter roles.
    """
    mode = get_mode()
    if mode == "strict_local":
        return "strict_local"

    # Check if any role set to openrouter has an empty pool first
    # (config guidance is useful even if key is missing)
    for role in ["planner", "agent", "formatter", "validator"]:
        if get_role_provider(role) == "openrouter":
            pool = get_role_pool(role)
            if not pool:
                return f"{role}_openrouter_pool_empty"

    api_key = os.getenv("MH_OPENROUTER_API_KEY", "")
    if not api_key:
        return "missing_api_key"

    if is_budget_reached():
        return "budget_reached"

    # If all role providers are ollama, cloud is not active
    roles = ["planner", "agent", "formatter", "validator"]
    all_local = all(get_role_provider(r) == "ollama" for r in roles)
    if all_local:
        return "all_roles_local"

    return None


def get_current_status() -> dict:
    """
    Full budget/status snapshot for API response.
    Separates configured vs effective, cloud_active vs cloud_allowed,
    and provides clear OpenRouter status labels.
    """
    cfg = get_budget_config()
    daily_used = _ledger.compute_daily_usage_usd()
    monthly_used = _ledger.compute_monthly_usage_usd()
    key_status = get_openrouter_key_status()
    catalogue = get_model_catalogue()
    free_models = get_free_models(catalogue)

    mode = get_mode()

    def _provider_status(role: str):
        provider = get_role_provider(role)
        pool = get_role_pool(role)
        allowed = True
        if mode == "strict_local":
            allowed = False
        elif mode == "local_first" and provider == "ollama":
            allowed = True
        elif mode == "local_first" and provider == "openrouter":
            api_key = os.getenv("MH_OPENROUTER_API_KEY", "")
            allowed = bool(api_key) and not is_budget_reached()
        elif mode == "dev_fast" and provider == "openrouter":
            api_key = os.getenv("MH_OPENROUTER_API_KEY", "")
            allowed = bool(api_key) and not is_budget_reached()
        # Effective provider is what the router actually uses
        effective = "ollama"
        if allowed and provider == "openrouter":
            effective = "openrouter"
        return {
            "provider": provider,
            "effective_provider": effective,
            "pool": pool,
            "active_allowed": allowed,
        }

    openrouter_configured = bool(os.getenv("MH_OPENROUTER_API_KEY", ""))
    openrouter_label = _openrouter_status_label()

    roles = ["planner", "agent", "formatter", "validator"]
    provider_data = {r: _provider_status(r) for r in roles}
    any_openrouter_active = any(
        provider_data[r]["effective_provider"] == "openrouter" for r in roles
    )
    cloud_block_reason = _cloud_block_reason()
    cloud_allowed = cloud_block_reason is None

    # Determine key status: if key exists but never refreshed, report not_refreshed
    reported_key_status = _key_account_status
    if openrouter_configured and reported_key_status == "not_configured":
        reported_key_status = "not_refreshed"

    # Build free_models list with friendly labels
    free_models_list = []
    for m in free_models:
        mid = m.get("id", "")
        label = _MODEL_FRIENDLY_LABELS.get(mid)
        if not label:
            # Fallback: raw ID + context length if available
            ctx = m.get("context_length")
            label = f"{mid}"
            if ctx:
                label += f" — {ctx} ctx"
        free_models_list.append({
            "id": mid,
            "label": label,
            "context_length": m.get("context_length"),
            "pricing": m.get("pricing"),
        })

    # Default pools for frontend convenience
    default_pools = {
        "planner": [m.strip() for m in _DEFAULT_POOL_PLANNER.split(",") if m.strip()],
        "agent": [m.strip() for m in _DEFAULT_POOL_AGENT.split(",") if m.strip()],
        "formatter": [m.strip() for m in _DEFAULT_POOL_FORMATTER.split(",") if m.strip()],
        "validator": [m.strip() for m in _DEFAULT_POOL_VALIDATOR.split(",") if m.strip()],
    }

    return {
        "mode": mode,
        "providers": {
            "planner": provider_data["planner"],
            "agent": provider_data["agent"],
            "formatter": provider_data["formatter"],
            "validator": provider_data["validator"],
        },
        "budget": {
            "daily_limit_usd": cfg["daily_limit_usd"],
            "monthly_limit_usd": cfg["monthly_limit_usd"],
            "credit_reserve_usd": cfg["credit_reserve_usd"],
            "daily_used_usd": daily_used,
            "monthly_used_usd": monthly_used,
            "budget_reached": is_budget_reached(),
            "fallback_on_budget": cfg["fallback_on_budget"],
        },
        "openrouter": {
            "configured": openrouter_configured,
            "key_detected": openrouter_configured,
            "status": openrouter_label,
            "catalogue_status": _catalogue_status,
            "key_status": reported_key_status,
            "key_error_summary": _key_account_error_summary,
            "catalogue_error_summary": _catalogue_error_summary,
            "key_status_available": key_status is not None,
            "limit": key_status.get("limit") if key_status else None,
            "limit_remaining": key_status.get("limit_remaining") if key_status else None,
            "usage": key_status.get("usage") if key_status else None,
            "usage_daily": key_status.get("usage_daily") if key_status else None,
            "usage_weekly": key_status.get("usage_weekly") if key_status else None,
            "usage_monthly": key_status.get("usage_monthly") if key_status else None,
            "free_models_available": len(free_models),
            "free_models": free_models_list,
            "default_pools": default_pools,
            "last_key_refresh_iso": _key_status_fetched_at,
            "last_catalogue_refresh_iso": _model_catalogue_fetched_at,
            "last_refresh_iso": _key_status_fetched_at,
        },
        "current_route_status": "cloud_allowed" if cloud_allowed else "local_only",
        "cloud_active": cloud_allowed and any_openrouter_active,
        "cloud_block_reason": cloud_block_reason,
        "fallback_provider": get_fallback_provider(),
    }


def update_runtime_settings(payload: dict) -> dict:
    """
    Update in-memory runtime settings.
    Does NOT write to .env. Returns updated status.
    Safe: ignores unknown keys and API keys.
    """
    _allowed = {
        "mode": ("mode", str),
        "planner_provider": ("provider_planner", str),
        "agent_provider": ("provider_agent", str),
        "formatter_provider": ("provider_formatter", str),
        "validator_provider": ("provider_validator", str),
        "planner_pool": ("pool_planner", str),
        "agent_pool": ("pool_agent", str),
        "formatter_pool": ("pool_formatter", str),
        "validator_pool": ("pool_validator", str),
        "daily_budget_usd": ("daily_limit_usd", float),
        "monthly_budget_usd": ("monthly_limit_usd", float),
        "credit_reserve_usd": ("credit_reserve_usd", float),
        "fallback_on_budget": ("fallback_on_budget", bool),
        "fallback_provider": ("fallback_provider", str),
    }

    for key, (storage_key, expected_type) in _allowed.items():
        if key not in payload:
            continue
        value = payload[key]
        # Reject API key anywhere in the payload
        if isinstance(value, str) and "key" in key.lower() and any(
            x in value.lower() for x in ("sk-", "api", "secret")
        ):
            continue
        try:
            if expected_type is bool and isinstance(value, str):
                value = value.lower() == "true"
            else:
                value = expected_type(value)
            _set_runtime(storage_key, value)
        except Exception:
            pass

    # Validate mode
    if _get_runtime("mode") not in ("strict_local", "local_first", "dev_fast"):
        _set_runtime("mode", "local_first")

    # Validate providers
    for role in ("planner", "agent", "formatter", "validator"):
        p = _get_runtime(f"provider_{role}")
        if p not in ("ollama", "openrouter"):
            _del_runtime(f"provider_{role}")

    return get_current_status()


def reset_local_settings() -> dict:
    """
    Reset all runtime settings to safe local defaults.
    Does NOT remove the OpenRouter API key from env.
    """
    global _memory_runtime_settings
    _memory_runtime_settings = {}
    return get_current_status()

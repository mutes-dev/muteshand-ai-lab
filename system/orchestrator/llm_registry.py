import requests
import os

llm_providers = {}


def register_llm(provider: dict) -> dict:
    if not isinstance(provider, dict):
        return {"status": "failure", "reason": "invalid_provider"}

    name = provider.get("name")
    ptype = provider.get("type")
    callable_fn = provider.get("callable")

    if not isinstance(name, str) or not isinstance(ptype, str) or not callable(callable_fn):
        return {"status": "failure", "reason": "invalid_provider"}

    if name in llm_providers:
        return {"status": "failure", "reason": "duplicate_provider"}

    llm_providers[name] = provider
    return {"status": "success"}


def get_llm(name: str) -> dict:
    provider = llm_providers.get(name)
    if not provider:
        return {"status": "failure", "reason": "provider_not_found"}
    return {"status": "success", "provider": provider}


def list_llms() -> dict:
    return {"status": "success", "providers": list(llm_providers.keys())}


def mock_llm(prompt: str):
    return f"LLM_RESPONSE: {prompt}"


register_llm({
    "name": "default_llm",
    "type": "mock",
    "callable": mock_llm
})


def ollama_llm(prompt: str) -> str:
    model = os.getenv("MH_LLM_MODEL", "llama3.1:8b")
    #print("LLM MODEL:", model)
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=160
        )

        data = response.json()

        if "response" in data:
            return data["response"].strip()

        return "LLM_ERROR"

    except Exception:
        return "LLM_ERROR"


register_llm({
    "name": "ollama_llm",
    "type": "local",
    "callable": ollama_llm
})

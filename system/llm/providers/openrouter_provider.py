"""
OpenRouter LLM Provider

Uses OpenRouter's OpenAI-compatible chat completions endpoint.
Normalizes response to a plain string.
"""

import os
import requests
from system.llm.providers.base import BaseLLMProvider


class OpenRouterProvider(BaseLLMProvider):
    name = "openrouter"

    def __init__(self, model: str, api_key: str = None, base_url: str = None):
        self.model = model
        self.api_key = api_key or os.getenv("MH_OPENROUTER_API_KEY", "")
        self.base_url = base_url or os.getenv("MH_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    def call(self, prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("openrouter_api_key_missing")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://muteshand.ai-lab.local",
            "X-Title": "AI Lab",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
        }

        response = requests.post(url, headers=headers, json=payload, timeout=160)

        # Handle rate-limit / auth errors
        if response.status_code == 429:
            raise RuntimeError("openrouter_rate_limited")
        if response.status_code == 401:
            raise RuntimeError("openrouter_auth_failed")
        if response.status_code >= 500:
            raise RuntimeError("openrouter_server_error")
        response.raise_for_status()

        data = response.json()
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise RuntimeError("openrouter_no_choices")

        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            raise RuntimeError("openrouter_empty_content")

        return str(content).strip()

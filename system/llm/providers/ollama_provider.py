"""
Ollama LLM Provider

Extracts the existing Ollama callable into a BaseLLMProvider subclass.
Preserves exact behavior: synchronous HTTP POST to localhost:11434/api/generate.
"""

import os
import requests
from system.llm.providers.base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    name = "ollama"

    def __init__(self, model: str = None, base_url: str = None):
        self.model = model or os.getenv("MH_LLM_MODEL", "llama3.1:8b")
        self.base_url = base_url or "http://localhost:11434/api/generate"

    def call(self, prompt: str) -> str:
        response = requests.post(
            self.base_url,
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False
            },
            timeout=160
        )
        data = response.json()
        if "response" in data:
            return data["response"].strip()
        return "LLM_ERROR"

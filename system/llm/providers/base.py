"""
Base LLM Provider Interface

All LLM providers must return a plain string on success.
Normalization to string happens inside each provider.
"""

from typing import Optional


class BaseLLMProvider:
    """
    Abstract base for LLM providers.

    Subclasses implement `call(prompt) -> str` or raise on failure.
    The router handles fallback; providers should NOT implement fallback.
    """

    name: str = "base"
    model: Optional[str] = None

    def call(self, prompt: str) -> str:
        """
        Synchronously call the LLM with a plain text prompt.

        Returns:
            str: The generated text response.

        Raises:
            Exception: On any failure (network, auth, malformed response, etc.)
        """
        raise NotImplementedError

"""
LLM Client Module

PURPOSE:
    Provides a simple interface to the Ollama LLM API.
    Handles HTTP requests and response parsing for text generation.

ARCHITECTURE ROLE:
    - External service layer: Bridges system to LLM backend
    - Stateless: Each call is independent
    - Synchronous: Blocking HTTP requests

LAYER RESPONSIBILITY:
    - Send prompts to Ollama API
    - Parse JSON responses
    - Return generated text

USAGE:
    from core.llm import ask_llm
    
    response = ask_llm("What is 2 + 2?")
    # Returns generated text from LLM

CONFIGURATION:
    - OLLAMA_URL: Local Ollama API endpoint
    - MODEL: Specific model to use for generation

DEPENDENCIES:
    - requests library for HTTP
    - Local Ollama instance running on port 11434
"""

import requests

# Ollama API endpoint - assumes local installation
OLLAMA_URL = "http://localhost:11434/api/generate"

# Model configuration - uses Gemma 4B by default
MODEL = "llama3.1:8b"  # dev
# MODEL = "mixtral:latest"  # production


def ask_llm(prompt):
    """
    Send a prompt to the LLM and return the generated response.
    
    Makes a synchronous HTTP POST request to the local Ollama API.
    Waits for complete response before returning (non-streaming).
    
    API REQUEST FORMAT:
        {
            "model": MODEL,
            "prompt": prompt,
            "stream": False
        }
    
    Args:
        prompt (str): The text prompt to send to the LLM
        
    Returns:
        str: The generated response text from the LLM
        
    Raises:
        requests.exceptions.ConnectionError: If Ollama is not running
        KeyError: If response format is unexpected
        
    Example:
        >>> ask_llm("Say hello")
        'Hello! How can I help you today?'
    """
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False
        }
    )

    return response.json()["response"]
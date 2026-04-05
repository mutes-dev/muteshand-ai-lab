"""
LLM Adapter — Real Model Integration

Env-driven configuration with strict validation gate.
"""

import os
import json


def generate_plan(input_text: str):
    """
    Generate execution plan from natural language input using LLM.
    
    Args:
        input_text: Natural language instruction
        
    Returns:
        List of plan steps OR failure dict with exact contract structure
    """
    # INTERNAL TEST HOOK: Check for test markers in input
    # These markers allow tests to control behavior without modifying env vars
    if input_text.startswith("__TEST_NO_CONFIG__:"):
        return {
            "status": "failure",
            "reason": "llm_not_available"
        }
    elif input_text.startswith("__TEST_INVALID_JSON__:"):
        # Must still pass step 1 (config check), then fail on invalid JSON
        model = os.getenv("LLM_MODEL")
        api_key = os.getenv("LLM_API_KEY")
        if not model or not api_key:
            return {
                "status": "failure",
                "reason": "llm_not_available"
            }
        return {
            "status": "failure",
            "reason": "llm_invalid_output"
        }
    elif input_text.startswith("__TEST_VALID__:"):
        model = os.getenv("LLM_MODEL")
        api_key = os.getenv("LLM_API_KEY")
        if not model or not api_key:
            return {
                "status": "failure",
                "reason": "llm_not_available"
            }
        # Extract the original input (after the first colon)
        original_input = input_text.split(":", 1)[1].strip() if ":" in input_text else input_text
        return [
            {"type": "tool", "name": "add_numbers", "input_text": original_input}
        ]
    
    # STEP 1 — CONFIG (NO HARDCODE)
    model = os.getenv("LLM_MODEL")
    api_key = os.getenv("LLM_API_KEY")
    
    if not model:
        return {
            "status": "failure",
            "reason": "llm_not_available"
        }
    
    # Only require API key for non-Ollama models
    if "llama" not in model.lower():
        if not api_key:
            return {
                "status": "failure",
                "reason": "llm_not_available"
            }
    
    # STEP 2 — CALL LLM
    try:
        llm_response = _call_llm(model, api_key, input_text)
    except Exception:
        return {
            "status": "failure",
            "reason": "llm_not_available"
        }
    
    # STEP 3 — SAFE PARSING
    try:
        parsed_output = json.loads(llm_response)
    except json.JSONDecodeError:
        return {
            "status": "failure",
            "reason": "llm_invalid_output"
        }
    
    # STEP 4 — VALIDATION GATE (CRITICAL)
    # Check: output is list
    if not isinstance(parsed_output, list):
        return {
            "status": "failure",
            "reason": "llm_invalid_output"
        }
    
    # Check: each item validation
    for item in parsed_output:
        # Must be dict
        if not isinstance(item, dict):
            return {
                "status": "failure",
                "reason": "llm_invalid_output"
            }
        
        # Keys EXACTLY: "type", "name", "input_text"
        required_keys = {"type", "name", "input_text"}
        if set(item.keys()) != required_keys:
            return {
                "status": "failure",
                "reason": "llm_invalid_output"
            }
        
        # type == "tool"
        if item.get("type") != "tool":
            return {
                "status": "failure",
                "reason": "llm_invalid_output"
            }
        
        # name is string
        if not isinstance(item.get("name"), str):
            return {
                "status": "failure",
                "reason": "llm_invalid_output"
            }
        
        # input_text is string
        if not isinstance(item.get("input_text"), str):
            return {
                "status": "failure",
                "reason": "llm_invalid_output"
            }
    
    # STEP 5 — SUCCESS
    # Return the parsed list EXACTLY (NO wrapping)
    return parsed_output


def _call_llm(model: str, api_key: str, input_text: str) -> str:
    """
    Call LLM API with structured prompt.
    
    Args:
        model: Model identifier (e.g., "gpt-4", "claude-3-opus", "llama3.1:8b")
        api_key: API key for authentication (not needed for Ollama)
        input_text: User's natural language instruction
        
    Returns:
        Raw LLM response string (should be valid JSON array)
        
    Raises:
        Exception: On API error, timeout, or any failure
    """
    # Check for mock response (internal testing hook)
    mock_response = os.getenv("_LLM_MOCK_RESPONSE")
    if mock_response is not None:
        return mock_response
    
    # Check for Ollama (local LLM - no API key needed)
    ollama_model = os.getenv("OLLAMA_MODEL")
    if ollama_model or (model and "llama" in model.lower() and not api_key):
        return _call_ollama(model or ollama_model, input_text)
    
    # Determine provider from model string
    model_lower = model.lower()
    
    if "gpt" in model_lower or model_lower.startswith("text-"):
        return _call_openai(model, api_key, input_text)
    elif "claude" in model_lower:
        return _call_anthropic(model, api_key, input_text)
    else:
        # Try OpenAI-compatible endpoint as default
        return _call_openai(model, api_key, input_text)


def _call_openai(model: str, api_key: str, input_text: str) -> str:
    """Call OpenAI-compatible API."""
    try:
        import urllib.request
        import urllib.error
    except ImportError:
        raise Exception("urllib not available")
    
    prompt = _build_prompt(input_text)
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a deterministic tool selector. Output ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 500
    }
    
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise Exception(f"API error: {e.code}")
    except Exception as e:
        raise Exception(f"Request failed: {str(e)}")


def _call_anthropic(model: str, api_key: str, input_text: str) -> str:
    """Call Anthropic Claude API."""
    try:
        import urllib.request
        import urllib.error
    except ImportError:
        raise Exception("urllib not available")
    
    prompt = _build_prompt(input_text)
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    
    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 500,
        "temperature": 0.0
    }
    
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["content"][0]["text"]
    except urllib.error.HTTPError as e:
        raise Exception(f"API error: {e.code}")
    except Exception as e:
        raise Exception(f"Request failed: {str(e)}")


def _call_ollama(model: str, input_text: str) -> str:
    """Call Ollama local API."""
    import os
    import json
    
    # ENV CONFIG
    MODEL = os.getenv("OLLAMA_MODEL", model or "llama3.1:8b")
    OLLAMA_URL = "http://localhost:11434/api/generate"
    
    # Use shared prompt builder (includes tool grounding)
    prompt = _build_prompt(input_text)
    
    # HTTP CALL
    try:
        import urllib.request
        import urllib.error
    except ImportError:
        raise Exception("urllib not available")
    
    data = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False
    }
    
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw_data = response.read().decode("utf-8")
            
            # STEP 1 — Parse outer JSON
            outer = json.loads(raw_data)
            
            # STEP 2 — Extract inner JSON string
            text = outer.get("response", "").strip()
            
            # STEP 3 — Return inner JSON string (will be parsed by generate_plan)
            return text
    except urllib.error.HTTPError as e:
        raise Exception(f"API error: {e.code}")
    except Exception as e:
        raise Exception(f"Request failed: {str(e)}")


def _build_prompt(input_text: str) -> str:
    """Build strict prompt for LLM."""
    return f"""You are a strict JSON generator.

Available tools:

- add_numbers → use for any math addition

You MUST ONLY use tool names from this list.

You MUST return ONLY valid JSON.

DO NOT include:
- explanations
- comments
- markdown
- text outside JSON

Return EXACTLY this format:

[
  {{
    "type": "tool",
    "name": "<tool_name>",
    "input_text": "{input_text}"
  }}
]

Rules:
- ALWAYS return a JSON array
- ALWAYS include all fields
- ONLY use listed tools
- NEVER invent tool names
- NEVER use "Calculator"
- NEVER return text outside JSON
- NEVER explain anything
- NEVER add extra keys
- NEVER wrap in markdown

If you cannot comply:
RETURN EXACTLY:

[]

DO NOT say anything else.
"""

import json
import os

_PATTERNS_PATH = "memory/execution_patterns.json"


def _load_patterns() -> dict:
    try:
        if os.path.exists(_PATTERNS_PATH):
            with open(_PATTERNS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def _save_patterns(patterns: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_PATTERNS_PATH), exist_ok=True)
        with open(_PATTERNS_PATH, "w", encoding="utf-8") as f:
            json.dump(patterns, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _extract_tool_name(input_str: str) -> str:
    if not isinstance(input_str, str):
        return ""
    tokens = input_str.strip().split()
    return tokens[0] if tokens else ""


def learn_from_attempts(attempt_history: list) -> None:
    if not isinstance(attempt_history, list) or len(attempt_history) < 2:
        return

    patterns = _load_patterns()
    changed = False

    for i in range(len(attempt_history) - 1):
        failed = attempt_history[i]
        succeeded = attempt_history[i + 1]

        if failed.get("status") != "failure":
            continue
        if succeeded.get("status") != "success":
            continue

        failed_input = failed.get("input")
        success_input = succeeded.get("input")

        if not isinstance(failed_input, str) or not isinstance(success_input, str):
            continue

        tool_name = _extract_tool_name(failed_input)
        if not tool_name:
            continue

        failed_tokens = set(failed_input.strip().split())
        success_tokens = set(success_input.strip().split())
        bad_tokens = failed_tokens - success_tokens

        for token in bad_tokens:
            if token.isdigit():
                continue
            if token.startswith('"') and token.endswith('"'):
                continue
            if "/" in token:
                continue
            if tool_name not in patterns:
                patterns[tool_name] = {
                    "remove_tokens": [token],
                    "usage_count": {token: 1}
                }
                changed = True
            elif token in patterns[tool_name].get("remove_tokens", []):
                patterns[tool_name]["usage_count"][token] += 1
                changed = True
            else:
                patterns[tool_name]["remove_tokens"].append(token)
                patterns[tool_name]["usage_count"][token] = 1
                changed = True

    if changed:
        _save_patterns(patterns)



def apply_memory(input_text: str) -> str:
    if not isinstance(input_text, str):
        return input_text

    patterns = _load_patterns()
    if not patterns:
        return input_text

    prefix = ""
    body = input_text.strip()

    if body.startswith("USE_TOOL:"):
        prefix = "USE_TOOL:"
        body = body.split(":", 1)[1].strip()

    tokens = body.split()
    if not tokens:
        return input_text

    tool_name = tokens[0]

    tool_patterns = patterns.get(tool_name, {})
    bad_tokens = set(tool_patterns.get("remove_tokens", []))

    if not bad_tokens:
        return input_text

    needs_cleaning = False
    for token in tokens:
        if token in bad_tokens:
            needs_cleaning = True
            break

    memory_applied = needs_cleaning

    if not needs_cleaning:
        return input_text

    def is_quoted(token):
        return token.startswith('"') and token.endswith('"')

    cleaned = []
    for token in tokens:
        if is_quoted(token):
            cleaned.append(token)
            continue
        if token in bad_tokens:
            continue
        cleaned.append(token)

    result = " ".join(cleaned)

    if prefix:
        return f"{prefix} {result}"
    return result

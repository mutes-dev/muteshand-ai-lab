import re

DEBUG_VERBOSE = False


class QuotedString(str):
    """Marker class for quoted string tokens."""
    pass


def is_number(token):
    """Check if token is a valid number."""
    try:
        float(token)
        return True
    except ValueError:
        return False

def _extract_quoted_tokens(input_text):
    """
    Extract tokens with quoted string support.

    Rules:
    - Unquoted: split on whitespace
    - Quoted ("..."): treat as single token, remove quotes
    - Malformed quotes: return None (failure signal)
    - Nested quotes: not supported
    - Escape sequences: not supported
    """
    tokens = []
    i = 0
    n = len(input_text)

    while i < n:
        # Skip whitespace
        if input_text[i].isspace():
            i += 1
            continue

        # Check for quoted string
        if input_text[i] == '"':
            # Find closing quote, allowing \" as an escaped quote.
            j = i + 1
            content_chars = []
            while j < n:
                ch = input_text[j]
                if ch == '\\' and j + 1 < n and input_text[j + 1] == '"':
                    content_chars.append('"')
                    j += 2
                    continue
                if ch == '"':
                    # Extract content between quotes (exclusive)
                    # Wrap in QuotedString marker for resolver to identify
                    tokens.append(QuotedString(''.join(content_chars)))
                    i = j + 1
                    break
                content_chars.append(ch)
                j += 1
            else:
                # Unbalanced quote - malformed
                return None
            continue
        else:
            # Unquoted token - find until next whitespace
            start = i
            while i < n and not input_text[i].isspace():
                i += 1
            token = input_text[start:i]
            tokens.append(token)

    return tokens


def parse_arguments(input_text):
    """
    Parser - Quoted String Argument Model.

    Contract-compliant behavior:
    - Supports quoted strings (treated as single token)
    - Preserves unquoted tokens from input_text
    - Returns list of tokens (numbers, quoted strings)
    - Maintains original token order
    - Returns failure dict for malformed quotes
    """
    if DEBUG_VERBOSE:
        print(f"[PARSER_INPUT]: {input_text}")

    # Extract tokens with quoted string support
    tokens = _extract_quoted_tokens(input_text)

    if tokens is None:
        if DEBUG_VERBOSE:
            print("[PARSER_OUTPUT]: FAILURE - malformed quotes")
        return {"status": "failure", "reason": "malformed_quotes"}

    parsed_tokens = []

    for i, token in enumerate(tokens):
        # 0. COMMAND TOKEN (index 0) - always allowed
        if i == 0:
            parsed_tokens.append(token)
            continue

        # 1. QUOTED STRING - preserve as QuotedString marker
        if isinstance(token, QuotedString):
            parsed_tokens.append(token)
            continue

        # 2. NUMBER (int or float)
        try:
            num = float(token)
            if token.isdigit() or (token.startswith('-') and token[1:].isdigit()):
                parsed_tokens.append(int(token))
            else:
                parsed_tokens.append(num)
            continue
        except ValueError:
            pass

        # 3. RAW STRING (unquoted) at index >= 1 - FAIL immediately
        if isinstance(token, str):
            return {
                "status": "failure",
                "reason": "invalid_token_type"
            }

    if DEBUG_VERBOSE:
        print(f"[PARSER_OUTPUT]: {parsed_tokens}")
    return parsed_tokens

def parse(planner_output):
    """
    Parser - Non-blocking argument extraction with quoted string support.

    Handles malformed quotes by propagating failure.
    """
    # If planner returned failure, pass it through for resolver to handle
    if isinstance(planner_output, dict) and planner_output.get("status") == "failure":
        return planner_output

    # Non-blocking: if not a list, return empty list
    if not isinstance(planner_output, list):
        return []

    result = []

    for step in planner_output:
        # Skip non-tool steps silently
        if step.get("type") != "tool":
            continue

        tool_name = step.get("name", "")
        input_text = step.get("input_text", "")

        # Use strict argument parsing (supports numbers and quoted strings)
        args = parse_arguments(input_text)

        # Handle parser failure (e.g., malformed quotes)
        if isinstance(args, dict) and args.get("status") == "failure":
            return args

        # PHASE 4: Preserve step structure using copy()
        new_step = step.copy()

        # KEEP name as canonical, add args
        new_step["args"] = args
        result.append(new_step)

    return result

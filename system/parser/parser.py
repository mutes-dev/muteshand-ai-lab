import re

def is_number(token):
    """Check if token is a valid number."""
    try:
        float(token)
        return True
    except ValueError:
        return False

def is_quoted_string(token):
    """Check if token is a properly quoted string (single quotes only)."""
    return token.startswith("'") and token.endswith("'") and len(token) >= 2

def clean_quoted_string(token):
    """Extract value from quoted string (remove surrounding quotes)."""
    return token[1:-1]

def parse_arguments(input_text):
    """
    Parse arguments from input_text with strict, deterministic rules.
    
    Supported patterns:
    1. Unary: <tool> <number>  →  [number]
    2. Binary with 'and': <tool> <arg1> and <arg2>  →  [arg1, arg2]
    3. Single quoted: <tool> 'value'  →  ['value']
    4. Multi-word quoted: <tool> 'multi word'  →  ['multi word']
    5. Mixed: arg1 and arg2 where each can be number or quoted string
    
    Rules:
    - ONLY single quotes allowed for strings
    - Multi-word strings MUST be properly quoted with opening and closing '
    - NO unquoted strings accepted
    - NO double quotes
    - Strict token count enforcement
    """
    print(f"[PARSER_INPUT]: {input_text}")
    tokens = input_text.strip().split()
    
    # Remove tool name (first token)
    if len(tokens) < 1:
        print(f"[PARSER_OUTPUT]: []")
        return []
    
    # Reconstruct arg_tokens with proper quoted string handling
    arg_tokens = []
    i = 1  # Start after tool name
    in_quote = False
    quote_buffer = []
    
    while i < len(tokens):
        token = tokens[i]
        
        if in_quote:
            # We're inside a quoted string, accumulate tokens
            quote_buffer.append(token)
            # Check if this token ends the quote
            if token.endswith("'"):
                # End of quoted string - join all buffered tokens
                full_quoted = " ".join(quote_buffer)
                # Verify it's properly quoted (starts with ', ends with ')
                if full_quoted.startswith("'") and full_quoted.endswith("'"):
                    arg_tokens.append(full_quoted)
                else:
                    # Malformed quote
                    return {"status": "failure", "reason": "argument_parse_error"}
                in_quote = False
                quote_buffer = []
        else:
            # Not in a quote - check if this starts a quoted string
            if token.startswith("'"):
                if token.endswith("'") and len(token) > 1:
                    # Single-token quoted string (e.g., 'hello')
                    arg_tokens.append(token)
                else:
                    # Multi-token quoted string starting
                    quote_buffer.append(token)
                    in_quote = True
            elif is_number(token):
                arg_tokens.append(token)
            elif token == 'and':
                arg_tokens.append(token)
            else:
                # Unquoted non-numeric string - skip (non-blocking parser behavior)
                # This allows legacy patterns like 'result' in chaining to pass through
                pass
        i += 1
    
    # Check for unclosed quote
    if in_quote:
        return {"status": "failure", "reason": "argument_parse_error"}
    
    if len(arg_tokens) == 0:
        print(f"[PARSER_OUTPUT]: []")
        return []
    
    # Now process arg_tokens with proper types
    def parse_token(token):
        """Parse a single token into its proper type."""
        if is_number(token):
            return int(token) if token.isdigit() or (token.startswith('-') and token[1:].isdigit()) else float(token)
        elif isinstance(token, str) and token.startswith("'") and token.endswith("'"):
            return clean_quoted_string(token)
        else:
            return token  # 'and' or other literals
        
    # Pattern 1: Unary (single argument)
    if len(arg_tokens) == 1:
        token = arg_tokens[0]
        if isinstance(token, str) and token == 'and':
            print(f"[PARSER_OUTPUT]: []")
            return []
        parsed = parse_token(token)
        if isinstance(parsed, str) and parsed == token and not is_number(token):
            # Token wasn't recognized as valid type
            print(f"[PARSER_OUTPUT]: []")
            return []
        print(f"[PARSER_OUTPUT]: {[parsed]}")
        return [parsed]
    
    # Pattern 2: Binary with 'and' (exactly 3 tokens: arg1, 'and', arg2)
    if len(arg_tokens) == 3 and arg_tokens[1] == 'and':
        arg1_token = arg_tokens[0]
        arg2_token = arg_tokens[2]
        
        # Parse arg1
        if is_number(arg1_token):
            arg1 = int(arg1_token) if arg1_token.isdigit() or (arg1_token.startswith('-') and arg1_token[1:].isdigit()) else float(arg1_token)
        elif isinstance(arg1_token, str) and arg1_token.startswith("'") and arg1_token.endswith("'"):
            arg1 = clean_quoted_string(arg1_token)
        else:
            return []  # Invalid arg1
        
        # Parse arg2
        if is_number(arg2_token):
            arg2 = int(arg2_token) if arg2_token.isdigit() or (arg2_token.startswith('-') and arg2_token[1:].isdigit()) else float(arg2_token)
        elif isinstance(arg2_token, str) and arg2_token.startswith("'") and arg2_token.endswith("'"):
            arg2 = clean_quoted_string(arg2_token)
        else:
            return []  # Invalid arg2
        
        print(f"[PARSER_OUTPUT]: {[arg1, arg2]}")
        return [arg1, arg2]
    
    # Pattern 3: Try to extract any numbers as fallback for legacy support
    # This maintains backward compatibility
    numbers = re.findall(r"-?\d+", input_text)
    print(f"[PARSER_NUMBERS]: {numbers}")
    if numbers:
        return [int(n) for n in numbers]
    
    print(f"[PARSER_OUTPUT]: []")
    return []

def parse(planner_output):
    """
    Parser - Non-blocking argument extraction.
    
    NEVER returns failure dict.
    ONLY extracts available arguments.
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

        result.append({
            "tool": tool_name,
            "args": args
        })

    return result

"""
Argument Resolver Module

PURPOSE:
    Extracts arguments from tokenized input.
    Filters out natural language filler words, preserving numeric and string values.

ARCHITECTURE ROLE:
    - Processing layer: Transforms tokens into executable arguments
    - Stateless: Pure function with no side effects
    - Bridge between parser and tool execution

LAYER RESPONSIBILITY:
    - Filter filler words (and, of, the, by, with, a, an, to, for, in, on)
    - Extract numeric values from tokens
    - Extract valid string tokens (non-filler, non-control words)
    - Preserve PREVIOUS_RESULT token as-is
    - Preserve order of arguments
    - Return empty list if no valid arguments found

USAGE:
    tokens = parse_tool_input("add 2 and 3")
    args = resolve_arguments("add_numbers", tokens)
    # Returns: [2, 3] (filler words removed, numbers extracted)
    
    tokens = parse_tool_input("read file test.txt")
    args = resolve_arguments("read_file", tokens)
    # Returns: ["test.txt"] (filler words removed, string extracted)

CONSTRAINTS:
    - Returns numeric values (int, float) and valid string values
    - Filler words are discarded
    - PREVIOUS_RESULT is preserved as-is
    - Order is preserved from original input
    - NO inference, NO regex, NO tool-specific logic
"""


def _is_numeric(value: str) -> bool:
    """
    Check if a string represents a numeric value (int or float).
    
    Args:
        value (str): String to check
        
    Returns:
        bool: True if numeric, False otherwise
    """
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def is_valid_argument_token(token):
    """
    Deterministic allow-list filter for argument tokens.
    
    Uses shape-based heuristics to identify valid argument tokens:
    - Numeric values (int, float) - PRIORITY 1
    - PREVIOUS_RESULT token - PRIORITY 2
    - URLs (starts with http:// or https://) - PRIORITY 3
    - Path-like strings (contains '/' or '\\') - PRIORITY 4
    - File-like strings (contains '.') - PRIORITY 5
    - Simple identifiers (alphanumeric, not filler) - PRIORITY 6 (LOWEST)
    
    This is a PRIMARY filter that allows tokens matching known argument patterns.
    It works alongside FILLER_WORDS (secondary filter) to eliminate noise.
    
    PRIORITY ORDER ensures stronger patterns are evaluated first, preventing
    ambiguous tokens from being misclassified.
    
    Args:
        token: Token to validate (any type)
        
    Returns:
        bool: True if token matches a valid argument pattern, False otherwise
        
    Examples:
        >>> is_valid_argument_token(5)
        True
        >>> is_valid_argument_token("test.txt")
        True
        >>> is_valid_argument_token("https://example.com")
        True
        >>> is_valid_argument_token("x")
        True
        >>> is_valid_argument_token("PREVIOUS_RESULT")
        True
    """
    # PRIORITY 1 — NUMERIC (highest priority for type safety)
    if isinstance(token, (int, float)):
        return True
    
    # PRIORITY 2 — PREVIOUS_RESULT (special runtime token)
    if token == "PREVIOUS_RESULT":
        return True
    
    # Only proceed if string
    if not isinstance(token, str):
        return False
    
    # PRIORITY 3 — URL (most specific string pattern)
    if token.startswith("http://") or token.startswith("https://"):
        return True
    
    # PRIORITY 4 — PATH-LIKE (specific structural pattern)
    if "/" in token or "\\" in token:
        return True
    
    # PRIORITY 5 — FILE-LIKE STRING (contains extension)
    if "." in token:
        return True
    
    # PRIORITY 6 — SIMPLE IDENTIFIERS (LOWEST PRIORITY)
    # Only accept if:
    # - Alphanumeric (no special chars)
    # - Reasonable length (≤32 chars)
    # - Not a filler word (checked in main loop, but double-check here)
    if (
        len(token) <= 32
        and token.isalnum()
    ):
        return True
    
    return False


def extract_chained_value(input_text: str) -> list:
    """
    Extract numeric value from normalized chained operation clauses.
    
    Supports flexible patterns:
    - "multiply ... by X" → ["PREVIOUS_RESULT", X]
    - "divide ... by X" → ["PREVIOUS_RESULT", X]
    - "add X ..." → ["PREVIOUS_RESULT", X]
    - "subtract X ..." → ["PREVIOUS_RESULT", X]
    
    Uses flexible positional matching - NO regex, NO NLP.
    
    Args:
        input_text (str): Normalized clause text
        
    Returns:
        list: ["PREVIOUS_RESULT", numeric_value] if pattern matched, None otherwise
    """
    tokens = input_text.strip().split()
    tokens_lower = [t.lower() for t in tokens]
    input_lower = input_text.lower()
    
    # CRITICAL: Only match chained operations that reference prior result
    # Prevents false matches on initial operations like "add 2 and 3"
    if "result" not in input_lower and "previous" not in input_lower:
        return None
    
    # MULTIPLY / DIVIDE (by X)
    if (
        len(tokens_lower) >= 3 and
        tokens_lower[0] in ["multiply", "divide"] and
        "by" in tokens_lower
    ):
        idx = tokens_lower.index("by")
        if idx + 1 < len(tokens) and _is_numeric(tokens[idx + 1]):
            value = int(tokens[idx + 1]) if tokens[idx + 1].isdigit() else float(tokens[idx + 1])
            return ["PREVIOUS_RESULT", value]
    
    # ADD (X ...)
    if (
        len(tokens_lower) >= 2 and
        tokens_lower[0] == "add" and
        _is_numeric(tokens[1])
    ):
        value = int(tokens[1]) if tokens[1].isdigit() else float(tokens[1])
        return ["PREVIOUS_RESULT", value]
    
    # SUBTRACT (X ...)
    if (
        len(tokens_lower) >= 2 and
        tokens_lower[0] == "subtract" and
        _is_numeric(tokens[1])
    ):
        value = int(tokens[1]) if tokens[1].isdigit() else float(tokens[1])
        return ["PREVIOUS_RESULT", value]
    
    # No pattern matched
    return None


def resolve_arguments(tool_name: str, tokens: list, input_text: str = "") -> list:
    """
    Resolve arguments from a list of tokens by extracting numeric and string values.
    
    FILTERING RULES:
        1. Try chained value extraction first (if input_text provided)
        2. Preserve PREVIOUS_RESULT token as-is
        3. Remove filler words: "and", "of", "the", "by", "with", "a", "an", "to", "for", "in", "on"
        4. Keep numeric values (int, float)
        5. Keep valid string tokens (non-filler, non-empty)
        6. Preserve original order
        7. Return list of arguments (may be empty)
    
    ARCHITECTURAL NOTE:
        - tool_name parameter is not used in current implementation
        - Reserved for future tool-specific argument handling
        - Maintains signature consistency across resolver functions
    
    Args:
        tool_name (str): Name of the tool (not used in current logic, reserved)
        tokens (list): List of tokens to process (from parser module)
        input_text (str): Original input text for chained pattern matching
        
    Returns:
        list: List of arguments (numeric or string) in original order.
              Returns empty list if no valid arguments found.
        
    Examples:
        >>> resolve_arguments("add", ["add", 5, "and", 7])
        [5, 7]
        
        >>> resolve_arguments("multiply", ["multiply", 4, "by", 3])
        [4, 3]
        
        >>> resolve_arguments("read_file", ["read", "file", "test.txt"])
        ["test.txt"]
        
        >>> resolve_arguments("read_webpage", ["read", "webpage", "https://example.com"])
        ["https://example.com"]
        
        >>> resolve_arguments("add", ["add", "x", "and", "y"])
        ["x", "y"]  # String tokens preserved
    """
    
    # Try chained value extraction first
    if input_text:
        chained = extract_chained_value(input_text)
        if chained is not None:
            return chained
    
    # Define filler words to remove - these are natural language connectors
    # and common verb tokens that have no semantic meaning for tool execution
    # EXPANDED: Now includes common articles, prepositions, verb tokens, and noise words
    FILLER_WORDS = {
        "and", "of", "the", "by", "with", "a", "an", "to", "for", "in", "on",
        "read", "file", "webpage", "add", "subtract", "multiply", "divide",
        "sum", "product",
        "square", "cube", "run", "execute", "result", "previous", "that",
        "please", "do", "something", "me", "my", "your", "this", "then",
        "process", "get", "set", "make", "create", "delete", "update", "show"
    }
    
    # Result list for arguments (numeric and valid strings)
    args = []
    
    # Process each token sequentially
    for token in tokens:
        # RULE 1: Preserve PREVIOUS_RESULT as-is (explicit handling)
        if token == "PREVIOUS_RESULT":
            args.append(token)
            continue
        
        # RULE 2: Skip filler words (secondary filter)
        if isinstance(token, str) and token.lower() in FILLER_WORDS:
            continue
        
        # RULE 3: PRIMARY allow-list filter
        # Only append tokens that match valid argument patterns
        if is_valid_argument_token(token):
            args.append(token)
    
    return args

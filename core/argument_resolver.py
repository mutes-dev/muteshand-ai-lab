"""
Argument Resolver Module

PURPOSE:
    Extracts numeric arguments from tokenized input.
    Filters out natural language filler words, preserving only numeric values.

ARCHITECTURE ROLE:
    - Processing layer: Transforms tokens into executable arguments
    - Stateless: Pure function with no side effects
    - Bridge between parser and tool execution

LAYER RESPONSIBILITY:
    - Filter filler words (and, of, the, by, with)
    - Extract only numeric values from tokens
    - Preserve order of numeric arguments
    - Return empty list if no numeric values found

USAGE:
    tokens = parse_tool_input("add 2 and 3")
    args = resolve_arguments("add_numbers", tokens)
    # Returns: [2, 3] (filler words removed, numbers extracted)

CONSTRAINTS:
    - Only returns numeric values (int, float)
    - Non-numeric tokens are discarded
    - Order is preserved from original input
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
    Resolve arguments from a list of tokens by extracting numeric values.
    
    FILTERING RULES:
        1. Try chained value extraction first (if input_text provided)
        2. Remove filler words: "and", "of", "the", "by", "with"
        3. Keep only numeric values (int, float)
        4. Preserve original order
        5. Return list of numeric values only (may be empty)
    
    ARCHITECTURAL NOTE:
        - tool_name parameter is not used in current implementation
        - Reserved for future tool-specific argument handling
        - Maintains signature consistency across resolver functions
    
    Args:
        tool_name (str): Name of the tool (not used in current logic, reserved)
        tokens (list): List of tokens to process (from parser module)
        input_text (str): Original input text for chained pattern matching
        
    Returns:
        list: List of numeric values (int or float) in original order.
              Returns empty list if no numeric values found.
        
    Examples:
        >>> resolve_arguments("add", ["add", 5, "and", 7])
        [5, 7]
        
        >>> resolve_arguments("multiply", ["multiply", 4, "by", 3])
        [4, 3]
        
        >>> resolve_arguments("square", ["square", 5])
        [5]
        
        >>> resolve_arguments("add", ["add", "x", "and", "y"])
        []  # No numeric values, returns empty
    """
    
    # Try chained value extraction first
    if input_text:
        chained = extract_chained_value(input_text)
        if chained is not None:
            return chained
    
    # Define filler words to remove - these are natural language connectors
    # that have no semantic meaning for tool execution
    FILLER_WORDS = {"and", "of", "the", "by", "with"}
    
    # Result list for numeric arguments
    numeric_args = []
    
    # Process each token sequentially
    for token in tokens:
        # Skip filler words (case-insensitive comparison)
        if isinstance(token, str) and token.lower() in FILLER_WORDS:
            continue
        
        # Keep numeric values only (int or float)
        if isinstance(token, (int, float)):
            numeric_args.append(token)
    
    return numeric_args

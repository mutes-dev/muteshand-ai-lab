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


def resolve_arguments(tool_name: str, tokens: list) -> list:
    """
    Resolve arguments from a list of tokens by extracting numeric values.
    
    FILTERING RULES:
        1. Remove filler words: "and", "of", "the", "by", "with"
        2. Keep only numeric values (int, float)
        3. Preserve original order
        4. Return list of numeric values only (may be empty)
    
    ARCHITECTURAL NOTE:
        - tool_name parameter is not used in current implementation
        - Reserved for future tool-specific argument handling
        - Maintains signature consistency across resolver functions
    
    Args:
        tool_name (str): Name of the tool (not used in current logic, reserved)
        tokens (list): List of tokens to process (from parser module)
        
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

"""
Input Parser Module

PURPOSE:
    Tokenizes natural language input for tool execution.
    Converts raw input strings into structured tokens (numbers, strings, words).

ARCHITECTURE ROLE:
    - Preprocessing layer: Prepares input for downstream processing
    - Stateless: No side effects, pure function
    - Used by argument resolver and tool executor

LAYER RESPONSIBILITY:
    - Extract tokens preserving original order
    - Convert numeric strings to int/float
    - Handle quoted strings (single and double quotes)
    - Ignore whitespace and commas

USAGE:
    tokens = parse_tool_input("add 2 and 3")
    # Returns: ["add", 2, "and", 3]
"""

import re


def parse_tool_input(input_text: str):
    """
    Order-preserving parser for tool inputs.
    
    Tokenizes input text into a list of values. Supports:
    - Numbers (integers and floats, including negative)
    - Single-quoted strings: 'hello'
    - Double-quoted strings: "hello"
    - Unquoted words (alphanumeric and underscores)
    
    Whitespace and commas are treated as separators.
    
    PARSING RULES:
        1. Single quotes have highest priority
        2. Double quotes have second priority  
        3. Numbers are converted to int or float
        4. Everything else becomes a string word
    
    Args:
        input_text (str): Raw input text to parse. May be None.
        
    Returns:
        list: Ordered list of tokens. Returns empty list for None or empty input.
        Numbers are int or float. Quoted strings preserve content.
        
    Examples:
        >>> parse_tool_input("add 2 and 3")
        ['add', 2, 'and', 3]
        
        >>> parse_tool_input("multiply 4.5 by 2")
        ['multiply', 4.5, 'by', 2]
        
        >>> parse_tool_input("search 'hello world'")
        ['search', 'hello world']
        
        >>> parse_tool_input("")
        []
        
        >>> parse_tool_input(None)
        []
    """
    
    # Handle None input gracefully
    if input_text is None:
        return []
    
    # Normalize to string and strip whitespace
    input_text = str(input_text).strip()
    
    # Normalize: collapse multiple spaces and lowercase
    input_text = " ".join(input_text.split())
    input_text = input_text.lower()
    
    # Handle empty input
    if not input_text:
        return []
    
    args = []
    
    # Regex pattern matches in order of priority:
    # 1. '([^']*)'  - Single-quoted strings (captured without quotes)
    # 2. "([^"]*)"  - Double-quoted strings (captured without quotes)
    # 3. -?\d+\.\d+|-?\d+ - Numbers (float or int, negative supported)
    # 4. [^\s,]+    - Words (non-whitespace, non-comma sequences)
    token_pattern = r"'([^']*)'|\"([^\"]*)\"|(-?\d+\.\d+|-?\d+)|([^\s,]+)"
    
    matches = re.findall(token_pattern, input_text)
    
    # Process each regex match tuple
    for match in matches:
        # match is a 4-tuple: (single_quote, double_quote, number, word)
        quoted_single, quoted_double, number, word = match
        
        if quoted_single:
            # Single-quoted string takes priority
            args.append(quoted_single)
        elif quoted_double:
            # Double-quoted string is second priority
            args.append(quoted_double)
        elif number:
            # Convert numeric string to appropriate type
            if "." in number:
                args.append(float(number))
            else:
                args.append(int(number))
        elif word:
            # Unquoted word becomes string token
            args.append(word)
    
    return args
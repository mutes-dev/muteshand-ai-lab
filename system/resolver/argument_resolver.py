import json
import os
import re

# EXPLICIT PHRASE MAPPING - Synced with planner
TOOL_PHRASES = {
    "add_numbers": ["add", "sum", "addition"],
    "subtract_numbers": ["subtract", "difference", "minus"],
    "multiply_numbers": ["multiply", "product", "times"],
    "divide_numbers": ["divide"],
    "square_number": ["square"],
    "cube_number": ["cube"],
    "factorial": ["factorial"],
    "fibonacci": ["fibonacci"],
    "square_root": ["root"],
    "multiply_square_root": ["multisqrt"],
    "multiply_string": ["multiply string"],
    "list_files": ["list files"],
    "read_file": ["read file"],
    "read_webpage": ["read webpage"],
    "web_search": ["web search"],
    "write_file": ["write file"]
}

# Load tool_index once at module level
_TOOL_INDEX = None

def _load_tool_index():
    """Load tool_index from tools.json."""
    global _TOOL_INDEX
    if _TOOL_INDEX is None:
        tool_index_path = os.path.join(os.path.dirname(__file__), "..", "..", "memory", "tool_index", "tools.json")
        tool_index_path = os.path.normpath(tool_index_path)
        with open(tool_index_path, 'r') as f:
            _TOOL_INDEX = json.load(f)
    return _TOOL_INDEX

def _is_number(token):
    """Check if token is a valid number."""
    try:
        float(token)
        return True
    except ValueError:
        return False

def _strip_phrase(input_text, tool_name):
    """
    Remove matched command phrase from input_text.
    
    Rules:
    - Evaluate ONLY phrases for this tool
    - Match MUST be full phrase (word boundary)
    - If multiple matches -> select LONGEST match
    - Preserve remaining text exactly
    """
    phrases = TOOL_PHRASES.get(tool_name, [])
    if not phrases:
        return input_text
    
    # Find longest matching phrase at start of input
    matched_phrase = None
    text = input_text.strip()
    
    # Sort phrases by length (longest first) for deterministic matching
    sorted_phrases = sorted(phrases, key=lambda p: len(p), reverse=True)
    
    for phrase in sorted_phrases:
        # Match phrase at start with word boundary
        pattern = r'^' + re.escape(phrase) + r'\b'
        if re.match(pattern, text):
            matched_phrase = phrase
            break
    
    if matched_phrase:
        # Remove matched phrase from start
        # Use replace with count=1 to remove only first occurrence at start
        cleaned = text.replace(matched_phrase, "", 1).strip()
        return cleaned
    
    return input_text

def _construct_args(tool_name, numbers, input_text):
    """
    Schema-driven argument construction.
    
    Uses tool_index schema to construct arguments from:
    - numbers: parser output (numeric args only)
    - input_text: original raw input (after phrase stripping)
    
    NO tool-specific logic.
    NO inference.
    ONLY schema-driven mapping.
    """
    tool_index = _load_tool_index()
    
    if tool_name not in tool_index:
        return numbers
    
    inputs_schema = tool_index[tool_name].get("inputs", {})
    if not inputs_schema:
        return []
    
    # Convert schema to ordered list of types
    schema_types = list(inputs_schema.values())
    
    # If schema is all numbers, return parser output directly
    if all(t == "number" for t in schema_types):
        return numbers
    
    # STRIP COMMAND PHRASE from input_text
    cleaned_input = _strip_phrase(input_text, tool_name)
    
    # Tokenize CLEANED input (after phrase removal)
    tokens = cleaned_input.strip().split()
    
    # Create string token pool by removing numbers (positional match)
    string_tokens = []
    number_idx = 0
    
    for token in tokens:
        if _is_number(token) and number_idx < len(numbers):
            # Check if this token matches the next number from parser
            try:
                if token.isdigit() or (token.startswith('-') and token[1:].isdigit()):
                    token_value = int(token)
                else:
                    token_value = float(token)
                
                if token_value == numbers[number_idx]:
                    # This token is a number from parser - skip it
                    number_idx += 1
                    continue
            except:
                pass
        
        # Not a number or doesn't match - add to string tokens
        string_tokens.append(token)
    
    # Map arguments according to schema
    args = []
    num_idx = 0
    str_idx = 0
    
    for arg_type in schema_types:
        if arg_type == "number":
            if num_idx < len(numbers):
                args.append(numbers[num_idx])
                num_idx += 1
            else:
                # Missing number - return empty to trigger validation failure
                return []
        
        elif arg_type == "string":
            # Count remaining string fields in schema
            remaining_string_fields = schema_types[len(args):].count("string")
            
            if remaining_string_fields == 1:
                # Last string field - take all remaining string tokens
                if str_idx < len(string_tokens):
                    value = " ".join(string_tokens[str_idx:])
                    args.append(value)
                    str_idx = len(string_tokens)
                else:
                    # Missing string - return empty to trigger validation failure
                    return []
            else:
                # Multiple string fields remain - take first token
                if str_idx < len(string_tokens):
                    args.append(string_tokens[str_idx])
                    str_idx += 1
                else:
                    # Missing string - return empty to trigger validation failure
                    return []
    
    return args

def resolve(plan: list, input_text: str) -> list:
    resolved_plan = []

    for i, step in enumerate(plan):
        tool = step["tool"]
        numbers = step["args"]  # Parser output (numbers only)
        
        # Construct arguments using schema and original input_text
        args = _construct_args(tool, numbers, input_text)

        # PREVIOUS_RESULT injection (chaining support)
        if i > 0:
            if len(args) == 1:
                args = ["PREVIOUS_RESULT", args[0]]

        resolved_plan.append({
            "tool": tool,
            "args": args
        })

    return resolved_plan

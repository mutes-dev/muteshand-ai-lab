import json
import os

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

def _construct_args(tool_name, tokens):
    """
    Positional argument construction - NO type filtering.

    Rules:
    - Discard command token (tokens[0])
    - Map remaining tokens positionally to args
    - NO type checking (validator handles this)
    - NO filtering by type
    - Full consumption required: token count must match expected arg count

    Returns:
    - list of args on success (all data tokens)
    - empty list [] on failure (count mismatch)
    """
    tool_index = _load_tool_index()

    if tool_name not in tool_index:
        return tokens[1:] if len(tokens) > 0 else []

    inputs_schema = tool_index[tool_name].get("inputs", {})
    expected_count = len(inputs_schema)

    # Discard command token (first token)
    if len(tokens) == 0:
        return []
    data_tokens = tokens[1:]

    # STRUCTURAL CHECK: token count must match expected argument count
    # This ensures validator receives correct number for type checking
    if len(data_tokens) != expected_count:
        return []

    # Return all data tokens directly - NO type filtering
    # Validator will check types
    return data_tokens

def resolve(plan: list, input_text: str) -> list:
    """
    Resolve plan steps to execution format.

    STRICT: No chaining support. Each step resolved independently.
    """
    resolved_plan = []

    for step in plan:
        tool = step["name"]
        tokens = step["args"]

        # Construct arguments from tokens ONLY
        args = _construct_args(tool, tokens)

        resolved_plan.append({
            "name": tool,
            "args": args
        })

    return resolved_plan

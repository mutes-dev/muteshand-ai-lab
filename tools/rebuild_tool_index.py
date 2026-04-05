INPUT_SPEC = {}

def normalize_input_spec(input_spec):
    """
    Normalize flat INPUT_SPEC to structured format for tools.json.
    
    Converts: {"param": "type"}
    To:       {"param": {"type": "type", "required": true}}
    
    Args:
        input_spec (dict): Flat input spec from tool file
        
    Returns:
        dict: Structured format compatible with validation
    """
    return {
        param: {
            "type": type_str,
            "required": True
        }
        for param, type_str in input_spec.items()
    }

def validate_normalized_inputs(inputs):
    """
    Validate that inputs are in correct structured format.
    
    Raises ValueError if structure is invalid.
    
    Args:
        inputs (dict): Normalized input spec to validate
        
    Raises:
        ValueError: If any input spec is not a dict or missing required fields
    """
    for param, spec in inputs.items():
        if not isinstance(spec, dict):
            raise ValueError(f"Invalid input spec for '{param}' — not dict")
        if "type" not in spec:
            raise ValueError(f"Missing 'type' in input spec for '{param}'")
        if "required" not in spec:
            raise ValueError(f"Missing 'required' in input spec for '{param}'")

def run():
    import os
    import json
    import importlib

    BASE_PATH = "E:/MutesHand"
    tools_dir = os.path.join(BASE_PATH, "tools")
    index_file = os.path.join(BASE_PATH, "memory", "tool_index", "tools.json")

    # Ensure index directory exists
    os.makedirs(os.path.dirname(index_file), exist_ok=True)

    tool_index = {}

    for file in os.listdir(tools_dir):

        if not file.endswith(".py"):
            continue

        tool_name = file[:-3]

        try:
            module = importlib.import_module(f"tools.{tool_name}")
            importlib.reload(module)

            input_spec = getattr(module, "INPUT_SPEC", {})
            inputs = normalize_input_spec(input_spec)
            validate_normalized_inputs(inputs)

        except Exception as e:
            print(f"Tool registration failed for '{tool_name}': {e}")
            inputs = {}

        tool_index[tool_name] = {
            "description": f"Tool {tool_name}",
            "inputs": inputs,
            "tags": []
        }

    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(tool_index, f, indent=2)

    return "Tool index rebuilt."
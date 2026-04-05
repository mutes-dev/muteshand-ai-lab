"""
Registry Builder

Purpose:
    Build validation and execution registries from tool metadata and implementations.

Rules:
    - Deterministic
    - No side effects
    - Explicit loading only
    - No inference
"""

import json
import os
import importlib.util


_TYPE_MAP = {
    "number": int,
    "string": str
}


def _map_type(type_str: str) -> type:
    """Map type string to Python type."""
    return _TYPE_MAP[type_str]


def build_registries(tool_index_path: str, tools_dir: str):
    """
    Build validation and execution registries.
    
    Returns:
        tuple: (validation_registry, execution_registry)
    """
    with open(tool_index_path, "r") as f:
        tool_index = json.load(f)

    validation_registry = {}
    execution_registry = {}

    for tool_name, entry in tool_index.items():
        # VALIDATION REGISTRY
        inputs = entry.get("inputs", [])
        
        # Handle both array and dict formats
        if isinstance(inputs, dict):
            args = len(inputs)
            types = [_map_type(t) for t in inputs.values()]
        elif isinstance(inputs, list):
            args = len(inputs)
            types = [_map_type(param.get("type", "string")) for param in inputs]
        else:
            args = 0
            types = []
        
        validation_registry[tool_name] = {
            "args": args,
            "types": types
        }

        # EXECUTION REGISTRY
        tool_file = os.path.join(tools_dir, f"{tool_name}.py")

        if not os.path.exists(tool_file):
            raise Exception(f"tool_load_error_{tool_name}")

        spec = importlib.util.spec_from_file_location(tool_name, tool_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "run"):
            raise Exception(f"tool_missing_run_{tool_name}")

        execution_registry[tool_name] = module.run

    # Consistency check
    if set(validation_registry.keys()) != set(execution_registry.keys()):
        raise Exception("registry_key_mismatch")

    return validation_registry, execution_registry

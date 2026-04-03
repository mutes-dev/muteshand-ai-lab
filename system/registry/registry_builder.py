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
    with open(tool_index_path, "r") as f:
        tool_index = json.load(f)

    validation_registry = {}
    execution_registry = {}

    for tool_name, entry in tool_index.items():
        # VALIDATION REGISTRY
        inputs = entry.get("inputs", {})
        args = len(inputs)
        
        types = []
        for param_name, param_spec in inputs.items():
            type_str = param_spec["type"]
            mapped_type = _map_type(type_str)
            types.append(mapped_type)
        
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

    # STRICT CONSISTENCY CHECK
    if set(validation_registry.keys()) != set(execution_registry.keys()):
        raise Exception("registry_key_mismatch")

    print(f"Validation keys count: {len(validation_registry)}")
    print(f"Execution keys count: {len(execution_registry)}")
    print(f"Mismatch: {set(validation_registry.keys()) ^ set(execution_registry.keys())}")

    return validation_registry, execution_registry

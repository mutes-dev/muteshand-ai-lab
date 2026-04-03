"""
System Entry Point

Responsibility:
- Orchestrate validation → execution pipeline
- Enforce fail-fast behavior

Pipeline:
plan → validation → execution → result

Rules:
- MUST NOT contain business logic
- MUST NOT modify plan
- MUST NOT perform validation logic
- MUST NOT perform execution logic
"""

from core.validation import validate
from system.execution.executor import execute


def run(plan: list, validation_registry: dict, execution_registry: dict) -> dict:
    """
    Orchestrate validation → execution pipeline.
    
    Args:
        plan: Structured plan (list of steps)
        validation_registry: Tool metadata for validation
        execution_registry: Tool callables for execution
    
    Returns:
        dict: Execution result or validation failure
    """
    # STEP 1 — VALIDATION
    print("ENTRY → PLAN RECEIVED:", plan)
    print("ENTRY → VALIDATION REGISTRY KEYS SAMPLE:", list(validation_registry.keys())[:5])
    validation_result = validate(plan, validation_registry)
    
    # STEP 2 — FAIL-FAST
    if validation_result["status"] == "failure":
        return validation_result
    
    # STEP 3 — EXECUTION
    execution_result = execute(plan, execution_registry)
    
    # STEP 4 — RETURN
    return execution_result

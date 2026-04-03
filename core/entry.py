"""
Entry Layer (Phase 2)

PURPOSE:
    Strict pipeline orchestrator between validation and execution.

ARCHITECTURE ROLE:
    - Orchestrates validation → execution pipeline
    - Pure orchestration, NO business logic
    - Enforces fail-fast behavior

RULES:
    - MUST be deterministic
    - MUST NOT modify plan
    - MUST NOT modify registries
    - MUST NOT add logic
    - MUST return outputs unchanged
"""

from core.validation import validate
from system.execution.executor import execute


def run(plan: list, validation_registry: dict, execution_registry: dict) -> dict:
    """
    Execute the validation → execution pipeline.
    
    INPUT:
        plan: list of steps, each step is {"tool": str, "args": list}
        validation_registry: dict mapping tool_name -> {"args": int, "types": list}
        execution_registry: dict mapping tool_name -> callable
    
    OUTPUT:
        Validation failure → return validation result
        Execution result → return execution result
    
    PIPELINE:
        1. Validate plan
        2. If validation fails → return failure
        3. If validation succeeds → execute plan
        4. Return execution result
    """
    validation_result = validate(plan, validation_registry)
    
    if validation_result["status"] == "failure":
        return validation_result
    
    execution_result = execute(plan, execution_registry)
    
    return execution_result

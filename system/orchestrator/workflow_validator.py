import json
import os
import re

from system.orchestrator.synthesis_dependency_utils import (
    _extract_explicit_step_references,
    _get_required_synthesis_dependencies,
    _is_all_prior_synthesis_step,
)

VALID_WORKFLOW_STATUSES = ["QUEUED", "ACTIVE", "PAUSED", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED"]
VALID_STEP_STATUSES = ["PENDING", "ACTIVE", "RETRY", "COMPLETED", "FAILED", "BLOCKED"]
REQUIRED_WORKFLOW_KEYS = ["id", "name", "status", "steps"]

# === STRUCTURAL VALIDATION (Pre-Resolution) ===
# Per PLAN_STEP_CONTRACT_V1: Plan steps MUST NOT include tool_call
# These fields are validated on ALL steps (plan and execution-ready)
REQUIRED_PLAN_STEP_KEYS = ["id", "type", "purpose", "expected_outcome", "risk", "importance", "resource_targets"]

# === STEP_SCHEMA VALIDATION (Post-Resolution) ===
# Per STEP_SCHEMA_CONTRACT_V1: Only execution-ready steps are validated
# Resolution MUST produce valid STEP_SCHEMA before execution
REQUIRED_STEP_SCHEMA_KEYS = ["id", "type", "purpose", "tool_call", "expected_outcome", "risk", "importance", "resource_targets"]

# Per STEP_SCHEMA_CONTRACT_V1: Enum validations
VALID_STEP_TYPES = [
    "ANALYZE", "RESEARCH", "PLAN", "PROPOSE",
    "EXECUTE_API", "EXECUTE_LOCAL", "EXECUTE_FILE", "EXECUTE_INSTALL",
    "EXECUTE_SYSTEM_SETTINGS_SERVICES", "EXECUTE_ENVIRONMENT",
    "VALIDATE", "GENERATE", "BUILD"
]
VALID_RISK_LEVELS = ["LOW", "MEDIUM", "HIGH"]
VALID_IMPORTANCE_LEVELS = ["LOW", "MEDIUM", "HIGH"]


_KNOWN_TOOL_NAMES = None


def _get_known_tool_names():
    global _KNOWN_TOOL_NAMES
    if _KNOWN_TOOL_NAMES is None:
        tool_index_path = os.path.join("system", "tool_index", "tools.json")
        try:
            with open(tool_index_path, "r", encoding="utf-8") as f:
                tool_index = json.load(f)
            _KNOWN_TOOL_NAMES = {
                name for name, data in tool_index.items()
                if isinstance(data, dict) and data.get("production", False)
            }
        except Exception:
            _KNOWN_TOOL_NAMES = set()
    return _KNOWN_TOOL_NAMES


# Keywords that indicate a step references a prior step's output.
# Per DEPENDENCY_MODEL_CONTRACT_V1: if a step consumes prior output,
# it MUST declare depends_on explicitly. System MUST NOT infer — but MUST detect
# the undeclared case and fail with a clear error.
_CONTEXT_REFERENCE_KEYWORDS = ["the result", "previous result", "prior result"]


def _validate_dag(steps: list) -> dict:
    """
    Validate that the dependency graph is a valid DAG (Directed Acyclic Graph).

    Per DEPENDENCY_MODEL_CONTRACT_V1 Section 2:
    - Graph MUST be acyclic (no loops)
    - Graph MUST be resolvable (no missing nodes)

    Uses iterative DFS with a recursion stack to detect cycles.
    Returns {"status": "success"} or structured failure with step_id.

    MUST NOT modify dependencies or auto-correct. Validate only.
    """
    # Build adjacency map: step_id -> list of step_ids it depends on
    graph = {}
    for step in steps:
        if isinstance(step, dict):
            graph[step["id"]] = step.get("depends_on", [])

    # DFS cycle detection: WHITE=0 (unvisited), GRAY=1 (in stack), BLACK=2 (done)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}

    def _dfs(start: str):
        # Iterative DFS using explicit stack of (node, iterator_over_neighbors)
        stack = [(start, iter(graph.get(start, [])))]
        color[start] = GRAY
        while stack:
            node, neighbors = stack[-1]
            try:
                neighbor = next(neighbors)
                if neighbor not in color:
                    # Neighbor is outside graph — already caught by reference check
                    continue
                if color[neighbor] == GRAY:
                    # Cycle detected: neighbor is on the current recursion path
                    return neighbor
                if color[neighbor] == WHITE:
                    color[neighbor] = GRAY
                    stack.append((neighbor, iter(graph.get(neighbor, []))))
            except StopIteration:
                color[node] = BLACK
                stack.pop()
        return None

    for node in graph:
        if color[node] == WHITE:
            cycle_node = _dfs(node)
            if cycle_node is not None:
                return {
                    "status": "failure",
                    "reason": "circular_dependency",
                    "step_id": cycle_node,
                    "message": f"Circular dependency detected involving step '{cycle_node}'"
                }

    return {"status": "success"}


def validate_step_schema(step: dict) -> dict:
    """
    Post-resolution STEP_SCHEMA validation.
    
    Per STEP_SCHEMA_CONTRACT_V1:
    - ONLY execution-ready steps may be validated
    - Resolution MUST produce valid STEP_SCHEMA before execution
    - Must validate: tool_call present, required fields, enum values
    
    Args:
        step: The resolved step dict (post-resolution, should have tool_call)
        
    Returns:
        {"status": "success"} or {"status": "failure", "reason": ...}
    """
    if not isinstance(step, dict):
        return {"status": "failure", "reason": "invalid_step_type"}
    
    # Check all STEP_SCHEMA required fields
    for key in REQUIRED_STEP_SCHEMA_KEYS:
        if key not in step:
            return {"status": "failure", "reason": f"missing_step_schema_field:{key}"}
    
    # Validate tool_call is not empty
    tool_call = str(step.get("tool_call", "")).strip()
    if not tool_call:
        return {"status": "failure", "reason": "empty_tool_call"}

    if tool_call.startswith("USE_TOOL:"):
        return {"status": "failure", "reason": "malformed_tool_call_directive_prefix"}

    selected_tool = step.get("selected_tool")
    if selected_tool:
        if selected_tool == "USE_TOOL:":
            return {"status": "failure", "reason": "invalid_selected_tool"}
        if selected_tool not in _get_known_tool_names():
            return {"status": "failure", "reason": "invalid_selected_tool"}

    first_token = tool_call.split()[0] if tool_call.split() else None
    if first_token and first_token not in _get_known_tool_names():
        return {"status": "failure", "reason": "invalid_tool_call_tool_name"}

    # Enum validations
    if step.get("type") not in VALID_STEP_TYPES:
        return {"status": "failure", "reason": "invalid_step_type"}

    if step.get("risk") not in VALID_RISK_LEVELS:
        return {"status": "failure", "reason": "invalid_risk_level"}

    if step.get("importance") not in VALID_IMPORTANCE_LEVELS:
        return {"status": "failure", "reason": "invalid_importance_level"}
    
    return {"status": "success"}


def validate_workflow(workflow: dict) -> dict:
    """
    Structural workflow validation (pre-resolution).
    
    Per PLAN_STEP_CONTRACT_V1:
    - Planner output MUST NOT be validated against STEP_SCHEMA
    - Plan steps have: id, type, purpose, expected_outcome, risk, importance (NO tool_call)
    
    Per STEP_SCHEMA_CONTRACT_V1:
    - STEP_SCHEMA validation only applies to execution-ready steps (post-resolution)
    - STEP_SCHEMA validation occurs ONLY in step_executor.py after resolution
    
    Args:
        workflow: The workflow dict to validate
        
    Returns:
        {"status": "success"} or {"status": "failure", "reason": ...}
    """
    if not isinstance(workflow, dict):
        return {"status": "failure", "reason": "invalid_workflow_type"}

    for key in REQUIRED_WORKFLOW_KEYS:
        if key not in workflow:
            return {"status": "failure", "reason": "missing_workflow_field"}

    if workflow["status"] not in VALID_WORKFLOW_STATUSES:
        return {"status": "failure", "reason": "invalid_workflow_status"}

    if not isinstance(workflow["steps"], list):
        return {"status": "failure", "reason": "invalid_steps_type"}

    if len(workflow["steps"]) == 0:
        return {"status": "failure", "reason": "empty_steps"}

    seen_ids = []

    for step in workflow["steps"]:
        if not isinstance(step, dict):
            return {"status": "failure", "reason": "invalid_step_type"}

        # === STRUCTURAL VALIDATION (Pre-Resolution) ===
        # Per PLAN_STEP_CONTRACT_V1: Plan steps have these fields (NO tool_call required yet)
        for key in REQUIRED_PLAN_STEP_KEYS:
            if key not in step:
                return {"status": "failure", "reason": f"missing_step_field:{key}"}

        # Enum validations (applies to both plan and execution steps)
        if step.get("type") not in VALID_STEP_TYPES:
            return {"status": "failure", "reason": "invalid_step_type"}

        if step.get("risk") not in VALID_RISK_LEVELS:
            return {"status": "failure", "reason": "invalid_risk_level"}

        if step.get("importance") not in VALID_IMPORTANCE_LEVELS:
            return {"status": "failure", "reason": "invalid_importance_level"}

        # Runtime fields (validated if present)
        if "status" in step and step["status"] not in VALID_STEP_STATUSES:
            return {"status": "failure", "reason": "invalid_step_status"}

        if step["id"] in seen_ids:
            return {"status": "failure", "reason": "duplicate_step_id"}

        seen_ids.append(step["id"])

    # === DEPENDENCY GRAPH VALIDATION (DEPENDENCY_MODEL_CONTRACT_V1) ===
    # Collect all valid step ids for reference checking.
    all_step_ids = {s.get("id") for s in workflow["steps"] if isinstance(s, dict)}

    for step in workflow["steps"]:
        step_id = step.get("id", "unknown")
        depends_on = step.get("depends_on", [])

        # Rule 1: All depends_on references MUST point to existing step ids.
        # Per contract: "reference an existing id"
        if isinstance(depends_on, list):
            for ref in depends_on:
                if ref not in all_step_ids:
                    return {
                        "status": "failure",
                        "reason": "invalid_dependency_reference",
                        "step_id": step_id,
                        "message": f"Dependency required but not declared: step '{step_id}' references unknown step '{ref}'"
                    }
                if ref == step_id:
                    return {
                        "status": "failure",
                        "reason": "self_dependency",
                        "step_id": step_id,
                        "message": f"Dependency required but not declared: step '{step_id}' references itself"
                    }

    # === DAG CYCLE DETECTION (DEPENDENCY_MODEL_CONTRACT_V1 Section 2) ===
    # Run after reference validation so all referenced ids are confirmed to exist.
    # Blocks execution on any cycle — no auto-fix, no partial execution.
    dag_result = _validate_dag(workflow["steps"])
    if dag_result["status"] == "failure":
        return dag_result

    # === PARTIAL DEPENDENCY DECLARATION CHECK (ISSUE-PDIAG-001) ===
    # Every explicit step reference in purpose or expected_outcome MUST appear in depends_on.
    # Validator MUST NOT auto-repair bad planner output — MUST fail before execution.
    for step in workflow["steps"]:
        step_id = step.get("id", "unknown")
        depends_on = step.get("depends_on", []) or []
        declared = set(depends_on) if isinstance(depends_on, list) else set()

        referenced = []
        seen_refs = set()
        for field in ["purpose", "expected_outcome"]:
            for ref in _extract_explicit_step_references(step.get(field, "")):
                if ref not in seen_refs:
                    seen_refs.add(ref)
                    referenced.append(ref)

        missing = [ref for ref in referenced if ref not in declared]
        if missing:
            return {
                "status": "failure",
                "reason": "partial_dependency_declaration",
                "step_id": step_id,
                "message": f"Step '{step_id}' references {missing} but depends_on only declares {list(declared)}",
                "missing_dependencies": missing
            }

    # === FINAL SYNTHESIS DEPENDENCY COMPLETENESS CHECK (ISSUE-PDIAG-002A) ===
    # If a clearly identified final synthesis step exists in a multi-step workflow,
    # it must declare dependencies on all required prior source steps.
    # Does NOT auto-bind. Does NOT create synthesis steps.
    total_steps = len(workflow["steps"])
    for i, step in enumerate(workflow["steps"]):
        if not _is_all_prior_synthesis_step(step, i, total_steps):
            continue

        step_id = step.get("id", "unknown")
        declared = set(step.get("depends_on", []) or [])
        required = _get_required_synthesis_dependencies(workflow["steps"], i)

        missing = required - declared
        if missing:
            return {
                "status": "failure",
                "reason": "under_declared_synthesis_dependencies",
                "step_id": step_id,
                "message": f"Step '{step_id}' is a final synthesis step but does not declare dependencies on all required source steps: missing {sorted(missing)}",
                "missing_dependencies": sorted(missing)
            }

    for step in workflow["steps"]:
        step_id = step.get("id", "unknown")
        depends_on = step.get("depends_on", [])

        # Rule 2: If step purpose references prior context keywords but depends_on is empty,
        # the dependency is implicitly required but not declared — FAIL.
        # Per contract: step "relies on output from another step" REQUIRES depends_on.
        # System MUST NOT auto-fix — MUST fail with clear error.
        purpose_lower = (step.get("purpose") or step.get("input") or "").lower()
        if any(kw in purpose_lower for kw in _CONTEXT_REFERENCE_KEYWORDS):
            if not depends_on:
                return {
                    "status": "failure",
                    "reason": "dependency_not_declared",
                    "step_id": step_id,
                    "message": f"Dependency required but not declared: step '{step_id}' references prior output without depends_on"
                }

    return {"status": "success"}

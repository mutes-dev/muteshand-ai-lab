VALID_WORKFLOW_STATUSES = ["QUEUED", "ACTIVE", "PAUSED", "BLOCKED", "COMPLETED", "FAILED"]
VALID_STEP_STATUSES = ["PENDING", "ACTIVE", "COMPLETED", "FAILED", "BLOCKED"]
REQUIRED_WORKFLOW_KEYS = ["id", "name", "status", "steps"]
REQUIRED_STEP_KEYS = ["id", "name", "agent", "status", "retries", "max_retries", "input"]

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


def validate_workflow(workflow: dict) -> dict:
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

        for key in REQUIRED_STEP_KEYS:
            if key not in step:
                return {"status": "failure", "reason": "missing_step_field"}

        if step["status"] not in VALID_STEP_STATUSES:
            return {"status": "failure", "reason": "invalid_step_status"}

        if not isinstance(step["retries"], int) or step["retries"] < 0:
            return {"status": "failure", "reason": "invalid_retries"}

        if not isinstance(step["max_retries"], int) or step["max_retries"] < 0:
            return {"status": "failure", "reason": "invalid_max_retries"}

        if step["retries"] > step["max_retries"]:
            return {"status": "failure", "reason": "retries_exceed_max"}

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

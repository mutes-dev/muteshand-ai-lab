"""RESOURCE ACCESS RESOLVER — Deterministic resource identity + access mode classification.

Complies with SPRINT-11C Phase 2 SA design decision:
- Deterministic local mapping from known capability/tool identity.
- Target identity + access mode classification only.
- Does NOT own lifecycle, governance, execution truth, system_entry, projection,
  AG1, learning, dependency resolution, or planner semantic interpretation.

Placement:
- Pre-runtime helper/module near capability compiler / planning-compiler boundary.
- Consumed by conflict_detector and execution_scheduler.
- Capability-emitted and structurally known tool/resource cases only.

Authority boundary:
- tools.json metadata is NOT scheduling/conflict authority in this slice.
- This resolver uses a hardcoded deterministic mapping, not tools.json fields.
- Unknown/missing access defaults conservative.
"""

from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Deterministic tool -> (target_type, access_mode) mapping
# ---------------------------------------------------------------------------
# Approved mapping source per SA decision 2026-07-03.
# Hardcoded deterministic mapping — NOT read from tools.json.

TOOL_ACCESS_MAP: Dict[str, Tuple[str, str]] = {
    # File read
    "read_file": ("file", "read"),
    "read_csv": ("file", "read"),
    "read_pdf": ("file", "read"),
    "read_docx": ("file", "read"),
    "read_spreadsheet": ("file", "read"),
    "read_image_text": ("file", "read"),
    "read_pdf_ocr": ("file", "read"),
    # Directory read
    "list_files": ("directory", "read_directory"),
    # Text transform
    "semantic_transform": ("compute", "compute_only"),
    # Web read
    "read_webpage": ("url", "external_read"),
    # Finalization / no resource
    "finalize_output": ("compute", "no_resource"),
    # Arithmetic / compute only
    "add_numbers": ("compute", "compute_only"),
    "subtract_numbers": ("compute", "compute_only"),
    "multiply_numbers": ("compute", "compute_only"),
    "divide_numbers": ("compute", "compute_only"),
    "square_number": ("compute", "compute_only"),
    "cube_number": ("compute", "compute_only"),
    "square_root": ("compute", "compute_only"),
    "factorial": ("compute", "compute_only"),
    "fibonacci": ("compute", "compute_only"),
    "bad_add": ("compute", "compute_only"),
    "broken_add": ("compute", "compute_only"),
    "broken_syntax_tool": ("compute", "compute_only"),
    "crash_tool": ("compute", "compute_only"),
    "test_valid_add": ("compute", "compute_only"),
    "multiply_string": ("compute", "compute_only"),
    # File mutation (available as tools, though no capability compiler emits them yet)
    "write_file": ("file", "write"),
    "edit_file": ("file", "edit"),
    "append_file": ("file", "append"),
    # Search / read-only discovery
    "grep": ("file", "read"),
    "glob": ("directory", "read_directory"),
    # System / environment (conservative)
    "run_system_maintenance": ("system", "write"),
    "health_check_system": ("system", "read"),
    "self_test_system": ("system", "read"),
    "migrate_error_handling": ("system", "write"),
    "inspect_manager_section": ("system", "read"),
    "rebuild_tool_index": ("system", "write"),
    # Web / external
    "web_search": ("url", "external_read"),
    # Code execution
    "run_python": ("compute", "compute_only"),
}

# ---------------------------------------------------------------------------
# Access mode categories for conflict classification
# ---------------------------------------------------------------------------

READ_ONLY_ACCESS_MODES = {
    "read",
    "read_directory",
    "external_read",
    "compute_only",
    "no_resource",
}

MUTATING_ACCESS_MODES = {
    "write",
    "edit",
    "append",
    "delete",
}

CONSERVATIVE_ACCESS_MODES = {
    "unknown",
}


def _extract_tool_name_from_tool_call(tool_call: Optional[str]) -> Optional[str]:
    """Extract tool name from a tool_call string like 'USE_TOOL: read_file path'."""
    if not tool_call or not isinstance(tool_call, str):
        return None
    # Format: "USE_TOOL: tool_name args..."
    if tool_call.startswith("USE_TOOL:"):
        parts = tool_call.replace("USE_TOOL:", "").strip().split()
        if parts:
            return parts[0]
    # Try generic format: just the tool name at start
    parts = tool_call.strip().split()
    if parts:
        return parts[0]
    return None


def resolve_step_access(step: dict) -> dict:
    """
    Resolve access mode metadata for a step.

    Resolution order (most specific first):
    1. capability_metadata["allowed_tool"] — capability-emitted workflows
    2. tool_call string — post-tool-selection / pre-execution
    3. step type fallback — ANALYZE/RESEARCH/etc. treated as read-only
    4. unknown/conservative

    Returns:
        {
            "target_type": str,   # file | directory | url | domain | compute | system | unknown
            "access_mode": str,   # read | read_directory | external_read | write | edit |
                                  # append | delete | compute_only | no_resource | unknown
            "source": str,        # capability_compiler | tool_identity_mapping |
                                  # structured_tool_args | step_type_fallback | unknown
        }
    """
    # 1. capability_metadata.allowed_tool (capability-emitted workflows)
    cap_meta = step.get("capability_metadata", {})
    allowed_tool = cap_meta.get("allowed_tool")
    if allowed_tool and allowed_tool in TOOL_ACCESS_MAP:
        target_type, access_mode = TOOL_ACCESS_MAP[allowed_tool]
        return {
            "target_type": target_type,
            "access_mode": access_mode,
            "source": "capability_compiler",
        }

    # 2. tool_call string (post-tool-selection)
    tool_call = step.get("tool_call")
    tool_name = _extract_tool_name_from_tool_call(tool_call)
    if tool_name and tool_name in TOOL_ACCESS_MAP:
        target_type, access_mode = TOOL_ACCESS_MAP[tool_name]
        return {
            "target_type": target_type,
            "access_mode": access_mode,
            "source": "tool_identity_mapping",
        }

    # 3. step type fallback
    step_type = step.get("type", "EXECUTE_API")
    read_only_step_types = {"ANALYZE", "RESEARCH", "VALIDATE", "PLAN", "PROPOSE", "GENERATE"}
    if step_type in read_only_step_types:
        return {
            "target_type": "unknown",
            "access_mode": "read",  # read-only step type = safe parallel
            "source": "step_type_fallback",
        }

    # 4. unknown / conservative
    return {
        "target_type": "unknown",
        "access_mode": "unknown",
        "source": "unknown",
    }


def is_read_only_access(access_mode: str) -> bool:
    """Return True if access mode is read-only (no mutation)."""
    return access_mode in READ_ONLY_ACCESS_MODES


def is_mutating_access(access_mode: str) -> bool:
    """Return True if access mode modifies the target resource."""
    return access_mode in MUTATING_ACCESS_MODES


def is_unknown_access(access_mode: str) -> bool:
    """Return True if access mode is unknown (requires conservative treatment)."""
    return access_mode in CONSERVATIVE_ACCESS_MODES


def classify_conflict_severity(
    access_mode_a: str,
    access_mode_b: str,
) -> str:
    """
    Classify conflict severity based on resolved access modes of two steps.

    Per SPRINT-11C Phase 2 approved conflict semantics:
    - No mutation conflict: read+read, read_directory+read_directory,
      external_read+external_read, compute_only/no_resource.
    - Conflict or conservative ordering: read+write/edit/append,
      write/write, append/append, edit+read, unknown+known mutating,
      unknown+unknown.
    - Unknown/missing access remains conservative.

    Returns: "LOW" | "MEDIUM" | "HIGH"
    """
    # no_resource means no concrete resource exists → no mutation conflict
    if access_mode_a == "no_resource" or access_mode_b == "no_resource":
        return "LOW"

    # Unknown access is always conservative
    if access_mode_a == "unknown" or access_mode_b == "unknown":
        return "MEDIUM"

    # Both read-only → LOW (safe parallel)
    if is_read_only_access(access_mode_a) and is_read_only_access(access_mode_b):
        return "LOW"

    # Any mutating access involved → MEDIUM
    # (write, edit, append, delete with anything that has a shared resource)
    if is_mutating_access(access_mode_a) or is_mutating_access(access_mode_b):
        # If both are mutating, it could be HIGH, but MEDIUM is the baseline
        # for EXECUTE_API-level mutation. HIGH is reserved for destructive
        # step types (EXECUTE_FILE, EXECUTE_INSTALL, etc.) handled separately.
        return "MEDIUM"

    # Fallback: anything not explicitly categorized → conservative MEDIUM
    return "MEDIUM"

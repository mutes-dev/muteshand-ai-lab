"""Capability Registry — Metadata/lookup/factory surface only.

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 8:
- Read-only configuration surface at runtime
- Does NOT execute, manage state, schedule, or coordinate agents
- Does NOT own lifecycle, execution, governance, persistence, projection, or learning
"""

from typing import Any


# === REGISTERED CAPABILITIES (AGENT-001B Phase 1) ===
# Only arithmetic capability is registered in this slice.
# Future capabilities require explicit contract amendment and Head Dev approval.

_CAPABILITY_ENTRIES = {
    "arithmetic": {
        "capability_id": "arithmetic",
        "capability_name": "Arithmetic Capability",
        "domain": "arithmetic",
        "supported_intents": [
            "add", "sum", "plus",
            "subtract", "minus", "difference",
            "multiply", "times", "product",
            "divide", "division", "quotient",
            "square", "cube", "square root",
            "factorial", "fibonacci",
            "calculate", "compute",
        ],
        "route_confidence_policy": "deterministic_keyword_match",
        "normalizer_or_compiler_entrypoint": "system.orchestrator.capabilities.arithmetic_capability:compile_arithmetic_workflow",
        "allowed_tool_families": ["math"],
        "allowed_tools": [
            "add_numbers",
            "subtract_numbers",
            "multiply_numbers",
            "divide_numbers",
            "square_number",
            "cube_number",
            "square_root",
            "factorial",
            "fibonacci",
        ],
        "risk_flags": [],
        "fallback_behavior": "ROUTE_FALLBACK_TO_PLANNER",
        "observability_label": "Arithmetic",
        "contract_version": "AGENT_CAPABILITY_ROUTING_CONTRACT_V1",
    },
    "document_local_read": {
        "capability_id": "document_local_read",
        "capability_name": "Read-Only Document / Local-File Capability",
        "domain": "document_local_read",
        "supported_intents": [
            "read file", "show file", "open file", "display file", "view file",
            "summarize file", "summary of file",
            "list files", "show files", "list folder", "show folder",
            "files in", "contents of",
        ],
        "route_confidence_policy": "deterministic_keyword_match_with_explicit_path",
        "normalizer_or_compiler_entrypoint": "system.orchestrator.capabilities.document_local_read_capability:compile_document_local_read_workflow",
        "allowed_tool_families": ["file_read", "text_finalization"],
        "allowed_tools": [
            "read_file",
            "list_files",
            "finalize_output",
        ],
        "risk_flags": ["path_traversal_guard", "literal_preservation_required", "read_only_only"],
        "fallback_behavior": "ROUTE_FALLBACK_TO_PLANNER",
        "observability_label": "DocumentLocalRead",
        "contract_version": "AGENT_CAPABILITY_ROUTING_CONTRACT_V1",
    },
}


def get_capability(capability_id: str) -> dict | None:
    """Return capability metadata entry by ID, or None if not registered."""
    return _CAPABILITY_ENTRIES.get(capability_id)


def list_capabilities() -> list[dict]:
    """Return list of all registered capability metadata entries."""
    return list(_CAPABILITY_ENTRIES.values())


def get_registered_capabilities() -> dict[str, dict]:
    """Return shallow copy of the full registered capabilities mapping."""
    return dict(_CAPABILITY_ENTRIES)

"""Capability Registry — Metadata/lookup/factory surface only.

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 8:
- Read-only configuration surface at runtime
- Does NOT execute, manage state, schedule, or coordinate agents
- Does NOT own lifecycle, execution, governance, persistence, projection, or learning
"""

from typing import Any


# === REGISTERED CAPABILITIES (AGENT-001B Phase 1 + AGENT-001E + AGENT-001G) ===
# Only arithmetic, document_local_read, and web_read are registered.
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
            "summarize file", "summary of file", "explain file", "explain what is in file",
            "extract key points from file",
            "list files", "show files", "list folder", "show folder",
            "files in", "contents of",
            "preview table schema", "preview schema", "table schema",
            "resolve table reference", "resolve cell", "resolve row",
        ],
        "route_confidence_policy": "deterministic_keyword_match_with_explicit_path",
        "normalizer_or_compiler_entrypoint": "system.orchestrator.capabilities.document_local_read_capability:compile_document_local_read_workflow",
        "allowed_tool_families": ["file_read", "text_finalization"],
        "allowed_tools": [
            "read_file",
            "read_csv",
            "read_pdf",
            "read_docx",
            "read_spreadsheet",
            "read_image_text",
            "read_pdf_ocr",
            "list_files",
            "preview_table_schema",
            "resolve_table_reference",
            "finalize_output",
            # semantic_transform is consumed via AG1 shortcut, not directly emitted by compiler
        ],
        "risk_flags": ["path_traversal_guard", "literal_preservation_required", "read_only_only"],
        "fallback_behavior": "ROUTE_FALLBACK_TO_PLANNER",
        "observability_label": "DocumentLocalRead",
        "contract_version": "AGENT_CAPABILITY_ROUTING_CONTRACT_V1",
    },
    "web_read": {
        "capability_id": "web_read",
        "capability_name": "Web Page Read Capability",
        "domain": "web_read",
        "supported_intents": [
            "read webpage", "show webpage", "open webpage", "display webpage", "view webpage",
            "fetch webpage", "summarize webpage", "get webpage", "explain webpage",
            "explain url", "explain website", "explain page", "explain site",
            "extract key points from webpage", "extract key points from url",
            "read url", "read website", "read page", "read site",
            "read http", "read https",
        ],
        "route_confidence_policy": "deterministic_keyword_match_with_explicit_url",
        "normalizer_or_compiler_entrypoint": "system.orchestrator.capabilities.web_read_capability:compile_web_read_workflow",
        "allowed_tool_families": ["web_read", "text_finalization"],
        "allowed_tools": [
            "read_webpage",
            "finalize_output",
        ],
        "risk_flags": ["literal_preservation_required", "read_only_only", "external_call_user_control"],
        "fallback_behavior": "ROUTE_FALLBACK_TO_PLANNER",
        "observability_label": "WebRead",
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

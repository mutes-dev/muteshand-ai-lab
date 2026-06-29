"""Document Local Read Capability — Deterministic read-only file/folder detector/compiler.

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 10A:
- High-confidence explicit local-file read/list/summarize/explain detection only
- No LLM. No system_entry import. No execution.
- Emits explicit candidate workflow/DAG with depends_on.
- Fallback for ambiguous, mutation, mixed-domain, grep/glob, multi-file, unsupported final actions.

Supported deterministic DAG shapes:
- read_file -> finalize_output  (present mode)
- read_file -> finalize_output  (summarize/explain/extract_key_points mode)
- list_files -> finalize_output  (present mode)
- No grep/glob/multi-file.
"""

import re
from typing import Any


# === Mutation detection — conservative fallback keywords ===
_MUTATION_KEYWORDS = frozenset([
    "write", "edit", "append", "delete", "remove", "erase", "create file",
    "save", "update", "modify", "overwrite", "replace file",
])

# === Mixed-domain detection — conservative fallback keywords ===
_MIXED_DOMAIN_KEYWORDS = frozenset([
    "web", "website", "url", "http", "https", "internet", "browse",
    "download", "upload", "email", "send mail", "calendar", "schedule",
    "api", "external", "search the web", "google", "online",
    "add ", "plus ", "subtract ", "minus ", "multiply ", "divide ",
    "calculate", "compute", "square root", "factorial", "fibonacci",
])

# === Grep/glob/search detection — first-slice fallback ===
_GREP_GLOB_KEYWORDS = frozenset([
    "grep", "search for", "search within", "find pattern", "match pattern",
    "glob", "match files", "find all files", "list matching", "files matching",
    "search in", "search files for", "regex", "regular expression",
    "find all", "all .py", "all .txt", "all .json", "all .md",
])

# === Read-file intent patterns ===
# Each entry: (regex, has_path_group: bool)
# Ordered by specificity (most specific first).
_READ_FILE_PATTERNS = [
    # Read/show/open/display the file "path" / 'path'
    (re.compile(r'(?:read|show|open|display|view)\s+(?:the\s+)?(?:file\s+)?["\']([^"\']+)["\']', re.IGNORECASE), True),
    # Read/show/open/display file "path" / 'path'
    (re.compile(r'(?:read|show|open|display|view)\s+(?:the\s+)?(?:contents\s+of\s+)?["\']([^"\']+)["\']', re.IGNORECASE), True),
    # Read/show/open/display path (unquoted, with extension)
    # Handles: "Show me the contents of config.json", "Read tmp/file.txt"
    (re.compile(r'(?:read|show|open|display|view)\s+(?:me\s+)?(?:the\s+)?(?:contents\s+of\s+)?(?:file\s+)?([a-zA-Z0-9_./\\~-]+\.[a-zA-Z0-9]{1,10})', re.IGNORECASE), True),
]

# === List-files intent patterns ===
_LIST_FILES_PATTERNS = [
    # List files in "folder" / 'folder'
    (re.compile(r'(?:list|show)\s+(?:the\s+)?(?:files\s+in|contents\s+of|files\s+inside)\s+["\']([^"\']+)["\']', re.IGNORECASE), True),
    # List files in the folder "folder" / 'folder'
    (re.compile(r'(?:list|show)\s+(?:the\s+)?(?:files\s+in|contents\s+of|files\s+inside)\s+(?:the\s+(?:folder|directory)\s+)?["\']([^"\']+)["\']', re.IGNORECASE), True),
    # List files in the folder X (unquoted)
    (re.compile(r'(?:list|show)\s+(?:the\s+)?(?:files\s+in|contents\s+of|files\s+inside)\s+(?:the\s+(?:folder|directory)\s+)?([a-zA-Z0-9_./\\~-]+)', re.IGNORECASE), True),
    # List the folder "folder"
    (re.compile(r'(?:list|show)\s+(?:the\s+)?(?:folder|directory)\s+["\']([^"\']+)["\']', re.IGNORECASE), True),
    # List the folder X (unquoted)
    (re.compile(r'(?:list|show)\s+(?:the\s+)?(?:folder|directory)\s+([a-zA-Z0-9_./\\~-]+)', re.IGNORECASE), True),
    # Files in "folder"
    (re.compile(r'(?:files|contents)\s+(?:in|inside|of)\s+["\']([^"\']+)["\']', re.IGNORECASE), True),
    # Files in the folder X (unquoted)
    (re.compile(r'(?:files|contents)\s+(?:in|inside|of)\s+(?:the\s+(?:folder|directory)\s+)?([a-zA-Z0-9_./\\~-]+)', re.IGNORECASE), True),
]

# === Vague/ambiguous fallback patterns ===
_AMBIGUOUS_FILE_REFERENCES = frozenset([
    "the file", "that file", "this file", "a file", "some file",
])

# === Supported transform actions ===
# These are handled by explicit transform workflows, not by unsupported fallback.
_TRANSFORM_FILE_ACTIONS = {
    "summarize": re.compile(
        r"\b(?:summarize|summarise|summary\s+of|give\s+me\s+a\s+summary\s+of)\b",
        re.IGNORECASE,
    ),
    "explain": re.compile(
        r"\b(?:explain|explain\s+what\s+is\s+in)\b",
        re.IGNORECASE,
    ),
    "extract_key_points": re.compile(
        r"\b(?:extract\s+key\s+points\s+from)\b",
        re.IGNORECASE,
    ),
}

# === Unsupported final action detection ===
# compare/analyze/fact-check remain deferred; summarize/explain/extract are now supported.
_UNSUPPORTED_FINAL_ACTION_RE = re.compile(
    r"\b(?:compare|comparison\s+of|analyze|analyse|analysis\s+of|fact-check|fact\s+check)\b",
    re.IGNORECASE,
)


# === File-prompt heuristic for router fallback labeling ===
_FILE_PROMPT_TOKENS = frozenset([
    "file", "folder", "directory", "read the file", "show the file",
    "open the file", "display the file", "view the file", "list files",
    "show files", "files in", "contents of", "list the folder",
    "show the folder", "list the directory", "show the directory",
    ".txt", ".md", ".json", ".py", ".csv", ".log", ".xml", ".yml", ".yaml",
])


def _is_file_mutation(text: str) -> bool:
    """Return True if prompt contains file mutation keywords."""
    lower = text.lower()
    return any(kw in lower for kw in _MUTATION_KEYWORDS)


def _is_mixed_domain(text: str) -> bool:
    """Return True if prompt contains mixed-domain keywords."""
    lower = text.lower()
    return any(kw in lower for kw in _MIXED_DOMAIN_KEYWORDS)


def _is_grep_glob_request(text: str) -> bool:
    """Return True if prompt asks for grep/glob/search within files (first-slice fallback)."""
    lower = text.lower()
    return any(kw in lower for kw in _GREP_GLOB_KEYWORDS)


def _is_ambiguous_file_reference(text: str) -> bool:
    """Return True if prompt contains vague file references without explicit path."""
    lower = text.lower()
    # Only trigger if ambiguous phrase exists AND no explicit path with extension found
    has_ambiguous = any(kw in lower for kw in _AMBIGUOUS_FILE_REFERENCES)
    if not has_ambiguous:
        return False
    # Check if an explicit file path with extension exists
    has_explicit_path = bool(re.search(r'[a-zA-Z0-9_./\\~-]+\.[a-zA-Z0-9]{1,10}', text))
    return not has_explicit_path


def _has_unsupported_final_action(text: str) -> bool:
    return bool(_UNSUPPORTED_FINAL_ACTION_RE.search(text))


def _unsupported_final_action_reason(text: str) -> str:
    return "fallback_unsupported_final_action"


def _detect_transform_file_action(text: str) -> str | None:
    """Return supported transform action (summarize/explain/extract_key_points) if present."""
    for action, pattern in _TRANSFORM_FILE_ACTIONS.items():
        if pattern.search(text):
            return action
    return None


def _extract_transform_file_path(text: str, action: str) -> str | None:
    """Extract explicit file path from a transform-intent prompt for the given action."""
    if action not in _TRANSFORM_FILE_ACTIONS:
        return None
    verb_pattern = _TRANSFORM_FILE_ACTIONS[action].pattern
    # Quoted path
    quoted = re.compile(
        rf"(?:{verb_pattern})\s+(?:the\s+)?(?:file\s+)?[\"\']([^\"\']+)[\"\']",
        re.IGNORECASE,
    )
    m = quoted.search(text)
    if m:
        path = m.group(1).strip()
        if path:
            return path
    # Unquoted path with extension
    unquoted = re.compile(
        rf"(?:{verb_pattern})\s+(?:the\s+)?(?:file\s+)?([a-zA-Z0-9_./\\~-]+\.[a-zA-Z0-9]{1,10})",
        re.IGNORECASE,
    )
    m = unquoted.search(text)
    if m:
        path = m.group(1).strip()
        if path:
            return path
    return None


def is_document_local_prompt(user_input: str) -> bool:
    """Return True if prompt is plausibly local-file-related (for router fallback labeling)."""
    if not user_input or not isinstance(user_input, str):
        return False
    lower = user_input.lower()
    return any(kw in lower for kw in _FILE_PROMPT_TOKENS)


def detect_document_local_read_fallback_reason(user_input: str) -> str:
    """Return a specific fallback reason code for a non-routed local-file prompt.

    This is advisory metadata only; the route decision remains the authority.
    """
    if not user_input or not isinstance(user_input, str):
        return "fallback_missing_explicit_file_path"

    if _is_file_mutation(user_input):
        return "fallback_unsupported_operation"

    if _is_mixed_domain(user_input):
        return "fallback_mixed_domain"

    if _is_grep_glob_request(user_input):
        return "fallback_grep_glob_not_supported"

    if _is_ambiguous_file_reference(user_input):
        return "fallback_ambiguous_file_reference"

    if _has_unsupported_final_action(user_input):
        return _unsupported_final_action_reason(user_input)

    if not _extract_read_file_path(user_input) and not _extract_list_files_folder(user_input):
        return "fallback_missing_explicit_file_path"

    return "fallback_unsupported_operation"


def _extract_read_file_path(text: str) -> str | None:
    """Extract explicit file path from a read-file intent prompt."""
    for pattern, has_group in _READ_FILE_PATTERNS:
        m = pattern.search(text)
        if m and has_group:
            path = m.group(1).strip()
            if path:
                return path
    return None


def _extract_list_files_folder(text: str) -> str | None:
    """Extract explicit folder path from a list-files intent prompt."""
    for pattern, has_group in _LIST_FILES_PATTERNS:
        m = pattern.search(text)
        if m and has_group:
            path = m.group(1).strip()
            if path:
                return path
    return None


def _build_read_file_workflow(user_input: str, file_path: str) -> dict:
    """Build a read_file -> finalize_output candidate workflow."""
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Read local file",
        "purpose": f"Read the local file \"{file_path}\"",
        "expected_outcome": "File contents retrieved",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",  # semantic label only, not execution authority
        "depends_on": [],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_explicit_read_file",
            "allowed_tool_family": "file_read",
            "allowed_tool": "read_file",
        },
        # Do not prepopulate tool_call for file tools (route_prepopulation_allowed=false)
    }

    step_2 = {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": "Present file contents",
        "purpose": "Present the file contents from step_1",
        "expected_outcome": "Result shown",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": ["step_1"],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_explicit_read_file",
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": "present",
            "intent_mode": "present",
            "transform_required": False,
        },
    }

    return {
        "id": None,  # set by caller from pre_generated_workflow_id
        "name": "document_local_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1, step_2],
        "approval_required": False,
    }


def _build_transform_file_workflow(
    user_input: str,
    file_path: str,
    final_action: str,
    intent_mode: str,
    purpose_template: str,
) -> dict:
    """Build a read_file -> finalize_output candidate workflow for a transform final action."""
    route_reason_code = f"accepted_explicit_{final_action}_file"
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Read local file",
        "purpose": f"Read the local file \"{file_path}\"",
        "expected_outcome": "File contents retrieved",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": [],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": route_reason_code,
            "allowed_tool_family": "file_read",
            "allowed_tool": "read_file",
        },
    }

    step_2 = {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": f"{final_action.replace('_', ' ').title()} file contents",
        "purpose": purpose_template,
        "expected_outcome": "Result shown",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": ["step_1"],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": route_reason_code,
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": final_action,
            "intent_mode": intent_mode,
            "transform_required": True,
        },
    }

    return {
        "id": None,
        "name": "document_local_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1, step_2],
        "approval_required": False,
    }


def _build_list_files_workflow(user_input: str, folder_path: str) -> dict:
    """Build a list_files -> finalize_output candidate workflow."""
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "List local files",
        "purpose": f"List files in the local folder \"{folder_path}\"",
        "expected_outcome": "File listing retrieved",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": [],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_explicit_list_files",
            "allowed_tool_family": "file_read",
            "allowed_tool": "list_files",
        },
    }

    step_2 = {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": "Present file listing",
        "purpose": "Present the file listing from step_1",
        "expected_outcome": "Result shown",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": ["step_1"],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_explicit_list_files",
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": "present",
            "intent_mode": "list",
            "transform_required": False,
        },
    }

    return {
        "id": None,
        "name": "document_local_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1, step_2],
        "approval_required": False,
    }


def compile_document_local_read_workflow(user_input: str, route_metadata: dict | None = None) -> dict | None:
    """
    Compile a high-confidence explicit read-only local-file prompt into a candidate workflow.

    Returns workflow dict compatible with validate_workflow,
    or None if prompt should fall back to planner.

    Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 10A:
    - No LLM calls
    - No system_entry import
    - Explicit DAG emission with depends_on
    - Exact literal preservation for file/folder paths
    """
    if not user_input or not isinstance(user_input, str):
        return None

    # === FAIL-SAFE CHECKS ===
    if _is_file_mutation(user_input):
        return None
    if _is_mixed_domain(user_input):
        return None
    if _is_grep_glob_request(user_input):
        return None
    if _is_ambiguous_file_reference(user_input):
        return None

    # === Supported transform file intents (summarize/explain/extract_key_points) ===
    transform_action = _detect_transform_file_action(user_input)
    if transform_action:
        transform_path = _extract_transform_file_path(user_input, transform_action)
        if transform_path:
            purpose_templates = {
                "summarize": "Summarize the file contents from step_1",
                "explain": "Explain the file contents from step_1",
                "extract_key_points": "Extract key points from the file contents from step_1",
            }
            return _build_transform_file_workflow(
                user_input,
                transform_path,
                transform_action,
                transform_action,
                purpose_templates[transform_action],
            )
        # Transform verb present but no explicit path → fall back to planner
        return None

    # === Unsupported final actions (compare/analyze/fact-check) ===
    if _has_unsupported_final_action(user_input):
        return None

    # === Try read_file intent ===
    file_path = _extract_read_file_path(user_input)
    if file_path:
        return _build_read_file_workflow(user_input, file_path)

    # === Try list_files intent ===
    folder_path = _extract_list_files_folder(user_input)
    if folder_path:
        return _build_list_files_workflow(user_input, folder_path)

    # === No matching explicit intent ===
    return None

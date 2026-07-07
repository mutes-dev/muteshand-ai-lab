"""
Tool Profile Selector — TOOL_PROFILE_GATING_CONTRACT_V1 §4

Deterministic profile selection based on user input keywords.

Selection order (first match wins):
0. Mixed-domain workflow (file+web, compute+write, etc.) -> GeneralFallbackProfile
1. Explicit file write/edit/append -> FileMutationProfile
2. Explicit summarize/explain/extract_key_points -> DocumentSummaryProfile
3. Explicit URL read -> WebReadProfile
4. Unsupported document Q&A/analysis -> GeneralFallbackProfile
5. Pure arithmetic/computation -> ComputeProfile
6. Explicit file read/list -> DocumentReadProfile
7. Uncertain or mixed-domain -> GeneralFallbackProfile

This module does NOT:
- Override planner authority
- Execute tools
- Influence lifecycle/governance/execution_result
"""

import re
from typing import Optional


_URL_PATTERN = re.compile(r'https?://', re.IGNORECASE)

_FILE_WRITE_KEYWORDS = [
    "write file", "create file", "write to", "save to file",
    "edit file", "update file", "replace in file", "modify file",
    "append to file", "append file", "add to file", "add a line",
    "write ' ", 'write "', "overwrite file",
]

_FILE_WRITE_PATTERNS = re.compile(
    r'\b(write|edit|append|create|overwrite|save)\b.*\.(txt|py|js|json|csv|md|html|xml|yaml|yml|cfg|ini|log|tsv)',
    re.IGNORECASE,
)

_FILE_READ_KEYWORDS = [
    "read file", "show file", "open file", "display file", "view file",
    "list files", "show files", "list folder", "show folder",
    "files in", "contents of", "read csv", "read pdf", "read docx",
    "read spreadsheet", "read image", "read xlsx",
]

_FILE_READ_PATTERNS = re.compile(
    r'\b(read|show|open|display|view|list)\b.*\.(txt|py|js|json|csv|md|html|xml|yaml|yml|cfg|ini|log|tsv|pdf|docx|xlsx|png|jpg|jpeg)',
    re.IGNORECASE,
)

_SUMMARY_KEYWORDS = [
    "summarize", "summary of", "explain", "extract key points",
    "key points from", "extract_key_points",
]

_ARITHMETIC_KEYWORDS = [
    "add", "sum", "plus", "subtract", "minus", "difference",
    "multiply", "times", "product", "divide", "division", "quotient",
    "square", "cube", "square root", "factorial", "fibonacci",
    "calculate", "compute",
]

# === Document Q&A / analysis intent detection ===
# These patterns detect unsupported document Q&A or analysis prompts
# that should NOT select DocumentReadProfile or ComputeProfile.
# They are checked AFTER supported profiles (FileMutation, DocumentSummary, WebRead)
# and BEFORE ComputeProfile/DocumentReadProfile.
_DOCUMENT_QA_ANALYSIS_RE = re.compile(
    r'\b(?:tell\s+me|what\s+(?:is|are|was|were)|what\'s|'
    r'who\s+(?:has|is|are|was)|where\s+(?:is|are)|'
    r'how\s+(?:big|much|many|long|tall|wide|far|old)|'
    r'highest\s+\w+|lowest\s+\w+)',
    re.IGNORECASE,
)

_CALCULATE_WITH_FILE_RE = re.compile(
    r'\bcalculate\b.*\.(?:csv|xlsx|xls|tsv|pdf|docx|txt)',
    re.IGNORECASE,
)

# === Mixed-domain workflow detection ===
# Keywords that indicate web/search intent alongside file/compute intent.
_MIXED_WEB_KEYWORDS = [
    "search the web", "search online", "web search", "google",
    "browse the web", "find more info", "find more information",
    "search the internet", "look up online", "find info online",
    "search for more", "search for related",
]


def _matches_any(text: str, keywords: list) -> bool:
    text_lower = text.lower()
    for kw in keywords:
        if kw in text_lower:
            return True
    return False


def _matches_write_pattern(text: str) -> bool:
    return bool(_FILE_WRITE_PATTERNS.search(text))


def _matches_read_pattern(text: str) -> bool:
    return bool(_FILE_READ_PATTERNS.search(text))


def _has_document_qa_or_analysis_intent(text: str) -> bool:
    """Detect unsupported document Q&A or analysis intent in user input."""
    if _DOCUMENT_QA_ANALYSIS_RE.search(text):
        return True
    if _CALCULATE_WITH_FILE_RE.search(text):
        return True
    return False


def _is_mixed_domain_workflow(text: str) -> bool:
    """Detect prompts that span multiple tool domains (e.g. file read + web, compute + file write).

    Returns True when the prompt has indicators from 2+ different tool domains,
    meaning a single narrow profile would block legitimate steps.
    """
    text_lower = text.lower()

    has_file_read = _matches_read_pattern(text) or _matches_any(text, _FILE_READ_KEYWORDS)
    has_file_write = _matches_any(text, _FILE_WRITE_KEYWORDS) or _matches_write_pattern(text)
    has_url = bool(_URL_PATTERN.search(text))
    has_web_search = any(kw in text_lower for kw in _MIXED_WEB_KEYWORDS)
    has_compute = _matches_any(text, _ARITHMETIC_KEYWORDS)

    # File read + web search = mixed
    if has_file_read and has_web_search:
        return True

    # Compute + file mutation = mixed
    if has_compute and has_file_write:
        return True

    # File mutation + web = mixed
    if has_file_write and (has_web_search or has_url):
        return True

    # File read + URL — only mixed if there is a local file path outside the URL
    if has_url and has_file_read:
        text_without_urls = _URL_PATTERN.sub("", text)
        if _matches_read_pattern(text_without_urls) or _matches_any(text_without_urls, _FILE_READ_KEYWORDS):
            return True

    return False


def select_profile(user_input: str) -> str:
    """
    Deterministically select a tool profile based on user input.

    Args:
        user_input: Raw user input string.

    Returns:
        Profile name string (one of the defined profiles).
    """
    if not user_input or not isinstance(user_input, str):
        return "GeneralFallbackProfile"

    # 0. Mixed-domain workflow — check before single-domain profiles
    if _is_mixed_domain_workflow(user_input):
        return "GeneralFallbackProfile"

    # 1. File mutation — check first since write/edit are explicit
    if _matches_any(user_input, _FILE_WRITE_KEYWORDS) or _matches_write_pattern(user_input):
        return "FileMutationProfile"

    # 2. Summary/explain/extract — before plain read since these imply synthesis
    if _matches_any(user_input, _SUMMARY_KEYWORDS):
        return "DocumentSummaryProfile"

    # 3. URL read
    if _URL_PATTERN.search(user_input):
        return "WebReadProfile"

    # 4. Unsupported document Q&A / analysis — before compute/read
    if _has_document_qa_or_analysis_intent(user_input):
        return "GeneralFallbackProfile"

    # 5. Pure arithmetic/computation
    if _matches_any(user_input, _ARITHMETIC_KEYWORDS):
        return "ComputeProfile"

    # 6. Explicit file read/list
    if _matches_any(user_input, _FILE_READ_KEYWORDS) or _matches_read_pattern(user_input):
        return "DocumentReadProfile"

    # 7. Fallback
    return "GeneralFallbackProfile"


def select_profile_with_reason(user_input: str) -> dict:
    """
    Select a profile and return metadata with reason code.

    Returns:
        Dict with keys: profile_name, profile_reason_code
    """
    if not user_input or not isinstance(user_input, str):
        return {
            "profile_name": "GeneralFallbackProfile",
            "profile_reason_code": "empty_input",
        }

    if _is_mixed_domain_workflow(user_input):
        return {
            "profile_name": "GeneralFallbackProfile",
            "profile_reason_code": "mixed_domain_workflow",
        }

    if _matches_any(user_input, _FILE_WRITE_KEYWORDS) or _matches_write_pattern(user_input):
        return {
            "profile_name": "FileMutationProfile",
            "profile_reason_code": "explicit_file_mutation",
        }

    if _matches_any(user_input, _SUMMARY_KEYWORDS):
        return {
            "profile_name": "DocumentSummaryProfile",
            "profile_reason_code": "explicit_summarize_explain_extract",
        }

    if _URL_PATTERN.search(user_input):
        return {
            "profile_name": "WebReadProfile",
            "profile_reason_code": "explicit_url_read",
        }

    if _has_document_qa_or_analysis_intent(user_input):
        return {
            "profile_name": "GeneralFallbackProfile",
            "profile_reason_code": "unsupported_document_qa_or_analysis",
        }

    if _matches_any(user_input, _ARITHMETIC_KEYWORDS):
        return {
            "profile_name": "ComputeProfile",
            "profile_reason_code": "pure_arithmetic_computation",
        }

    if _matches_any(user_input, _FILE_READ_KEYWORDS) or _matches_read_pattern(user_input):
        return {
            "profile_name": "DocumentReadProfile",
            "profile_reason_code": "explicit_file_read_list",
        }

    return {
        "profile_name": "GeneralFallbackProfile",
        "profile_reason_code": "uncertain_mixed_domain",
    }


def capability_to_profile(capability_id: Optional[str]) -> Optional[str]:
    """
    Map a capability router capability_id to a recommended profile.

    Returns None if no mapping exists.
    """
    _CAPABILITY_PROFILE_MAP = {
        "arithmetic": "ComputeProfile",
        "document_local_read": "DocumentReadProfile",
        "web_read": "WebReadProfile",
    }
    if not capability_id:
        return None
    return _CAPABILITY_PROFILE_MAP.get(capability_id)

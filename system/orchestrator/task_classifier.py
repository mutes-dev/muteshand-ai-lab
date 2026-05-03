"""
Task Classifier — Phase 2.1 Implementation

PURE CLASSIFICATION MODULE — ADVISORY ONLY

Responsibilities:
- Classify user input into task categories
- Recommend autonomy levels
- Suggest approval requirements

Constraints:
- MUST NOT control execution
- MUST NOT integrate into runtime
- MUST NOT call system_entry
- MUST NOT execute tools
- PURE FUNCTION ONLY

Architecture:
- Primary: Rule-based classification (deterministic)
- Optional: LLM-assisted (future extension)
- Output: Structured recommendation (not binding)
"""

from typing import Dict, Any


# CRITICAL keywords — ALWAYS require approval
CRITICAL_KEYWORDS = [
    "delete", "remove", "overwrite", "wipe", "erase", "destroy",
    "install", "uninstall", "setup", "configure system",
    "external", "api", "webhook", "callback", "http", "https",
    "execute system command", "run shell", "bash", "powershell",
    "sudo", "admin", "root", "chmod", "chown",
    "rm -rf", "format", "fdisk", "diskpart"
]

# COMPLEX keywords — Analysis/planning tasks
COMPLEX_KEYWORDS = [
    "build", "create", "develop", "implement", "design",
    "analyze", "analysis", "evaluate", "assess",
    "generate", "synthesize", "compile",
    "plan", "strategy", "roadmap", "architecture",
    "research", "investigate", "explore",
    "refactor", "restructure", "migrate"
]

# SIMPLE indicators — Direct operations (checked if no critical/complex found)
SIMPLE_INDICATORS = [
    "add", "sum", "plus", "+",
    "subtract", "minus", "-",
    "multiply", "times", "*",
    "divide", "/", "divided by",
    "square", "cube", "root",
    "calculate", "compute", "solve",
    "read", "show", "display", "list", "get",
    "write", "save", "store"
]


def _normalize_input(user_input: str) -> tuple:
    """
    Normalize input: lowercase, strip, remove punctuation, extract words.
    
    Returns: (normalized_string, words_list)
    """
    # Lowercase and strip
    text = user_input.lower().strip()
    
    # Remove basic punctuation
    for char in ".!?,:;\"'()[]{}<>/|\\":
        text = text.replace(char, " ")
    
    # Split into words
    words = [w for w in text.split() if w]
    return text, words


def _word_matches_keyword(word: str, keyword: str) -> bool:
    """
    Check if word matches keyword with boundary checking.
    
    Rules:
    - Exact match: "delete" matches "delete"
    - Word boundary: "delete" matches "deleted" (suffix), "delete-" (compound)
    - No substring match: "delete" does NOT match "deleteLine" or "predelete"
    """
    # Exact match
    if word == keyword:
        return True
    
    # Suffix match: "deleted" contains "delete" + suffix
    if word.startswith(keyword):
        # Word starts with keyword — check it's a valid continuation
        suffix = word[len(keyword):]
        # Valid suffixes: "d", "s", "ed", "ing", "-", "_", digits
        if suffix and suffix[0] in "ds_-0123456789":
            return True
        if suffix in ("ed", "ing", "s", "d"):
            return True
    
    return False


def classify_task(user_input: str) -> Dict[str, Any]:
    """
    Classify user task into category with autonomy and approval recommendations.
    
    PURE FUNCTION — NO side effects, NO execution, NO system calls.
    
    Args:
        user_input: Raw user input string
        
    Returns:
        dict: {
            "classification": "simple" | "complex" | "critical",
            "autonomy_level": "high" | "medium" | "low" | "none",
            "approval_required": bool,
            "reasoning": str,
            "confidence": float  # 0.0 to 1.0
        }
    """
    if not user_input or not isinstance(user_input, str):
        return {
            "classification": "simple",
            "autonomy_level": "high",
            "approval_required": False,
            "reasoning": "Empty or invalid input — defaulting to safe simple classification",
            "confidence": 0.95
        }
    
    # Normalize input: lowercase, strip, remove punctuation, extract words
    normalized, words = _normalize_input(user_input)
    
    # Track matched and ignored keywords for reasoning
    matched_keywords = []
    ignored_keywords = []
    
    # ===== CRITICAL CHECK (Highest Priority) =====
    # Word-boundary matching: check each word against keywords
    for keyword in CRITICAL_KEYWORDS:
        # Handle multi-word keywords (e.g., "execute system command")
        if " " in keyword:
            if keyword in normalized:
                matched_keywords.append(keyword)
        else:
            # Single word: check against all words with boundary matching
            keyword_found = False
            for word in words:
                if _word_matches_keyword(word, keyword):
                    matched_keywords.append(keyword)
                    keyword_found = True
                    break  # Only count keyword once
            # Check if keyword appears but was ignored due to boundary
            if not keyword_found and keyword in normalized:
                ignored_keywords.append(keyword)
    
    if matched_keywords:
        # Build reasoning with matched keywords, optionally note ignored
        unique_matched = set(matched_keywords)
        reasoning = f"CRITICAL keywords detected: {', '.join(unique_matched)}. " \
                   "This task involves destructive operations, external systems, " \
                   "or system-level changes requiring explicit user approval."
        if ignored_keywords:
            reasoning += f" (Note: {', '.join(set(ignored_keywords))} appeared in compound terms and were ignored.)"
        return {
            "classification": "critical",
            "autonomy_level": "none",
            "approval_required": True,
            "reasoning": reasoning,
            "confidence": 0.92  # Top of range 0.9-0.95
        }
    
    # ===== COMPLEX CHECK =====
    # Word-boundary matching for complex keywords
    for keyword in COMPLEX_KEYWORDS:
        if " " in keyword:
            if keyword in normalized:
                matched_keywords.append(keyword)
        else:
            keyword_found = False
            for word in words:
                if _word_matches_keyword(word, keyword):
                    matched_keywords.append(keyword)
                    keyword_found = True
                    break
            if not keyword_found and keyword in normalized:
                ignored_keywords.append(keyword)
    
    if matched_keywords:
        unique_matched = set(matched_keywords)
        reasoning = f"Complex task indicators: {', '.join(unique_matched)}. " \
                   "This task involves multi-step planning, analysis, or creation " \
                   "and requires approval before execution."
        if ignored_keywords:
            reasoning += f" (Note: {', '.join(set(ignored_keywords))} appeared in compound terms and were ignored.)"
        return {
            "classification": "complex",
            "autonomy_level": "medium",
            "approval_required": True,
            "reasoning": reasoning,
            "confidence": 0.75  # Mid-range 0.7-0.8
        }
    
    # ===== SIMPLE FALLBACK =====
    # No keywords matched at all
    if ignored_keywords:
        # Keywords were seen but ignored due to word-boundary rules
        reasoning = f"Keyword(s) '{', '.join(set(ignored_keywords))}' detected within compound terms and ignored due to word-boundary rules. " \
                   "No valid task indicators matched. Defaulting to simple classification."
    else:
        reasoning = "No relevant keywords detected."
    
    return {
        "classification": "simple",
        "autonomy_level": "high",
        "approval_required": False,
        "reasoning": reasoning,
        "confidence": 0.55  # Mid-range 0.5-0.6
    }


# Future extension: LLM-assisted classification (optional, non-blocking)
def classify_task_with_llm(user_input: str, use_llm: bool = False) -> Dict[str, Any]:
    """
    Extended classification with optional LLM assistance.
    
    WARNING: LLM is NON-AUTHORITATIVE. Rule-based result always takes precedence.
    
    Args:
        user_input: Raw user input string
        use_llm: Whether to request LLM assistance (default: False)
        
    Returns:
        dict: Same format as classify_task, with optional LLM reasoning appended
    """
    # ALWAYS get rule-based classification first (primary)
    rule_result = classify_task(user_input)
    
    # If LLM not requested, return rule-based result only
    if not use_llm:
        return rule_result
    
    # LLM assistance is advisory only — does not override rule-based decision
    # This is a placeholder for future LLM integration
    # Current behavior: append LLM note but keep original classification
    
    rule_result["llm_assistance"] = "requested"
    rule_result["llm_note"] = "LLM classification is advisory only. Rule-based result preserved."
    rule_result["reasoning"] += " [LLM assistance requested but not overriding rule-based decision.]"
    
    return rule_result


# Test runner for development/verification

"""
semantic_expectation.py — Semantic Expectation Model (Phase 1)

Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1:
- Semantic expectations are planner-derived, deterministic, lightweight
- Semantic expectations are advisory-only (NO runtime authority)
- Semantic expectations are NOT operational execution metadata
- Null expectation = no semantic drift basis (valid, not an error)

Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1 §12:
- Semantic observability remains advisory-only
- Semantic drift MUST NOT directly mutate runtime behavior

Per DERIVED_STATE_INVALIDATION_CONTRACT_V1 §4:
- Semantic expectation mutation MAY invalidate drift baselines and observability caches
- Expectations are snapshot-linked to step revision

PROHIBITED:
- No LLM calls
- No embeddings/vectors
- No autonomous semantic generation
- No governance authority
- No retry triggers
"""

from typing import Optional, Dict, Any


# ── Allowed Domain Values (SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §10) ─────────

DOMAIN_NUMERIC = "numeric"
DOMAIN_TEXT = "text"
DOMAIN_LIST = "list"
DOMAIN_BOOLEAN = "boolean"
DOMAIN_STRUCTURED = "structured"
DOMAIN_VOID = "void"

VALID_SEMANTIC_DOMAINS = frozenset({
    DOMAIN_NUMERIC, DOMAIN_TEXT, DOMAIN_LIST,
    DOMAIN_BOOLEAN, DOMAIN_STRUCTURED, DOMAIN_VOID,
})

# ── Allowed Category Values ───────────────────────────────────────────────────

CATEGORY_ARITHMETIC = "arithmetic"
CATEGORY_RETRIEVAL = "retrieval"
CATEGORY_TRANSFORMATION = "transformation"
CATEGORY_GENERATION = "generation"
CATEGORY_COMPARISON = "comparison"
CATEGORY_FORMATTING = "formatting"

VALID_SEMANTIC_CATEGORIES = frozenset({
    CATEGORY_ARITHMETIC, CATEGORY_RETRIEVAL, CATEGORY_TRANSFORMATION,
    CATEGORY_GENERATION, CATEGORY_COMPARISON, CATEGORY_FORMATTING,
})

# ── Allowed Shape Values ──────────────────────────────────────────────────────

SHAPE_SCALAR = "scalar"
SHAPE_COLLECTION = "collection"
SHAPE_VOID = "void"

VALID_OUTPUT_SHAPES = frozenset({SHAPE_SCALAR, SHAPE_COLLECTION, SHAPE_VOID})

# ── Known math_executor purpose keywords (deterministic classification) ───────
_ARITHMETIC_KEYWORDS = frozenset({
    "add", "subtract", "multiply", "divide", "square", "cube",
    "sum", "product", "difference", "quotient", "remainder",
    "modulo", "power", "root", "average", "mean", "total",
    "calculate", "compute", "percent", "fraction", "negate",
    "increment", "decrement", "double", "triple", "half",
})

# ── Retrieval/fetch keywords ──────────────────────────────────────────────────
_RETRIEVAL_KEYWORDS = frozenset({
    "fetch", "get", "retrieve", "read", "load", "query", "lookup",
    "find", "search", "list", "show", "display",
})

# ── Transformation/processing keywords ───────────────────────────────────────
_TRANSFORMATION_KEYWORDS = frozenset({
    "transform", "convert", "parse", "format", "normalize",
    "filter", "sort", "map", "reduce", "extract", "process",
    "encode", "decode", "serialize", "deserialize", "split",
})

# ── Generation keywords ───────────────────────────────────────────────────────
_GENERATION_KEYWORDS = frozenset({
    "generate", "create", "build", "write", "produce",
    "synthesize", "draft", "compose", "render", "compile",
})

# ── Comparison/boolean keywords ───────────────────────────────────────────────
_COMPARISON_KEYWORDS = frozenset({
    "compare", "check", "verify", "validate", "test", "assert",
    "equal", "greater", "less", "match", "differ",
})

# ── Formatting/presentation keywords ─────────────────────────────────────────
_FORMATTING_KEYWORDS = frozenset({
    "explain", "describe", "summarize", "repeat", "print", "output", "display",
    "format", "present", "report", "echo",
})


def _words(text: str):
    """Extract lowercase words from text (no regex dependency)."""
    return set(text.lower().replace(",", " ").replace(".", " ").split())


def derive_semantic_expectation(
    agent: Optional[str] = None,
    purpose: Optional[str] = None,
    classification: Optional[str] = None,
    output_constraint_format: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Derive a semantic expectation dict from existing planner signals.

    Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §5:
    - Semantic expectation generation belongs to planner/orchestrator
    - Derivation MUST be deterministic, replayable, lightweight

    Args:
        agent: Planner agent field (e.g. "math_executor", "general_agent")
        purpose: Step purpose string (natural language instruction)
        classification: Task classifier output ("simple"/"complex"/"critical")
        output_constraint_format: Optional extracted constraint format
            (from _extract_constraints_llm — e.g. "list", "count", "words")

    Returns:
        Dict with semantic_domain, semantic_category, output_shape
        OR None if no derivation is possible (safe null = no drift basis)
    """
    if not agent and not purpose and not classification:
        return None

    semantic_domain = None
    semantic_category = None
    output_shape = SHAPE_SCALAR

    purpose_words = _words(purpose) if purpose else set()

    # ── AGENT-FIRST classification (highest signal confidence) ────────────────
    if agent == "math_executor":
        semantic_domain = DOMAIN_NUMERIC
        semantic_category = CATEGORY_ARITHMETIC
        output_shape = SHAPE_SCALAR

    elif agent == "general_agent":
        # Purpose-driven classification for general agent
        if purpose_words & _ARITHMETIC_KEYWORDS:
            semantic_domain = DOMAIN_NUMERIC
            semantic_category = CATEGORY_ARITHMETIC
            output_shape = SHAPE_SCALAR
        elif purpose_words & _RETRIEVAL_KEYWORDS:
            semantic_domain = DOMAIN_TEXT
            semantic_category = CATEGORY_RETRIEVAL
            output_shape = SHAPE_SCALAR
        elif purpose_words & _TRANSFORMATION_KEYWORDS:
            semantic_domain = DOMAIN_TEXT
            semantic_category = CATEGORY_TRANSFORMATION
            output_shape = SHAPE_SCALAR
        elif purpose_words & _GENERATION_KEYWORDS:
            semantic_domain = DOMAIN_TEXT
            semantic_category = CATEGORY_GENERATION
            output_shape = SHAPE_SCALAR
        elif purpose_words & _COMPARISON_KEYWORDS:
            semantic_domain = DOMAIN_BOOLEAN
            semantic_category = CATEGORY_COMPARISON
            output_shape = SHAPE_SCALAR
        elif purpose_words & _FORMATTING_KEYWORDS:
            semantic_domain = DOMAIN_TEXT
            semantic_category = CATEGORY_FORMATTING
            output_shape = SHAPE_SCALAR
        else:
            # Ambiguous purpose — no confident derivation
            # Per contract: ambiguity MUST safely degrade to null
            return None

    else:
        # Unknown agent — purpose-only fallback
        if purpose_words & _ARITHMETIC_KEYWORDS:
            semantic_domain = DOMAIN_NUMERIC
            semantic_category = CATEGORY_ARITHMETIC
            output_shape = SHAPE_SCALAR
        elif purpose_words & _RETRIEVAL_KEYWORDS:
            semantic_domain = DOMAIN_TEXT
            semantic_category = CATEGORY_RETRIEVAL
            output_shape = SHAPE_SCALAR
        else:
            # Cannot confidently derive — return null
            return None

    # ── OUTPUT SHAPE OVERRIDE from constraint format (if present) ────────────
    # Constraint format is a stronger signal for output_shape than agent alone
    if output_constraint_format == "list":
        output_shape = SHAPE_COLLECTION
    elif output_constraint_format == "count":
        # Count is numeric scalar
        semantic_domain = DOMAIN_NUMERIC
        output_shape = SHAPE_SCALAR
    elif output_constraint_format in ("words", "first_word", "empty", "unique"):
        semantic_domain = DOMAIN_TEXT
        output_shape = SHAPE_SCALAR

    if semantic_domain is None:
        return None

    return {
        "semantic_domain": semantic_domain,
        "semantic_category": semantic_category,
        "output_shape": output_shape,
    }


def is_valid_semantic_expectation(se: Any) -> bool:
    """
    Return True if se is a non-null, structurally valid semantic expectation.
    Returns False for None, empty dict, or invalid domain/shape values.
    """
    if not isinstance(se, dict):
        return False
    domain = se.get("semantic_domain")
    shape = se.get("output_shape")
    # domain is required; category and shape may be null
    return domain in VALID_SEMANTIC_DOMAINS


def null_expectation() -> None:
    """
    Explicit null expectation sentinel.
    Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1:
    Null = no semantic drift basis. VALID. Not an error.
    """
    return None

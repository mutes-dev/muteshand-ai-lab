INPUT_SPEC = {
    "text": "string",
    "action": "string",
}

import re
from typing import Any, Dict, List, Optional

# ── Deterministic chunking bounds ────────────────────────────────────────────

_DEFAULT_CHUNK_SIZE = 5000
_DEFAULT_MAX_CHUNKS = 8
_DEFAULT_OVERLAP = 200

# Narrow action allowlist
_ALLOWED_ACTIONS = frozenset({"summarize", "explain", "extract_key_points", "answer_question"})


# ── Narrow, fixed chunk prompts (tool-internal only) ───────────────────────

_CHUNK_PROMPTS = {
    "summarize": (
        "Summarize the following text concisely. "
        "Preserve the main ideas and key details. "
        "Do not mention tools, processes, or instructions. "
        "Return only the summary.\n\n{text}"
    ),
    "explain": (
        "Explain the following text clearly and accurately. "
        "Preserve the meaning and cover the main concepts. "
        "Do not mention tools, processes, or instructions. "
        "Return only the explanation.\n\n{text}"
    ),
    "extract_key_points": (
        "Extract the key points from the following text as a concise bullet list. "
        "Each bullet should capture a distinct important idea. "
        "Do not mention tools, processes, or instructions. "
        "Return only the bullet list.\n\n{text}"
    ),
    "answer_question": (
        "Answer the question below using ONLY the provided document text. "
        "Do not use outside knowledge. "
        "Do not invent facts. "
        "Search for: direct matches, labels, nearby values, measurements, names, dates, and topic statements. "
        "For measurement/size/dimension questions, find the label in the text and return the value next to it. "
        "For label/value pairs (e.g., 'Client: Acme', 'Date: 2026-07-05'), return the matching value. "
        "For 'what is this document about?' or 'what is the main topic?', infer a concise topic from the meaningful text. "
        "For 'what validation does it mention?', return the exact validation phrase if present. "
        "Return 'not_found' only after checking the text for relevant direct or nearby evidence. "
        "Return 'insufficient_information' only if the provided text is empty, unreadable, or too thin to answer. "
        "Do not prefix the answer with 'found' or any other marker. "
        "Keep the answer concise. "
        "Include a short supporting excerpt only if it is safe and easy to do so.\n\n{text}"
    ),
}

_SYNTHESIS_PROMPTS = {
    "summarize": (
        "Combine the following partial summaries into one coherent final summary. "
        "Preserve the main ideas and key details. "
        "Do not mention that this was created from partial summaries. "
        "Return only the final summary.\n\n{chunks}"
    ),
    "explain": (
        "Combine the following partial explanations into one coherent final explanation. "
        "Preserve the meaning and cover the main concepts. "
        "Do not mention that this was created from partial explanations. "
        "Return only the final explanation.\n\n{chunks}"
    ),
    "extract_key_points": (
        "Combine the following partial bullet lists into one final consolidated bullet list. "
        "Remove duplicate ideas. Preserve distinct important points. "
        "Do not mention that this was created from partial lists. "
        "Return only the final bullet list.\n\n{chunks}"
    ),
    "answer_question": (
        "Combine the following partial answers into one final answer. "
        "Use only information present in the partial answers. "
        "Prefer any partial answer that gives a direct value, label, measurement, name, date, or validation phrase. "
        "If any partial answer contains the information, return it concisely. "
        "If no partial answer contains the information, return exactly 'not_found'. "
        "If the partial answers are insufficient, return exactly 'insufficient_information'. "
        "Keep the final answer concise. "
        "Do not invent facts.\n\n{chunks}"
    ),
}


def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Deterministically split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        # Advance by chunk_size minus overlap, but at least 1 character
        step = max(1, chunk_size - overlap)
        start += step
        # Prevent infinite loop on last chunk
        if end >= text_len:
            break

    return chunks


def _call_llm(prompt: str) -> Optional[str]:
    """Call the existing LLM execution stack. Returns text or None on failure."""
    try:
        from system.orchestrator.llm_registry import get_llm
        from system.orchestrator.llm_executor import execute_llm

        provider_result = get_llm("ollama_llm")
        if provider_result.get("status") != "success":
            return None

        result = execute_llm(
            provider_result["provider"],
            prompt,
            _perf_caller="semantic_transform",
            workflow_id=None,
        )
        if result.get("status") == "success":
            return result.get("result")
        return None
    except Exception:
        return None


def _transform_chunk(chunk: str, action: str) -> Optional[str]:
    """Run a single chunk through the action-specific LLM prompt."""
    template = _CHUNK_PROMPTS.get(action)
    if not template:
        return None
    prompt = template.replace("{text}", chunk)
    return _call_llm(prompt)


def _synthesize_results(chunk_results: List[str], action: str) -> Optional[str]:
    """Synthesize chunk-level outputs into a final result."""
    if not chunk_results:
        return None

    # Single chunk: passthrough
    if len(chunk_results) == 1:
        return chunk_results[0]

    template = _SYNTHESIS_PROMPTS.get(action)
    if not template:
        return "\n\n".join(chunk_results)

    chunks_text = "\n\n---\n\n".join(
        f"[Partial {i + 1}]:\n{result}"
        for i, result in enumerate(chunk_results)
    )
    prompt = template.replace("{chunks}", chunks_text)
    return _call_llm(prompt)


def _parse_answer_question_input(text: str) -> tuple[str, str]:
    """Extract (question, document) from the answer_question input format."""
    m = re.search(r"Question:\s*(.*?)\n\nDocument:\n(.*)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Fallback: if no explicit marker, treat whole text as document
    return "", text.strip()


# Measurement regex: number followed by unit, optionally with parenthetical dimensions.
# Use a negative lookahead (?![\w]) instead of \b so that Unicode superscripts like m² are
# matched correctly (\b between non-word and non-word does not match).
_MEASUREMENT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:m²|m2|sqm|ft²|ft2|sqft|m|cm|mm|in|ft|feet)"
    r"(?:\s*\(\s*\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?\s*\))?"
    r"(?![\w])",
    re.IGNORECASE,
)
_DIMENSIONS_RE = re.compile(r"\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?", re.IGNORECASE)


def _extract_measurement_near_label(text: str, target: str) -> Optional[str]:
    """If the target label appears in text, return a nearby measurement or dimension value."""
    lines = text.splitlines()
    target_lower = target.lower()
    for i, line in enumerate(lines):
        if target_lower in line.lower():
            candidates = [line]
            if i + 1 < len(lines):
                candidates.append(lines[i + 1])
            for candidate in candidates:
                m = _MEASUREMENT_RE.search(candidate)
                if m:
                    return m.group(0).strip()
            for candidate in candidates:
                m = _DIMENSIONS_RE.search(candidate)
                if m:
                    return m.group(0).strip()
    return None


def _extract_value_after_label(text: str, label: str) -> Optional[str]:
    """Find a label/value pair in text and return the value."""
    # Clean label for regex: strip leading/trailing whitespace and question mark
    clean_label = label.strip().rstrip("?").strip()
    if not clean_label:
        return None
    # Pattern: label: value or label = value or label - value
    patterns = [
        rf"{re.escape(clean_label)}\s*[:=]\s*(.+?)(?:\n|$)",
        rf"{re.escape(clean_label)}\s*[-]\s*(.+?)(?:\n|$)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()
    return None


def _extract_target_from_question(question: str) -> Optional[str]:
    """Extract a measurement target from a question, stripping leading articles."""
    q_lower = question.lower().rstrip("?").strip()
    m = re.search(
        r"(?:how big is|what is the size of|what are the dimensions of|what is the area of)\s+(.+?)$",
        q_lower,
    )
    if not m:
        return None
    target = m.group(1).strip()
    target = re.sub(r"^(the|a|an)\s+", "", target)
    return target


def _extract_label_from_question(question: str) -> Optional[str]:
    """Extract a label from a label/value question, stripping question words and trailing phrases."""
    q_lower = question.lower().rstrip("?").strip()
    # Remove leading question words
    q_lower = re.sub(
        r"^(what is the|what are the|what is|what are|what|who|when)\s+",
        "",
        q_lower,
    )
    # Remove trailing phrases like "does it mention" / "is mentioned"
    q_lower = re.sub(
        r"\s+(?:does it mention|does the document mention|is mentioned|are mentioned|did it mention|does it have)$",
        "",
        q_lower,
    )
    return q_lower.strip() or None


def _direct_extract_answer(text: str, question: str, llm_result: str) -> Optional[str]:
    """Bounded deterministic fallback: extract direct answer from text when LLM emits a fallback.

    Only fires when the LLM returns 'not_found' or 'insufficient_information'. Searches for
    direct measurements near labels and label/value pairs. Does not use broad reasoning.
    """
    if llm_result not in ("not_found", "insufficient_information"):
        return None

    # Measurement/size/dimension questions
    target = _extract_target_from_question(question)
    if target:
        value = _extract_measurement_near_label(text, target)
        if value:
            return value

    # Label/value questions
    label = _extract_label_from_question(question)
    if label:
        value = _extract_value_after_label(text, label)
        if value:
            return value

    return None


def _canonicalize_answer_question_result(result: str) -> str:
    """Canonicalize answer_question output to strict fallbacks.

    - If the LLM emits a fallback token followed by speculative text, strip the
      speculation and return exactly 'not_found' or 'insufficient_information'.
    - If the LLM emits a leading 'found' marker with an answer body, strip the
      marker and return the body.
    - If the LLM emits only 'found', return 'insufficient_information'.
    """
    if not result:
        return result
    stripped = result.strip()
    lower = stripped.lower()

    # Strict fallbacks: any variant followed by speculation -> canonical token
    fallback_tokens = (
        ("not_found", "_not_found_"),
        ("insufficient_information", "_insufficient_information_"),
    )
    for canonical, marker in fallback_tokens:
        if lower.startswith(canonical) or lower.startswith(marker):
            return canonical

    # Strip leading 'found' / '_found_' marker if an answer body follows
    if lower.startswith("found") or lower.startswith("_found_"):
        remainder = re.sub(r"^_?found_?\s*[:\-\.]?\s*", "", stripped, flags=re.IGNORECASE).strip()
        if remainder:
            return remainder
        return "insufficient_information"

    return stripped


def run(text, action="summarize", max_chunks=None, chunk_size=None, overlap=None):
    """
    Perform a semantic transform (summarize, explain, extract_key_points, answer_question)
    on potentially large text using deterministic chunking + bounded per-chunk
    LLM calls + synthesis.

    Input:
        text (str): source text to transform
        action (str): one of "summarize", "explain", "extract_key_points", "answer_question"
        max_chunks (int, optional): cap on number of chunks (default 8)
        chunk_size (int, optional): characters per chunk (default 5000)
        overlap (int, optional): overlap between chunks (default 200)

    For answer_question, the question should be embedded in the text parameter
    (e.g., "Question: ...\n\nDocument:\n...") by the caller.

    Returns:
        {"status": "success", "result": str} or
        {"status": "failure", "reason": str}
    """
    # ── Validation ─────────────────────────────────────────────────────────
    if not isinstance(text, str) or text.strip() == "":
        return {"status": "failure", "reason": "empty_or_invalid_text"}

    action = (action or "summarize").strip().lower()
    if action not in _ALLOWED_ACTIONS:
        return {
            "status": "failure",
            "reason": "unsupported_action",
            "detail": f"action must be one of {set(_ALLOWED_ACTIONS)}",
        }

    _chunk_size = chunk_size if isinstance(chunk_size, int) and chunk_size > 0 else _DEFAULT_CHUNK_SIZE
    _max_chunks = max_chunks if isinstance(max_chunks, int) and max_chunks > 0 else _DEFAULT_MAX_CHUNKS
    _overlap = overlap if isinstance(overlap, int) and overlap >= 0 else _DEFAULT_OVERLAP

    # ── Chunking ─────────────────────────────────────────────────────────────
    chunks = _chunk_text(text, _chunk_size, _overlap)

    # Enforce max_chunks bound: keep only first N bounded chunks; overflow omitted
    _overflow = False
    if len(chunks) > _max_chunks:
        chunks = chunks[:_max_chunks]
        _overflow = True

    # ── Per-chunk transform ──────────────────────────────────────────────────
    chunk_results = []
    for chunk in chunks:
        result = _transform_chunk(chunk, action)
        if result is None:
            # Fail-closed: if any chunk transform fails, report failure
            return {
                "status": "failure",
                "reason": "chunk_transform_failed",
                "detail": f"LLM transform failed for one of {len(chunks)} chunk(s)",
            }
        chunk_results.append(result)

    # ── Synthesis ──────────────────────────────────────────────────────────────
    final_result = _synthesize_results(chunk_results, action)
    if final_result is None:
        return {
            "status": "failure",
            "reason": "synthesis_failed",
            "detail": "Final synthesis step failed",
        }

    # Canonicalize answer_question fallbacks to prevent speculative text
    if action == "answer_question":
        final_result = _canonicalize_answer_question_result(final_result)
        # Bounded deterministic fallback: if the LLM returned a fallback token but
        # the answer is directly present in the text (measurement near label,
        # label/value pair), extract it rather than returning not_found.
        if final_result in ("not_found", "insufficient_information"):
            _question, _document = _parse_answer_question_input(text)
            _extracted = _direct_extract_answer(_document, _question, final_result)
            if _extracted:
                final_result = _extracted

    if _overflow:
        final_result = (
            f"{final_result}\n\n"
            f"[Note: this result was derived from the first {_max_chunks} text segments. "
            f"Additional content was not processed.]"
        )

    return {"status": "success", "result": final_result}

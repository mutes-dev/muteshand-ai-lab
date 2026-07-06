INPUT_SPEC = {
    "text": "string",
    "action": "string",
}

from typing import Dict, List, Optional

# ── Deterministic chunking bounds ────────────────────────────────────────────

_DEFAULT_CHUNK_SIZE = 5000
_DEFAULT_MAX_CHUNKS = 8
_DEFAULT_OVERLAP = 200

# Narrow action allowlist
# answer_question is quarantined per SPRINT-11 REALIGNMENT SLICE A.
_ALLOWED_ACTIONS = frozenset({"summarize", "explain", "extract_key_points"})


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


def run(text, action="summarize", max_chunks=None, chunk_size=None, overlap=None):
    """
    Perform a semantic transform (summarize, explain, extract_key_points)
    on potentially large text using deterministic chunking + bounded per-chunk
    LLM calls + synthesis.

    Input:
        text (str): source text to transform
        action (str): one of "summarize", "explain", "extract_key_points"
        max_chunks (int, optional): cap on number of chunks (default 8)
        chunk_size (int, optional): characters per chunk (default 5000)
        overlap (int, optional): overlap between chunks (default 200)

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

    if _overflow:
        final_result = (
            f"{final_result}\n\n"
            f"[Note: this result was derived from the first {_max_chunks} text segments. "
            f"Additional content was not processed.]"
        )

    return {"status": "success", "result": final_result}

"""
Tests for semantic_transform tool.

SPRINT-11-OPENING-SLICE-001 — Bounded large-document semantic transform.
"""
import unittest
from unittest.mock import patch, MagicMock

from tools.semantic_transform import run, _chunk_text, _ALLOWED_ACTIONS


class TestChunkText(unittest.TestCase):
    def test_short_text_single_chunk(self):
        text = "short text"
        chunks = _chunk_text(text, chunk_size=100, overlap=10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_exactly_chunk_size(self):
        text = "a" * 100
        chunks = _chunk_text(text, chunk_size=100, overlap=10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_two_chunks(self):
        text = "a" * 150
        chunks = _chunk_text(text, chunk_size=100, overlap=10)
        self.assertEqual(len(chunks), 2)
        # Second chunk should start at position 90 (100 - 10 overlap)
        self.assertTrue(chunks[1].startswith("a" * 10))

    def test_overlap_zero(self):
        text = "a" * 300
        chunks = _chunk_text(text, chunk_size=100, overlap=0)
        self.assertEqual(len(chunks), 3)


class TestRunValidation(unittest.TestCase):
    def test_unsupported_action(self):
        result = run("some text", action="compare")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "unsupported_action")

    def test_empty_text(self):
        result = run("", action="summarize")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "empty_or_invalid_text")

    def test_whitespace_only_text(self):
        result = run("   ", action="summarize")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "empty_or_invalid_text")

    def test_none_text(self):
        result = run(None, action="summarize")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "empty_or_invalid_text")

    def test_allowed_actions(self):
        for action in _ALLOWED_ACTIONS:
            with self.subTest(action=action):
                with patch("tools.semantic_transform._call_llm", return_value="mock result"):
                    result = run("some text", action=action)
                    self.assertEqual(result["status"], "success")
                    self.assertEqual(result["result"], "mock result")

    def test_default_action_is_summarize(self):
        with patch("tools.semantic_transform._call_llm", return_value="mock result"):
            result = run("some text")
            self.assertEqual(result["status"], "success")

    def test_case_insensitive_action(self):
        with patch("tools.semantic_transform._call_llm", return_value="mock result"):
            result = run("some text", action="SUMMARIZE")
            self.assertEqual(result["status"], "success")


class TestRunChunkingAndSynthesis(unittest.TestCase):
    def test_small_text_single_chunk_no_synthesis(self):
        """Text below chunk_size should not be split."""
        with patch("tools.semantic_transform._call_llm", return_value="single result") as mock_llm:
            result = run("small text", action="summarize", chunk_size=5000)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["result"], "single result")
            mock_llm.assert_called_once()

    def test_large_text_multiple_chunks_synthesized(self):
        """Text exceeding chunk_size should be split and synthesized."""
        text = "word " * 3000  # ~18K chars, will split into chunks
        with patch("tools.semantic_transform._call_llm", return_value="chunk result") as mock_llm:
            result = run(text, action="summarize", chunk_size=5000, max_chunks=8)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["result"], "chunk result")
            # Should call LLM at least twice (once per chunk + synthesis)
            self.assertGreaterEqual(mock_llm.call_count, 2)

    def test_max_chunks_cap(self):
        """max_chunks should prevent unbounded LLM calls."""
        text = "a" * 50000
        with patch("tools.semantic_transform._call_llm", return_value="chunk") as mock_llm:
            result = run(text, action="summarize", chunk_size=1000, max_chunks=3, overlap=0)
            self.assertEqual(result["status"], "success")
            # 3 chunk transforms + 1 synthesis = 4 LLM calls max
            self.assertLessEqual(mock_llm.call_count, 4)

    def test_no_chunk_exceeds_chunk_size(self):
        """Every processed chunk must respect the configured chunk_size bound."""
        text = "a" * 50000
        captured_prompts = []
        def capture_llm(prompt):
            captured_prompts.append(prompt)
            return "chunk"

        with patch("tools.semantic_transform._call_llm", side_effect=capture_llm):
            result = run(text, action="summarize", chunk_size=1000, max_chunks=3, overlap=0)
            self.assertEqual(result["status"], "success")
            # Extract raw text from each chunk prompt by removing the fixed template prefix
            from tools.semantic_transform import _CHUNK_PROMPTS
            template = _CHUNK_PROMPTS["summarize"]
            for prompt in captured_prompts:
                if "Partial" not in prompt and "Combine" not in prompt:
                    # This is a chunk prompt; the text part is after the template
                    prefix = template.replace("{text}", "")
                    if prompt.startswith(prefix):
                        chunk_text = prompt[len(prefix):]
                        self.assertLessEqual(len(chunk_text), 1000,
                            f"Chunk exceeded chunk_size: {len(chunk_text)} chars")

    def test_overflow_omitted_not_merged(self):
        """Overflow beyond max_chunks must be omitted, not merged into last chunk."""
        text = "a" * 50000
        captured_prompts = []
        def capture_llm(prompt):
            captured_prompts.append(prompt)
            return "chunk"

        with patch("tools.semantic_transform._call_llm", side_effect=capture_llm):
            result = run(text, action="summarize", chunk_size=1000, max_chunks=3, overlap=0)
            self.assertEqual(result["status"], "success")
            # All chunk prompts should contain at most 1000 chars of source text
            from tools.semantic_transform import _CHUNK_PROMPTS
            template = _CHUNK_PROMPTS["summarize"]
            prefix = template.replace("{text}", "")
            for prompt in captured_prompts:
                if "Partial" not in prompt and "Combine" not in prompt:
                    chunk_text = prompt[len(prefix):] if prompt.startswith(prefix) else prompt
                    self.assertLessEqual(len(chunk_text), 1000,
                        "Merged overflow detected: chunk exceeds chunk_size")

    def test_overflow_note_present_when_max_chunks_exceeded(self):
        """When source exceeds max_chunks capacity, output includes a bounded-overflow note."""
        text = "a" * 50000
        with patch("tools.semantic_transform._call_llm", return_value="summary"):
            result = run(text, action="summarize", chunk_size=1000, max_chunks=3, overlap=0)
            self.assertEqual(result["status"], "success")
            self.assertIn("first 3 text segments", result["result"])
            self.assertIn("Additional content was not processed", result["result"])

    def test_overflow_note_does_not_use_truncated_literal(self):
        """The overflow note must not contain the literal '[truncated]'."""
        text = "a" * 50000
        with patch("tools.semantic_transform._call_llm", return_value="summary"):
            result = run(text, action="summarize", chunk_size=1000, max_chunks=3, overlap=0)
            self.assertEqual(result["status"], "success")
            self.assertNotIn("[truncated]", result["result"])

    def test_overflow_behavior_is_deterministic(self):
        """Same input + same params must always produce same overflow note."""
        text = "a" * 50000
        results = []
        with patch("tools.semantic_transform._call_llm", return_value="summary"):
            for _ in range(3):
                result = run(text, action="summarize", chunk_size=1000, max_chunks=3, overlap=0)
                results.append(result["result"])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_no_literal_truncated_in_output(self):
        """Output must not contain literal '[truncated]' from the tool itself."""
        with patch("tools.semantic_transform._call_llm", return_value="clean result"):
            result = run("some text", action="summarize")
            self.assertEqual(result["status"], "success")
            self.assertNotIn("[truncated]", result["result"])

    def test_passes_through_existing_truncated_if_in_source(self):
        """If source already contains '[truncated]', tool should not remove it but also not add new one."""
        with patch("tools.semantic_transform._call_llm", return_value="source had ... [truncated] marker"):
            result = run("source had ... [truncated] marker", action="summarize")
            self.assertEqual(result["status"], "success")
            # The mock returns the same text; tool itself does not add [truncated]
            self.assertEqual(result["result"], "source had ... [truncated] marker")

    def test_chunk_transform_failure_fail_closed(self):
        """If any chunk transform fails, return failure."""
        def side_effect(prompt):
            if "Partial" in prompt:
                return "synthesis"
            # First chunk succeeds, second fails
            calls = getattr(side_effect, "calls", 0)
            side_effect.calls = calls + 1
            if calls == 0:
                return "chunk1"
            return None

        text = "a" * 15000
        with patch("tools.semantic_transform._call_llm", side_effect=side_effect):
            result = run(text, action="summarize", chunk_size=5000)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "chunk_transform_failed")

    def test_synthesis_failure(self):
        """If synthesis fails, return failure."""
        def side_effect(prompt):
            if "Partial" in prompt:
                return None  # synthesis fails
            return "chunk"

        text = "a" * 15000
        with patch("tools.semantic_transform._call_llm", side_effect=side_effect):
            result = run(text, action="summarize", chunk_size=5000)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "synthesis_failed")

    def test_empty_chunk_results_no_synthesis_needed(self):
        """If only one chunk, synthesis is passthrough."""
        with patch("tools.semantic_transform._call_llm", return_value="passthrough"):
            result = run("small", action="explain", chunk_size=5000)
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["result"], "passthrough")


class TestRunResultShape(unittest.TestCase):
    def test_success_has_result_field(self):
        with patch("tools.semantic_transform._call_llm", return_value="output"):
            result = run("text", action="summarize")
            self.assertIn("status", result)
            self.assertIn("result", result)
            self.assertEqual(result["status"], "success")

    def test_failure_has_reason_field(self):
        result = run("", action="summarize")
        self.assertIn("status", result)
        self.assertIn("reason", result)
        self.assertEqual(result["status"], "failure")


if __name__ == "__main__":
    unittest.main()

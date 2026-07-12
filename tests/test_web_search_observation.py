"""
F3C-1 Stage A web_search observation tests.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.tools.search.core import search, SearchResult
from system.tools.search.observation import (
    build_web_search_observation,
    build_web_search_observation_for_failure,
)


class TestBuildWebSearchObservation(unittest.TestCase):

    def test_success_observation_shape(self):
        result = {
            "status": "success",
            "results": [
                SearchResult(title="T1", url="https://example.com/1", snippet="S1"),
                SearchResult(title="T2", url="https://example.com/2", snippet="S2"),
            ],
            "provider": "duckduckgo",
            "fallback_used": False,
        }
        obs = build_web_search_observation("hello", result, displayed_count=2)

        self.assertEqual(obs["observation_type"], "web_search")
        self.assertEqual(obs["evidence_status"], "observation_only")
        self.assertEqual(obs["query"], "hello")
        self.assertEqual(obs["provider"], "duckduckgo")
        self.assertEqual(obs["provider_host"], "html.duckduckgo.com")
        self.assertFalse(obs["fallback_used"])
        self.assertEqual(obs["outcome_kind"], "results")
        self.assertEqual(obs["result_count"], 2)
        self.assertEqual(obs["returned_result_count"], 2)
        self.assertEqual(len(obs["results"]), 2)
        self.assertEqual(obs["results"][0]["rank"], 1)
        self.assertEqual(obs["results"][0]["title"], "T1")
        self.assertEqual(obs["results"][0]["url"], "https://example.com/1")
        self.assertEqual(obs["results"][0]["snippet"], "S1")
        self.assertIn("retrieved_at", obs)
        self.assertIsInstance(obs["warnings"], list)
        self.assertIsInstance(obs["limitations"], list)

    def test_zero_results_outcome(self):
        result = {
            "status": "failure",
            "reason": "search_no_results",
            "detail": "none",
            "provider": "duckduckgo",
            "fallback_used": False,
        }
        obs = build_web_search_observation("hello", result)
        self.assertEqual(obs["outcome_kind"], "zero_results")
        self.assertEqual(obs["result_count"], 0)
        self.assertEqual(obs["returned_result_count"], 0)

    def test_endpoint_safety_blocked_outcome(self):
        result = {
            "status": "failure",
            "reason": "url_safety_blocked",
            "detail": "blocked",
            "provider": "duckduckgo",
            "fallback_used": False,
        }
        obs = build_web_search_observation("hello", result)
        self.assertEqual(obs["outcome_kind"], "endpoint_safety_blocked")

    def test_provider_timeout_outcome(self):
        result = {
            "status": "failure",
            "reason": "search_provider_timeout",
            "provider": "searxng",
            "fallback_used": True,
        }
        obs = build_web_search_observation("hello", result)
        self.assertEqual(obs["outcome_kind"], "provider_unavailable")
        self.assertTrue(obs["fallback_used"])

    def test_provider_parse_error_outcome(self):
        result = {
            "status": "failure",
            "reason": "search_parse_error",
            "provider": "searxng",
            "fallback_used": False,
        }
        obs = build_web_search_observation("hello", result)
        self.assertEqual(obs["outcome_kind"], "provider_failure")

    def test_no_provider_configured_outcome(self):
        result = {
            "status": "failure",
            "reason": "search_no_provider_configured",
            "provider": "auto",
            "fallback_used": False,
        }
        obs = build_web_search_observation("hello", result)
        self.assertEqual(obs["outcome_kind"], "provider_unavailable")

    def test_query_truncation(self):
        long_query = "x" * 10000
        result = {
            "status": "success",
            "results": [SearchResult(title="T", url="https://example.com", snippet="S")],
            "provider": "duckduckgo",
            "fallback_used": False,
        }
        obs = build_web_search_observation(long_query, result)
        self.assertTrue(obs["query_truncated"])
        self.assertEqual(len(obs["query"]), 8192)

    def test_result_bounds(self):
        results = [
            SearchResult(title=f"T{i}", url=f"https://example.com/{i}", snippet=f"S{i}")
            for i in range(10)
        ]
        result = {
            "status": "success",
            "results": results,
            "provider": "duckduckgo",
            "fallback_used": False,
        }
        obs = build_web_search_observation("hello", result, displayed_count=3)
        self.assertEqual(obs["result_count"], 10)
        self.assertEqual(obs["returned_result_count"], 3)
        self.assertEqual(len(obs["results"]), 5)

    def test_field_truncation(self):
        result = {
            "status": "success",
            "results": [
                SearchResult(title="t" * 500, url="u" * 3000, snippet="s" * 2000),
            ],
            "provider": "duckduckgo",
            "fallback_used": False,
        }
        obs = build_web_search_observation("hello", result)
        self.assertLessEqual(len(obs["results"][0]["title"]), 200)
        self.assertLessEqual(len(obs["results"][0]["url"]), 2048)
        self.assertLessEqual(len(obs["results"][0]["snippet"]), 1000)

    def test_searxng_provider_host_sanitized(self):
        with patch.dict(os.environ, {"SEARXNG_BASE_URL": "https://searx.example.com:8080/search?q=test"}):
            result = {
                "status": "success",
                "results": [SearchResult(title="T", url="https://a.com", snippet="S")],
                "provider": "searxng",
                "fallback_used": False,
            }
            obs = build_web_search_observation("hello", result)
            self.assertEqual(obs["provider_host"], "searx.example.com")

    def test_no_workflow_or_step_fields_in_raw_observation(self):
        result = {
            "status": "success",
            "results": [SearchResult(title="T", url="https://example.com", snippet="S")],
            "provider": "duckduckgo",
            "fallback_used": False,
        }
        obs = build_web_search_observation("hello", result)
        for key in [
            "workflow_id",
            "plan_id",
            "plan_version",
            "step_id",
            "execution_generation",
            "retry_generation",
            "attempt_index",
            "query_provenance",
            "continuation_link",
            "approval_control_id",
        ]:
            self.assertNotIn(key, obs)


class TestBuildWebSearchObservationForFailure(unittest.TestCase):

    def test_empty_query_failure(self):
        obs = build_web_search_observation_for_failure("", "empty_query")
        self.assertEqual(obs["outcome_kind"], "empty_query")
        self.assertEqual(obs["result_count"], 0)
        self.assertEqual(obs["provider"], "unknown")

    def test_wrapper_import_failure(self):
        obs = build_web_search_observation_for_failure("hello", "wrapper_import_failure")
        self.assertEqual(obs["outcome_kind"], "wrapper_import_failure")


class TestWebSearchToolEnvelope(unittest.TestCase):

    def test_success_envelope_preserves_result_string(self):
        ddg_html = """
        <html>
          <div class="result">
            <a class="result__a" href="https://example.com/1">Python Docs</a>
            <a class="result__snippet">Official Python documentation</a>
          </div>
        </html>
        """
        ddg_resp = MagicMock()
        ddg_resp.text = ddg_html
        ddg_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=ddg_resp):
            from tools import web_search
            result = web_search.run("python documentation")

        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "success")
        self.assertIsInstance(result["result"], str)
        self.assertIn("Top results:", result["result"])
        self.assertIsInstance(result["observation"], dict)
        self.assertEqual(result["observation"]["outcome_kind"], "results")

    def test_failure_envelope_preserves_result_string(self):
        import requests
        with patch("requests.post", side_effect=requests.exceptions.RequestException("fail")):
            from tools import web_search
            result = web_search.run("something")

        self.assertIsInstance(result, dict)
        self.assertEqual(result["result"], "no results found")
        self.assertIsInstance(result["observation"], dict)
        # Provider catches the network exception and returns a structured failure,
        # so the observation reflects provider_unavailability rather than wrapper exception.
        self.assertEqual(result["observation"]["outcome_kind"], "provider_unavailable")

    def test_empty_query_envelope(self):
        from tools import web_search
        result = web_search.run("")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["result"], "no results found")
        self.assertEqual(result["observation"]["outcome_kind"], "empty_query")

    def test_url_safety_blocked_envelope(self):
        with patch("system.tools.search.providers.validate_url", return_value={"status": "failure", "reason": "url_safety_blocked", "detail": "blocked"}):
            from tools import web_search
            result = web_search.run("hello")

        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "url_safety_blocked")
        self.assertIsInstance(result["observation"], dict)
        self.assertEqual(result["observation"]["outcome_kind"], "endpoint_safety_blocked")


class TestGenericCarrierPreservation(unittest.TestCase):

    def test_executor_preserves_dict_observation(self):
        from system.execution.executor import execute

        def tool_with_observation():
            return {
                "status": "success",
                "result": "ok",
                "observation": {"observation_type": "web_search", "evidence_status": "observation_only"},
                "extra_field": "ignored",
            }

        registry = {"test_tool": tool_with_observation}
        plan = [{"name": "test_tool", "args": []}]
        result = execute(plan, registry)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"], "ok")
        self.assertIsInstance(result.get("observation"), dict)
        self.assertNotIn("extra_field", result)

    def test_executor_ignores_non_dict_observation(self):
        from system.execution.executor import execute

        def tool_with_bad_observation():
            return {"status": "success", "result": "ok", "observation": "not a dict"}

        registry = {"test_tool": tool_with_bad_observation}
        result = execute([{"name": "test_tool", "args": []}], registry)

        self.assertEqual(result["status"], "success")
        self.assertNotIn("observation", result)

    def test_executor_preserves_failure_observation(self):
        from system.execution.executor import execute

        def tool_with_failure_observation():
            return {
                "status": "failure",
                "reason": "blocked",
                "observation": {"observation_type": "web_search", "evidence_status": "observation_only"},
            }

        registry = {"test_tool": tool_with_failure_observation}
        result = execute([{"name": "test_tool", "args": []}], registry)

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "blocked")
        self.assertIsInstance(result.get("observation"), dict)

    def test_system_entry_preserves_observation(self):
        ddg_html = """
        <html>
          <div class="result">
            <a class="result__a" href="https://example.com/1">Title</a>
            <a class="result__snippet">Snippet</a>
          </div>
        </html>
        """
        ddg_resp = MagicMock()
        ddg_resp.text = ddg_html
        ddg_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=ddg_resp):
            from system.entry.system_entry import system_entry
            result = system_entry('web_search "hello"', mode="normal")

        self.assertEqual(result["status"], "success")
        self.assertIsInstance(result["result"], str)
        self.assertIsInstance(result.get("observation"), dict)
        self.assertEqual(result["observation"]["observation_type"], "web_search")


if __name__ == "__main__":
    unittest.main(verbosity=2)

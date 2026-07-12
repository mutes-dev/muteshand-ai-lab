"""
F3C read_webpage observation envelope tests.

No external network calls; all HTTP/URL paths are mocked.
"""

import sys
import os

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from unittest.mock import patch, MagicMock
import unittest

from tools import read_webpage


HTML_LONG = "x" * 6000
HTML_WITH_TITLE = (
    "<html><head><title>Example Page</title></head>"
    "<body><p>Hello world</p></body></html>"
)


def _make_response(text, status_code=200, content_type="text/html", is_redirect=False, is_permanent_redirect=False):
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    mock.headers = {"content-type": content_type}
    mock.is_redirect = is_redirect
    mock.is_permanent_redirect = is_permanent_redirect
    if status_code >= 400:
        from requests.exceptions import HTTPError
        mock.raise_for_status.side_effect = HTTPError(response=mock)
    return mock


@patch("system.security.url_validator.validate_url", return_value={"status": "success"})
class TestReadWebpageObservationEnvelope(unittest.TestCase):

    def test_success_returns_legacy_result_plus_observation(self, _mock_val):
        with patch("requests.get", return_value=_make_response(HTML_WITH_TITLE)):
            result = read_webpage.run("https://example.com")

        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "success")
        self.assertIn("result", result)
        self.assertIn("Hello world", result["result"])
        self.assertIsInstance(result["observation"], dict)

    def test_observation_shape_on_success(self, _mock_val):
        with patch("requests.get", return_value=_make_response(HTML_WITH_TITLE)):
            result = read_webpage.run("https://example.com")

        obs = result["observation"]
        self.assertEqual(obs["observation_type"], "read_webpage")
        self.assertEqual(obs["tool_name"], "read_webpage")
        self.assertEqual(obs["evidence_status"], "observation_only")
        self.assertEqual(obs["requested_url"], "https://example.com")
        self.assertEqual(obs["final_url"], "https://example.com")
        self.assertEqual(obs["source_domain"], "example.com")
        self.assertEqual(obs["title"], "Example Page")
        self.assertTrue(obs["observation_id"].startswith("obs_"))
        self.assertIsNotNone(obs["retrieved_at"])
        self.assertEqual(obs["status"], "success")
        self.assertEqual(obs["truncation_limit"], 5000)

    def test_failure_returns_reason_detail_plus_observation(self, _mock_val):
        with patch("requests.get", return_value=_make_response("not found", status_code=404)):
            result = read_webpage.run("https://example.com/missing")

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "http_error")
        self.assertIn("detail", result)
        self.assertIsInstance(result["observation"], dict)

    def test_failure_observation_shape(self, _mock_val):
        with patch("requests.get", return_value=_make_response("not found", status_code=404)):
            result = read_webpage.run("https://example.com/missing")

        obs = result["observation"]
        self.assertEqual(obs["observation_type"], "read_webpage")
        self.assertEqual(obs["status"], "failure")
        self.assertEqual(obs["failure_reason"], "http_error")
        self.assertIsNone(obs["final_url"])
        self.assertIsNone(obs["title"])
        self.assertEqual(obs["extracted_length"], 0)
        self.assertFalse(obs["truncated"])

    def test_truncation_metadata(self, _mock_val):
        html = f"<html><body><p>{HTML_LONG}</p></body></html>"
        with patch("requests.get", return_value=_make_response(html)):
            result = read_webpage.run("https://example.com")

        obs = result["observation"]
        self.assertTrue(obs["truncated"])
        self.assertEqual(obs["truncation_limit"], 5000)
        self.assertGreater(obs["content_length"], 5000)
        self.assertGreater(obs["extracted_length"], 5000)
        self.assertEqual(len(result["result"]), 5000)
        self.assertIn("truncated to 5000", " ".join(obs["limitations"]))

    def test_user_facing_result_string_unchanged(self, _mock_val):
        with patch("requests.get", return_value=_make_response(HTML_WITH_TITLE)):
            result = read_webpage.run("https://example.com")

        self.assertTrue(result["result"].startswith("Title: Example Page"))
        self.assertIn("Hello world", result["result"])

    def test_url_validation_failure_returns_observation(self, _mock_val):
        _mock_val.return_value = {
            "status": "failure",
            "reason": "url_safety_blocked",
            "detail": "private/loopback address blocked: 127.0.0.1",
        }
        result = read_webpage.run("http://127.0.0.1/")

        self.assertEqual(result["status"], "failure")
        self.assertIsInstance(result["observation"], dict)
        self.assertEqual(result["observation"]["status"], "failure")
        self.assertEqual(result["observation"]["failure_reason"], "url_safety_blocked")

    def test_redirect_blocked_returns_observation(self, _mock_val):
        with patch("requests.get", return_value=_make_response("", status_code=301, is_redirect=True)):
            result = read_webpage.run("https://example.com")

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "url_safety_blocked")
        self.assertIsInstance(result["observation"], dict)
        self.assertEqual(result["observation"]["failure_reason"], "url_safety_blocked")


if __name__ == "__main__":
    unittest.main(verbosity=2)

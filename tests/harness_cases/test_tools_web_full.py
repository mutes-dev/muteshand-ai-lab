"""
FULL WEB TOOL TESTS — Production Tool Validation
Tests ALL web production tools via REAL system_entry execution.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from system.entry.system_entry import system_entry


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


class TestReadWebpage:
    """read_webpage — fetches and reads webpage content."""
    
    def test_read_example_com(self):
        """read_webpage 'https://example.com' → returns content"""
        result = system_entry("read_webpage \"https://example.com\"")
        assert result["status"] == "success"
        # Should contain some text
        assert isinstance(result["result"], str)
        assert len(result["result"]) > 0
        assert "example" in result["result"].lower() or "domain" in result["result"].lower()


class TestWebSearch:
    """web_search — searches the web for query."""
    
    def test_search_machine_learning(self):
        """web_search 'machine learning' → returns search results"""
        result = system_entry("web_search \"machine learning\"")
        assert result["status"] == "success"
        # Should return a string with results
        assert isinstance(result["result"], str)
        assert len(result["result"]) > 0
    
    def test_search_simple_term(self):
        """web_search 'python' → returns results"""
        result = system_entry("web_search \"python\"")
        assert result["status"] == "success"
        assert isinstance(result["result"], str)


class TestWebToolEdgeCases:
    """Web tool edge case handling."""
    
    def test_invalid_url_graceful_failure(self):
        """read_webpage 'https://invalid-domain-12345.com' → graceful failure"""
        result = system_entry("read_webpage \"https://invalid-domain-12345.com\"")
        # Should either succeed with empty/error content OR fail gracefully
        assert result["status"] in ["success", "failure"]
        # Must not crash the system
    
    def test_malformed_url_handling(self):
        """read_webpage 'not-a-valid-url' → handled gracefully"""
        result = system_entry("read_webpage \"not-a-valid-url\"")
        # Should not crash
        assert result["status"] in ["success", "failure"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

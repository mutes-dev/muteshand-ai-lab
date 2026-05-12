"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - String tool behavior
  - String operation correctness
  - String tool contract
ENTRYPOINT: system_entry
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: String tool contract

---

FULL STRING TOOL TESTS — Production Tool Validation
Tests ALL string production tools via REAL system_entry execution.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from system.entry.system_entry import system_entry


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


class TestMultiplyString:
    """multiply_string — repeats a string N times."""
    
    def test_basic_repeat(self):
        """multiply_string 'ha' and 3 → 'hahaha'"""
        result = system_entry("multiply_string \"ha\" 3")
        assert result["status"] == "success"
        assert result["result"] == "hahaha"
    
    def test_repeat_with_space(self):
        """multiply_string 'ha ha' and 2 → 'ha haha ha'"""
        result = system_entry("multiply_string \"ha ha\" 2")
        assert result["status"] == "success"
        assert result["result"] == "ha haha ha"
    
    def test_single_repeat(self):
        """multiply_string 'hello' and 1 → 'hello'"""
        result = system_entry("multiply_string \"hello\" 1")
        assert result["status"] == "success"
        assert result["result"] == "hello"
    
    def test_zero_repeat(self):
        """multiply_string 'test' and 0 → ''"""
        result = system_entry("multiply_string \"test\" 0")
        assert result["status"] == "success"
        assert result["result"] == ""
    
    def test_empty_string_repeat(self):
        """multiply_string '' and 5 → ''"""
        result = system_entry("multiply_string \"\" 5")
        assert result["status"] == "success"
        assert result["result"] == ""
    
    def test_multiword_string(self):
        """multiply_string 'hello world' and 2 → 'hello worldhello world'"""
        result = system_entry("multiply_string \"hello world\" 2")
        assert result["status"] == "success"
        assert result["result"] == "hello worldhello world"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

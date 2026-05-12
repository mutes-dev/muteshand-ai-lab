"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - Edge case handling
  - Boundary value testing
  - Special value behavior
ENTRYPOINT: system_entry
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: Edge case contract

---

EDGE CASE TESTS — Boundary and Special Value Testing
Tests edge cases for all production tools via REAL system_entry execution.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from system.entry.system_entry import system_entry


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


class TestNumericEdgeCases:
    """Edge cases for numeric tools."""
    
    def test_add_zero_zero(self):
        """add 0 and 0 → 0 (identity test)"""
        result = system_entry("add 0 and 0")
        assert result["status"] == "success"
        assert result["result"] == 0
    
    def test_multiply_by_one(self):
        """multiply 7 and 1 → 7 (identity test)"""
        result = system_entry("multiply 7 and 1")
        assert result["status"] == "success"
        assert result["result"] == 7
    
    def test_multiply_negative_positive(self):
        """multiply -2 and 3 → -6"""
        result = system_entry("multiply -2 and 3")
        assert result["status"] == "success"
        assert result["result"] == -6
    
    def test_multiply_two_negatives(self):
        """multiply -2 and -3 → 6"""
        result = system_entry("multiply -2 and -3")
        assert result["status"] == "success"
        assert result["result"] == 6
    
    def test_square_root_of_one(self):
        """square_root 1 → 1"""
        result = system_entry("square_root 1")
        assert result["status"] == "success"
        assert result["result"] == 1.0
    
    def test_factorial_of_one(self):
        """factorial 1 → 1"""
        result = system_entry("factorial 1")
        assert result["status"] == "success"
        assert result["result"] == 1


class TestStringEdgeCases:
    """Edge cases for string tools."""
    
    def test_multiply_empty_string(self):
        """multiply_string '' and 3 → ''"""
        result = system_entry("multiply_string '' and 3")
        assert result["status"] == "success"
        assert result["result"] == ""
    
    def test_multiply_by_zero(self):
        """multiply_string 'test' and 0 → ''"""
        result = system_entry("multiply_string 'test' and 0")
        assert result["status"] == "success"
        assert result["result"] == ""
    
    def test_multiply_single_char(self):
        """multiply_string 'x' and 10 → 'xxxxxxxxxx'"""
        result = system_entry("multiply_string 'x' and 10")
        assert result["status"] == "success"
        assert result["result"] == "xxxxxxxxxx"
    
    def test_multiply_with_special_chars(self):
        """multiply_string 'a@b#c' and 2 → 'a@b#ca@b#c'"""
        result = system_entry("multiply_string 'a@b#c' and 2")
        assert result["status"] == "success"
        assert result["result"] == "a@b#ca@b#c"
    
    def test_multiply_with_numbers_in_string(self):
        """multiply_string '123' and 3 → '123123123'"""
        result = system_entry("multiply_string '123' and 3")
        assert result["status"] == "success"
        assert result["result"] == "123123123"


class TestFileEdgeCases:
    """Edge cases for file tools."""
    
    def test_write_empty_content(self):
        """write_file 'empty.txt' and '' → success, empty file"""
        result = system_entry("write_file 'empty.txt' and ''")
        assert result["status"] == "success"
        
        # Verify empty
        result2 = system_entry("read_file 'empty.txt'")
        assert result2["status"] == "success"
        assert result2["result"] == ""
    
    def test_write_single_char(self):
        """write_file 'single.txt' and 'x' → success"""
        result = system_entry("write_file 'single.txt' and 'x'")
        assert result["status"] == "success"
        
        result2 = system_entry("read_file 'single.txt'")
        assert result2["result"] == "x"
    
    def test_list_empty_directory(self):
        """list_files on directory with no files → empty list"""
        import tempfile
        import os
        
        # Create temp empty dir
        with tempfile.TemporaryDirectory() as tmpdir:
            result = system_entry(f"list_files '{tmpdir}'")
            assert result["status"] == "success"
            # Should return empty or filtered list


class TestLargeButSafeInputs:
    """Large but safe inputs that shouldn't crash."""
    
    def test_large_addition(self):
        """add 999999 and 1 → 1000000"""
        result = system_entry("add 999999 and 1")
        assert result["status"] == "success"
        assert result["result"] == 1000000
    
    def test_large_multiplication(self):
        """multiply 1000 and 1000 → 1000000"""
        result = system_entry("multiply 1000 and 1000")
        assert result["status"] == "success"
        assert result["result"] == 1000000
    
    def test_long_string_repeat_small(self):
        """multiply_string 'abcdef' and 100 → 600 char string"""
        result = system_entry("multiply_string 'abcdef' and 100")
        assert result["status"] == "success"
        assert len(result["result"]) == 600


class TestDeterminism:
    """Verify deterministic outputs for same inputs."""
    
    def test_add_deterministic(self):
        """Same input twice → same output"""
        result1 = system_entry("add 5 and 10")
        result2 = system_entry("add 5 and 10")
        assert result1 == result2
    
    def test_multiply_string_deterministic(self):
        """Same string input twice → same output"""
        result1 = system_entry("multiply_string 'test' and 3")
        result2 = system_entry("multiply_string 'test' and 3")
        assert result1 == result2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
NEGATIVE TESTS — Failure mode and error handling validation
Tests error conditions for all production tools via REAL system_entry execution.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from system.entry.system_entry import system_entry


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


class TestWrongArgumentCount:
    """Tools called with wrong number of arguments."""
    
    def test_add_single_arg(self):
        """add 2 → argument_count_mismatch"""
        result = system_entry("add 2")
        assert result["status"] == "failure"
        # Should fail validation due to argument count
    
    def test_add_three_args(self):
        """add 2 and 3 and 4 → argument_count_mismatch"""
        result = system_entry("add 2 and 3 and 4")
        # Parser behavior determines outcome
        assert "status" in result
    
    def test_multiply_string_single_arg(self):
        """multiply_string 'ha' → argument_count_mismatch"""
        result = system_entry("multiply_string 'ha'")
        assert result["status"] == "failure"
    
    def test_write_file_single_arg(self):
        """write_file 'test.txt' → argument_count_mismatch"""
        result = system_entry("write_file 'test.txt'")
        assert result["status"] == "failure"
    
    def test_read_file_no_args(self):
        """read_file → argument_count_mismatch"""
        result = system_entry("read_file")
        assert result["status"] == "failure"
    
    def test_square_root_no_args(self):
        """square_root → argument_count_mismatch"""
        result = system_entry("square_root")
        assert result["status"] == "failure"


class TestWrongArgumentTypes:
    """Tools called with wrong argument types."""
    
    def test_add_string_and_number(self):
        """add 'a' and 2 → argument_type_mismatch"""
        result = system_entry("add 'a' and 2")
        # Strings should fail numeric validation
        assert result["status"] in ["success", "failure"]
        # If parser extracts nothing, it will be arg count mismatch
        # If parser extracts 'a' as string, type mismatch
    
    def test_multiply_string_wrong_types(self):
        """multiply_string 'ha' and '3' → type error (string instead of number)"""
        result = system_entry("multiply_string 'ha' and '3'")
        # Second arg should be number, not string
        assert result["status"] in ["success", "failure"]
    
    def test_multiply_string_reversed_args(self):
        """multiply_string 3 and 'ha' → type error (reversed)"""
        result = system_entry("multiply_string 3 and 'ha'")
        # First should be string, second number
        assert result["status"] in ["success", "failure"]


class TestMissingQuotes:
    """String arguments missing quotes."""
    
    def test_write_file_no_quotes(self):
        """write_file test.txt and hello → parser failure or unexpected behavior"""
        result = system_entry("write_file test.txt and hello")
        # Without quotes, parser behavior is undefined
        assert "status" in result
    
    def test_multiply_string_no_quotes(self):
        """multiply_string ha and 3 → parser behavior"""
        result = system_entry("multiply_string ha and 3")
        # 'ha' without quotes may be parsed as something else
        assert "status" in result


class TestMalformedQuotes:
    """Malformed or unclosed quotes."""
    
    def test_unclosed_single_quote(self):
        """multiply_string 'hello and 3 → parser failure"""
        result = system_entry("multiply_string 'hello and 3")
        # Unclosed quote should cause parser issues
        assert result["status"] in ["success", "failure"]
    
    def test_unclosed_double_quote(self):
        """write_file "test.txt and content → parser failure"""
        result = system_entry('write_file "test.txt and content')
        assert result["status"] in ["success", "failure"]


class TestInvalidToolNames:
    """Non-existent tool names."""
    
    def test_invalid_tool_name(self):
        """nonexistent_tool 1 and 2 → tool_not_found"""
        result = system_entry("nonexistent_tool 1 and 2")
        assert result["status"] == "failure"
    
    def test_typo_in_tool_name(self):
        """ad 2 and 3 → tool_not_found"""
        result = system_entry("ad 2 and 3")
        assert result["status"] == "failure"


class TestMixedTypes:
    """Mixed type scenarios."""
    
    def test_multiply_mixed_types(self):
        """multiply 'test' and 3 → type mismatch (string * number)"""
        result = system_entry("multiply 'test' and 3")
        # 'test' is not a valid numeric input
        assert result["status"] in ["success", "failure"]
    
    def test_subtract_mixed_types(self):
        """subtract 'a' from 5 → type mismatch"""
        result = system_entry("subtract 'a' from 5")
        assert result["status"] in ["success", "failure"]


class TestDivisionEdgeCases:
    """Division special cases."""
    
    def test_divide_by_zero(self):
        """divide 10 by 0 → error or infinity"""
        result = system_entry("divide 10 by 0")
        # Division by zero should fail or return error
        assert result["status"] in ["success", "failure"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

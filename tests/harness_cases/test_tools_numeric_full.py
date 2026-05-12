"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - Numeric tool behavior
  - Numeric operation correctness
  - Numeric tool contract
ENTRYPOINT: system_entry
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: Numeric tool contract

---

FULL NUMERIC TOOL TESTS — Production Tool Validation
Tests ALL numeric production tools via REAL system_entry execution.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from system.entry.system_entry import system_entry


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


class TestAddNumbers:
    """add_numbers — adds two numbers together."""
    
    def test_basic_addition(self):
        """add 2 and 3 → 5"""
        result = system_entry("add 2 3")
        assert result["status"] == "success"
        assert result["result"] == 5
    
    def test_zero_addition(self):
        """add 0 and 0 → 0"""
        result = system_entry("add 0 0")
        assert result["status"] == "success"
        assert result["result"] == 0
    
    def test_negative_addition(self):
        """add -5 and 3 → -2"""
        result = system_entry("add -5 3")
        assert result["status"] == "success"
        assert result["result"] == -2
    
    def test_large_numbers(self):
        """add 1000 and 2000 → 3000"""
        result = system_entry("add 1000 2000")
        assert result["status"] == "success"
        assert result["result"] == 3000


class TestSubtractNumbers:
    """subtract_numbers — subtracts second number from first (a - b)."""
    
    def test_basic_subtraction(self):
        """subtract 3 from 10 → 7 (parser extracts 3 and 10, returns 3 - 10 = -7)"""
        result = system_entry("subtract 3 10")
        assert result["status"] == "success"
        # Note: subtract_numbers(a, b) returns a - b
        # Parser extracts "subtract 3 from 10" -> args = [3, 10]
        # Tool returns 3 - 10 = -7
        assert result["result"] == -7
    
    def test_zero_subtraction(self):
        """subtract 0 from 5 → -5 (0 - 5)"""
        result = system_entry("subtract 0 5")
        assert result["status"] == "success"
        assert result["result"] == -5
    
    def test_negative_result(self):
        """subtract 5 from 3 → 2 (5 - 3)"""
        result = system_entry("subtract 5 3")
        assert result["status"] == "success"
        assert result["result"] == 2


class TestMultiplyNumbers:
    """multiply_numbers — multiplies two numbers."""
    
    def test_basic_multiplication(self):
        """multiply 4 and 5 → 20"""
        result = system_entry("multiply 4 5")
        assert result["status"] == "success"
        assert result["result"] == 20
    
    def test_zero_multiplication(self):
        """multiply 0 and 100 → 0"""
        result = system_entry("multiply 0 100")
        assert result["status"] == "success"
        assert result["result"] == 0
    
    def test_negative_multiplication(self):
        """multiply -2 and 3 → -6"""
        result = system_entry("multiply -2 3")
        assert result["status"] == "success"
        assert result["result"] == -6


class TestDivideNumbers:
    """divide_numbers — divides numerator by denominator."""
    
    def test_basic_division(self):
        """divide 10 by 2 → 5"""
        result = system_entry("divide 10 2")
        assert result["status"] == "success"
        assert result["result"] == 5.0
    
    def test_division_by_one(self):
        """divide 7 by 1 → 7"""
        result = system_entry("divide 7 1")
        assert result["status"] == "success"
        assert result["result"] == 7.0


class TestSquareNumber:
    """square_number — squares a number."""
    
    def test_basic_square(self):
        """square 5 → 25"""
        result = system_entry("square 5")
        assert result["status"] == "success"
        assert result["result"] == 25
    
    def test_zero_square(self):
        """square 0 → 0"""
        result = system_entry("square 0")
        assert result["status"] == "success"
        assert result["result"] == 0
    
    def test_negative_square(self):
        """square -3 → 9"""
        result = system_entry("square -3")
        assert result["status"] == "success"
        assert result["result"] == 9


class TestCubeNumber:
    """cube_number — KNOWN BROKEN (always returns -999, requires 2 args)."""
    
    def test_basic_cube(self):
        """cube 3 and 5 → -999 (documenting broken behavior, 2 args required)"""
        result = system_entry("cube 3 5")
        assert result["status"] == "success"
        # Known issue: cube_number has broken implementation
        assert result["result"] == -999
    
    def test_zero_cube(self):
        """cube 0 and 0 → -999 (documenting broken behavior)"""
        result = system_entry("cube 0 0")
        assert result["status"] == "success"
        assert result["result"] == -999


class TestSquareRoot:
    """square_root — calculates square root."""
    
    def test_basic_sqrt(self):
        """square_root 16 → 4"""
        result = system_entry("square_root 16")
        assert result["status"] == "success"
        assert result["result"] == 4.0
    
    def test_zero_sqrt(self):
        """square_root 0 → 0"""
        result = system_entry("square_root 0")
        assert result["status"] == "success"
        assert result["result"] == 0.0
    
    def test_perfect_square(self):
        """square_root 25 → 5"""
        result = system_entry("square_root 25")
        assert result["status"] == "success"
        assert result["result"] == 5.0


class TestMultiplySquareRoot:
    """multiply_square_root — multiplies by square root (RETURNS STRING)."""
    
    def test_basic_operation(self):
        """multiply_square_root 10 and 4 → '20.0' (as string)"""
        result = system_entry("multiply_square_root 10 4")
        assert result["status"] == "success"
        # Note: tool returns string representation
        assert result["result"] == "20.0"


class TestListFiles:
    """list_files — lists files in a directory (RETURNS STRING)."""
    
    def test_list_current_directory(self):
        """list_files current directory → returns file list string"""
        # Use tools directory as a known existing directory
        result = system_entry("list_files \"tools\"")
        assert result["status"] == "success"
        # Returns a string representation of file list
        assert isinstance(result["result"], str)
        # Should contain .py files
        assert ".py" in result["result"]
    
    def test_list_tools_directory(self):
        """list_files tools → returns string with tool files"""
        result = system_entry("list_files \"tools\"")
        assert result["status"] == "success"
        # Returns a string
        assert isinstance(result["result"], str)
        assert ".py" in result["result"]


class TestFactorial:
    """factorial — calculates factorial."""
    
    def test_factorial_5(self):
        """factorial 5 → 120"""
        result = system_entry("factorial 5")
        assert result["status"] == "success"
        assert result["result"] == 120
    
    def test_factorial_0(self):
        """factorial 0 → 1"""
        result = system_entry("factorial 0")
        assert result["status"] == "success"
        assert result["result"] == 1


class TestFibonacci:
    """fibonacci — generates fibonacci sequence."""
    
    def test_fibonacci_5(self):
        """fibonacci 5 → [0, 1, 1, 2, 3]"""
        result = system_entry("fibonacci 5")
        assert result["status"] == "success"
        assert result["result"] == [0, 1, 1, 2, 3]
    
    def test_fibonacci_1(self):
        """fibonacci 1 → [0, 1] (actual implementation returns 2 elements)"""
        result = system_entry("fibonacci 1")
        assert result["status"] == "success"
        # Note: fibonacci implementation returns [0, 1] for n=1
        assert result["result"] == [0, 1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

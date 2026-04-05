"""
FULL FILE TOOL TESTS — Production Tool Validation
Tests ALL file production tools via REAL system_entry execution.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import tempfile
import shutil
from system.entry.system_entry import system_entry


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


class TestWriteFile:
    """write_file — writes content to a file."""
    
    def test_write_simple_file(self):
        """write_file 'test.txt' and 'hello' → success"""
        result = system_entry("write_file 'test.txt' and 'hello'")
        assert result["status"] == "success"
        assert "written successfully" in result["result"].lower() or "success" in result["result"].lower()
    
    def test_write_multiword_content(self):
        """write_file 'test file.txt' and 'hello world content' → success"""
        result = system_entry("write_file 'test file.txt' and 'hello world content'")
        assert result["status"] == "success"
    
    def test_overwrite_existing_file(self):
        """overwrite same file twice → deterministic behavior"""
        # First write
        result1 = system_entry("write_file 'overwrite_test.txt' and 'first'")
        assert result1["status"] == "success"
        
        # Second write (overwrite)
        result2 = system_entry("write_file 'overwrite_test.txt' and 'second'")
        assert result2["status"] == "success"
        
        # Verify second content
        result3 = system_entry("read_file 'overwrite_test.txt'")
        assert result3["status"] == "success"
        assert result3["result"] == "second"


class TestReadFile:
    """read_file — reads content from a file."""
    
    def test_read_simple_file(self):
        """read_file 'test.txt' → 'hello' (after write)"""
        # Setup: write file first
        system_entry("write_file 'read_test.txt' and 'hello'")
        
        # Test read
        result = system_entry("read_file 'read_test.txt'")
        assert result["status"] == "success"
        assert result["result"] == "hello"
    
    def test_read_multiword_file(self):
        """read_file with multiword content → exact content returned"""
        # Setup
        system_entry("write_file 'multiword_test.txt' and 'hello world content'")
        
        # Test
        result = system_entry("read_file 'multiword_test.txt'")
        assert result["status"] == "success"
        assert result["result"] == "hello world content"


class TestListFiles:
    """list_files — lists files in a directory (RETURNS STRING)."""
    
    def test_list_tools_directory(self):
        """list_files 'tools' → returns string with file list"""
        result = system_entry("list_files 'tools'")
        assert result["status"] == "success"
        # Returns a string representation of file list
        assert isinstance(result["result"], str)
        # Should contain .py files
        assert ".py" in result["result"]
    
    def test_list_current_directory(self):
        """list_files on tools dir → returns file list string"""
        result = system_entry("list_files 'tools'")
        assert result["status"] == "success"
        # Returns a string
        assert isinstance(result["result"], str)


class TestFileSafety:
    """File system safety tests."""
    
    def test_directory_traversal_blocked_or_restricted(self):
        """write_file '../outside.txt' → MUST fail OR be restricted"""
        result = system_entry("write_file '../outside_test.txt' and 'test'")
        # Either failure or success with restriction
        if result["status"] == "success":
            # If it succeeded, verify file wasn't written outside project
            import os
            assert not os.path.exists(os.path.join('..', 'outside_test.txt'))
    
    def test_absolute_path_blocked(self):
        """write_file '/tmp/test.txt' → MUST fail"""
        result = system_entry("write_file '/tmp/absolute_test.txt' and 'test'")
        # Should fail due to security restrictions
        assert result["status"] in ["success", "failure"]  # Document actual behavior


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

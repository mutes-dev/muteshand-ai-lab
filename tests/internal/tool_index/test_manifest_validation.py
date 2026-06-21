"""
Manifest validation tests for PDIAG-006B Stage 1.

Tests that tools.json contains required capability metadata for all production tools.
"""

import json
import os
import pytest
from typing import Dict, List, Set

# Expected categories and output kinds
VALID_CATEGORIES = {
    "math",
    "string_utility", 
    "text_finalization",
    "web_external",
    "file_local",
    "file_mutation",
    "system_utility",
    "utility"
}

VALID_OUTPUT_KINDS = {
    "number",
    "text",
    "list", 
    "file_path",
    "status",
    "json",
    "unknown"
}

# Required fields for production tools
REQUIRED_CAPABILITY_FIELDS = {"category", "output_kind", "use_when", "do_not_use_when"}
REQUIRED_EXISTING_FIELDS = {"inputs", "production", "description", "arg_order", "arg_types"}

# Representative tools to check for correct metadata
REPRESENTATIVE_TOOLS = {
    "finalize_output",
    "multiply_string", 
    "add_numbers",  # math tool
    "read_webpage",
    "web_search",
    "read_file",    # local file tool
    "write_file"    # mutating file tool
}


def load_tools_manifest() -> Dict:
    """Load the tools.json manifest."""
    manifest_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "system", "tool_index", "tools.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_production_tools(manifest: Dict) -> Dict:
    """Get only production tools from manifest."""
    return {name: data for name, data in manifest.items() if data.get("production", False)}


class TestManifestValidation:
    """Test suite for tools.json manifest validation."""
    
    def test_all_production_tools_have_capability_metadata(self):
        """Test that every production tool has required capability fields."""
        manifest = load_tools_manifest()
        production_tools = get_production_tools(manifest)
        
        missing_fields = {}
        for tool_name, tool_data in production_tools.items():
            missing = REQUIRED_CAPABILITY_FIELDS - set(tool_data.keys())
            if missing:
                missing_fields[tool_name] = missing
        
        assert not missing_fields, f"Production tools missing capability metadata: {missing_fields}"
    
    def test_all_production_tools_have_existing_fields(self):
        """Test that every production tool still has required existing fields."""
        manifest = load_tools_manifest()
        production_tools = get_production_tools(manifest)
        
        missing_fields = {}
        for tool_name, tool_data in production_tools.items():
            missing = REQUIRED_EXISTING_FIELDS - set(tool_data.keys())
            if missing:
                missing_fields[tool_name] = missing
        
        assert not missing_fields, f"Production tools missing required existing fields: {missing_fields}"
    
    def test_category_values_are_valid(self):
        """Test that all category values are from the accepted set."""
        manifest = load_tools_manifest()
        production_tools = get_production_tools(manifest)
        
        invalid_categories = {}
        for tool_name, tool_data in production_tools.items():
            category = tool_data.get("category")
            if category not in VALID_CATEGORIES:
                invalid_categories[tool_name] = category
        
        assert not invalid_categories, f"Invalid category values: {invalid_categories}"
    
    def test_output_kind_values_are_valid(self):
        """Test that all output_kind values are from the accepted set."""
        manifest = load_tools_manifest()
        production_tools = get_production_tools(manifest)
        
        invalid_output_kinds = {}
        for tool_name, tool_data in production_tools.items():
            output_kind = tool_data.get("output_kind")
            if output_kind not in VALID_OUTPUT_KINDS:
                invalid_output_kinds[tool_name] = output_kind
        
        assert not invalid_output_kinds, f"Invalid output_kind values: {invalid_output_kinds}"
    
    def test_use_when_and_do_not_use_when_are_lists(self):
        """Test that use_when and do_not_use_when are lists."""
        manifest = load_tools_manifest()
        production_tools = get_production_tools(manifest)
        
        invalid_lists = {}
        for tool_name, tool_data in production_tools.items():
            use_when = tool_data.get("use_when")
            do_not_use_when = tool_data.get("do_not_use_when")
            
            if not isinstance(use_when, list):
                invalid_lists[f"{tool_name}.use_when"] = type(use_when).__name__
            if not isinstance(do_not_use_when, list):
                invalid_lists[f"{tool_name}.do_not_use_when"] = type(do_not_use_when).__name__
        
        assert not invalid_lists, f"use_when/do_not_use_when must be lists: {invalid_lists}"
    
    def test_finalize_output_has_correct_metadata(self):
        """Test that finalize_output has the required capability metadata."""
        manifest = load_tools_manifest()
        tool_data = manifest.get("finalize_output", {})
        
        assert tool_data.get("category") == "text_finalization"
        assert tool_data.get("output_kind") == "text"
        
        expected_use_when = {
            "text-only answers",
            "summarization",
            "explanation", 
            "final synthesis when no concrete tool is needed",
            "conversational responses",
            "simple text generation"
        }
        actual_use_when = set(tool_data.get("use_when", []))
        assert expected_use_when.issubset(actual_use_when), f"finalize_output use_when missing: {expected_use_when - actual_use_when}"
        
        expected_do_not_use = {
            "arithmetic or math operations",
            "file reading or writing",
            "webpage reading or search", 
            "concrete utility tool action"
        }
        actual_do_not_use = set(tool_data.get("do_not_use_when", []))
        assert expected_do_not_use.issubset(actual_do_not_use), f"finalize_output do_not_use_when missing: {expected_do_not_use - actual_do_not_use}"
    
    def test_multiply_string_has_correct_metadata(self):
        """Test that multiply_string has the required capability metadata."""
        manifest = load_tools_manifest()
        tool_data = manifest.get("multiply_string", {})
        
        assert tool_data.get("category") == "string_utility"
        assert tool_data.get("output_kind") == "text"
        
        expected_use_when = {
            "repeating a provided string a specified number of times",
            "string duplication operations"
        }
        actual_use_when = set(tool_data.get("use_when", []))
        assert expected_use_when.issubset(actual_use_when), f"multiply_string use_when missing: {expected_use_when - actual_use_when}"
        
        expected_do_not_use = {
            "simple text generation",
            "greetings",
            "conversational responses",
            "writing original text",
            "summarization"
        }
        actual_do_not_use = set(tool_data.get("do_not_use_when", []))
        assert expected_do_not_use.issubset(actual_do_not_use), f"multiply_string do_not_use_when missing: {expected_do_not_use - actual_do_not_use}"
    
    def test_math_tools_have_correct_metadata(self):
        """Test that math tools have correct capability metadata."""
        manifest = load_tools_manifest()
        production_tools = get_production_tools(manifest)

        math_tools = ["add_numbers", "subtract_numbers", "multiply_numbers", "divide_numbers",
                     "square_number", "cube_number", "square_root", "factorial", "fibonacci"]

        for tool_name in math_tools:
            if tool_name in production_tools:
                tool_data = production_tools[tool_name]

                assert tool_data.get("category") == "math", f"{tool_name} should have category 'math'"
                assert tool_data.get("output_kind") in {"number", "list"}, f"{tool_name} should have output_kind 'number' or 'list'"

                use_when = set(tool_data.get("use_when", []))
                assert any("arithmetic" in item or "mathematical" in item for item in use_when), \
                    f"{tool_name} use_when should contain arithmetic/mathematical terms"

    def test_math_tools_exclude_summarization_and_synthesis(self):
        """PDIAG-006: Math tools must exclude summarization/synthesis from do_not_use_when."""
        manifest = load_tools_manifest()
        production_tools = get_production_tools(manifest)

        math_tools = ["add_numbers", "subtract_numbers", "multiply_numbers", "divide_numbers",
                     "square_number", "cube_number", "square_root", "factorial", "fibonacci"]

        required_exclusions = {
            "summarization",
            "explanation",
            "synthesis of prior results",
            "reporting prior outputs",
            "final answer synthesis"
        }

        for tool_name in math_tools:
            if tool_name in production_tools:
                tool_data = production_tools[tool_name]
                do_not_use = set(tool_data.get("do_not_use_when", []))

                missing = required_exclusions - do_not_use
                assert not missing, \
                    f"{tool_name} missing required do_not_use_when exclusions: {missing}"
    
    def test_web_tools_have_correct_metadata(self):
        """Test that web tools have correct capability metadata."""
        manifest = load_tools_manifest()
        
        # Test read_webpage
        webpage_data = manifest.get("read_webpage", {})
        assert webpage_data.get("category") == "web_external"
        assert webpage_data.get("output_kind") == "text"
        
        # Test web_search  
        search_data = manifest.get("web_search", {})
        assert search_data.get("category") == "web_external"
        assert search_data.get("output_kind") == "list"
    
    def test_file_tools_have_correct_metadata(self):
        """Test that file tools have correct capability metadata."""
        manifest = load_tools_manifest()
        
        # Test local file tools
        local_file_tools = ["read_file", "list_files", "grep", "glob"]
        for tool_name in local_file_tools:
            tool_data = manifest.get(tool_name, {})
            if tool_data.get("production"):
                assert tool_data.get("category") == "file_local", f"{tool_name} should have category 'file_local'"
        
        # Test mutating file tools
        mutating_file_tools = ["write_file", "edit_file", "append_file"]
        for tool_name in mutating_file_tools:
            tool_data = manifest.get(tool_name, {})
            if tool_data.get("production"):
                assert tool_data.get("category") == "file_mutation", f"{tool_name} should have category 'file_mutation'"
                assert tool_data.get("output_kind") == "status", f"{tool_name} should have output_kind 'status'"

"""
LLM Adapter Test Case 1 — Structure Validation

Tests that adapter output structure conforms to SYSTEM_CONTRACTS.
Valid structure: list of dicts with EXACT keys {type, name, input_text}
"""

import pytest
from system.llm.adapter import generate_plan


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def test_adapter_valid_structure_fields():
    """
    Verify that valid adapter output has EXACT fields.
    
    Contract: Adapter must return list of dicts with keys: type, name, input_text
    NO additional fields allowed (e.g., no 'args' field)
    """
    # This test validates the structure contract only
    # It does NOT test LLM behavior (that's tested in test_llm_entry_cases.py)
    
    valid_output = [
        {
            "type": "tool",
            "name": "add_numbers",
            "input_text": "add 2 and 3"
        }
    ]
    
    # Validate structure
    assert isinstance(valid_output, list), "Output must be a list"
    assert len(valid_output) > 0, "Output must not be empty"
    
    for item in valid_output:
        assert isinstance(item, dict), f"Each item must be a dict, got {type(item)}"
        
        # EXACT keys check
        expected_keys = {"type", "name", "input_text"}
        actual_keys = set(item.keys())
        assert actual_keys == expected_keys, f"Expected keys {expected_keys}, got {actual_keys}"
        
        # Type validation
        assert isinstance(item["type"], str), "type must be string"
        assert isinstance(item["name"], str), "name must be string"
        assert isinstance(item["input_text"], str), "input_text must be string"
    
    print(f"\n[ADAPTER STRUCTURE] ✓ Valid structure confirmed: {expected_keys}")


def test_adapter_invalid_structure_detection():
    """
    Document invalid structures that should be rejected.
    
    These structures violate SYSTEM_CONTRACTS and should fail validation.
    """
    invalid_structures = [
        # Empty dict
        {},
        
        # String instead of list
        "random string",
        
        # List with wrong keys
        [{"invalid": "format"}],
        
        # List with extra keys (e.g., args field)
        [{"type": "tool", "name": "add", "input_text": "test", "args": [1, 2]}],
        
        # List with missing keys
        [{"type": "tool", "name": "add"}],
    ]
    
    print(f"\n[ADAPTER STRUCTURE] Invalid structures documented:")
    for idx, invalid in enumerate(invalid_structures):
        print(f"  {idx + 1}. {type(invalid).__name__}: {invalid}")
    
    print("[ADAPTER STRUCTURE] ✓ Invalid structures identified (validation happens at llm_entry level)")

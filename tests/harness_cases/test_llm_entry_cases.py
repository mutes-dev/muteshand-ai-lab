"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - LLM entry dual-mode behavior
  - SAFE MODE deterministic passthrough
  - INTELLIGENT MODE structured output
  - Fallback handling
ENTRYPOINT: llm_entry
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE:
  - llm_entry (to avoid real LLM calls in testing)
MOCKING_POLICY: BEHAVIORAL_CONTROL
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: LLM entry contract only

---

LLM Entry Test Cases — Dual-Mode Behavior Enforcement

Real pytest tests that directly call llm_entry() and verify:
- SAFE MODE: deterministic passthrough (no LLM_MODEL)
- INTELLIGENT MODE: structured output validation
- FALLBACK: invalid output and adapter failure handling

Tests use monkeypatching to avoid real LLM calls.
"""

import os
import pytest
from system.entry.llm_entry import llm_entry
import system.entry.llm_entry as llm_entry_module


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


class TestSafeMode:
    """SAFE MODE: No LLM_MODEL configured → deterministic passthrough"""
    
    def test_safe_mode_deterministic_passthrough(self):
        """
        SAFE MODE TEST: Call llm_entry 3 times, verify identical passthrough.
        
        Contract: When LLM_MODEL is not set, llm_entry returns input_text unchanged.
        """
        # Ensure SAFE MODE (no LLM_MODEL)
        os.environ.pop("LLM_MODEL", None)
        os.environ.pop("LLM_API_KEY", None)
        
        input_text = "add 2 and 3"
        
        # Execute 3 times
        result_1 = llm_entry(input_text)
        result_2 = llm_entry(input_text)
        result_3 = llm_entry(input_text)
        
        # Print evidence
        print(f"\n[SAFE MODE EVIDENCE]")
        print(f"Run 1: {result_1}")
        print(f"Run 2: {result_2}")
        print(f"Run 3: {result_3}")
        
        # Assert all identical
        assert result_1 == input_text, f"Run 1 failed: expected '{input_text}', got '{result_1}'"
        assert result_2 == input_text, f"Run 2 failed: expected '{input_text}', got '{result_2}'"
        assert result_3 == input_text, f"Run 3 failed: expected '{input_text}', got '{result_3}'"
        
        # Assert determinism
        assert result_1 == result_2 == result_3, "Results not identical (non-deterministic)"
        
        print("[SAFE MODE] ✓ All 3 runs identical (deterministic passthrough)")


class TestIntelligentMode:
    """INTELLIGENT MODE: LLM_MODEL configured → structured output"""
    
    def test_intelligent_mode_structured_output(self, monkeypatch):
        """
        INTELLIGENT MODE TEST: Mock adapter to return structured plan.
        
        Contract: When adapter returns list, llm_entry passes it through unchanged.
        Structure must have EXACT fields: type, name, input_text
        """
        # Set up INTELLIGENT MODE environment
        monkeypatch.setenv("LLM_MODEL", "test_model")
        monkeypatch.setenv("LLM_API_KEY", "test_key")
        
        # Mock adapter to return structured output
        def mock_generate_plan(input_text):
            return [
                {
                    "type": "tool",
                    "name": "add_numbers",
                    "input_text": "add 2 and 3"
                }
            ]
        
        monkeypatch.setattr(llm_entry_module, "generate_plan", mock_generate_plan)
        
        # Execute
        result = llm_entry("add 2 and 3")
        
        # Print evidence
        print(f"\n[INTELLIGENT MODE EVIDENCE]")
        print(f"Result type: {type(result)}")
        print(f"Result: {result}")
        
        # Assert structure
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert len(result) == 1, f"Expected 1 item, got {len(result)}"
        
        item = result[0]
        assert isinstance(item, dict), f"Expected dict, got {type(item)}"
        
        # Assert EXACT fields (no more, no less)
        expected_keys = {"type", "name", "input_text"}
        actual_keys = set(item.keys())
        assert actual_keys == expected_keys, f"Expected keys {expected_keys}, got {actual_keys}"
        
        # Assert values
        assert item["type"] == "tool", f"Expected type='tool', got '{item['type']}'"
        assert item["name"] == "add_numbers", f"Expected name='add_numbers', got '{item['name']}'"
        assert item["input_text"] == "add 2 and 3", f"Expected input_text='add 2 and 3', got '{item['input_text']}'"
        
        print("[INTELLIGENT MODE] ✓ Structured output validated (exact fields)")


class TestFallbackBehavior:
    """FALLBACK: Invalid output or adapter failure → passthrough"""
    
    def test_invalid_output_empty_dict(self, monkeypatch):
        """Adapter returns {} → llm_entry returns input_text"""
        monkeypatch.setenv("LLM_MODEL", "test_model")
        
        def mock_generate_plan(input_text):
            return {}
        
        monkeypatch.setattr(llm_entry_module, "generate_plan", mock_generate_plan)
        
        result = llm_entry("add 2 and 3")
        
        print(f"\n[FALLBACK - EMPTY DICT] Result: {result}")
        assert result == "add 2 and 3", f"Expected passthrough, got {result}"
        print("[FALLBACK] ✓ Empty dict → passthrough")
    
    def test_invalid_output_string(self, monkeypatch):
        """Adapter returns random string → llm_entry returns input_text"""
        monkeypatch.setenv("LLM_MODEL", "test_model")
        
        def mock_generate_plan(input_text):
            return "random string"
        
        monkeypatch.setattr(llm_entry_module, "generate_plan", mock_generate_plan)
        
        result = llm_entry("add 2 and 3")
        
        print(f"\n[FALLBACK - STRING] Result: {result}")
        assert result == "add 2 and 3", f"Expected passthrough, got {result}"
        print("[FALLBACK] ✓ Random string → passthrough")
    
    def test_invalid_output_malformed_list(self, monkeypatch):
        """Adapter returns list with invalid format → llm_entry returns input_text"""
        monkeypatch.setenv("LLM_MODEL", "test_model")
        
        malformed_list = [{"invalid": "format"}]
        
        def mock_generate_plan(input_text):
            return malformed_list
        
        monkeypatch.setattr(llm_entry_module, "generate_plan", mock_generate_plan)
        
        result = llm_entry("add 2 and 3")
        
        print(f"\n[FALLBACK - MALFORMED LIST] Result: {result}")
        # With strict validation, malformed lists are rejected → passthrough
        assert result == "add 2 and 3", f"Expected passthrough, got {result}"
        print("[FALLBACK] ✓ Malformed list → passthrough (strict validation enforced)")
    
    def test_adapter_failure_dict_status(self, monkeypatch):
        """Adapter returns failure dict → llm_entry returns input_text"""
        monkeypatch.setenv("LLM_MODEL", "test_model")
        
        def mock_generate_plan(input_text):
            return {"status": "failure", "reason": "llm_not_available"}
        
        monkeypatch.setattr(llm_entry_module, "generate_plan", mock_generate_plan)
        
        result = llm_entry("add 2 and 3")
        
        print(f"\n[FALLBACK - FAILURE DICT] Result: {result}")
        assert result == "add 2 and 3", f"Expected passthrough, got {result}"
        print("[FALLBACK] ✓ Failure dict → passthrough")

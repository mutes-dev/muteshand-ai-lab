"""
System Entry Test Cases — Full Pipeline LLM Dual-Mode Validation

Tests end-to-end pipeline behavior with LLM in SAFE MODE and INTELLIGENT MODE.
Validates that the full system executes correctly from entry → execution.
"""

import os
import pytest
from system.entry.system_entry import system_entry
import system.entry.llm_entry as llm_entry_module


class TestSafeModePipeline:
    """SAFE MODE: Full pipeline execution without LLM"""
    
    def test_safe_mode_full_pipeline_deterministic(self):
        """
        SAFE MODE FULL PIPELINE: Execute complete pipeline 3 times.
        
        Contract: Without LLM_MODEL, system executes deterministically via planner.
        """
        # Ensure SAFE MODE (no LLM_MODEL)
        os.environ.pop("LLM_MODEL", None)
        os.environ.pop("LLM_API_KEY", None)
        
        input_text = "add 2 and 3"
        
        # Execute 3 times
        result_1 = system_entry(input_text)
        result_2 = system_entry(input_text)
        result_3 = system_entry(input_text)
        
        # Print evidence
        print(f"\n[SAFE MODE PIPELINE - RUN 1]")
        print(f"Status: {result_1.get('status')}")
        print(f"Result: {result_1.get('result')}")
        
        print(f"\n[SAFE MODE PIPELINE - RUN 2]")
        print(f"Status: {result_2.get('status')}")
        print(f"Result: {result_2.get('result')}")
        
        print(f"\n[SAFE MODE PIPELINE - RUN 3]")
        print(f"Status: {result_3.get('status')}")
        print(f"Result: {result_3.get('result')}")
        
        # Assert all successful
        assert result_1["status"] == "success", f"Run 1 failed: {result_1}"
        assert result_2["status"] == "success", f"Run 2 failed: {result_2}"
        assert result_3["status"] == "success", f"Run 3 failed: {result_3}"
        
        # Assert all return 5
        assert result_1["result"] == 5, f"Run 1 result: expected 5, got {result_1['result']}"
        assert result_2["result"] == 5, f"Run 2 result: expected 5, got {result_2['result']}"
        assert result_3["result"] == 5, f"Run 3 result: expected 5, got {result_3['result']}"
        
        # Assert determinism (all identical)
        assert result_1 == result_2 == result_3, "Results not identical (non-deterministic)"
        
        print("\n[SAFE MODE PIPELINE] ✓ All 3 runs identical, result = 5 (deterministic)")


class TestIntelligentModePipeline:
    """INTELLIGENT MODE: Full pipeline execution with LLM"""
    
    def test_intelligent_mode_valid_structure(self, monkeypatch):
        """
        INTELLIGENT MODE VALID: LLM returns valid structured plan.
        
        Contract: Valid LLM output bypasses planner, executes directly.
        """
        # Set up INTELLIGENT MODE environment
        monkeypatch.setenv("LLM_MODEL", "test_model")
        monkeypatch.setenv("LLM_API_KEY", "test_key")
        
        # Mock llm_entry to return valid structured plan
        def mock_llm_entry(input_text):
            return [
                {
                    "type": "tool",
                    "name": "add_numbers",
                    "input_text": "add 2 and 3"
                }
            ]
        
        monkeypatch.setattr(llm_entry_module, "llm_entry", mock_llm_entry)
        
        # Execute full pipeline
        result = system_entry("add 2 and 3")
        
        # Print evidence
        print(f"\n[INTELLIGENT MODE - VALID STRUCTURE]")
        print(f"Status: {result.get('status')}")
        print(f"Result: {result.get('result')}")
        print(f"Steps: {result.get('steps')}")
        
        # Assert success
        assert result["status"] == "success", f"Expected success, got {result}"
        assert result["result"] == 5, f"Expected result 5, got {result['result']}"
        
        print("[INTELLIGENT MODE] ✓ Valid structure → direct execution → result = 5")
    
    def test_intelligent_mode_invalid_output_fallback(self, monkeypatch):
        """
        INTELLIGENT MODE INVALID: LLM returns invalid structure.
        
        Contract: Invalid LLM output → llm_entry returns input_text → planner handles.
        """
        # Set up INTELLIGENT MODE environment
        monkeypatch.setenv("LLM_MODEL", "test_model")
        monkeypatch.setenv("LLM_API_KEY", "test_key")
        
        # Mock llm_entry to return invalid structure
        # Real llm_entry validation will reject it and return input_text
        def mock_llm_entry(input_text):
            return [{"invalid": "format"}]
        
        monkeypatch.setattr(llm_entry_module, "llm_entry", mock_llm_entry)
        
        # Execute full pipeline
        result = system_entry("add 2 and 3")
        
        # Print evidence
        print(f"\n[INTELLIGENT MODE - INVALID OUTPUT FALLBACK]")
        print(f"Status: {result.get('status')}")
        print(f"Result: {result.get('result')}")
        print(f"Flow: Invalid LLM output → passthrough → planner → execution")
        
        # Assert success (planner handled it)
        assert result["status"] == "success", f"Expected success, got {result}"
        assert result["result"] == 5, f"Expected result 5, got {result['result']}"
        
        print("[INTELLIGENT MODE] ✓ Invalid output → passthrough → planner → result = 5")
    
    def test_adapter_failure_fallback(self, monkeypatch):
        """
        ADAPTER FAILURE: Adapter raises exception.
        
        Contract: Exception → llm_entry returns input_text → planner handles.
        """
        # Set up INTELLIGENT MODE environment
        monkeypatch.setenv("LLM_MODEL", "test_model")
        monkeypatch.setenv("LLM_API_KEY", "test_key")
        
        # Mock llm_entry to raise exception
        # Real llm_entry exception handling will catch it and return input_text
        def mock_llm_entry(input_text):
            raise Exception("LLM failure")
        
        monkeypatch.setattr(llm_entry_module, "llm_entry", mock_llm_entry)
        
        # Execute full pipeline
        result = system_entry("add 2 and 3")
        
        # Print evidence
        print(f"\n[ADAPTER FAILURE FALLBACK]")
        print(f"Status: {result.get('status')}")
        print(f"Result: {result.get('result')}")
        print(f"Flow: Adapter failure → passthrough → planner → execution")
        
        # Assert success (planner handled it)
        assert result["status"] == "success", f"Expected success, got {result}"
        assert result["result"] == 5, f"Expected result 5, got {result['result']}"
        
        print("[ADAPTER FAILURE] ✓ Exception → passthrough → planner → result = 5")


# Legacy TEST_CASES for harness compatibility
TEST_CASES = [
    {
        "name": "planner_path_add_numbers",
        "type": "system",
        "input": "add 2 and 3",
        "expected": {
            "status": "success",
            "result": 5
        }
    },
    {
        "name": "validation_blocks_invalid_input",
        "type": "system",
        "input": "add 2 and hello",
        "expected": {
            "status": "failure",
            "reason": "argument_count_mismatch"
        }
    }
]

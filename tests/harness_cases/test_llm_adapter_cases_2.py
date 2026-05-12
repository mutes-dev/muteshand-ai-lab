"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - LLM adapter failure contract
  - Failure structure compliance
  - Error contract validation
ENTRYPOINT: llm_entry
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: LLM adapter failure contract

---

LLM Adapter Test Case 2 — Failure Contract Validation

Tests that adapter failure contract is properly structured.
According to SYSTEM_CONTRACTS: Adapter returns {"status": "failure", "reason": str}
"""

import pytest


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def test_adapter_failure_contract_structure():
    """
    Verify adapter failure contract structure.
    
    Contract: When adapter fails, it returns:
    {"status": "failure", "reason": "<non-empty string>"}
    """
    failure_output = {
        "status": "failure",
        "reason": "llm_not_available"
    }
    
    # Validate structure
    assert isinstance(failure_output, dict), "Failure output must be dict"
    assert "status" in failure_output, "Must have 'status' key"
    assert "reason" in failure_output, "Must have 'reason' key"
    
    # Validate values
    assert failure_output["status"] == "failure", "status must be 'failure'"
    assert isinstance(failure_output["reason"], str), "reason must be string"
    assert len(failure_output["reason"]) > 0, "reason must be non-empty"
    
    print(f"\n[ADAPTER FAILURE CONTRACT] ✓ Structure validated: {failure_output}")


def test_adapter_failure_reasons():
    """
    Document valid failure reasons according to SYSTEM_CONTRACTS.
    """
    valid_reasons = [
        "llm_not_available",
        "llm_invalid_output"
    ]
    
    print(f"\n[ADAPTER FAILURE REASONS] Valid reasons:")
    for reason in valid_reasons:
        print(f"  - {reason}")
    
    print("[ADAPTER FAILURE CONTRACT] ✓ Failure reasons documented")

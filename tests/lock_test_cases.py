"""
CATEGORY: REGRESSION
AUTHORITY_LAYER: Historical Bug Prevention
VALIDATES:
  - Phase 4B lock certification
  - Core execution tests
  - Validation tests
  - Chaining tests
  - Phase 4B feature tests
ENTRYPOINT: execute_from_input
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: HISTORICAL_BUG_PREVENTION
ARCHITECTURAL_SCOPE: Phase 4B lock certification

HISTORICAL_FIX: Phase 4B lock certification
REGRESSION_REASON: Prevent recurrence of Phase 4B lock issues
PRESERVATION_PRIORITY: HIGH

---

Lock Test Cases — Phase 4B Lock Validation Test Suite

PURPOSE:
    Defines comprehensive test cases for Phase 4B lock certification.
    
INCLUDES:
    - Core execution tests
    - Validation tests
    - Chaining tests
    - Phase 4B feature tests (Input Normalizer, TOOL_PHRASES, CHAIN_CONNECTORS)
"""

# =============================================================================
# PHASE 4B LOCK TEST SUITE
# =============================================================================

LOCK_TEST_CASES = [
    # =========================================================================
    # CATEGORY 1: EXECUTION LAYER TESTS (MANDATORY SUCCESS)
    # =========================================================================
    
    {
        "name": "exec_basic_add",
        "input": "add 2 and 3",
        "expected": {
            "status": "success",
            "result": "5"
        },
        "category": "execution",
        "priority": "P0",
        "phase4b_checks": {
            "tool_phrases": "add_numbers",
            "chain_steps": 1
        }
    },
    
    {
        "name": "exec_basic_multiply",
        "input": "multiply 2 and 3",
        "expected": {
            "status": "success",
            "result": "6"
        },
        "category": "execution",
        "priority": "P0",
        "phase4b_checks": {
            "tool_phrases": "multiply_numbers",
            "chain_steps": 1
        }
    },
    
    {
        "name": "exec_chain_normalized",
        "input": "add 2 and 3 then multiply by 4",
        "expected": {
            "status": "success",
            "result": "20"
        },
        "category": "chaining",
        "priority": "P0",
        "phase4b_checks": {
            "chain_steps": 2,
            "chain_connectors": True
        }
    },
    
    {
        "name": "exec_chain_explicit",
        "input": "add 2 and 3 then multiply the result by 4",
        "expected": {
            "status": "success",
            "result": "20"
        },
        "category": "chaining",
        "priority": "P0",
        "phase4b_checks": {
            "chain_steps": 2,
            "chain_connectors": True
        }
    },
    
    # =========================================================================
    # CATEGORY 2: VALIDATION LAYER TESTS (EXPECTED FAILURES)
    # =========================================================================
    
    {
        "name": "val_missing_args",
        "input": "multiply by",
        "expected": {
            "status": "failure",
            "reason": "argument count"
        },
        "category": "validation",
        "priority": "P0"
    },
    
    {
        "name": "val_invalid_input",
        "input": "add x and y",
        "expected": {
            "status": "failure"
        },
        "category": "validation",
        "priority": "P0"
    },
    
    {
        "name": "val_empty_input",
        "input": "",
        "expected": {
            "status": "failure"
        },
        "category": "validation",
        "priority": "P0"
    },
    
    {
        "name": "val_malformed_input",
        "input": "???",
        "expected": {
            "status": "failure"
        },
        "category": "validation",
        "priority": "P0"
    },
    
    # =========================================================================
    # CATEGORY 3: CHAINING TESTS (MANDATORY SUCCESS)
    # =========================================================================
    
    {
        "name": "chain_previous_result",
        "input": "add 2 and 3 then multiply the result by 4",
        "expected": {
            "status": "success",
            "result": "20"
        },
        "category": "chaining",
        "priority": "P0",
        "phase4b_checks": {
            "chain_steps": 2
        }
    },
    
    {
        "name": "chain_missing_previous",
        "input": "multiply the result by 4",
        "expected": {
            "status": "failure",
            "reason": "PREVIOUS_RESULT"
        },
        "category": "chaining",
        "priority": "P0"
    },
    
    # =========================================================================
    # CATEGORY 4: PHASE 4B FEATURE TESTS
    # =========================================================================
    
    # Input Normalizer Tests
    {
        "name": "phase4b_input_normalizer_please",
        "input": "please add 2 and 3",
        "expected": {
            "status": "success",
            "result": "5"
        },
        "category": "phase4b_input_normalizer",
        "priority": "P0",
        "phase4b_checks": {
            "input_normalizer": True,
            "tool_phrases": "add_numbers"
        }
    },
    
    {
        "name": "phase4b_input_normalizer_hey",
        "input": "hey multiply 2 and 3",
        "expected": {
            "status": "success",
            "result": "6"
        },
        "category": "phase4b_input_normalizer",
        "priority": "P0",
        "phase4b_checks": {
            "input_normalizer": True,
            "tool_phrases": "multiply_numbers"
        }
    },
    
    # TOOL_PHRASES Tests
    {
        "name": "phase4b_tool_phrases_sum",
        "input": "sum of 2 and 3",
        "expected": {
            "status": "success",
            "result": "5"
        },
        "category": "phase4b_tool_phrases",
        "priority": "P0",
        "phase4b_checks": {
            "tool_phrases": "add_numbers"
        }
    },
    
    {
        "name": "phase4b_tool_phrases_product",
        "input": "product of 2 and 3",
        "expected": {
            "status": "success",
            "result": "6"
        },
        "category": "phase4b_tool_phrases",
        "priority": "P0",
        "phase4b_checks": {
            "tool_phrases": "multiply_numbers"
        }
    },
    
    # CHAIN_CONNECTORS Tests
    {
        "name": "phase4b_chain_connectors_then",
        "input": "add 2 and 3 then multiply by 4",
        "expected": {
            "status": "success",
            "result": "20"
        },
        "category": "phase4b_chain_connectors",
        "priority": "P0",
        "phase4b_checks": {
            "chain_steps": 2,
            "chain_connectors": True
        }
    },
    
    {
        "name": "phase4b_chain_connectors_and_alone",
        "input": "add 2 and 3 and 4",
        "expected": {
            "status": "success",
            "result": "9"
        },
        "category": "phase4b_chain_connectors",
        "priority": "P0",
        "phase4b_checks": {
            "chain_steps": 1,  # Should NOT split on "and" alone
            "chain_connectors": True
        }
    },
]


def get_p0_tests():
    """Get all P0 (critical) tests."""
    return [test for test in LOCK_TEST_CASES if test.get("priority") == "P0"]


def get_tests_by_category(category: str):
    """Get tests by category."""
    return [test for test in LOCK_TEST_CASES if test.get("category") == category]

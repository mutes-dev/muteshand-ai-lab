"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - Auto-generated test cases
  - Basic execution correctness
ENTRYPOINT: execute_from_input
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: Basic execution only

---

Auto-Generated Test Cases - Generated from manual test runs

DO NOT EDIT MANUALLY
"""

TEST_CASES = [
  {
    "input": "add 2 and 3",
    "expected": {
      "status": "success",
      "result": 5
    }
  },
  {
    "input": "add 0 and 0",
    "expected": {
      "status": "success",
      "result": 0
    }
  },
  {
    "input": "add -5 and 3",
    "expected": {
      "status": "success",
      "result": -2
    }
  },
  {
    "input": "add 1000 and 2000",
    "expected": {
      "status": "success",
      "result": 3000
    }
  },
  {
    "input": "subtract 3 from 10",
    "expected": {
      "status": "success",
      "result": -7
    }
  },
  {
    "input": "subtract 0 from 5",
    "expected": {
      "status": "success",
      "result": -5
    }
  },
  {
    "input": "subtract 5 from 3",
    "expected": {
      "status": "success",
      "result": 2
    }
  },
  {
    "input": "multiply 4 and 5",
    "expected": {
      "status": "success",
      "result": 20
    }
  },
  {
    "input": "multiply 0 and 100",
    "expected": {
      "status": "success",
      "result": 0
    }
  },
  {
    "input": "multiply -2 and 3",
    "expected": {
      "status": "success",
      "result": -6
    }
  },
  {
    "input": "divide 10 by 2",
    "expected": {
      "status": "success",
      "result": 5.0
    }
  },
  {
    "input": "divide 7 by 1",
    "expected": {
      "status": "success",
      "result": 7.0
    }
  },
  {
    "input": "square 5",
    "expected": {
      "status": "success",
      "result": 25
    }
  },
  {
    "input": "square 0",
    "expected": {
      "status": "success",
      "result": 0
    }
  },
  {
    "input": "square -3",
    "expected": {
      "status": "success",
      "result": 9
    }
  },
  {
    "input": "cube 3 and 5",
    "expected": {
      "status": "failure",
      "reason": "argument_count_mismatch"
    }
  },
  {
    "input": "cube 0 and 0",
    "expected": {
      "status": "failure",
      "reason": "argument_count_mismatch"
    }
  },
  {
    "input": "square_root 16",
    "expected": {
      "status": "success",
      "result": 4.0
    }
  },
  {
    "input": "square_root 0",
    "expected": {
      "status": "success",
      "result": 0.0
    }
  },
  {
    "input": "square_root 25",
    "expected": {
      "status": "success",
      "result": 5.0
    }
  },
  {
    "input": "multiply_square_root 10 and 4",
    "expected": {
      "status": "success",
      "result": "20.0"
    }
  },
  {
    "input": "factorial 5",
    "expected": {
      "status": "success",
      "result": 120
    }
  },
  {
    "input": "factorial 0",
    "expected": {
      "status": "success",
      "result": 1
    }
  },
  {
    "input": "fibonacci 5",
    "expected": {
      "status": "success",
      "result": [
        0,
        1,
        1,
        2,
        3
      ]
    }
  },
  {
    "input": "fibonacci 1",
    "expected": {
      "status": "success",
      "result": [
        0,
        1
      ]
    }
  }
]
# AI LAB — LAYERED REGRESSION TESTING SYSTEM

## 📋 Overview

This directory contains an upgraded regression testing harness with:

- **Layered test structure** (EXECUTION, VALIDATION, PLANNER)
- **Parallel execution** via PowerShell jobs
- **File-based logging** for each layer
- **Batch reporting** for ChatGPT analysis

---

## 📁 Files

### Core Test Files

- **`manager_regression_test.py`** - Original regression test suite (preserved)
- **`manager_regression_test_layered.py`** - NEW layered test suite with edge cases
- **`run_parallel_tests.ps1`** - PowerShell script for parallel execution
- **`generate_batch_report.py`** - Consolidates logs for ChatGPT analysis

---

## 🧱 Test Layers

### EXECUTION LAYER (13 tests)
**Validates:** Tool execution, PREVIOUS_RESULT chaining, result propagation, error handling

**Key Tests:**
- Basic tool execution
- 2-step and 3-step chaining
- PREVIOUS_RESULT token substitution
- Error propagation blocking
- Repair loop functionality

### VALIDATION LAYER (8 tests)
**Validates:** Plan validation, argument count checks, tool existence, schema enforcement

**Key Tests:**
- Unknown tool rejection
- Missing arguments detection
- Invalid input types
- Chaining without previous result
- Multi-step reference blocking

### PLANNER LAYER (10 tests)
**Validates:** Tool selection, plan structure, JSON integrity, step decomposition

**Key Tests:**
- Basic tool selection
- Nested operation decomposition
- Multi-step plan generation
- Natural language vs function syntax
- Sequential same-tool operations

---

## 🚀 Usage

### Run Single Layer

```powershell
# Execution layer only
python manager_regression_test_layered.py --layer execution

# Validation layer only
python manager_regression_test_layered.py --layer validation

# Planner layer only
python manager_regression_test_layered.py --layer planner

# All layers sequentially
python manager_regression_test_layered.py --layer all
```

### Run Parallel (All Layers)

```powershell
# Run all layers in parallel PowerShell jobs
.\run_parallel_tests.ps1
```

**Benefits:**
- 3x faster execution (layers run simultaneously)
- Independent process isolation
- Separate log files per layer

### Generate Batch Report

```powershell
# After running tests, consolidate logs
python generate_batch_report.py
```

**Output:** `E:\MutesHand\logs\regression_tests\batch_report_for_chatgpt.txt`

**Use Case:** Copy this file and paste into ChatGPT for automated analysis

---

## 📊 Log Files

Each layer generates a separate log file:

```
E:\MutesHand\logs\regression_tests\
├── execution_layer_regression_log.txt
├── validation_layer_regression_log.txt
├── planner_layer_regression_log.txt
└── batch_report_for_chatgpt.txt
```

### Log Format

Each log contains:
- Test name
- Layer being validated
- What the test validates
- Goal
- Expected result
- Actual result
- Pass/Fail status
- Failure reason (if applicable)
- Duration
- Summary statistics

---

## 🧪 Test Structure

Each test case includes:

```python
{
    "name": "EXEC-01: Basic Tool Execution",
    "goal": "add 2 and 3",
    "layer": "EXECUTION",
    "validates": "Single tool execution with direct args",
    "expected_type": "exact",
    "expected": "5",
}
```

**Fields:**
- `name` - Unique test identifier with layer prefix
- `goal` - Natural language goal sent to manager
- `layer` - Which layer is being tested
- `validates` - What specific behavior is being validated
- `expected_type` - "exact" or "contains"
- `expected` - Expected result (string or list)
- `forbidden` - (optional) Content that should NOT appear in output

---

## 🔍 Edge Cases Added

### EXECUTION Layer
- ✅ Multi-step PREVIOUS_RESULT chaining (3+ steps)
- ✅ PREVIOUS_RESULT in different arg positions
- ✅ Error propagation blocking
- ✅ Sequential operations with same tool

### VALIDATION Layer
- ✅ True non-existing tool (not in tool index)
- ✅ Missing arguments detection
- ✅ Invalid input types
- ✅ Chaining without previous result
- ✅ Multi-step reference blocking

### PLANNER Layer
- ✅ Natural language vs function syntax
- ✅ Nested operation decomposition
- ✅ Ambiguous phrasing handling
- ✅ Sequential same-tool operations

---

## 📈 Parallel Execution Flow

```
run_parallel_tests.ps1
    ├── Start-Job (Execution Layer)
    ├── Start-Job (Validation Layer)
    └── Start-Job (Planner Layer)
         ↓
    Wait for all jobs to complete
         ↓
    Collect outputs
         ↓
    Display consolidated results
```

**Timing:**
- Sequential: ~3-5 minutes per layer = 9-15 minutes total
- Parallel: ~3-5 minutes total (all layers simultaneously)

---

## ⚠️ Important Notes

### System Behavior NOT Modified

- ❌ No changes to `manager.py`
- ❌ No changes to planner logic
- ❌ No changes to validation logic
- ❌ No changes to execution logic
- ✅ Only test harness upgraded

### Test Expectations

Some tests are **designed to fail** to validate error handling:
- `VAL-01` - Should reject unknown tools
- `VAL-02` - Should reject missing arguments
- `EXEC-09` - Should handle division by zero gracefully

**These are NOT bugs** - they validate the system correctly rejects invalid inputs.

---

## 🎯 ChatGPT Analysis Workflow

1. Run parallel tests:
   ```powershell
   .\run_parallel_tests.ps1
   ```

2. Generate batch report:
   ```powershell
   python generate_batch_report.py
   ```

3. Copy `batch_report_for_chatgpt.txt` contents

4. Paste into ChatGPT with prompt:
   ```
   Analyze this regression test report. Identify:
   - Which tests failed unexpectedly
   - Patterns in failures
   - Whether failures indicate bugs or test issues
   - Recommendations for fixes
   ```

---

## 📝 Adding New Tests

### Step 1: Choose Layer

Determine which layer your test validates:
- **EXECUTION** - Tool execution, chaining, results
- **VALIDATION** - Plan validation, arg checks
- **PLANNER** - Tool selection, plan structure

### Step 2: Add Test Case

Add to appropriate list in `manager_regression_test_layered.py`:

```python
{
    "name": "EXEC-14: Your Test Name",
    "goal": "your natural language goal",
    "layer": "EXECUTION",
    "validates": "what behavior you're testing",
    "expected_type": "exact",  # or "contains"
    "expected": "expected result",
    "forbidden": ["optional", "forbidden", "content"],
}
```

### Step 3: Run Tests

```powershell
python manager_regression_test_layered.py --layer execution
```

---

## 🔧 Troubleshooting

### Tests Hang or Timeout

**Cause:** Manager waiting for input or LLM call stuck

**Fix:** Check manager.log for last action, verify API keys

### Log Files Not Generated

**Cause:** Permission issues or path doesn't exist

**Fix:** Ensure `E:\MutesHand\logs\regression_tests\` exists with write permissions

### Parallel Execution Fails

**Cause:** PowerShell execution policy

**Fix:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Tests Fail Unexpectedly

**Cause:** System behavior changed or test expectations wrong

**Fix:** 
1. Check individual test log in `logs/regression_tests/`
2. Run test manually to reproduce
3. Compare with expected behavior

---

## 📊 Example Log Output

```
================================================================================
AI LAB — EXECUTION LAYER REGRESSION LOG
================================================================================

✓ [PASS] EXEC-01: Basic Tool Execution
  Layer: EXECUTION
  Validates: Single tool execution with direct args
  Goal: add 2 and 3
  Expected: 5
  Final Answer: 5
  Duration: 9.47s
--------------------------------------------------------------------------------

✗ [FAIL] EXEC-09: Domain Error - No Repair
  Layer: EXECUTION
  Validates: Tool returns error without triggering repair
  Goal: divide 10 by 0
  Expected: ['division by zero']
  Final Answer: Error: Division by zero
  Failure Reason: Found forbidden content: 'repair'
  Flags: VALIDATION_BLOCKED
  Duration: 6.79s
--------------------------------------------------------------------------------

================================================================================
SUMMARY
================================================================================
Total Tests:       13
Passed:            9 (69%)
Failed:            4 (30%)
Crashes:           0
Validation Blocks: 0

OVERALL: ✗ FAIL
================================================================================
```

---

## 🎯 Design Principles

1. **Improve visibility and speed — NOT system behavior**
2. **Layered testing enables targeted debugging**
3. **Parallel execution reduces feedback time**
4. **File-based logs enable batch analysis**
5. **Clean output format optimized for LLM analysis**

---

## 📞 Support

For issues or questions:
1. Check this README
2. Review log files in `logs/regression_tests/`
3. Run individual tests to isolate issues
4. Use batch report for ChatGPT analysis

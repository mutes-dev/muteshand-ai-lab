# AI Lab — Deterministic Tool Execution System

## 1. Project Overview

**What it is:** An AI-driven tool execution system with deterministic core components and LLM-based planning.

**Purpose:** Convert natural language goals into structured tool execution plans, execute them reliably, and handle failures through repair loops.

**Design Philosophy:**
- **Deterministic core:** Parser, resolver, validation, and execution are 100% deterministic
- **Layered architecture:** Strict separation of concerns between components
- **Planner as only non-deterministic component:** The LLM-based planner generates structure; all downstream processing is deterministic
- **Fail visible:** All errors are explicit and logged

## 2. Architecture Overview

Execution Pipeline:

```
User Input
    ↓
Planner (LLM) → Structured Plan [type, name, args, input_text]
    ↓
Validation (Schema, Tools, Args, Chaining)
    ↓
Chain Resolver → PREVIOUS_RESULT substitution
    ↓
Tool/Agent Execution
    ↓
Result
```

### Layer Responsibilities

| Layer | Responsibility | MUST NOT |
|-------|---------------|----------|
| **Planner** | Generate structured plan from natural language | Execute tools, resolve arguments |
| **Parser** | Tokenize input into numbers, strings, words | Execute logic, resolve dependencies |
| **Argument Resolver** | Extract numeric values from tokens | Handle non-numeric args, chain resolution |
| **Chain Resolver** | Substitute PREVIOUS_RESULT tokens | Validate plan structure |
| **Validation** | Check plan structure, tool existence, arg count, chaining rules | Execute or modify plans |
| **Execution** | Run tools/agents, handle results, trigger repairs | Generate plans or validate |

## 3. Project Structure

```
E:\MutesHand\
├── core/                      # Core deterministic modules
│   ├── config.py             # Configuration constants
│   ├── parser.py             # Input tokenization
│   ├── argument_resolver.py  # Numeric arg extraction
│   ├── chain_resolver.py     # PREVIOUS_RESULT resolution
│   ├── validation.py         # Plan validation
│   ├── logger.py             # Logging utilities
│   ├── tool_executor.py      # Tool execution
│   ├── llm.py                # LLM interface
│   └── planner.py            # Plan generation (LLM-based)
│
├── projects/manager/        # Main orchestrator
│   └── manager.py            # Goal processing, execution loop
│
├── tools/                     # Tool implementations
├── agents/                    # Agent implementations
├── tests/                     # Test suite
│   ├── run_tests.py         # Main test runner
│   └── *_test.py            # Specific test files
│
├── memory/                    # System state persistence
└── logs/                      # Execution logs
```

## 4. How to Run

### Interactive Mode
```bash
cd E:\MutesHand
python projects/manager/manager.py [mode]
# mode: debug (default), normal, quiet
```

Example:
```
> python projects/manager/manager.py debug
Enter goal (end with an empty line):
> add 2 and 3

FINAL ANSWER: 5
```

### Headless Mode
```python
from projects.manager.manager import process_goal
result = process_goal("add 2 and 3")
```

### Test Mode
```bash
cd E:\MutesHand
python tests/run_tests.py --layer execution
```

## 5. Testing

### Test Runners

| Command | Purpose |
|---------|---------|
| `python tests/run_tests.py --layer execution` | Run execution tests |
| `python tests/run_tests.py --layer validation` | Run validation tests |
| `python tests/run_tests.py --layer planner` | Run planner tests |
| `.\tests\run_parallel_tests.ps1` | Run all layers in parallel |

### Test Structure
- **Execution Layer:** Tool execution, chaining, error propagation
- **Validation Layer:** Plan validation, argument checking
- **Planner Layer:** Tool selection, plan structure

## 6. Design Principles

1. **Strict Layer Isolation**
   - No cross-layer logic
   - Planner only generates structure
   - Execution only runs validated plans

2. **No Hidden Logic**
   - All behavior explicit in code
   - No magic transformations
   - Every step logged

3. **Deterministic Core**
   - Parser → tokens
   - Resolver → numeric args
   - Chain Resolver → value substitution
   - All 100% reproducible

4. **Failure Visibility**
   - All errors logged to `logs/manager.log`
   - Execution history in `memory/execution_log.json`
   - No silent failures

5. **No Argument Creation**
   - Arguments only from parser → resolver pipeline
   - No ad-hoc arg generation
   - Empty args fail validation

## 7. Development Rules

**CRITICAL:**
- DO NOT modify core layers without architecture review
- DO NOT introduce cross-layer logic (e.g., planner doing validation)
- DO NOT use LLM for analysis or reasoning tasks — use deterministic code
- ALWAYS follow `ARCHITECTURAL SOURCE OF TRUTH.txt`
- NEVER commit `__pycache__/`, `venv/`, or `logs/`

**Layer Modification Policy:**
| Layer | Modify? | Notes |
|-------|---------|-------|
| config | ✅ Safe | Add constants only |
| parser | ⚠️ Review | Changes affect all downstream |
| resolver | ⚠️ Review | Changes affect tool inputs |
| validation | ⚠️ Review | Changes affect plan acceptance |
| planner | ✅ Safe | Iteration expected |
| manager | ⚠️ Review | Core orchestration logic |

## 8. Git & Environment

### Ignored (never commit)
```
__pycache__/
*.pyc
venv/
logs/
*.log
memory/*.json  (except tool_index/tools.json)
```

### Required Setup
1. Python 3.10+
2. Ollama running locally (port 11434)
3. Model: `gemma3:4b` (configurable in `core/llm.py`)

## 9. Current Status

| Component | Status |
|-----------|--------|
| Core pipeline | ✅ Stable, deterministic |
| Parser | ✅ Production ready |
| Resolver | ✅ Production ready |
| Validation | ✅ Production ready |
| Planner | ⚠️ Functional, iterative improvement ongoing |
| Manager | ✅ Stable |

**Known Limitations:**
- Planner occasionally generates imperfect plans (replanning handles this)
- Complex multi-step chains require explicit "then" phrasing
- Tool repair limited to 3 attempts per tool

**System is operational and tested.**

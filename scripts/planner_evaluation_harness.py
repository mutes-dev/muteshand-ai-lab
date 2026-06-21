#!/usr/bin/env python3
"""
Planner Evaluation Harness — ISSUE-PDIAG-006-P1 Phase 1

Industry-level planner diagnostic tool for live LLM evaluation.
OPT-IN ONLY — Not part of normal test/CI runs.

This harness:
- Calls plan_workflow() with real LLM (no mocking)
- Evaluates planning output across 9 scoring dimensions
- Detects PDIAG-006-P1 and other failure patterns
- Preserves full artifacts for prompt V1 vs V2 comparison
- Does NOT execute workflows, call AG1 directly, or run tools

Usage:
    python scripts/planner_evaluation_harness.py --list-cases
    python scripts/planner_evaluation_harness.py --priority P0 --dry-run
    python scripts/planner_evaluation_harness.py --priority P0 --limit 2
    python scripts/planner_evaluation_harness.py --case E.1

Output:
    test_outputs/planner_evaluation/<timestamp>/
        - planner_evaluation_results.json
        - planner_evaluation_summary.md
        - planner_evaluation_category_summary.csv
        - planner_evaluation_failures.md
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

sys.path.insert(0, str(Path(__file__).parent.parent))
from system.orchestrator.orchestrator_planner import plan_workflow
from system.diagnostics.planner_capture import PlannerCaptureContext

# =============================================================================
# CONSTANTS
# =============================================================================

REQUIRED_STEP_FIELDS = ["id", "name", "purpose", "agent", "estimated_complexity"]

# =============================================================================
# P0 CASE REGISTRY (29 Critical Cases) - Part 1
# =============================================================================

P0_CASES_PART1 = [
    # A. Single-step capability (7 cases)
    {"id": "A.1", "priority": "P0", "category": "single_step", "user_input": "Calculate 12 plus 8", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False},
    {"id": "A.2", "priority": "P0", "category": "single_step", "user_input": "Subtract 25 from 100", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False},
    {"id": "A.3", "priority": "P0", "category": "single_step", "user_input": "Multiply 7 and 6", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False},
    {"id": "A.5", "priority": "P0", "category": "single_step", "user_input": "Read the file C:\\temp\\notes.txt", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False},
    {"id": "A.6", "priority": "P0", "category": "single_step", "user_input": "Write 'hello world' to C:\\temp\\test.txt", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False},
    {"id": "A.7", "priority": "P0", "category": "single_step", "user_input": "Edit C:\\temp\\config.txt replacing 'old' with 'new'", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation", "operation_preservation"], "critical_gate": False},
    {"id": "A.11", "priority": "P0", "category": "single_step", "user_input": "Write a short paragraph about planning", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation", "authority_boundary"], "critical_gate": False},
]

P0_CASES_PART2 = [
    # B. Independent parallel workflows (3 cases)
    {"id": "B.1", "priority": "P0", "category": "independent_parallel", "user_input": "Calculate 12+8. Calculate 7×6. Calculate 100-25.", "expected_step_count": 3, "expected_dependencies": [[], [], []], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "All steps should have empty depends_on"},
    {"id": "B.7", "priority": "P0", "category": "independent_parallel", "user_input": "Add 2 and 3. Multiply 4 and 5.", "expected_step_count": 2, "expected_dependencies": [[], []], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "step_2 must NOT depend on step_1"},
    {"id": "B.8", "priority": "P0", "category": "independent_parallel", "user_input": "Read file A. Read file B.", "expected_step_count": 2, "expected_dependencies": [[], []], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Both should have empty depends_on"},

    # C. Dependent chains (3 cases)
    {"id": "C.1", "priority": "P0", "category": "dependent_chain", "user_input": "Add 2 and 3 then multiply the result by 10.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "step_2 depends on step_1"},
    {"id": "C.3", "priority": "P0", "category": "dependent_chain", "user_input": "Read C:\\temp\\notes.txt, then summarize the contents.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "File read to synthesis"},
    {"id": "C.10", "priority": "P0", "category": "dependent_chain", "user_input": "Read C:\\temp\\input.txt, then write a summary to C:\\temp\\output.txt.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Read file to write derived summary"},
]

P0_CASES_PART3 = [
    # D. Resource sequencing (6 cases - critical safety)
    {"id": "D.1", "priority": "P0", "category": "resource_sequencing", "user_input": "Write 'hello' to C:\\temp\\test.txt, then read it back.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": True, "notes": "Write then read same file"},
    {"id": "D.2", "priority": "P0", "category": "resource_sequencing", "user_input": "Edit C:\\temp\\test.txt replacing 'old' with 'new', then read it.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": True, "notes": "Edit then read same file"},
    {"id": "D.3", "priority": "P0", "category": "resource_sequencing", "user_input": "Write to file C:\\temp\\A.txt, edit file C:\\temp\\A.txt, then read file C:\\temp\\A.txt.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_2"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": True, "notes": "Write → edit → read chain"},
    {"id": "D.4", "priority": "P0", "category": "resource_sequencing", "user_input": "Read file C:\\temp\\A.txt, edit file C:\\temp\\A.txt, then read file C:\\temp\\A.txt again.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_2"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": True, "notes": "Read → edit → read chain"},
    {"id": "D.5", "priority": "P0", "category": "resource_sequencing", "user_input": "Write data to C:\\temp\\input.txt, then read it and write summary to C:\\temp\\output.txt.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_2"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": True, "notes": "Write input → read input → write output"},
    {"id": "D.10", "priority": "P0", "category": "resource_sequencing", "user_input": "Write 'X' to C:\\temp\\file.txt. Write 'Y' to C:\\temp\\file.txt.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": True, "notes": "Same-file write collision — must be sequential"},
]

P0_CASES_PART4 = [
    # E. Multi-source fan-in final synthesis (3 cases - PDIAG-006-P1 critical)
    {"id": "E.1", "priority": "P0", "category": "final_synthesis", "user_input": "Calculate 12+8. Calculate 7×6. Calculate 100-25. Summarize all results.", "expected_step_count": 4, "expected_dependencies": [[], [], [], ["step_1", "step_2", "step_3"]], "scoring_focus": ["final_intent_score", "dependency_score"], "critical_gate": True, "notes": "PDIAG-006-P1: summarize must NOT become addition"},
    {"id": "E.5", "priority": "P0", "category": "final_synthesis", "user_input": "Read file C:\\temp\\a.txt. Read file C:\\temp\\b.txt. Write a report using both.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score", "dependency_score"], "critical_gate": True, "notes": "Two files to final report"},
    {"id": "E.6", "priority": "P0", "category": "final_synthesis", "user_input": "Read https://example.com. Read https://iana.org. Compare them.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score", "dependency_score"], "critical_gate": True, "notes": "Two webpages to comparison"},

    # G. Final intent preservation (2 cases)
    {"id": "G.1", "priority": "P0", "category": "final_intent", "user_input": "Calculate 12+8. Calculate 7×6. Summarize all results.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score"], "critical_gate": True, "notes": "Summarize must not become arithmetic"},
    {"id": "G.4", "priority": "P0", "category": "final_intent", "user_input": "Read C:\\temp\\a.txt. Read C:\\temp\\b.txt. Write final report.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score"], "critical_gate": True, "notes": "Final report must not become file op"},

    # I. Authority boundary (6 cases)
    {"id": "I.1", "priority": "P0", "category": "authority_boundary", "user_input": "Add 2 and 3", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["authority_boundary_score"], "critical_gate": True, "notes": "No tool_call field"},
    {"id": "I.2", "priority": "P0", "category": "authority_boundary", "user_input": "Read file C:\\temp\\a.txt", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["authority_boundary_score"], "critical_gate": True, "notes": "No function syntax in purpose"},
    {"id": "I.3", "priority": "P0", "category": "authority_boundary", "user_input": "Calculate 2+3", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["authority_boundary_score"], "critical_gate": True, "notes": "No computed literal '5' in step"},
    {"id": "I.4", "priority": "P0", "category": "authority_boundary", "user_input": "Write to file", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["authority_boundary_score"], "critical_gate": True, "notes": "No actual file written during planning"},
    {"id": "I.5", "priority": "P0", "category": "authority_boundary", "user_input": "Multiply 3 and 4", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["authority_boundary_score"], "critical_gate": True, "notes": "No direct invocation multiply_numbers(3,4)"},
    {"id": "I.10", "priority": "P0", "category": "authority_boundary", "user_input": "Calculate anything", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["authority_boundary_score", "structural_pass"], "critical_gate": True, "notes": "Schema compliance: valid JSON, required fields"},
]

# Combine all parts
P0_CASES = P0_CASES_PART1 + P0_CASES_PART2 + P0_CASES_PART3 + P0_CASES_PART4

# =============================================================================
# P1A ESSENTIAL SUBSET (25 cases) — EVAL1A
# =============================================================================

P1A_CASES = [
    # C. Dependent chains (4 cases)
    {"id": "C.4", "priority": "P1", "category": "dependent_chain", "user_input": "Read C:\\temp\\log.txt, then extract all error lines.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "File read to extract"},
    {"id": "C.5", "priority": "P1", "category": "dependent_chain", "user_input": "List files in C:\\temp, then summarize what was found.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Folder list to synthesis"},
    {"id": "C.7", "priority": "P1", "category": "dependent_chain", "user_input": "Read https://example.com, then give me a short summary.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Web read to summary"},
    {"id": "C.8", "priority": "P1", "category": "dependent_chain", "user_input": "Search for 'python tutorial', then read the first result.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Search then read result"},

    # D. Resource sequencing (5 cases)
    {"id": "D.6", "priority": "P1", "category": "resource_sequencing", "user_input": "Write to C:\\temp\\newfile.txt, then list C:\\temp to confirm.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": False, "notes": "Write then list same dir"},
    {"id": "D.7", "priority": "P1", "category": "resource_sequencing", "user_input": "Edit C:\\temp\\log.txt, then search for 'SUCCESS' in same file.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": False, "notes": "Edit then grep same file"},
    {"id": "D.9", "priority": "P1", "category": "resource_sequencing", "user_input": "Write to file A. Read file A. Read file A again.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": False, "notes": "Write then multiple reads"},
    {"id": "D.11", "priority": "P1", "category": "resource_sequencing", "user_input": "Edit file A (X to Y). Edit file A (Y to Z).", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": False, "notes": "Sequential edits same file"},
    {"id": "D.13", "priority": "P1", "category": "resource_sequencing", "user_input": "Find all .py files, then read the first match.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": False, "notes": "Glob then read first match"},

    # E. Multi-source fan-in / final synthesis (4 cases)
    {"id": "E.2", "priority": "P1", "category": "final_synthesis", "user_input": "Calculate 12+8. Calculate 7×6. List all results.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score", "dependency_score"], "critical_gate": False, "notes": "Multi-math to list"},
    {"id": "E.3", "priority": "P1", "category": "final_synthesis", "user_input": "Calculate A. Calculate B. Compare the results.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score", "dependency_score"], "critical_gate": False, "notes": "Multi-math to compare"},
    {"id": "E.7", "priority": "P1", "category": "final_synthesis", "user_input": "Calculate 12+8. List files in C:\\temp. Give final answer with both.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score", "dependency_score"], "critical_gate": False, "notes": "Mixed source to final answer"},
    {"id": "E.8", "priority": "P1", "category": "final_synthesis", "user_input": "Read local file. Read webpage. Create brief from both.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score", "dependency_score"], "critical_gate": False, "notes": "File + web to brief"},

    # F. Fan-out workflows (3 cases)
    {"id": "F.1", "priority": "P1", "category": "fan_out", "user_input": "Read file A, then summarize it AND extract keywords.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1"]], "scoring_focus": ["dag_correctness", "dependency_score"], "critical_gate": False, "notes": "Read to summarize + extract"},
    {"id": "F.3", "priority": "P1", "category": "fan_out", "user_input": "Calculate result, then explain it AND save it to file.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1"]], "scoring_focus": ["dag_correctness", "dependency_score"], "critical_gate": False, "notes": "Calc to explain + save"},
    {"id": "F.6", "priority": "P1", "category": "fan_out", "user_input": "Read config, then validate it AND backup to .bak.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1"]], "scoring_focus": ["dag_correctness", "dependency_score"], "critical_gate": False, "notes": "Read to validate + backup"},

    # G. Final intent preservation (3 cases)
    {"id": "G.2", "priority": "P1", "category": "final_intent", "user_input": "Calculate A. Calculate B. List all results.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Enumeration not addition"},
    {"id": "G.3", "priority": "P1", "category": "final_intent", "user_input": "Calculate A. Calculate B. Compare the results.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Comparison not subtraction"},
    {"id": "G.7", "priority": "P1", "category": "final_intent", "user_input": "Calculate result. Explain the result.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Explanation not arithmetic"},

    # H. Edge and negative cases (4 cases)
    {"id": "H.1", "priority": "P1", "category": "edge_negative", "user_input": "power 2 to 4", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation", "authority_boundary"], "critical_gate": False, "notes": "Preserve unsupported op"},
    {"id": "H.2", "priority": "P1", "category": "edge_negative", "user_input": "Repeat the word 'test' zero times", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False, "notes": "Preserve zero"},
    {"id": "H.7", "priority": "P1", "category": "edge_negative", "user_input": "Write 'X' to C:\\temp\\A.txt. Write 'Y' to C:\\temp\\A.txt. Read C:\\temp\\A.txt.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_2"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": False, "notes": "Collision then read"},
    {"id": "H.9", "priority": "P1", "category": "edge_negative", "user_input": "Read C:\\temp\\a.txt and C:\\temp\\b.txt, then combine them.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Implied dependency on both"},

    # I. Authority boundary (3 cases)
    {"id": "I.6", "priority": "P1", "category": "authority_boundary", "user_input": "Search for 'API documentation'", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["authority_boundary_score"], "critical_gate": False, "notes": "Natural language only"},
    {"id": "I.7", "priority": "P1", "category": "authority_boundary", "user_input": "Execute this calculation", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["authority_boundary_score"], "critical_gate": False, "notes": "No execution claim"},
    {"id": "I.8", "priority": "P1", "category": "authority_boundary", "user_input": "Update the config file", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["authority_boundary_score"], "critical_gate": False, "notes": "No state mutation claim"},
]

# =============================================================================
# P1B LOWER-RISK REMAINING SUBSET (29 cases) — EVAL1B
# =============================================================================

P1B_CASES = [
    # A. Single-step capability (4 cases)
    {"id": "A.4", "priority": "P1", "category": "single_step", "user_input": "Repeat the word 'hello' five times", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False},
    {"id": "A.8", "priority": "P1", "category": "single_step", "user_input": "List all files in C:\\temp", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False},
    {"id": "A.9", "priority": "P1", "category": "single_step", "user_input": "Search for 'TODO' in C:\\temp\\*.py", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False},
    {"id": "A.10", "priority": "P1", "category": "single_step", "user_input": "Read the webpage https://example.com", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False},

    # B. Independent parallel workflows (5 cases)
    {"id": "B.2", "priority": "P1", "category": "independent_parallel", "user_input": "Read C:\\temp\\a.txt. Read C:\\temp\\b.txt. Read C:\\temp\\c.txt.", "expected_step_count": 3, "expected_dependencies": [[], [], []], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "All steps should have empty depends_on"},
    {"id": "B.3", "priority": "P1", "category": "independent_parallel", "user_input": "Calculate 12+8. List files in C:\\temp. Write a paragraph about planning.", "expected_step_count": 3, "expected_dependencies": [[], [], []], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Mixed independent operations"},
    {"id": "B.4", "priority": "P1", "category": "independent_parallel", "user_input": "Read https://example.com. Read https://iana.org.", "expected_step_count": 2, "expected_dependencies": [[], []], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Web reads are independent"},
    {"id": "B.5", "priority": "P1", "category": "independent_parallel", "user_input": "Multiply 3 by 4. Divide 20 by 5. Add 7 and 8.", "expected_step_count": 3, "expected_dependencies": [[], [], []], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Parallel eligible math operations"},
    {"id": "B.6", "priority": "P1", "category": "independent_parallel", "user_input": "Search for 'error' in logs. Calculate total count. Read the README.", "expected_step_count": 3, "expected_dependencies": [[], [], []], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Mixed categories, independent"},

    # C. Dependent chains (2 cases)
    {"id": "C.2", "priority": "P1", "category": "dependent_chain", "user_input": "Repeat 'test' 3 times, then repeat that result twice.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "String chain dependency"},
    {"id": "C.9", "priority": "P1", "category": "dependent_chain", "user_input": "Add 2 and 3. Multiply that by 4. Subtract 5 from the result.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_2"]], "scoring_focus": ["dependency_score", "dag_correctness"], "critical_gate": False, "notes": "Linear math chain"},

    # D. Resource sequencing (1 case)
    {"id": "D.12", "priority": "P1", "category": "resource_sequencing", "user_input": "Read C:\\temp\\config.txt, then write updated version to same path.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": False, "notes": "Read then write same file"},

    # E. Multi-source fan-in / final synthesis (5 cases)
    {"id": "E.4", "priority": "P1", "category": "final_synthesis", "user_input": "Calculate A. Calculate B. Then add both results.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Explicit addition is the intent"},
    {"id": "E.11", "priority": "P1", "category": "final_synthesis", "user_input": "Read A. Read B. Read C. Write report using all three.", "expected_step_count": 4, "expected_dependencies": [[], [], [], ["step_1", "step_2", "step_3"]], "scoring_focus": ["final_intent_score", "dag_correctness"], "critical_gate": False, "notes": "Multi-source to final report"},
    {"id": "E.12", "priority": "P1", "category": "final_synthesis", "user_input": "Calc option A. Calc option B. Recommend best.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Calculation to recommendation"},
    {"id": "E.13", "priority": "P1", "category": "final_synthesis", "user_input": "Calculate result. Explain how it was derived.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Derivation explanation"},
    {"id": "E.14", "priority": "P1", "category": "final_synthesis", "user_input": "Read A. Search B. Calc C. Write final report.", "expected_step_count": 4, "expected_dependencies": [[], [], [], ["step_1", "step_2", "step_3"]], "scoring_focus": ["final_intent_score", "dag_correctness"], "critical_gate": False, "notes": "Full workflow to final report"},

    # F. Fan-out workflows (4 cases)
    {"id": "F.2", "priority": "P1", "category": "fan_out", "user_input": "Read webpage, then summarize it AND save a copy to file.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1"]], "scoring_focus": ["dag_correctness", "dependency_score"], "critical_gate": False, "notes": "Web read to summarize + save"},
    {"id": "F.4", "priority": "P1", "category": "fan_out", "user_input": "List folder, then count files AND list .txt files.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1"]], "scoring_focus": ["dag_correctness", "dependency_score"], "critical_gate": False, "notes": "List to count + filter"},
    {"id": "F.8", "priority": "P1", "category": "fan_out", "user_input": "Calculate total, then show percentage AND save to report.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1"]], "scoring_focus": ["dag_correctness", "dependency_score"], "critical_gate": False, "notes": "Calc to display + save"},
    {"id": "F.9", "priority": "P1", "category": "fan_out", "user_input": "Search for errors, then count them AND list unique types.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1"]], "scoring_focus": ["dag_correctness", "dependency_score"], "critical_gate": False, "notes": "Search to count + unique list"},

    # G. Final intent preservation (7 cases)
    {"id": "G.5", "priority": "P1", "category": "final_intent", "user_input": "Read sources. Create short brief.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Brief synthesis"},
    {"id": "G.6", "priority": "P1", "category": "final_intent", "user_input": "Calc A. Calc B. Recommend best option.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Recommendation not arithmetic"},
    {"id": "G.8", "priority": "P1", "category": "final_intent", "user_input": "Do A. Do B. Give final answer.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Final answer synthesis"},
    {"id": "G.9", "priority": "P1", "category": "final_intent", "user_input": "Gather data. Draw conclusion.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Conclusion synthesis"},
    {"id": "G.10", "priority": "P1", "category": "final_intent", "user_input": "Read logs. Provide analysis.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Analysis synthesis"},
    {"id": "G.11", "priority": "P1", "category": "final_intent", "user_input": "Read docs. Give overview.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Overview synthesis"},
    {"id": "G.12", "priority": "P1", "category": "final_intent", "user_input": "Check A. Check B. Provide assessment.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score"], "critical_gate": False, "notes": "Assessment synthesis"},

    # H. Edge and negative cases (1 case)
    {"id": "H.14", "priority": "P1", "category": "edge_negative", "user_input": "Read local file. Read webpage. Compare.", "expected_step_count": 3, "expected_dependencies": [[], [], ["step_1", "step_2"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Web+local mix, ensure dependencies"},

    # I. Authority boundary (1 case)
    {"id": "I.9", "priority": "P1", "category": "authority_boundary", "user_input": "Plan this workflow", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["authority_boundary_score"], "critical_gate": False, "notes": "Output is candidate, not truth"},
]

# =============================================================================
# P1C1 HIGHER-RISK REMAINING SUBSET (10 cases) — EVAL1C1
# =============================================================================

P1C1_CASES = [
    # C. Dependent chains (3 cases)
    {"id": "C.6", "priority": "P1", "category": "dependent_chain", "user_input": "Search for 'ERROR' in logs, then summarize the matches.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Search then summarize matches"},
    {"id": "C.11", "priority": "P1", "category": "dependent_chain", "user_input": "Search for 'API docs', read the first result, then summarize it.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_2"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Web search chain"},
    {"id": "C.12", "priority": "P1", "category": "dependent_chain", "user_input": "Find all .txt files in C:\\temp, then read the first one found.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Glob then read first match"},

    # D. Resource sequencing (1 case)
    {"id": "D.8", "priority": "P1", "category": "resource_sequencing", "user_input": "List C:\\temp, then find all .log files in C:\\temp.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["resource_sequence_score"], "critical_gate": False, "notes": "List then glob same folder (pronoun/dependency ambiguous)"},

    # E. Final synthesis (2 cases)
    {"id": "E.9", "priority": "P1", "category": "final_synthesis", "user_input": "List folder. Search those files. Summarize findings.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score", "dependency_score"], "critical_gate": False, "notes": "Pronoun dependency: those files"},
    {"id": "E.10", "priority": "P1", "category": "final_synthesis", "user_input": "Search web. Read result. Summarize.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1", "step_2"]], "scoring_focus": ["final_intent_score", "dependency_score"], "critical_gate": False, "notes": "Web search then read then summarize"},

    # F. Fan-out workflows (3 cases)
    {"id": "F.5", "priority": "P1", "category": "fan_out", "user_input": "Search for X, then read first result AND summarize all results.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1"]], "scoring_focus": ["dag_correctness", "dependency_score"], "critical_gate": False, "notes": "Search to read + summarize"},
    {"id": "F.7", "priority": "P1", "category": "fan_out", "user_input": "Search, read result, then summarize AND extract links.", "expected_step_count": 4, "expected_dependencies": [[], ["step_1"], ["step_2"], ["step_2"]], "scoring_focus": ["dag_correctness", "dependency_score"], "critical_gate": False, "notes": "Web chain with fan-out"},
    {"id": "F.10", "priority": "P1", "category": "fan_out", "user_input": "Read A, write summary to B, then create final answer using both.", "expected_step_count": 3, "expected_dependencies": [[], ["step_1"], ["step_1", "step_2"]], "scoring_focus": ["dag_correctness", "dependency_score"], "critical_gate": False, "notes": "Fan-out + fan-in DAG"},

    # H. Edge and negative cases (1 case)
    {"id": "H.10", "priority": "P1", "category": "edge_negative", "user_input": "Transcribe the audio file.", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False, "notes": "Unsupported operation — no audio tool"},
]

# =============================================================================
# P2 EDGE/NEGATIVE CASES (7 cases) — EVAL1P2
# =============================================================================

P2_CASES = [
    # H. Edge and negative cases (7 cases)
    {"id": "H.3", "priority": "P2", "category": "edge_negative", "user_input": "Calculate fibonacci of factorial of 5", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False, "notes": "Unsupported nested operation — preserve intent, no approximation"},
    {"id": "H.4", "priority": "P2", "category": "edge_negative", "user_input": "Do the first thing, then summarize it.", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False, "notes": "Ambiguous reference — expected REVIEW"},
    {"id": "H.5", "priority": "P2", "category": "edge_negative", "user_input": "Read file A, then search it.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["dependency_score"], "critical_gate": False, "notes": "Pronoun dependency — expected REVIEW"},
    {"id": "H.6", "priority": "P2", "category": "edge_negative", "user_input": "Process the data.", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False, "notes": "Vague instruction — expected REVIEW"},
    {"id": "H.8", "priority": "P2", "category": "edge_negative", "user_input": "Check everything and report.", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation"], "critical_gate": False, "notes": "Unclear scope — expected REVIEW"},
    {"id": "H.13", "priority": "P2", "category": "edge_negative", "user_input": "Edit C:\\temp\\unknown.txt replacing 'old' with 'new'", "expected_step_count": 1, "expected_dependencies": [], "scoring_focus": ["intent_segmentation", "authority_boundary"], "critical_gate": False, "notes": "Edit without read — edge case"},
    {"id": "H.15", "priority": "P2", "category": "edge_negative", "user_input": "Call external API and process result.", "expected_step_count": 2, "expected_dependencies": [[], ["step_1"]], "scoring_focus": ["authority_boundary_score", "dependency_score"], "critical_gate": False, "notes": "External API planning — authority boundary test"},
]

ALL_CASES = P0_CASES + P1A_CASES + P1B_CASES + P1C1_CASES + P2_CASES

EXTENDED_REGISTRY = {
    "P0": P0_CASES,
    "P1A": P1A_CASES,
    "P1B": P1B_CASES,
    "P1C1": P1C1_CASES,
    "P1": P1A_CASES + P1B_CASES + P1C1_CASES,
    "P2": P2_CASES,
}


def get_all_cases(priority: Optional[str] = None) -> List[Dict]:
    if priority:
        return EXTENDED_REGISTRY.get(priority, [])
    return ALL_CASES


def get_case_by_id(case_id: str) -> Optional[Dict]:
    for case in ALL_CASES:
        if case["id"] == case_id:
            return case
    return None


def get_cases_by_category(category: str) -> List[Dict]:
    return [c for c in ALL_CASES if c["category"] == category]


# =============================================================================
# SCORING MODEL (9 Dimensions)
# =============================================================================

class ScoringResult:
    """Container for 9-dimensional scoring results."""

    def __init__(self):
        self.structural_pass: bool = True
        self.intent_segmentation_score: float = 1.0
        self.dependency_score: float = 1.0
        self.resource_sequence_score: float = 1.0
        self.final_intent_score: float = 1.0
        self.authority_boundary_score: float = 1.0
        self.dag_correctness: float = 1.0
        self.model_robustness: Optional[float] = None
        self.classification: str = "PASS"
        self.notes: List[str] = []

    def to_dict(self) -> Dict:
        return {
            "structural_pass": self.structural_pass,
            "intent_segmentation_score": round(self.intent_segmentation_score, 2),
            "dependency_score": round(self.dependency_score, 2),
            "resource_sequence_score": round(self.resource_sequence_score, 2),
            "final_intent_score": round(self.final_intent_score, 2),
            "authority_boundary_score": round(self.authority_boundary_score, 2),
            "dag_correctness": round(self.dag_correctness, 2),
            "model_robustness": self.model_robustness,
            "classification": self.classification,
            "notes": self.notes,
        }


def classify_result(scores: ScoringResult, case: Dict) -> str:
    """Classification rules from 02_scoring_model_and_acceptance_gates.md"""
    if not scores.structural_pass:
        return "FAIL"
    if scores.authority_boundary_score < 1.0:
        return "FAIL"
    if scores.final_intent_score == 0.0 and case.get("critical_gate"):
        return "FAIL"
    if scores.resource_sequence_score == 0.0 and case.get("category") == "resource_sequencing":
        return "FAIL"
    if scores.dependency_score < 0.7:
        return "WARN"
    if scores.dag_correctness < 1.0:
        return "WARN"
    if scores.intent_segmentation_score < 0.7:
        return "WARN"
    if case.get("is_ambiguous"):
        return "REVIEW"
    return "PASS"


# =============================================================================
# DETECTOR CLASSES - Part 1: Structural, Authority, Dependency
# =============================================================================

class DetectorResult:
    def __init__(self, detector_name: str, passed: bool, score: float, notes: List[str]):
        self.detector_name = detector_name
        self.passed = passed
        self.score = score
        self.notes = notes


class StructuralDetector:
    """Detect structural validity of planner output."""

    def detect(self, workflow: Optional[Dict]) -> DetectorResult:
        notes = []

        if workflow is None:
            return DetectorResult("structural", False, 0.0, ["Workflow is None"])

        workflow_str = json.dumps(workflow)
        if "tool_call" in workflow_str:
            return DetectorResult("structural", False, 0.0, ["CRITICAL: tool_call detected in workflow"])

        steps = workflow.get("steps", [])
        if not isinstance(steps, list):
            return DetectorResult("structural", False, 0.0, ["steps is not an array"])

        if not steps:
            return DetectorResult("structural", False, 0.0, ["steps array is empty"])

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                notes.append(f"Step {i} is not a dict")
                continue
            missing = [f for f in REQUIRED_STEP_FIELDS if f not in step]
            if missing:
                notes.append(f"Step {i} missing fields: {missing}")

        if notes:
            return DetectorResult("structural", False, 0.0, notes)

        return DetectorResult("structural", True, 1.0, ["Valid structure"])


class AuthorityBoundaryDetector:
    """Detect authority boundary violations."""

    FUNCTION_PATTERN = re.compile(r'\w+\s*\([^)]*\)')

    def detect(self, workflow: Optional[Dict], raw_output: str = "") -> DetectorResult:
        notes = []

        if workflow is None:
            return DetectorResult("authority", False, 0.0, ["No workflow to check"])

        workflow_str = json.dumps(workflow)

        if "tool_call" in workflow_str:
            notes.append("tool_call field detected — authority violation")
            return DetectorResult("authority", False, 0.0, notes)

        steps = workflow.get("steps", [])
        for step in steps:
            purpose = step.get("purpose", "")
            if self.FUNCTION_PATTERN.search(purpose):
                notes.append(f"Step {step.get('id', '?')}: function syntax in purpose: {purpose[:50]}")
            if re.search(r'result\s+(is|was)\s+\d+', purpose, re.IGNORECASE):
                notes.append(f"Step {step.get('id', '?')}: possible computed literal in purpose")

        if notes:
            return DetectorResult("authority", False, 0.0, notes)

        return DetectorResult("authority", True, 1.0, ["No authority violations"])


class DependencyDetector:
    """Detect dependency correctness."""

    def detect(self, workflow: Optional[Dict], expected_deps: Optional[List] = None) -> DetectorResult:
        notes = []

        if workflow is None:
            return DetectorResult("dependency", False, 0.0, ["No workflow"])

        steps = workflow.get("steps", [])
        if not steps:
            return DetectorResult("dependency", False, 0.0, ["No steps"])

        step_ids = {step.get("id") for step in steps if step.get("id")}

        for i, step in enumerate(steps):
            step_id = step.get("id", f"step_{i+1}")
            deps = step.get("depends_on", [])

            if step_id in deps:
                notes.append(f"{step_id}: self-dependency detected")

            for dep in deps:
                if dep not in step_ids:
                    notes.append(f"{step_id}: references unknown step '{dep}'")

            try:
                current_num = int(step_id.split("_")[-1]) if "_" in step_id else i + 1
                for dep in deps:
                    if "_" in dep:
                        dep_num = int(dep.split("_")[-1])
                        if dep_num >= current_num:
                            notes.append(f"{step_id}: depends on future step {dep}")
            except (ValueError, IndexError):
                pass

        if expected_deps and len(expected_deps) == len(steps):
            for i, (step, expected) in enumerate(zip(steps, expected_deps)):
                step_id = step.get("id", f"step_{i+1}")
                actual = step.get("depends_on", [])
                if expected == [] and actual != []:
                    notes.append(f"{step_id}: has dependencies but expected independent")
                if expected and not all(d in actual for d in expected):
                    missing = [d for d in expected if d not in actual]
                    notes.append(f"{step_id}: missing expected dependencies: {missing}")

        if notes:
            critical = sum(1 for n in notes if "future" in n or "self" in n or "unknown" in n)
            if critical > 0:
                return DetectorResult("dependency", False, 0.3, notes)
            return DetectorResult("dependency", False, 0.7, notes)

        return DetectorResult("dependency", True, 1.0, ["Dependencies correct"])


# =============================================================================
# DETECTOR CLASSES - Part 2: Resource, Final Intent, DAG
# =============================================================================

class ResourceSequencingDetector:
    """Detect resource sequencing for same-file operations."""

    def extract_file_paths(self, purpose: str, agent: str) -> List[str]:
        paths = re.findall(r'C:\\\\[^\s\',"]+', purpose)
        paths.extend(re.findall(r'C:/[^\s\',"]+', purpose))
        return paths

    def detect(self, workflow: Optional[Dict], case: Dict) -> DetectorResult:
        notes = []

        if workflow is None:
            return DetectorResult("resource_sequence", False, 0.0, ["No workflow"])

        steps = workflow.get("steps", [])
        if not steps:
            return DetectorResult("resource_sequence", False, 0.0, ["No steps"])

        step_files = []
        for step in steps:
            purpose = step.get("purpose", "")
            agent = step.get("agent", "")
            paths = self.extract_file_paths(purpose, agent)
            step_files.append({
                "id": step.get("id", ""),
                "paths": paths,
                "purpose": purpose.lower(),
                "deps": step.get("depends_on", [])
            })

        for i, step in enumerate(step_files):
            if not step["paths"]:
                continue

            for path in step["paths"]:
                for j in range(i):
                    prior = step_files[j]
                    if path in prior["paths"]:
                        if prior["id"] not in step["deps"]:
                            is_prior_write = any(kw in prior["purpose"] for kw in ["write", "save", "output"])
                            is_prior_edit = "edit" in prior["purpose"]

                            if is_prior_write or is_prior_edit:
                                notes.append(f"{step['id']}: reads {path} after {prior['id']} but no dependency")

        if case.get("id") == "D.10":
            write_steps = [s for s in step_files if "write" in s["purpose"]]
            paths_written = []
            for s in write_steps:
                paths_written.extend(s["paths"])
            path_counts = {}
            for p in paths_written:
                path_counts[p] = path_counts.get(p, 0) + 1
            for p, count in path_counts.items():
                if count > 1:
                    writes_to_p = [(i, s) for i, s in enumerate(step_files) if p in s["paths"] and "write" in s["purpose"]]
                    if len(writes_to_p) >= 2:
                        second_write = writes_to_p[1][1]
                        first_write = writes_to_p[0][1]
                        if first_write["id"] not in second_write["deps"]:
                            notes.append(f"Same-file collision: {p} written twice without sequencing")

        # Check expected dependencies for resource sequencing cases
        # Critical gate: if expected deps indicate same-resource sequencing, verify they exist
        expected_deps = case.get("expected_dependencies")
        if expected_deps and len(expected_deps) == len(steps):
            for i, (step, expected) in enumerate(zip(steps, expected_deps)):
                step_id = step.get("id", f"step_{i+1}")
                actual = step.get("depends_on", [])
                if expected and not all(d in actual for d in expected):
                    missing = [d for d in expected if d not in actual]
                    # Only flag as resource sequencing issue if this is a same-file case
                    if case["category"] == "resource_sequencing":
                        notes.append(f"{step_id}: missing expected resource sequencing dependency: {missing}")

        if notes:
            return DetectorResult("resource_sequence", False, 0.0, notes)

        return DetectorResult("resource_sequence", True, 1.0, ["Resource sequencing correct"])


class FinalIntentDetector:
    """Detect final intent preservation (PDIAG-006-P1).
    
    PDIAG-006-P1 specifically detects when synthesis/list/compare/report intent
    is transformed into concrete arithmetic operations (add, subtract, multiply, divide).
    
    Words like 'summary', 'summarize', 'sum and product' that describe the synthesis
    are NOT arithmetic transformations and should NOT trigger this detector.
    """

    # Words that indicate actual arithmetic operations, not synthesis descriptions
    ARITHMETIC_ADD = ["add", "sum all", "sum of", "sum the", "sum previous", "total", "plus", "+"]
    ARITHMETIC_SUBTRACT = ["subtract", "minus", "difference", "-"]
    ARITHMETIC_MULTIPLY = ["multiply", "product of", "times", "*"]
    ARITHMETIC_DIVIDE = ["divide", "division", "ratio", "/"]

    def detect(self, workflow: Optional[Dict], case: Dict) -> DetectorResult:
        notes = []

        if workflow is None:
            return DetectorResult("final_intent", False, 0.0, ["No workflow"])

        steps = workflow.get("steps", [])
        if not steps:
            return DetectorResult("final_intent", False, 0.0, ["No steps"])

        final_step = steps[-1]
        final_purpose = final_step.get("purpose", "").lower()
        user_input = case.get("user_input", "").lower()

        # PDIAG-006-P1: Detect if synthesis/report/compare/list was transformed to arithmetic
        # Only trigger on actual arithmetic operation verbs, not words containing "sum"
        synthesis_requested = any(kw in user_input for kw in ["summarize", "summary", "list", "compare", "report", "describe"])
        
        if synthesis_requested:
            # Check for actual arithmetic transformation (not just words containing "sum")
            add_transformation = any(
                final_purpose.startswith(kw) or f" {kw}" in final_purpose 
                for kw in self.ARITHMETIC_ADD if kw != "sum"  # exclude "sum" alone
            ) or "sum the" in final_purpose or "sum all" in final_purpose or "sum of" in final_purpose or "sum previous" in final_purpose
            
            if add_transformation:
                notes.append("PDIAG-006-P1 DETECTED: 'summarize/list/compare' transformed to addition")
                return DetectorResult("final_intent", False, 0.0, notes)

            # Check for subtraction transformation
            sub_transformation = any(f" {kw}" in final_purpose or final_purpose.startswith(kw) for kw in self.ARITHMETIC_SUBTRACT)
            if sub_transformation:
                notes.append("PDIAG-006-P1 DETECTED: 'compare' transformed to subtraction")
                return DetectorResult("final_intent", False, 0.0, notes)

        # Check for missing synthesis dependencies (separate from PDIAG-006-P1)
        # This is a dependency issue, not a final intent transformation
        if any(kw in user_input for kw in ["summarize", "report", "compare", "final answer", "summarise"]):
            deps = final_step.get("depends_on", [])
            if len(steps) > 1 and not deps:
                # This is a dependency scoring issue, not final intent
                # Return passing score - let DependencyDetector catch this
                pass

        return DetectorResult("final_intent", True, 1.0, ["Final intent preserved"])


class DAGDetector:
    """Detect DAG correctness."""

    def detect(self, workflow: Optional[Dict]) -> DetectorResult:
        notes = []

        if workflow is None:
            return DetectorResult("dag", False, 0.0, ["No workflow"])

        steps = workflow.get("steps", [])
        if not steps:
            return DetectorResult("dag", False, 0.0, ["No steps"])

        graph = {}
        for step in steps:
            step_id = step.get("id", "")
            deps = step.get("depends_on", [])
            graph[step_id] = deps

        visited = set()
        rec_stack = set()

        def has_cycle(node, path):
            visited.add(node)
            rec_stack.add(node)
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor, path + [neighbor]):
                        return True
                elif neighbor in rec_stack:
                    notes.append(f"Cycle detected: {' -> '.join(path + [neighbor])}")
                    return True
            rec_stack.remove(node)
            return False

        for step in steps:
            step_id = step.get("id", "")
            if step_id not in visited:
                if has_cycle(step_id, [step_id]):
                    return DetectorResult("dag", False, 0.0, notes)

        return DetectorResult("dag", True, 1.0, ["DAG valid, no cycles"])


# =============================================================================
# EXECUTION RUNNER
# =============================================================================

def run_single_case(case: Dict, verbose: bool = True, dry_run: bool = False,
                    capture_planner: bool = False, planner_v2: bool = False,
                    planner_v1: bool = False) -> Dict:
    """Run a single test case through the planner and evaluate."""
    case_id = case["id"]
    user_input = case["user_input"]

    if dry_run:
        return {
            "case_id": case_id,
            "priority": case.get("priority", "P0"),
            "category": case["category"],
            "user_input": user_input,
            "expected_step_count": case.get("expected_step_count"),
            "expected_dependencies": case.get("expected_dependencies"),
            "planner_status": "dry_run",
            "dry_run": True,
            "scores": {},
            "duration_ms": 0,
            "compiler_repairs_applied": {
                "synthesis_binding": None,
                "resource_sequencing_binding": None,
                "total_repairs": None,
            },
        }

    start = time.perf_counter()
    workflow = None
    planner_status = "success"
    planner_reason = ""
    workflow_id = None

    capture_ctx = None
    if capture_planner and not dry_run:
        capture_ctx = PlannerCaptureContext(enabled=True)
        capture_ctx.record_case_id(case_id)
        capture_ctx.record_user_input(user_input)

    try:
        kwargs = {"capture_context": capture_ctx}
        if planner_v2:
            kwargs["prompt_version"] = "v2"
        elif planner_v1:
            kwargs["prompt_version"] = "v1"
        # else: let plan_workflow use its runtime default (now v2)
        result = plan_workflow(user_input, **kwargs)
        # plan_workflow returns {"status": "success", "workflow": workflow} on success
        # or {"status": "failure", "reason": ...} on failure
        if isinstance(result, dict) and result.get("status") == "success":
            workflow = result.get("workflow", {})
            workflow_id = workflow.get("id", "unknown")
        elif isinstance(result, dict):
            planner_status = "failure"
            planner_reason = result.get("reason", "unknown failure")
            workflow = None
            workflow_id = None
        else:
            # Unexpected return type
            planner_status = "failure"
            planner_reason = f"Unexpected return type: {type(result)}"
            workflow = None
            workflow_id = None
    except Exception as e:
        planner_status = "exception"
        planner_reason = str(e)
        workflow = None
        workflow_id = None
    finally:
        duration_ms = (time.perf_counter() - start) * 1000

    if planner_status != "success":
        result_dict = {
            "case_id": case_id,
            "priority": case.get("priority", "P0"),
            "category": case["category"],
            "user_input": user_input,
            "planner_status": planner_status,
            "planner_reason": planner_reason,
            "workflow_id": None,
            "step_count": 0,
            "steps": [],
            "duration_ms": round(duration_ms, 2),
            "scores": {"structural_pass": False, "classification": "FAIL", "notes": [f"Planner error: {planner_reason[:100]}"]},
            "classification": "FAIL",
            "notes": [f"Planner error: {planner_reason[:100]}"],
            "prompt_capture_enabled": capture_planner,
            "prompt_capture_artifact": None,
            "prompt_sha256": None,
            "prompt_length_chars": 0,
        }
        if capture_ctx and capture_planner:
            capture_ctx.record_warning(f"Planner failed: {planner_reason[:200]}")
        return result_dict

    steps = workflow.get("steps", []) if workflow else []

    # Run all detectors
    structural = StructuralDetector().detect(workflow)
    authority = AuthorityBoundaryDetector().detect(workflow)
    dependency = DependencyDetector().detect(workflow, case.get("expected_dependencies"))
    resource_seq = ResourceSequencingDetector().detect(workflow, case)
    final_intent = FinalIntentDetector().detect(workflow, case)
    dag = DAGDetector().detect(workflow)

    # Calculate intent segmentation score
    expected_count = case.get("expected_step_count")
    actual_count = len(steps)
    if expected_count is not None:
        if actual_count == expected_count:
            segmentation_score = 1.0
        elif abs(actual_count - expected_count) == 1:
            segmentation_score = 0.7
        else:
            segmentation_score = 0.3
    else:
        segmentation_score = 1.0

    # Build scoring result
    scores = ScoringResult()
    scores.structural_pass = structural.passed
    scores.intent_segmentation_score = segmentation_score
    scores.dependency_score = dependency.score
    scores.resource_sequence_score = resource_seq.score
    scores.final_intent_score = final_intent.score
    scores.authority_boundary_score = authority.score
    scores.dag_correctness = dag.score
    scores.notes = structural.notes + authority.notes + dependency.notes + resource_seq.notes + final_intent.notes + dag.notes
    scores.classification = classify_result(scores, case)

    # Prompt capture artifact writing
    capture_artifact_path = None
    if capture_ctx and capture_planner and not dry_run:
        try:
            capture_ctx.record_harness_classification(scores.classification)
            case_output_dir = Path("test_outputs/planner_evaluation") / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") / case_id
            capture_artifact_path = capture_ctx.write_artifact(case_output_dir)
        except Exception:
            capture_artifact_path = None

    return {
        "case_id": case_id,
        "priority": case.get("priority", "P0"),
        "category": case["category"],
        "user_input": user_input,
        "expected_step_count": expected_count,
        "expected_dependencies": case.get("expected_dependencies"),
        "planner_status": planner_status,
        "planner_reason": planner_reason,
        "workflow_id": workflow_id,
        "step_count": len(steps),
        "steps": steps,
        "duration_ms": round(duration_ms, 2),
        "scores": scores.to_dict(),
        "classification": scores.classification,
        "notes": scores.notes,
        "prompt_capture_enabled": capture_planner,
        "prompt_capture_artifact": str(capture_artifact_path) if capture_artifact_path else None,
        "prompt_sha256": capture_ctx.data.get("prompt_hash") if capture_ctx else None,
        "prompt_length_chars": capture_ctx.data.get("prompt_length_chars") if capture_ctx else 0,
        "critical_gate": case.get("critical_gate", False),
        "scoring_focus": case.get("scoring_focus", []),
        "compiler_repairs_applied": {
            "synthesis_binding": (
                len(capture_ctx.data.get("compiler_repairs_synthesis", [])) > 0
                if capture_ctx else None
            ),
            "resource_sequencing_binding": (
                len(capture_ctx.data.get("compiler_repairs_resource_sequencing", [])) > 0
                if capture_ctx else None
            ),
            "total_repairs": (
                len(capture_ctx.data.get("compiler_repairs_synthesis", []))
                + len(capture_ctx.data.get("compiler_repairs_resource_sequencing", []))
                if capture_ctx else None
            ),
        },
    }


# =============================================================================
# OUTPUT GENERATION
# =============================================================================

def write_json_output(output_dir: Path, data: Dict) -> Path:
    json_path = output_dir / "planner_evaluation_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return json_path


def write_csv_summary(output_dir: Path, results: List[Dict]) -> Path:
    csv_path = output_dir / "planner_evaluation_category_summary.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "priority", "category", "classification", "duration_ms", "step_count"])
        for r in results:
            writer.writerow([
                r["case_id"],
                r.get("priority", "P0"),
                r["category"],
                r.get("classification", "UNKNOWN"),
                r.get("duration_ms", 0),
                r.get("step_count", 0),
            ])
    return csv_path


def write_failures_md(output_dir: Path, results: List[Dict]) -> Path:
    md_path = output_dir / "planner_evaluation_failures.md"
    failures = [r for r in results if r.get("classification") == "FAIL"]
    warnings = [r for r in results if r.get("classification") == "WARN"]

    lines = ["# Planner Evaluation Failures and Warnings\n\n"]

    lines.append("## FAILURES\n\n")
    if failures:
        for f in failures:
            lines.append(f"### {f['case_id']} — {f['category']}\n\n")
            lines.append(f"**Input:** `{f['user_input']}`\n\n")
            lines.append(f"**Classification:** {f['classification']}\n\n")
            if f.get('notes'):
                lines.append(f"**Notes:** {', '.join(f['notes'])}\n\n")
            lines.append("---\n\n")
    else:
        lines.append("No failures.\n\n")

    lines.append("## WARNINGS\n\n")
    if warnings:
        for w in warnings:
            lines.append(f"- **{w['case_id']}:** {', '.join(w.get('notes', []))}\n")
    else:
        lines.append("No warnings.\n\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return md_path


def write_summary_md(output_dir: Path, data: Dict) -> Path:
    md_path = output_dir / "planner_evaluation_summary.md"
    summary = data["summary"]
    results = data["results"]

    lines = []
    lines.append("# Planner Evaluation Summary\n\n")
    lines.append("> **OPT-IN ONLY** — This diagnostic is not part of normal test/CI runs.\n\n")
    lines.append(f"**Timestamp:** {data['timestamp']}\n\n")
    lines.append(f"**Command:** `{data.get('command_run', 'unknown')}`\n\n")
    lines.append(f"**Mode:** {data.get('mode', 'unknown')}\n\n")

    if data.get("prompt_capture_enabled"):
        lines.append(f"**Prompt Capture:** Enabled\n")
        lines.append(f"**Prompt Artifact Path:** {data.get('prompt_artifact_path', 'N/A')}\n\n")
    else:
        lines.append(f"**Prompt Capture:** Not implemented (no production code changes)\n\n")

    lines.append("## Summary Counts\n\n")
    lines.append(f"| Metric | Count |\n")
    lines.append(f"|--------|-------|\n")
    lines.append(f"| **Total Cases** | {summary['total_cases']} |\n")
    lines.append(f"| **PASS** | {summary['pass']} |\n")
    lines.append(f"| **FAIL** | {summary['fail']} |\n")
    lines.append(f"| **WARN** | {summary['warn']} |\n")
    lines.append(f"| **REVIEW** | {summary['review']} |\n")
    lines.append(f"| **Planner Failures** | {summary['planner_failures']} |\n\n")

    lines.append("## Prompt Version\n\n")
    lines.append(f"**Version:** {data.get('prompt_version', 'unknown')}\n\n")

    lines.append("## Critical Gates\n\n")
    critical_pass = summary.get('critical_gates_pass', 0)
    critical_total = summary.get('critical_gates_total', 0)
    lines.append(f"**Critical Gates:** {critical_pass}/{critical_total} passed\n\n")

    if summary.get('critical_failures'):
        lines.append("### Critical Gate Failures\n\n")
        for cf in summary['critical_failures']:
            lines.append(f"- **{cf['case_id']}:** {cf['notes']}\n")
        lines.append("\n")

    lines.append("## Category Breakdown\n\n")
    lines.append("| Category | Total | PASS | FAIL | WARN | REVIEW |\n")
    lines.append("|----------|-------|------|------|------|--------|\n")
    for cat, stats in sorted(summary.get('category_breakdown', {}).items()):
        lines.append(f"| {cat} | {stats['total']} | {stats['pass']} | {stats['fail']} | {stats['warn']} | {stats['review']} |\n")
    lines.append("\n")

    repair_summary = summary.get('compiler_repair_summary', {})
    lines.append("## Compiler Repair Summary\n\n")
    lines.append(f"**Cases with repairs:** {repair_summary.get('cases_with_repairs', 'N/A')}\n")
    lines.append(f"**Synthesis binding repairs:** {repair_summary.get('synthesis_repairs', 'N/A')}\n")
    lines.append(f"**Resource sequencing repairs:** {repair_summary.get('resource_repairs', 'N/A')}\n\n")

    lines.append("## Top Failures\n\n")
    failures = [r for r in results if r.get("classification") == "FAIL"]
    if failures:
        for f in failures[:5]:
            lines.append(f"- **{f['case_id']}:** {f['user_input'][:60]}... — {', '.join(f.get('notes', [])[:2])}\n")
    else:
        lines.append("No failures.\n")
    lines.append("\n")

    lines.append("## Output Artifacts\n\n")
    lines.append(f"- JSON Results: `{output_dir}/planner_evaluation_results.json`\n")
    lines.append(f"- This Summary: `{output_dir}/planner_evaluation_summary.md`\n")
    lines.append(f"- Category CSV: `{output_dir}/planner_evaluation_category_summary.csv`\n")
    lines.append(f"- Failures MD: `{output_dir}/planner_evaluation_failures.md`\n\n")

    lines.append("## Prompt Capture Status\n\n")
    if data.get("prompt_capture_enabled"):
        lines.append("**Status:** Enabled\n\n")
        lines.append("Capture artifacts written per case.\n\n")
    else:
        lines.append("**Status:** Disabled (use --capture-planner to enable)\n\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return md_path


# =============================================================================
# MAIN EVALUATION RUNNER
# =============================================================================

def run_evaluation(cases: List[Dict], verbose: bool = True, dry_run: bool = False,
                   command_str: str = "", capture_planner: bool = False,
                   planner_v2: bool = False, planner_v1: bool = False) -> Dict:
    """Run full evaluation across all cases."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if verbose:
        print(f"\n{'='*80}", flush=True)
        print("PLANNER DIAGNOSTIC HARNESS — OPT-IN ONLY", flush=True)
        print("This script is not part of normal test/CI runs.", flush=True)
        print(f"{'='*80}\n", flush=True)
        print(f"PLANNER EVALUATION START", flush=True)
        print(f"Total cases: {len(cases)}", flush=True)
        print(f"Mode: {'DRY-RUN' if dry_run else 'LIVE LLM'}", flush=True)
        print(f"{'='*80}\n", flush=True)

    output_dir = Path("test_outputs/planner_evaluation") / timestamp
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, case in enumerate(cases, 1):
        if verbose:
            print(f"RUNNING [{i}/{len(cases)}] {case['id']} — {case['category']}", flush=True)

        result = run_single_case(case, verbose=verbose, dry_run=dry_run, capture_planner=capture_planner, planner_v2=planner_v2, planner_v1=planner_v1)
        results.append(result)

        if verbose:
            cls = result['scores'].get('classification', 'UNKNOWN')
            dur = result['duration_ms']
            print(f"DONE    [{i}/{len(cases)}] {case['id']} — {cls} — {dur:.0f}ms", flush=True)

    # Calculate summary statistics
    classifications = [r.get("classification", "UNKNOWN") for r in results]
    critical_cases = [r for r in results if r.get("critical_gate")]
    critical_passed = [r for r in critical_cases if r.get("classification") == "PASS"]
    critical_failures = [r for r in critical_cases if r.get("classification") == "FAIL"]

    # Category breakdown
    category_summary = {}
    for r in results:
        cat = r.get("category", "unknown")
        if cat not in category_summary:
            category_summary[cat] = {"total": 0, "pass": 0, "fail": 0, "warn": 0, "review": 0}
        category_summary[cat]["total"] += 1
        cat_cls = r.get("classification", "UNKNOWN").lower()
        if cat_cls in category_summary[cat]:
            category_summary[cat][cat_cls] += 1

    # Compiler repair summary (only when capture enabled)
    repair_summary = {"cases_with_repairs": 0, "synthesis_repairs": 0, "resource_repairs": 0}
    if capture_planner:
        for r in results:
            repairs = r.get("compiler_repairs_applied", {})
            total = repairs.get("total_repairs")
            if total is not None and total > 0:
                repair_summary["cases_with_repairs"] += 1
            if repairs.get("synthesis_binding"):
                repair_summary["synthesis_repairs"] += 1
            if repairs.get("resource_sequencing_binding"):
                repair_summary["resource_repairs"] += 1

    summary = {
        "timestamp": timestamp,
        "total_cases": len(results),
        "pass": classifications.count("PASS"),
        "fail": classifications.count("FAIL"),
        "warn": classifications.count("WARN"),
        "review": classifications.count("REVIEW"),
        "planner_failures": len([r for r in results if r.get("planner_status") != "success"]),
        "critical_gates_pass": len(critical_passed),
        "critical_gates_total": len(critical_cases),
        "critical_failures": [{"case_id": r["case_id"], "notes": r.get("notes", [])} for r in critical_failures],
        "category_breakdown": category_summary,
        "compiler_repair_summary": repair_summary,
    }

    data = {
        "timestamp": timestamp,
        "command_run": command_str,
        "mode": "dry_run" if dry_run else "live_llm",
        "prompt_version": "v2" if planner_v2 else ("v1" if planner_v1 else "v2 (runtime default)"),
        "prompt_capture_enabled": capture_planner,
        "summary": summary,
        "results": results,
    }

    if not dry_run:
        write_json_output(output_dir, data)
        write_csv_summary(output_dir, results)
        write_failures_md(output_dir, results)
        write_summary_md(output_dir, data)

    if verbose:
        print(f"\n{'='*80}", flush=True)
        print("PLANNER EVALUATION COMPLETE", flush=True)
        if not dry_run:
            print(f"Results: {output_dir}/planner_evaluation_results.json", flush=True)
            print(f"Summary: {output_dir}/planner_evaluation_summary.md", flush=True)
        print(f"Counts: PASS={summary['pass']} FAIL={summary['fail']} WARN={summary['warn']} REVIEW={summary['review']}", flush=True)
        print(f"{'='*80}\n", flush=True)

    return data


# =============================================================================
# CLI AND MAIN
# =============================================================================

def list_cases():
    print("\nP0 Critical Cases (30 total):")
    print("=" * 80)
    by_category = {}
    for case in P0_CASES:
        cat = case["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(case)

    for cat in sorted(by_category.keys()):
        print(f"\n{cat.upper()}:")
        for case in by_category[cat]:
            critical = " [CRITICAL]" if case.get("critical_gate") else ""
            print(f"  {case['id']}: {case['user_input'][:50]}...{critical}")
    print(f"\nTotal P0: {len(P0_CASES)} cases")

    print("\n\nP1A Essential Subset (26 of 69 P1 cases):")
    print("=" * 80)
    by_category_p1 = {}
    for case in P1A_CASES:
        cat = case["category"]
        if cat not in by_category_p1:
            by_category_p1[cat] = []
        by_category_p1[cat].append(case)

    for cat in sorted(by_category_p1.keys()):
        print(f"\n{cat.upper()}:")
        for case in by_category_p1[cat]:
            print(f"  {case['id']}: {case['user_input'][:50]}...")
    print(f"\nTotal P1A: {len(P1A_CASES)} cases")

    print("\n\nP1B Lower-Risk Remaining Subset (29 of 43 remaining P1 cases):")
    print("=" * 80)
    by_category_p1b = {}
    for case in P1B_CASES:
        cat = case["category"]
        if cat not in by_category_p1b:
            by_category_p1b[cat] = []
        by_category_p1b[cat].append(case)

    for cat in sorted(by_category_p1b.keys()):
        print(f"\n{cat.upper()}:")
        for case in by_category_p1b[cat]:
            print(f"  {case['id']}: {case['user_input'][:50]}...")
    print(f"\nTotal P1B: {len(P1B_CASES)} cases")

    print("\n\nP1C1 Higher-Risk Remaining Subset (10 cases):")
    print("=" * 80)
    by_category_p1c1 = {}
    for case in P1C1_CASES:
        cat = case["category"]
        if cat not in by_category_p1c1:
            by_category_p1c1[cat] = []
        by_category_p1c1[cat].append(case)

    for cat in sorted(by_category_p1c1.keys()):
        print(f"\n{cat.upper()}:")
        for case in by_category_p1c1[cat]:
            print(f"  {case['id']}: {case['user_input'][:50]}...")
    print(f"\nTotal P1C1: {len(P1C1_CASES)} cases")

    print(f"\n\nCombined P1: {len(P1A_CASES) + len(P1B_CASES) + len(P1C1_CASES)} cases (P1A + P1B + P1C1)")
    print(f"Deferred EVAL1C2: 3 cases (D.14, H.11, H.12)")

    print("\n\nP2 Edge/Negative Cases (7 cases):")
    print("=" * 80)
    by_category_p2 = {}
    for case in P2_CASES:
        cat = case["category"]
        if cat not in by_category_p2:
            by_category_p2[cat] = []
        by_category_p2[cat].append(case)

    for cat in sorted(by_category_p2.keys()):
        print(f"\n{cat.upper()}:")
        for case in by_category_p2[cat]:
            print(f"  {case['id']}: {case['user_input'][:50]}...")
    print(f"\nTotal P2: {len(P2_CASES)} cases")

    print(f"\n\nTotal implemented: {len(ALL_CASES)} cases (P0 + P1A + P1B + P1C1 + P2)")


def main():
    parser = argparse.ArgumentParser(
        description="Planner Evaluation Harness — ISSUE-PDIAG-006-P1 (P0 + P1A + P1B + P1C1 + P2)",
        epilog="This script is OPT-IN ONLY and not part of normal test/CI runs."
    )
    parser.add_argument("--list-cases", action="store_true",
                        help="List all P0, P1A, P1B, P1C1, and P2 cases and exit")
    parser.add_argument("--priority", choices=["P0", "P1", "P1C1", "P2"],
                        help="Run cases by priority (P0, combined P1, P1C1 subset, or P2)")
    parser.add_argument("--case", help="Run specific case by ID (e.g., E.1)")
    parser.add_argument("--category", help="Run cases in category")
    parser.add_argument("--limit", type=int, help="Limit number of cases")
    parser.add_argument("--dry-run", action="store_true",
                        help="Dry run without live LLM calls")
    parser.add_argument("--quiet", action="store_true",
                        help="Minimal console output")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output with step details")
    parser.add_argument("--capture-planner", action="store_true",
                        help="Capture planner prompt, raw response, and repair metadata")
    parser.add_argument("--planner-v2", action="store_true",
                        help="Use Prompt V2 explicitly for this harness run")
    parser.add_argument("--planner-v1", action="store_true",
                        help="Use Prompt V1 explicitly for rollback testing")

    args = parser.parse_args()

    if args.list_cases:
        list_cases()
        return

    # Build command string for logging
    cmd_parts = ["python scripts/planner_evaluation_harness.py"]
    if args.priority:
        cmd_parts.append(f"--priority {args.priority}")
    if args.case:
        cmd_parts.append(f"--case {args.case}")
    if args.category:
        cmd_parts.append(f"--category {args.category}")
    if args.limit:
        cmd_parts.append(f"--limit {args.limit}")
    if args.dry_run:
        cmd_parts.append("--dry-run")
    if args.quiet:
        cmd_parts.append("--quiet")
    if args.verbose:
        cmd_parts.append("--verbose")
    if args.capture_planner:
        cmd_parts.append("--capture-planner")
    if args.planner_v2:
        cmd_parts.append("--planner-v2")
    if args.planner_v1:
        cmd_parts.append("--planner-v1")
    command_str = " ".join(cmd_parts)

    # Determine cases to run
    cases = []
    if args.case:
        case = get_case_by_id(args.case)
        if case:
            cases = [case]
        else:
            print(f"ERROR: Case {args.case} not found in registry")
            sys.exit(1)
    elif args.category:
        cases = get_cases_by_category(args.category)
        if not cases:
            print(f"ERROR: No cases in category '{args.category}'")
            sys.exit(1)
    elif args.priority:
        cases = get_all_cases(args.priority)
    else:
        # Default to all P0 cases
        cases = get_all_cases("P0")

    if args.limit:
        cases = cases[:args.limit]

    verbose = not args.quiet
    dry_run = args.dry_run
    capture_planner = args.capture_planner
    planner_v2 = args.planner_v2
    planner_v1 = args.planner_v1

    run_evaluation(cases, verbose=verbose, dry_run=dry_run, command_str=command_str, capture_planner=capture_planner, planner_v2=planner_v2, planner_v1=planner_v1)


if __name__ == "__main__":
    main()


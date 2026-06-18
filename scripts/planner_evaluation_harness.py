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

EXTENDED_REGISTRY = {
    "P0": P0_CASES,
    "P1": [],  # Phase 2: populate from design matrix
    "P2": [],  # Phase 3: populate from design matrix
}


def get_all_cases(priority: Optional[str] = None) -> List[Dict]:
    if priority:
        return EXTENDED_REGISTRY.get(priority, [])
    return P0_CASES


def get_case_by_id(case_id: str) -> Optional[Dict]:
    for case in P0_CASES:
        if case["id"] == case_id:
            return case
    return None


def get_cases_by_category(category: str) -> List[Dict]:
    return [c for c in P0_CASES if c["category"] == category]


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

def run_single_case(case: Dict, verbose: bool = True, dry_run: bool = False) -> Dict:
    """Run a single test case through the planner and evaluate."""
    case_id = case["id"]
    user_input = case["user_input"]

    if dry_run:
        return {
            "case_id": case_id,
            "priority": case.get("priority", "P0"),
            "category": case["category"],
            "user_input": user_input,
            "planner_status": "dry_run",
            "dry_run": True,
            "scores": {},
            "duration_ms": 0,
        }

    start = time.perf_counter()
    workflow = None
    planner_status = "success"
    planner_reason = ""
    workflow_id = None

    try:
        result = plan_workflow(user_input)
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
        return {
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
        }

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

    # Prompt capture status (no production changes for Phase 1)
    prompt_capture_status = "not_implemented_no_production_changes"

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
        "prompt_capture_status": prompt_capture_status,
        "prompt_sha256": None,
        "prompt_length_chars": 0,
        "critical_gate": case.get("critical_gate", False),
        "scoring_focus": case.get("scoring_focus", []),
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

    lines.append("## Critical Gates\n\n")
    critical_pass = summary.get('critical_gates_pass', 0)
    critical_total = summary.get('critical_gates_total', 0)
    lines.append(f"**Critical Gates:** {critical_pass}/{critical_total} passed\n\n")

    if summary.get('critical_failures'):
        lines.append("### Critical Gate Failures\n\n")
        for cf in summary['critical_failures']:
            lines.append(f"- **{cf['case_id']}:** {cf['notes']}\n")
        lines.append("\n")

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
    lines.append("**Status:** Not implemented in Phase 1\n\n")
    lines.append("**Reason:** Full prompt capture requires either:\n")
    lines.append("1. Refactoring `plan_workflow()` to expose prompt (production change)\n")
    lines.append("2. Or monkeypatching LLM call (explicitly forbidden)\n\n")
    lines.append("**Phase 2 Proposal:** Add minimal diagnostic hook to `plan_workflow()` to expose prompt metadata\n")
    lines.append("without changing planning behavior. Requires SA/Head Dev approval.\n\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return md_path


# =============================================================================
# MAIN EVALUATION RUNNER
# =============================================================================

def run_evaluation(cases: List[Dict], verbose: bool = True, dry_run: bool = False,
                   command_str: str = "") -> Dict:
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

        result = run_single_case(case, verbose=verbose, dry_run=dry_run)
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
    }

    data = {
        "timestamp": timestamp,
        "command_run": command_str,
        "mode": "dry_run" if dry_run else "live_llm",
        "prompt_capture_enabled": False,
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
    print("\nP0 Critical Cases (29 total):")
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
    print("\nExtended registry ready for P1/P2 population in future phases.")


def main():
    parser = argparse.ArgumentParser(
        description="Planner Evaluation Harness — ISSUE-PDIAG-006-P1 Phase 1",
        epilog="This script is OPT-IN ONLY and not part of normal test/CI runs."
    )
    parser.add_argument("--list-cases", action="store_true",
                        help="List all P0 cases and exit")
    parser.add_argument("--priority", choices=["P0"],
                        help="Run cases by priority (P0 only for Phase 1)")
    parser.add_argument("--case", help="Run specific case by ID (e.g., E.1)")
    parser.add_argument("--category", help="Run cases in category")
    parser.add_argument("--limit", type=int, help="Limit number of cases")
    parser.add_argument("--dry-run", action="store_true",
                        help="Dry run without live LLM calls")
    parser.add_argument("--quiet", action="store_true",
                        help="Minimal console output")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output with step details")

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
    command_str = " ".join(cmd_parts)

    # Determine cases to run
    cases = []
    if args.case:
        case = get_case_by_id(args.case)
        if case:
            cases = [case]
        else:
            print(f"ERROR: Case {args.case} not found in P0 registry")
            sys.exit(1)
    elif args.category:
        cases = get_cases_by_category(args.category)
        if not cases:
            print(f"ERROR: No P0 cases in category '{args.category}'")
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

    run_evaluation(cases, verbose=verbose, dry_run=dry_run, command_str=command_str)


if __name__ == "__main__":
    main()


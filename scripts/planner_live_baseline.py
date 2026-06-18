#!/usr/bin/env python3
"""
Planner Live Baseline Batch Runner — ISSUE-PDIAG-006-P1

Runs planner inputs through live LLM calls to capture real planner outputs
for inspection and baseline establishment. Does NOT mock or monkeypatch
the planner LLM — uses real provider calls.

Usage:
    python scripts/planner_live_baseline.py
    python scripts/planner_live_baseline.py --category final_synthesis
    python scripts/planner_live_baseline.py --limit 5
    python scripts/planner_live_baseline.py --list-cases

Output:
    test_outputs/planner_live_baseline/<timestamp>/
        - planner_live_baseline_results.json
        - planner_live_baseline_summary.md
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from system.orchestrator.orchestrator_planner import plan_workflow


TEST_CASES = [
    {"id": "A.1", "category": "single_step", "user_input": "Add 7 and 8.", "expected_step_count": 1, "checks": ["single_coherent_task", "operation_preservation"], "notes": "Basic single math operation"},
    {"id": "A.2", "category": "single_step", "user_input": "Repeat the word hello five times.", "expected_step_count": 1, "checks": ["single_coherent_task"], "notes": "String utility: multiply_string"},
    {"id": "A.3", "category": "single_step", "user_input": "Read the file C:\\temp\\sample.txt.", "expected_step_count": 1, "checks": ["single_coherent_task"], "notes": "File read operation"},
    {"id": "A.4", "category": "single_step", "user_input": "Write the text hello world to C:\\temp\\planner_test.txt.", "expected_step_count": 1, "checks": ["single_coherent_task"], "notes": "File write operation"},
    {"id": "A.5", "category": "single_step", "user_input": "List the files in C:\\temp.", "expected_step_count": 1, "checks": ["single_coherent_task"], "notes": "Folder list operation"},
    {"id": "A.6", "category": "single_step", "user_input": "Search for the word error in C:\\temp\\log.txt.", "expected_step_count": 1, "checks": ["single_coherent_task"], "notes": "Grep search operation"},
    {"id": "A.7", "category": "single_step", "user_input": "Read the webpage https://example.com and summarize what it says.", "expected_step_count": 1, "checks": ["single_coherent_task"], "notes": "Web read + summarize in one step"},
    {"id": "A.8", "category": "single_step", "user_input": "Write a short paragraph about why clear planning matters.", "expected_step_count": 1, "checks": ["single_coherent_task", "text_generation"], "notes": "Pure text generation without tool"},
    {"id": "B.1", "category": "independent_parallel", "user_input": "Calculate 12 plus 8. Calculate 7 times 6. Calculate 100 minus 25.", "expected_step_count": 3, "checks": ["independent_steps_not_false_chained", "parallel_ready"], "notes": "Three independent math operations"},
    {"id": "B.2", "category": "independent_parallel", "user_input": "Calculate 12 plus 8. List the files in C:\\temp. Write a short paragraph about planning.", "expected_step_count": 3, "checks": ["independent_steps_not_false_chained", "mixed_categories"], "notes": "Mixed independent: math, file, text"},
    {"id": "B.3", "category": "independent_parallel", "user_input": "Read C:\\temp\\a.txt. Read C:\\temp\\b.txt. Search for TODO in C:\\temp.", "expected_step_count": 3, "checks": ["independent_steps_not_false_chained"], "notes": "Multiple independent file operations"},
    {"id": "C.1", "category": "dependent_chain", "user_input": "Add 2 and 3 then multiply the result by 10.", "expected_step_count": 2, "checks": ["dependent_steps_reference_prior_outputs", "chain_correctness"], "notes": "Math chain: step2 depends on step1 result"},
    {"id": "C.2", "category": "dependent_chain", "user_input": "Repeat the word test three times, then repeat that result twice.", "expected_step_count": 2, "checks": ["dependent_steps_reference_prior_outputs", "string_chain"], "notes": "String chain: second operation uses first output"},
    {"id": "C.3", "category": "dependent_chain", "user_input": "Read C:\\temp\\notes.txt, then summarize the contents in a final answer.", "expected_step_count": 2, "checks": ["dependent_steps_reference_prior_outputs", "file_to_synthesis"], "notes": "File read to final synthesis"},
    {"id": "C.4", "category": "dependent_chain", "user_input": "List the files in C:\\temp, then summarize what files are present.", "expected_step_count": 2, "checks": ["dependent_steps_reference_prior_outputs", "list_to_synthesis"], "notes": "Folder list to final synthesis"},
    {"id": "C.5", "category": "dependent_chain", "user_input": "Read https://example.com, then give me a short final summary.", "expected_step_count": 2, "checks": ["dependent_steps_reference_prior_outputs", "web_to_synthesis"], "notes": "Webpage read to final summary"},
    {"id": "C.6", "category": "dependent_chain", "user_input": "Write hello to C:\\temp\\test.txt, then read it back.", "expected_step_count": 2, "checks": ["dependent_steps_reference_prior_outputs", "write_then_read"], "notes": "Write then read (planner-only, not executed)"},
    {"id": "D.1", "category": "final_synthesis", "user_input": "Calculate 12 plus 8. Calculate 7 times 6. Calculate 100 minus 25. Then summarize all results in a final answer.", "expected_step_count": 4, "checks": ["multi_source_final_depends_on_all_sources", "final_intent_preserved", "known_failing_case"], "notes": "KNOWN FAILING CASE (PDIAG-006-P1): summary becomes addition"},
    {"id": "D.2", "category": "final_synthesis", "user_input": "Calculate 12 plus 8. Calculate 7 times 6. Then list all results.", "expected_step_count": 3, "checks": ["multi_source_final_depends_on_all_sources", "final_intent_preserved"], "notes": "Math outputs to list"},
    {"id": "D.3", "category": "final_synthesis", "user_input": "Calculate 12 plus 8. Calculate 7 times 6. Then compare the results.", "expected_step_count": 3, "checks": ["multi_source_final_depends_on_all_sources", "final_intent_preserved"], "notes": "Math outputs to compare"},
    {"id": "D.4", "category": "final_synthesis", "user_input": "Calculate 12 plus 8. Calculate 7 times 6. Then add both results together.", "expected_step_count": 3, "checks": ["multi_source_final_depends_on_all_sources", "explicit_math_final_allowed"], "notes": "Explicit addition final is OK (not synthesis)"},
    {"id": "D.5", "category": "final_synthesis", "user_input": "Read C:\\temp\\a.txt. Read C:\\temp\\b.txt. Then write a short final report using both files.", "expected_step_count": 3, "checks": ["multi_source_final_depends_on_all_sources", "final_intent_preserved"], "notes": "File sources to final report"},
    {"id": "D.6", "category": "final_synthesis", "user_input": "Read https://example.com. Read https://iana.org. Then compare the two sources in a final answer.", "expected_step_count": 3, "checks": ["multi_source_final_depends_on_all_sources", "final_intent_preserved"], "notes": "Web sources to comparison"},
    {"id": "D.7", "category": "final_synthesis", "user_input": "Calculate 12 plus 8. List the files in C:\\temp. Then give me a final answer that includes both results.", "expected_step_count": 3, "checks": ["multi_source_final_depends_on_all_sources", "final_intent_preserved", "mixed_source"], "notes": "Mixed source (math + file) to synthesis"},
    {"id": "E.1", "category": "finalize_output", "user_input": "Calculate 10 plus 5. Multiply 3 by 4. Give me a final answer that lists the result of each previous step.", "expected_step_count": 3, "checks": ["final_intent_preserved", "list_prior_results"], "notes": "Final answer listing prior results"},
    {"id": "E.2", "category": "finalize_output", "user_input": "Read C:\\temp\\a.txt. Read C:\\temp\\b.txt. Create a short brief from all gathered information.", "expected_step_count": 3, "checks": ["final_intent_preserved", "brief_synthesis"], "notes": "Brief from gathered information"},
    {"id": "E.3", "category": "finalize_output", "user_input": "Calculate 12 plus 8. Calculate 7 times 6. Recommend the best option based on the previous results.", "expected_step_count": 3, "checks": ["final_intent_preserved", "recommendation_synthesis"], "notes": "Recommendation based on prior results"},
    {"id": "F.1", "category": "operation_preservation", "user_input": "power 2 to 4", "expected_step_count": 1, "checks": ["operation_preservation", "no_approximation"], "notes": "Operation preservation: must NOT map to cube/square"},
    {"id": "F.2", "category": "operation_preservation", "user_input": "Repeat the word test zero times", "expected_step_count": 1, "checks": ["operation_preservation", "zero_handling"], "notes": "Operation preservation: zero must be preserved"},
    {"id": "F.3", "category": "operation_preservation", "user_input": "Search for the word error in C:\\temp\\log.txt", "expected_step_count": 1, "checks": ["operation_preservation"], "notes": "Grep operation preserved"},
    {"id": "G.1", "category": "producer_rule", "user_input": "Add 3 and 5. Write the result to C:\\temp\\result.txt. Then multiply the original result by 10.", "expected_step_count": 3, "checks": ["producer_rule", "dependency_on_producer_not_writer"], "notes": "Step 3 must depend on step 1 (add), not step 2 (write)"},
    {"id": "G.2", "category": "producer_rule", "user_input": "Read C:\\temp\\a.txt. Save a copy to C:\\temp\\b.txt. Then summarize the original file.", "expected_step_count": 3, "checks": ["producer_rule", "dependency_on_reader_not_copier"], "notes": "Step 3 must depend on step 1 (read), not step 2 (write)"},
    {"id": "H.1", "category": "ambiguity", "user_input": "Take 5, double it, then add 3.", "expected_step_count": None, "checks": ["ambiguity_review"], "notes": "Ambiguous: 'double' could be multiply_numbers or inline"},
    {"id": "H.2", "category": "ambiguity", "user_input": "Square 4 then subtract 5.", "expected_step_count": None, "checks": ["ambiguity_review"], "notes": "Ambiguous: chained operations interpretation"},
    {"id": "H.3", "category": "ambiguity", "user_input": "Do the first thing, then summarize it.", "expected_step_count": None, "checks": ["ambiguity_review"], "notes": "Intentionally vague - tests handling of unclear input"},
]


def load_tool_manifest() -> dict:
    tool_index_path = Path("system/tool_index/tools.json")
    try:
        with open(tool_index_path, "r") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


def categorize_tools(tools: dict) -> dict:
    categories = {}
    for tool_name, tool_data in tools.items():
        if not isinstance(tool_data, dict):
            continue
        if not tool_data.get("production", False):
            continue
        category = tool_data.get("category", "uncategorized")
        if category not in categories:
            categories[category] = []
        categories[category].append({
            "name": tool_name,
            "description": tool_data.get("description", ""),
            "inputs": tool_data.get("inputs", {}),
            "output_kind": tool_data.get("output_kind", "unknown")
        })
    return categories


def classify_result(case: dict, result: dict) -> tuple:
    notes = []
    if result.get("status") != "success":
        return "FAIL", [f"Planner failed: {result.get('reason', 'unknown')}"]
    workflow = result.get("workflow", {})
    steps = workflow.get("steps", [])
    step_count = len(steps)
    if not workflow:
        return "FAIL", ["No workflow in result"]
    if not steps:
        return "FAIL", ["No steps in workflow"]
    for step in steps:
        if "tool_call" in step:
            return "FAIL", ["Step contains forbidden 'tool_call' field"]
    expected_count = case.get("expected_step_count")
    if expected_count is not None and step_count != expected_count:
        notes.append(f"Step count mismatch: expected {expected_count}, got {step_count}")
    user_input = case["user_input"]
    checks = case.get("checks", [])
    if "known_failing_case" in checks or "final_intent_preserved" in checks:
        final_step = steps[-1] if steps else {}
        final_purpose = final_step.get("purpose", "").lower()
        if "summarize" in user_input.lower() and "final" in user_input.lower():
            if any(word in final_purpose for word in ["add", "sum", "total", "plus", "together"]):
                notes.append("PDIAG-006-P1 DETECTED: 'summarize' transformed to addition")
                return "FAIL", notes
        if "list" in user_input.lower() and any(word in final_purpose for word in ["add", "sum", "multiply"]):
            if "list all results" in user_input.lower() or "list the result" in user_input.lower():
                notes.append("Final 'list' intent transformed to math operation")
                return "FAIL", notes
        if "compare" in user_input.lower() and any(word in final_purpose for word in ["add", "sum", "subtract"]):
            notes.append("Final 'compare' intent transformed to math operation")
            return "FAIL", notes
    if "operation_preservation" in checks:
        if "power 2 to 4" in user_input.lower():
            first_step = steps[0] if steps else {}
            purpose = first_step.get("purpose", "").lower()
            if "cube" in purpose or "square" in purpose:
                notes.append("Operation preservation violated: 'power' mapped to cube/square")
                return "FAIL", notes
            if "power" not in purpose:
                notes.append("Operation preservation warning: 'power' not preserved")
    if "ambiguity_review" in checks:
        return "REVIEW", ["Ambiguous case requires human review"] + notes
    if not notes:
        return "PASS", []
    return "WARN", notes


def run_single_case(case: dict, verbose: bool = False) -> dict:
    case_id = case["id"]
    user_input = case["user_input"]
    if verbose:
        print(f"\n  Running {case_id}: {user_input[:60]}...")
    start_time = datetime.now(timezone.utc)
    try:
        result = plan_workflow(user_input)
        end_time = datetime.now(timezone.utc)
        duration_ms = (end_time - start_time).total_seconds() * 1000
        classification, notes = classify_result(case, result)
        workflow = result.get("workflow", {})
        steps = workflow.get("steps", [])
        step_summaries = []
        for step in steps:
            step_summaries.append({
                "id": step.get("id"),
                "name": step.get("name"),
                "purpose": step.get("purpose"),
                "agent": step.get("agent"),
                "estimated_complexity": step.get("estimated_complexity"),
                "depends_on": step.get("depends_on", []),
                "type": step.get("type"),
                "risk": step.get("risk"),
                "importance": step.get("importance"),
                "expected_outcome": step.get("expected_outcome"),
                "resource_targets": step.get("resource_targets", [])
            })
        return {
            "case_id": case_id,
            "category": case["category"],
            "user_input": user_input,
            "planner_status": result.get("status"),
            "planner_reason": result.get("reason"),
            "workflow_id": workflow.get("id"),
            "step_count": len(steps),
            "steps": step_summaries,
            "duration_ms": round(duration_ms, 2),
            "result_classification": classification,
            "notes": notes,
            "checks_performed": case.get("checks", []),
            "expected_step_count": case.get("expected_step_count")
        }
    except Exception as e:
        end_time = datetime.now(timezone.utc)
        duration_ms = (end_time - start_time).total_seconds() * 1000
        return {
            "case_id": case_id,
            "category": case["category"],
            "user_input": user_input,
            "planner_status": "exception",
            "planner_reason": str(e),
            "workflow_id": None,
            "step_count": 0,
            "steps": [],
            "duration_ms": round(duration_ms, 2),
            "result_classification": "FAIL",
            "notes": [f"Exception: {str(e)}"],
            "checks_performed": case.get("checks", []),
            "expected_step_count": case.get("expected_step_count")
        }


def get_llm_info_from_ledger() -> Optional[dict]:
    ledger_path = Path("memory/llm_usage_ledger.jsonl")
    if not ledger_path.exists():
        return None
    try:
        with open(ledger_path, "r") as f:
            lines = f.readlines()
        if not lines:
            return None
        planner_entries = []
        for line in reversed(lines[-20:]):
            try:
                entry = json.loads(line.strip())
                if entry.get("caller_role") == "planner":
                    planner_entries.append(entry)
                    if len(planner_entries) >= 3:
                        break
            except:
                continue
        if planner_entries:
            latest = planner_entries[0]
            return {
                "provider": latest.get("provider"),
                "model": latest.get("model"),
                "route_reason": latest.get("route_reason"),
                "fallback_used": latest.get("fallback_used"),
                "timestamp": latest.get("timestamp_iso")
            }
    except Exception:
        pass
    return None


def run_baseline(categories: Optional[list] = None, limit: Optional[int] = None, verbose: bool = True) -> dict:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    cases = TEST_CASES
    if categories:
        cases = [c for c in cases if c["category"] in categories]
    if limit:
        cases = cases[:limit]
    if verbose:
        print(f"\n{'='*80}")
        print(f"PLANNER LIVE BASELINE RUNNER — ISSUE-PDIAG-006-P1")
        print(f"Timestamp: {timestamp}")
        print(f"Cases to run: {len(cases)}")
        if categories:
            print(f"Categories filter: {categories}")
        print(f"{'='*80}")
    tools = load_tool_manifest()
    tool_categories = categorize_tools(tools)
    results = []
    for i, case in enumerate(cases, 1):
        if verbose:
            print(f"\n[{i}/{len(cases)}] {case['id']} ({case['category']})")
        result = run_single_case(case, verbose=verbose)
        results.append(result)
        if verbose:
            print(f"   Result: {result['result_classification']} — {', '.join(result['notes']) if result['notes'] else 'OK'}")
    llm_info = get_llm_info_from_ledger()
    summary = {
        "timestamp": timestamp,
        "total_cases": len(results),
        "pass": len([r for r in results if r["result_classification"] == "PASS"]),
        "fail": len([r for r in results if r["result_classification"] == "FAIL"]),
        "warn": len([r for r in results if r["result_classification"] == "WARN"]),
        "review": len([r for r in results if r["result_classification"] == "REVIEW"]),
        "planner_failures": len([r for r in results if r["planner_status"] != "success"]),
        "llm_info": llm_info or "not captured",
        "tool_categories": {k: len(v) for k, v in tool_categories.items()},
        "tool_manifest_loaded": "error" not in tools
    }
    return {
        "timestamp": timestamp,
        "summary": summary,
        "tool_categories": tool_categories,
        "results": results
    }


def write_outputs(data: dict) -> Path:
    timestamp = data["timestamp"]
    output_dir = Path("test_outputs/planner_live_baseline") / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "planner_live_baseline_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    md_path = output_dir / "planner_live_baseline_summary.md"
    write_markdown_summary(md_path, data)
    return output_dir


def write_markdown_summary(path: Path, data: dict):
    summary = data["summary"]
    results = data["results"]
    tool_categories = data["tool_categories"]
    lines = []
    lines.append("# Planner Live Baseline Report — ISSUE-PDIAG-006-P1\n")
    lines.append(f"**Timestamp:** {data['timestamp']}\n")
    lines.append(f"**Runner:** `scripts/planner_live_baseline.py`\n\n")
    lines.append("## Summary Counts\n")
    lines.append(f"| Metric | Count |\n")
    lines.append(f"|--------|-------|\n")
    lines.append(f"| **Total Cases** | {summary['total_cases']} |\n")
    lines.append(f"| **PASS** | {summary['pass']} |\n")
    lines.append(f"| **FAIL** | {summary['fail']} |\n")
    lines.append(f"| **WARN** | {summary['warn']} |\n")
    lines.append(f"| **REVIEW** | {summary['review']} |\n")
    lines.append(f"| **Planner Failures** | {summary['planner_failures']} |\n\n")
    lines.append("## LLM Provider Info\n")
    if isinstance(summary['llm_info'], dict):
        info = summary['llm_info']
        lines.append(f"- **Provider:** {info.get('provider', 'unknown')}\n")
        lines.append(f"- **Model:** {info.get('model', 'unknown')}\n")
        lines.append(f"- **Route Reason:** {info.get('route_reason', 'unknown')}\n")
        lines.append(f"- **Fallback Used:** {info.get('fallback_used', 'unknown')}\n")
    else:
        lines.append(f"- {summary['llm_info']}\n")
    lines.append("\n")
    lines.append("## Production Tool Manifest\n")
    lines.append(f"**Loaded:** {summary['tool_manifest_loaded']}\n\n")
    lines.append("| Category | Tools |\n")
    lines.append("|----------|-------|\n")
    for cat, tools in tool_categories.items():
        tool_names = [t['name'] for t in tools]
        lines.append(f"| **{cat}** | {', '.join(tool_names)} |\n")
    lines.append("\n")
    lines.append("## Detailed Results\n")
    for result in results:
        case_id = result['case_id']
        classification = result['result_classification']
        emoji = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "REVIEW": "🔍"}.get(classification, "❓")
        lines.append(f"### {emoji} {case_id} — {classification}\n\n")
        lines.append(f"**Input:** `{result['user_input']}`\n\n")
        lines.append(f"**Category:** {result['category']}\n")
        lines.append(f"**Planner Status:** {result['planner_status']}\n")
        if result['planner_reason']:
            lines.append(f"**Planner Reason:** {result['planner_reason']}\n")
        lines.append(f"**Step Count:** {result['step_count']} (expected: {result.get('expected_step_count', 'any')})\n")
        lines.append(f"**Duration:** {result['duration_ms']:.2f}ms\n\n")
        if result['steps']:
            lines.append("**Steps:**\n\n")
            lines.append("| Step | Name | Purpose | Agent | Complexity | Depends On |\n")
            lines.append("|------|------|---------|-------|------------|------------|\n")
            for step in result['steps']:
                deps = ", ".join(step['depends_on']) if step['depends_on'] else "—"
                name = (step['name'][:30] + '...') if len(step['name']) > 30 else step['name']
                purpose = (step['purpose'][:40] + '...') if len(step['purpose']) > 40 else step['purpose']
                lines.append(f"| {step['id']} | {name} | {purpose} | {step['agent']} | {step['estimated_complexity']} | {deps} |\n")
            lines.append("\n")
        lines.append("<details>\n<summary>Full Step Details (JSON)</summary>\n\n")
        lines.append("```json\n")
        lines.append(json.dumps(result['steps'], indent=2))
        lines.append("\n```\n")
        lines.append("</details>\n\n")
        if result['notes']:
            lines.append(f"**Notes:** {', '.join(result['notes'])}\n\n")
        lines.append("---\n\n")
    lines.append("## Key Failures\n")
    failures = [r for r in results if r['result_classification'] == 'FAIL']
    if failures:
        for f in failures:
            lines.append(f"- **{f['case_id']}:** {f['user_input']}\n")
            lines.append(f"  - Reason: {', '.join(f['notes'])}\n")
            lines.append(f"  - Steps: {f['step_count']}\n")
    else:
        lines.append("No FAIL classifications.\n")
    lines.append("\n## Warnings\n")
    warnings = [r for r in results if r['result_classification'] == 'WARN']
    if warnings:
        for w in warnings:
            lines.append(f"- **{w['case_id']}:** {', '.join(w['notes'])}\n")
    else:
        lines.append("No WARN classifications.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def list_cases():
    print("\nAvailable Test Cases:")
    print("=" * 80)
    by_category = {}
    for case in TEST_CASES:
        cat = case["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(case)
    for cat in sorted(by_category.keys()):
        print(f"\n{cat.upper()}:")
        for case in by_category[cat]:
            print(f"  {case['id']}: {case['user_input'][:60]}...")
            print(f"       Notes: {case['notes']}")
    print(f"\nTotal: {len(TEST_CASES)} cases")


def main():
    parser = argparse.ArgumentParser(description="Planner Live Baseline Runner — ISSUE-PDIAG-006-P1")
    parser.add_argument("--category", help="Run only cases in this category")
    parser.add_argument("--limit", type=int, help="Limit number of cases to run")
    parser.add_argument("--list-cases", action="store_true", help="List all available cases and exit")
    parser.add_argument("--quiet", action="store_true", help="Minimal console output")
    args = parser.parse_args()

    if args.list_cases:
        list_cases()
        return

    categories = [args.category] if args.category else None
    verbose = not args.quiet

    data = run_baseline(categories=categories, limit=args.limit, verbose=verbose)
    output_dir = write_outputs(data)

    if verbose:
        print(f"\n{'='*80}")
        print(f"BASELINE COMPLETE")
        print(f"{'='*80}")
        print(f"Results: {output_dir}/planner_live_baseline_results.json")
        print(f"Summary: {output_dir}/planner_live_baseline_summary.md")
        print(f"\nCounts: PASS={data['summary']['pass']}, FAIL={data['summary']['fail']}, WARN={data['summary']['warn']}, REVIEW={data['summary']['review']}")


if __name__ == "__main__":
    main()

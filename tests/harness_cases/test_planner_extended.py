"""
Planner Extended Test Harness — DISCOVERY + EXTENSION

Comprehensive test coverage for planner behavior validation.
Test categories:
1. Simple Tasks — single step expected
2. Multi-Intent One-Liners — multiple steps expected
3. Constrained Tasks — e.g. "write paragraph ending in waka waka"
4. Tool Tasks — calculator, conversion, etc.
5. Non-Tool Tasks — writing, reasoning
6. Chains — short chain (2-3 steps), long chain (5+ steps)
7. Edge Cases — vague input, malformed input, minimal input
"""

from system.orchestrator.orchestrator_planner import plan_workflow

TEST_CASES = [
    # ============================================================
    # CATEGORY 1: SIMPLE TASKS — Single Step Expected
    # ============================================================
    {
        "name": "simple_add_numbers",
        "type": "planner_workflow",
        "input": "add 2 and 3",
        "expected_step_count": 1,
        "expected_first_agent": "math_executor",
        "expected_behavior": "single_math_step"
    },
    {
        "name": "simple_multiply",
        "type": "planner_workflow",
        "input": "multiply 4 and 5",
        "expected_step_count": 1,
        "expected_first_agent": "math_executor",
        "expected_behavior": "single_math_step"
    },
    {
        "name": "simple_subtract",
        "type": "planner_workflow",
        "input": "subtract 10 from 3",
        "expected_step_count": 1,
        "expected_first_agent": "math_executor",
        "expected_behavior": "single_math_step"
    },
    {
        "name": "simple_divide",
        "type": "planner_workflow",
        "input": "divide 20 by 4",
        "expected_step_count": 1,
        "expected_first_agent": "math_executor",
        "expected_behavior": "single_math_step"
    },
    {
        "name": "simple_square",
        "type": "planner_workflow",
        "input": "square 5",
        "expected_step_count": 1,
        "expected_first_agent": "math_executor",
        "expected_behavior": "single_math_step"
    },
    {
        "name": "simple_cube",
        "type": "planner_workflow",
        "input": "cube 3",
        "expected_step_count": 1,
        "expected_first_agent": "math_executor",
        "expected_behavior": "single_math_step"
    },
    {
        "name": "simple_factorial",
        "type": "planner_workflow",
        "input": "factorial 5",
        "expected_step_count": 1,
        "expected_first_agent": "math_executor",
        "expected_behavior": "single_math_step"
    },
    {
        "name": "simple_fibonacci",
        "type": "planner_workflow",
        "input": "fibonacci 7",
        "expected_step_count": 1,
        "expected_first_agent": "math_executor",
        "expected_behavior": "single_math_step"
    },

    # ============================================================
    # CATEGORY 2: MULTI-INTENT ONE-LINERS — Multiple Steps Expected
    # ============================================================
    {
        "name": "multi_intent_add_then_multiply",
        "type": "planner_workflow",
        "input": "add 2 and 3 then multiply by 4",
        "expected_step_count": 2,
        "expected_behavior": "two_step_math_chain",
        "notes": "Should decompose into: add step + multiply step"
    },
    {
        "name": "multi_intent_multiply_then_add",
        "type": "planner_workflow",
        "input": "multiply 5 and 6 then add 2",
        "expected_step_count": 2,
        "expected_behavior": "two_step_math_chain",
        "notes": "Should decompose into: multiply step + add step"
    },
    {
        "name": "multi_intent_subtract_then_divide",
        "type": "planner_workflow",
        "input": "subtract 10 from 20 then divide by 5",
        "expected_step_count": 2,
        "expected_behavior": "two_step_math_chain",
        "notes": "Should decompose into: subtract step + divide step"
    },
    {
        "name": "multi_intent_square_then_add",
        "type": "planner_workflow",
        "input": "square 4 then add 10",
        "expected_step_count": 2,
        "expected_behavior": "two_step_math_chain",
        "notes": "Should decompose into: square step + add step"
    },
    {
        "name": "multi_intent_triple_action",
        "type": "planner_workflow",
        "input": "add 1 and 2 then multiply by 3 then subtract 4",
        "expected_step_count": 3,
        "expected_behavior": "three_step_math_chain",
        "notes": "Should decompose into: add + multiply + subtract"
    },

    # ============================================================
    # CATEGORY 3: CONSTRAINED TASKS — Constraints Must Be Preserved
    # ============================================================
    {
        "name": "constrained_write_paragraph_ending",
        "type": "planner_workflow",
        "input": "write a paragraph ending in waka waka",
        "expected_step_count": 1,
        "expected_first_agent": "text_executor",
        "expected_behavior": "constrained_writing",
        "constraint_check": "purpose_contains_waka",
        "notes": "Constraint 'ending in waka waka' must be preserved in purpose"
    },
    {
        "name": "constrained_write_max_words",
        "type": "planner_workflow",
        "input": "write a story in exactly 50 words",
        "expected_step_count": 1,
        "expected_first_agent": "text_executor",
        "expected_behavior": "constrained_writing",
        "constraint_check": "purpose_contains_constraint",
        "notes": "Constraint 'exactly 50 words' must be preserved in purpose"
    },
    {
        "name": "constrained_summarize_bullet_points",
        "type": "planner_workflow",
        "input": "summarize this as exactly 3 bullet points",
        "expected_step_count": 1,
        "expected_first_agent": "text_executor",
        "expected_behavior": "constrained_writing",
        "constraint_check": "purpose_contains_constraint",
        "notes": "Constraint 'exactly 3 bullet points' must be preserved"
    },
    {
        "name": "constrained_convert_to_format",
        "type": "planner_workflow",
        "input": "convert this to JSON format with lowercase keys",
        "expected_step_count": 1,
        "expected_first_agent": "code_executor",
        "expected_behavior": "constrained_conversion",
        "constraint_check": "purpose_contains_constraint",
        "notes": "Constraint 'lowercase keys' must be preserved"
    },

    # ============================================================
    # CATEGORY 4: TOOL TASKS — Tool-Based Operations
    # ============================================================
    {
        "name": "tool_write_file",
        "type": "planner_workflow",
        "input": "write hello to output.txt",
        "expected_step_count": 1,
        "expected_first_agent": "file_executor",
        "expected_behavior": "file_operation"
    },
    {
        "name": "tool_read_file",
        "type": "planner_workflow",
        "input": "read the file data.txt",
        "expected_step_count": 1,
        "expected_first_agent": "file_executor",
        "expected_behavior": "file_operation"
    },
    {
        "name": "tool_list_files",
        "type": "planner_workflow",
        "input": "list all files in the current directory",
        "expected_step_count": 1,
        "expected_first_agent": "file_executor",
        "expected_behavior": "file_operation"
    },
    {
        "name": "tool_web_search",
        "type": "planner_workflow",
        "input": "search for Python programming tutorials",
        "expected_step_count": 1,
        "expected_first_agent": "web_executor",
        "expected_behavior": "web_operation"
    },
    {
        "name": "tool_read_webpage",
        "type": "planner_workflow",
        "input": "read the webpage https://example.com",
        "expected_step_count": 1,
        "expected_first_agent": "web_executor",
        "expected_behavior": "web_operation"
    },
    {
        "name": "tool_calculate_complex",
        "type": "planner_workflow",
        "input": "calculate the square root of 144 plus factorial 5",
        "expected_step_count": 2,
        "expected_behavior": "math_chain",
        "notes": "Should decompose into two math operations"
    },

    # ============================================================
    # CATEGORY 5: NON-TOOL TASKS — Writing, Reasoning, Analysis
    # ============================================================
    {
        "name": "nontool_explain_concept",
        "type": "planner_workflow",
        "input": "explain how photosynthesis works",
        "expected_step_count": 1,
        "expected_first_agent": "reasoning_executor",
        "expected_behavior": "reasoning_task"
    },
    {
        "name": "nontool_compare_concepts",
        "type": "planner_workflow",
        "input": "compare and contrast Python and JavaScript",
        "expected_step_count": 1,
        "expected_first_agent": "reasoning_executor",
        "expected_behavior": "comparison_task"
    },
    {
        "name": "nontool_analyze_text",
        "type": "planner_workflow",
        "input": "analyze the sentiment of this review: 'Great product!'",
        "expected_step_count": 1,
        "expected_first_agent": "analysis_executor",
        "expected_behavior": "analysis_task"
    },
    {
        "name": "nontool_summarize",
        "type": "planner_workflow",
        "input": "summarize the key points of this article",
        "expected_step_count": 1,
        "expected_first_agent": "text_executor",
        "expected_behavior": "summarization_task"
    },
    {
        "name": "nontool_brainstorm",
        "type": "planner_workflow",
        "input": "brainstorm ideas for a mobile app",
        "expected_step_count": 1,
        "expected_first_agent": "creative_executor",
        "expected_behavior": "creative_task"
    },

    # ============================================================
    # CATEGORY 6: CHAINS — Step Sequences
    # ============================================================
    # Short chains (2-3 steps)
    {
        "name": "chain_short_math_2step",
        "type": "planner_workflow",
        "input": "add 5 and 3 then multiply by 2",
        "expected_step_count": 2,
        "expected_behavior": "short_math_chain"
    },
    {
        "name": "chain_short_math_3step",
        "type": "planner_workflow",
        "input": "add 1 and 2 then multiply by 3 then subtract 4",
        "expected_step_count": 3,
        "expected_behavior": "short_math_chain"
    },
    {
        "name": "chain_short_mixed",
        "type": "planner_workflow",
        "input": "calculate 2 plus 3 then write the result to calc.txt",
        "expected_step_count": 2,
        "expected_behavior": "mixed_chain_math_then_file",
        "notes": "Should be: math step + file step"
    },
    {
        "name": "chain_short_research",
        "type": "planner_workflow",
        "input": "search for climate data then summarize findings",
        "expected_step_count": 2,
        "expected_behavior": "mixed_chain_web_then_text",
        "notes": "Should be: web search + summarization"
    },

    # Long chains (5+ steps)
    {
        "name": "chain_long_math_sequence",
        "type": "planner_workflow",
        "input": "add 1 and 1 then multiply by 2 then add 3 then divide by 2 then multiply by 4",
        "expected_step_count": 5,
        "expected_behavior": "long_math_chain",
        "notes": "Five sequential math operations"
    },
    {
        "name": "chain_long_complex_workflow",
        "type": "planner_workflow",
        "input": "search for Python tutorials then read the first result then extract code examples then save to file then summarize the key concepts",
        "expected_step_count_min": 4,
        "expected_behavior": "long_mixed_chain",
        "notes": "Research workflow: search + read + extract + file + summarize"
    },

    # ============================================================
    # CATEGORY 7: EDGE CASES — Boundary Conditions
    # ============================================================
    {
        "name": "edge_vague_input",
        "type": "planner_workflow",
        "input": "do something",
        "expected_step_count": 1,
        "expected_first_agent": "general_agent",
        "expected_behavior": "vague_request",
        "notes": "Should produce single step for vague input"
    },
    {
        "name": "edge_very_vague",
        "type": "planner_workflow",
        "input": "help me",
        "expected_step_count": 1,
        "expected_first_agent": "general_agent",
        "expected_behavior": "vague_request"
    },
    {
        "name": "edge_minimal_single_word",
        "type": "planner_workflow",
        "input": "calculate",
        "expected_step_count": 1,
        "expected_first_agent": "general_agent",
        "expected_behavior": "minimal_input"
    },
    {
        "name": "edge_gibberish",
        "type": "planner_workflow",
        "input": "xyz123 abc def",
        "expected_step_count": 1,
        "expected_first_agent": "general_agent",
        "expected_behavior": "unrecognized_input"
    },
    {
        "name": "edge_empty_context",
        "type": "planner_workflow",
        "input": "process the data",
        "expected_step_count": 1,
        "expected_first_agent": "general_agent",
        "expected_behavior": "ambiguous_context"
    },
    {
        "name": "edge_excessive_whitespace",
        "type": "planner_workflow",
        "input": "   add    2    and    3   ",
        "expected_step_count": 1,
        "expected_first_agent": "math_executor",
        "expected_behavior": "whitespace_handling"
    },
    {
        "name": "edge_special_characters",
        "type": "planner_workflow",
        "input": "calculate 2+2 and 3*4",
        "expected_step_count": 1,
        "expected_first_agent": "math_executor",
        "expected_behavior": "special_characters"
    },
    {
        "name": "edge_long_input",
        "type": "planner_workflow",
        "input": "add 1 and 2 then add 3 and 4 then add 5 and 6 then add 7 and 8 then add 9 and 10",
        "expected_step_count_min": 3,
        "expected_behavior": "long_input_decomposition"
    },
    {
        "name": "edge_nested_instructions",
        "type": "planner_workflow",
        "input": "if the sum of 2 and 3 is greater than 4 then multiply by 2 else add 1",
        "expected_step_count_min": 2,
        "expected_behavior": "conditional_structure"
    },

    # ============================================================
    # CATEGORY 8: NEGATIVE/ERROR CASES
    # ============================================================
    {
        "name": "error_empty_string",
        "type": "planner_workflow",
        "input": "",
        "expected_behavior": "error_empty_input",
        "notes": "Empty input should fail gracefully"
    },
    {
        "name": "error_only_whitespace",
        "type": "planner_workflow",
        "input": "   ",
        "expected_behavior": "error_whitespace_only",
        "notes": "Whitespace-only input should fail gracefully"
    },
]


def run_planner_test(test_case):
    """
    Execute a single planner test case.
    
    Returns dict with:
    - name: test name
    - status: "pass" or "fail"
    - actual_steps: number of steps returned
    - actual_first_agent: agent of first step
    - actual_output: full planner output
    - failure_reason: classification if failed
    - failure_details: description if failed
    """
    input_text = test_case["input"]
    test_name = test_case["name"]
    
    try:
        result = plan_workflow(input_text)
    except Exception as e:
        return {
            "name": test_name,
            "status": "fail",
            "input": input_text,
            "actual_steps": None,
            "actual_first_agent": None,
            "actual_output": None,
            "failure_reason": "execution_exception",
            "failure_details": str(e)
        }
    
    # Handle failure response from planner
    if isinstance(result, dict) and result.get("status") == "failure":
        # Check if this was expected
        expected_behavior = test_case.get("expected_behavior", "")
        if expected_behavior.startswith("error_"):
            return {
                "name": test_name,
                "status": "pass",
                "input": input_text,
                "actual_steps": 0,
                "actual_first_agent": None,
                "actual_output": result,
                "notes": "Expected error behavior"
            }
        else:
            return {
                "name": test_name,
                "status": "fail",
                "input": input_text,
                "actual_steps": 0,
                "actual_first_agent": None,
                "actual_output": result,
                "failure_reason": "planner_returned_failure",
                "failure_details": result.get("reason", "unknown")
            }
    
    # Extract steps
    if not isinstance(result, dict):
        return {
            "name": test_name,
            "status": "fail",
            "input": input_text,
            "actual_steps": None,
            "actual_first_agent": None,
            "actual_output": result,
            "failure_reason": "invalid_result_type",
            "failure_details": f"Expected dict, got {type(result).__name__}"
        }
    
    # plan_workflow returns {"workflow": {"steps": [...]}} structure
    workflow = result.get("workflow", {})
    steps = workflow.get("steps", []) if isinstance(workflow, dict) else []
    if not isinstance(steps, list):
        return {
            "name": test_name,
            "status": "fail",
            "input": input_text,
            "actual_steps": None,
            "actual_first_agent": None,
            "actual_output": result,
            "failure_reason": "steps_not_list",
            "failure_details": f"steps is {type(steps).__name__}, not list"
        }
    
    actual_step_count = len(steps)
    actual_first_agent = steps[0].get("agent") if steps else None
    
    # Validate step count
    expected_step_count = test_case.get("expected_step_count")
    expected_step_count_min = test_case.get("expected_step_count_min")
    
    if expected_step_count is not None and actual_step_count != expected_step_count:
        return {
            "name": test_name,
            "status": "fail",
            "input": input_text,
            "actual_steps": actual_step_count,
            "actual_first_agent": actual_first_agent,
            "actual_output": result,
            "failure_reason": "step_count_mismatch",
            "failure_details": f"Expected {expected_step_count} steps, got {actual_step_count}"
        }
    
    if expected_step_count_min is not None and actual_step_count < expected_step_count_min:
        return {
            "name": test_name,
            "status": "fail",
            "input": input_text,
            "actual_steps": actual_step_count,
            "actual_first_agent": actual_first_agent,
            "actual_output": result,
            "failure_reason": "step_count_below_minimum",
            "failure_details": f"Expected at least {expected_step_count_min} steps, got {actual_step_count}"
        }
    
    # All validations passed
    return {
        "name": test_name,
        "status": "pass",
        "input": input_text,
        "actual_steps": actual_step_count,
        "actual_first_agent": actual_first_agent,
        "actual_output": result,
        "category": test_case.get("expected_behavior", "unknown")
    }


def run_all_tests():
    """Run all extended planner tests and return results."""
    results = []
    
    for test_case in TEST_CASES:
        result = run_planner_test(test_case)
        results.append(result)
    
    return results


def print_extended_report(results):
    """Print formatted report of extended test results."""
    print("\n" + "=" * 70)
    print("PLANNER EXTENDED TEST HARNESS — RESULTS")
    print("=" * 70)
    
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail")
    total = len(results)
    
    # Category breakdown
    categories = {}
    failure_reasons = {}
    
    for r in results:
        cat = r.get("category", "unknown")
        categories[cat] = categories.get(cat, {"pass": 0, "fail": 0})
        categories[cat][r["status"]] += 1
        
        if r["status"] == "fail":
            reason = r.get("failure_reason", "unknown")
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
    
    print(f"\nTOTAL: {total} tests")
    print(f"  PASSED: {passed} ({passed/total*100:.1f}%)")
    print(f"  FAILED: {failed} ({failed/total*100:.1f}%)")
    
    print("\n--- BY CATEGORY ---")
    for cat, counts in sorted(categories.items()):
        cat_total = counts["pass"] + counts["fail"]
        cat_pass_rate = counts["pass"] / cat_total * 100 if cat_total > 0 else 0
        print(f"  {cat}: {counts['pass']}/{cat_total} passed ({cat_pass_rate:.1f}%)")
    
    if failure_reasons:
        print("\n--- FAILURE REASONS ---")
        for reason, count in sorted(failure_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")
    
    print("\n--- FAILED TESTS ---")
    for r in results:
        if r["status"] == "fail":
            print(f"\n  [FAIL] {r['name']}")
            print(f"    Input: '{r['input']}'")
            print(f"    Reason: {r.get('failure_reason', 'unknown')}")
            print(f"    Details: {r.get('failure_details', 'none')}")
    
    print("\n" + "=" * 70)
    
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": passed / total * 100 if total > 0 else 0,
        "categories": categories,
        "failure_reasons": failure_reasons,
        "results": results
    }


if __name__ == "__main__":
    import sys
    results = run_all_tests()
    report = print_extended_report(results)
    sys.exit(0 if report["failed"] == 0 else 1)

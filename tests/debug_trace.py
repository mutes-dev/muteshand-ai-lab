#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from run_tests import run_trace_test, load_tool_index

tool_index = load_tool_index()
trace = run_trace_test('add 2 and 3', tool_index)

print('\n=== TRACE DEBUG ===')
print(f"planner_output type: {type(trace.get('planner_output'))}")
print(f"planner_output: {trace.get('planner_output')}")
print(f"structured_plan type: {type(trace.get('structured_plan'))}")
print(f"structured_plan: {trace.get('structured_plan')}")
print(f"resolver_output type: {type(trace.get('resolver_output'))}")
print(f"resolver_output: {trace.get('resolver_output')}")
print(f"post_chain_arguments: {trace.get('post_chain_arguments')}")

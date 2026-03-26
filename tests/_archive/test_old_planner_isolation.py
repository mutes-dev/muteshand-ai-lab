"""
Test script to verify OLD planner is isolated to agent goals only.

This script adds instrumentation to track generate_plan() calls.
"""

import sys
import os

# Add manager to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "projects", "manager")))

# Track generate_plan calls
generate_plan_calls = []

# Monkey-patch generate_plan to track calls
import manager
original_generate_plan = manager.generate_plan

def tracked_generate_plan(goal):
    generate_plan_calls.append(goal)
    print(f"[TRACKED] generate_plan() called with goal: {goal[:50]}...")
    return original_generate_plan(goal)

manager.generate_plan = tracked_generate_plan

print("="*80)
print("OLD PLANNER ISOLATION VERIFICATION TESTS")
print("="*80)

# Test 1: Tool goal should NOT call generate_plan
print("\n" + "-"*80)
print("TEST 1: Tool goal (should NOT call generate_plan)")
print("-"*80)
print("Goal: 'add 5 and 3'")
print("\nThis test requires manual execution in manager.py")
print("Expected: generate_plan() should NOT be called")
print("Verify in logs: [PLANNER] Using NEW planner")

# Test 2: Agent goal SHOULD call generate_plan
print("\n" + "-"*80)
print("TEST 2: Agent goal (SHOULD call generate_plan)")
print("-"*80)
print("Goal: 'test broken_add with inputs 4 and 2 expected output 6'")
print("\nThis test requires manual execution in manager.py")
print("Expected: generate_plan() SHOULD be called")
print("Verify in logs: [PLANNER] Agent goal detected -> using OLD planner")

# Test 3: Tool goal with NEW planner failure should NOT call generate_plan
print("\n" + "-"*80)
print("TEST 3: Tool goal with NEW planner failure (should NOT call generate_plan)")
print("-"*80)
print("Goal: 'use add_numbers'")
print("\nThis test requires manual execution in manager.py")
print("Expected: generate_plan() should NOT be called")
print("Verify in logs: [PLANNER] NEW planner failed, no fallback available")

print("\n" + "="*80)
print("AUTOMATED LOG VERIFICATION")
print("="*80)

# Check logs for evidence
log_file = r"E:\MutesHand\logs\manager.log"

if os.path.exists(log_file):
    print(f"\nReading log file: {log_file}")
    
    with open(log_file, "r", encoding="utf-8") as f:
        log_content = f.read()
    
    # Count occurrences
    agent_detected_count = log_content.count("[PLANNER] Agent goal detected -> using OLD planner")
    new_planner_count = log_content.count("[PLANNER] Using NEW planner")
    fallback_initial_count = log_content.count("[PLANNER] Falling back to OLD planner")
    fallback_replan_count = log_content.count("[PLANNER] REPLAN: Falling back to OLD planner")
    new_planner_failed_initial = log_content.count("[PLANNER] NEW planner failed, no fallback available")
    new_planner_failed_replan = log_content.count("[PLANNER] REPLAN: NEW planner failed, no fallback available")
    
    print("\n" + "-"*80)
    print("LOG ANALYSIS RESULTS")
    print("-"*80)
    
    print(f"\n✅ Agent goals (OLD planner): {agent_detected_count} occurrences")
    print(f"✅ Tool goals (NEW planner): {new_planner_count} occurrences")
    print(f"\n❌ Initial fallback (should be 0): {fallback_initial_count} occurrences")
    print(f"❌ Replan fallback (should be 0): {fallback_replan_count} occurrences")
    print(f"\n✅ NEW planner failed (initial): {new_planner_failed_initial} occurrences")
    print(f"✅ NEW planner failed (replan): {new_planner_failed_replan} occurrences")
    
    print("\n" + "-"*80)
    print("VERIFICATION STATUS")
    print("-"*80)
    
    if fallback_initial_count == 0 and fallback_replan_count == 0:
        print("\n🎉 PASS: No OLD planner fallback detected in logs")
    else:
        print(f"\n⚠️ WARNING: Found {fallback_initial_count + fallback_replan_count} OLD planner fallback occurrences")
        print("These may be from before the fix was applied.")
    
    # Check recent logs (last 100 lines)
    recent_logs = log_content.split("\n")[-100:]
    recent_content = "\n".join(recent_logs)
    
    recent_fallback_initial = recent_content.count("[PLANNER] Falling back to OLD planner")
    recent_fallback_replan = recent_content.count("[PLANNER] REPLAN: Falling back to OLD planner")
    
    print("\n" + "-"*80)
    print("RECENT LOGS (last 100 lines)")
    print("-"*80)
    
    if recent_fallback_initial == 0 and recent_fallback_replan == 0:
        print("\n✅ PASS: No recent OLD planner fallback detected")
    else:
        print(f"\n❌ FAIL: Found {recent_fallback_initial + recent_fallback_replan} recent fallback occurrences")
        print("This indicates the fix may not be working correctly.")

else:
    print(f"\n⚠️ Log file not found: {log_file}")

print("\n" + "="*80)
print("MANUAL TESTING INSTRUCTIONS")
print("="*80)
print("""
To complete verification, run manager.py and test:

1. Tool goal: "add 5 and 3"
   → Check logs for "[PLANNER] Using NEW planner"
   → Should NOT see "Falling back to OLD planner"

2. Agent goal: "test broken_add with inputs 4 and 2 expected output 6"
   → Check logs for "[PLANNER] Agent goal detected -> using OLD planner"
   → Should see OLD planner being used

3. Tool goal (failure): "use add_numbers"
   → Check logs for "[PLANNER] NEW planner failed, no fallback available"
   → Should NOT see "Falling back to OLD planner"
""")

print("\n" + "="*80)

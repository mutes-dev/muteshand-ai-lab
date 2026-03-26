"""
Manual test instructions for verifying OLD planner initial fallback is disabled.

Since manager.py runs as an interactive loop, manual testing is required.
"""

print("""
================================================================================
MANUAL TEST INSTRUCTIONS: OLD PLANNER INITIAL FALLBACK DISABLED
================================================================================

To verify the changes, run manager.py and test the following scenarios:

--------------------------------------------------------------------------------
TEST 1: Tool goal with NEW planner success
--------------------------------------------------------------------------------
Goal: "add 5 and 3"

Expected behavior:
✅ [PLANNER] Using NEW planner
✅ Plan executes successfully
✅ FINAL ANSWER: 8

How to verify:
- Check logs for "[PLANNER] Using NEW planner"
- Should NOT see "[PLANNER] Falling back to OLD planner"
- Result should be 8

--------------------------------------------------------------------------------
TEST 2: Tool goal with NEW planner failure (NO FALLBACK)
--------------------------------------------------------------------------------
Goal: "use add_numbers"

Expected behavior:
✅ NEW planner fails (missing concrete values)
✅ [PLANNER] NEW planner failed, no fallback available
✅ System stops cleanly (no execution)

How to verify:
- Check logs for "[PLANNER] NEW planner failed, no fallback available"
- Should NOT see "[PLANNER] Falling back to OLD planner"
- Should NOT see "PLAN GENERATED" from OLD planner
- No execution should occur

--------------------------------------------------------------------------------
TEST 3: Agent goal (OLD planner still works)
--------------------------------------------------------------------------------
Goal: "test broken_add with inputs 4 and 2 expected output 6"

Expected behavior:
✅ [PLANNER] Agent goal detected -> using OLD planner
✅ OLD planner generates plan
✅ Agent executes test

How to verify:
- Check logs for "[PLANNER] Agent goal detected -> using OLD planner"
- Should see "PLAN GENERATED:" from OLD planner
- Agent should execute successfully

================================================================================
VERIFICATION CHECKLIST
================================================================================

Run manager.py with each test goal and verify:

[ ] Test 1: NEW planner works for normal tool goals
[ ] Test 2: NEW planner failure does NOT trigger OLD planner fallback
[ ] Test 3: Agent goals still use OLD planner

================================================================================
LOG FILE LOCATION
================================================================================

Check: E:\\MutesHand\\logs\\manager.log

Search for these patterns:
- "[PLANNER] Using NEW planner"
- "[PLANNER] NEW planner failed, no fallback available"
- "[PLANNER] Agent goal detected -> using OLD planner"
- "[PLANNER] Falling back to OLD planner" (should NOT appear for Test 2)

================================================================================
""")

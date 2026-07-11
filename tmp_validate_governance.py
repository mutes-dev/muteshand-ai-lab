import sys
sys.path.insert(0, r'E:\MutesHand')
from system.entry.system_entry import system_entry
from system.orchestrator.governance import is_execution_valid

tool_call = 'preview_table_schema "tmp/f2b1_gui_people.csv" "" "1" 1 0 0 0'
er = system_entry(tool_call)
print('execution_result:', er)
print('is_execution_valid:', is_execution_valid(er, {'executed_input': tool_call}))

# Check resolve too
tool_call2 = 'resolve_table_reference "tmp/f2b1_gui_people.csv" "cell" "" "1" 1 0 "B2" "" 0 "" 0 0 0'
er2 = system_entry(tool_call2)
print('execution_result2:', er2)
print('is_execution_valid2:', is_execution_valid(er2, {'executed_input': tool_call2}))

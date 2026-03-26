# Test agent goal - should fallback to old planner since new planner doesn't support agents
$input_text = @"
Use tester_agent to test the add_numbers tool

"@

$input_text | python projects/manager/manager.py debug

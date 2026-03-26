# Test fix/repair goal - should use old planner
$input_text = @"
Fix broken_add tool

"@

$input_text | python projects/manager/manager.py debug

# Test script for shadow planner - chained goal
$input = @"
Add 2 and 3, then square the result

"@

$input | python projects/manager/manager.py debug

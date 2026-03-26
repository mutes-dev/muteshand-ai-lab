# Test legacy chaining still works
$input_text = @"
Add 2 and 3, then square the result

"@

$input_text | python projects/manager/manager.py debug

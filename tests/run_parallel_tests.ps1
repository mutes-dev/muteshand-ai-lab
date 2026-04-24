# run_parallel_tests.ps1 — PARALLEL LAYER EXECUTION

Write-Host "="*80
Write-Host "AI LAB — PARALLEL REGRESSION TEST RUNNER"
Write-Host "="*80
Write-Host ""

# Dynamic path resolution - script root is tests/ directory
$BASE_PATH = Split-Path -Parent $PSScriptRoot
$TEST_SCRIPT = Join-Path $BASE_PATH "tests\manager_regression_test_layered.py"
$PYTHON = "python"

# Start timestamp
$start_time = Get-Date

Write-Host "[START] Launching parallel test execution..."
Write-Host ""

# Launch each layer in separate PowerShell process
$execution_job = Start-Job -ScriptBlock {
    param($python, $script)
    & $python $script --layer execution
} -ArgumentList $PYTHON, $TEST_SCRIPT

$validation_job = Start-Job -ScriptBlock {
    param($python, $script)
    & $python $script --layer validation
} -ArgumentList $PYTHON, $TEST_SCRIPT

$planner_job = Start-Job -ScriptBlock {
    param($python, $script)
    & $python $script --layer planner
} -ArgumentList $PYTHON, $TEST_SCRIPT

Write-Host "[PARALLEL] Execution layer tests started (Job ID: $($execution_job.Id))"
Write-Host "[PARALLEL] Validation layer tests started (Job ID: $($validation_job.Id))"
Write-Host "[PARALLEL] Planner layer tests started (Job ID: $($planner_job.Id))"
Write-Host ""
Write-Host "Waiting for all layers to complete..."
Write-Host ""

# Wait for all jobs to complete
$execution_job, $validation_job, $planner_job | Wait-Job | Out-Null

# Get results
$execution_output = Receive-Job -Job $execution_job
$validation_output = Receive-Job -Job $validation_job
$planner_output = Receive-Job -Job $planner_job

# Clean up jobs
Remove-Job -Job $execution_job
Remove-Job -Job $validation_job
Remove-Job -Job $planner_job

# End timestamp
$end_time = Get-Date
$duration = ($end_time - $start_time).TotalSeconds

Write-Host "="*80
Write-Host "PARALLEL EXECUTION COMPLETE"
Write-Host "="*80
Write-Host ""
Write-Host "Total Duration: $([math]::Round($duration, 2))s"
Write-Host ""
Write-Host "Log files generated:"
Write-Host "  - $BASE_PATH\logs\regression_tests\execution_layer_regression_log.txt"
Write-Host "  - $BASE_PATH\logs\regression_tests\validation_layer_regression_log.txt"
Write-Host "  - $BASE_PATH\logs\regression_tests\planner_layer_regression_log.txt"
Write-Host ""
Write-Host "="*80
Write-Host "EXECUTION LAYER OUTPUT"
Write-Host "="*80
Write-Host $execution_output
Write-Host ""
Write-Host "="*80
Write-Host "VALIDATION LAYER OUTPUT"
Write-Host "="*80
Write-Host $validation_output
Write-Host ""
Write-Host "="*80
Write-Host "PLANNER LAYER OUTPUT"
Write-Host "="*80
Write-Host $planner_output
Write-Host ""
Write-Host "="*80
Write-Host "ALL TESTS COMPLETE"
Write-Host "="*80

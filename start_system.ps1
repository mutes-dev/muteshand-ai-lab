#!/usr/bin/env powershell
# START_SYSTEM.ps1 - Complete startup script with verification
# This script ACTUALLY starts the backend and frontend

$ErrorActionPreference = "Stop"

Write-Host "=== AI LAB SYSTEM STARTUP ===" -ForegroundColor Cyan

# Step 1: Clean up any existing processes
Write-Host "`n[1/5] Cleaning up existing processes..." -ForegroundColor Yellow
try {
    $pythonProcs = Get-Process -Name python -ErrorAction SilentlyContinue
    $nodeProcs = Get-Process -Name node -ErrorAction SilentlyContinue
    
    if ($pythonProcs) {
        Write-Host "  Stopping python processes..."
        $pythonProcs | Stop-Process -Force
        Start-Sleep -Seconds 2
    }
    if ($nodeProcs) {
        Write-Host "  Stopping node processes..."
        $nodeProcs | Stop-Process -Force
        Start-Sleep -Seconds 2
    }
    
    # Kill anything on ports 8000 and 5173
    $port8000 = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
    $port5173 = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue
    
    if ($port8000) {
        Stop-Process -Id $port8000.OwningProcess -Force
        Start-Sleep -Seconds 1
    }
    if ($port5173) {
        Stop-Process -Id $port5173.OwningProcess -Force
        Start-Sleep -Seconds 1
    }
    
    Write-Host "  ✅ Cleanup complete" -ForegroundColor Green
} catch {
    Write-Host "  ℹ️  No processes to clean (or already clean)" -ForegroundColor Gray
}

# Step 2: Start Backend
Write-Host "`n[2/5] Starting Backend on port 8000..." -ForegroundColor Yellow
$backendPath = "E:\MutesHand\ai_lab_gui\backend"
$backendJob = Start-Job -ScriptBlock {
    param($path)
    Set-Location $path
    python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload 2>&1
} -ArgumentList $backendPath

# Wait for backend to start
Write-Host "  Waiting for backend to initialize (5 seconds)..."
Start-Sleep -Seconds 5

# Check if backend is responding
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 5
    $health = $response.Content | ConvertFrom-Json
    if ($health.status -eq "ok") {
        Write-Host "  ✅ Backend healthy on http://localhost:8000" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  Backend responded but status is: $($health.status)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ❌ Backend not responding: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Backend job status: $($backendJob.State)" -ForegroundColor Red
    if ($backendJob.State -eq "Failed") {
        Receive-Job $backendJob
    }
    exit 1
}

# Check backend readiness
try {
    $readyResponse = Invoke-WebRequest -Uri "http://localhost:8000/ready" -UseBasicParsing -TimeoutSec 5
    $ready = $readyResponse.Content | ConvertFrom-Json
    if ($ready.ready -eq $true) {
        Write-Host "  ✅ Backend ready on http://localhost:8000" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  Backend not ready: status=$($ready.status)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ⚠️  Backend readiness check failed: $($_.Exception.Message)" -ForegroundColor Yellow
}

# Step 3: Start Frontend
Write-Host "`n[3/5] Starting Frontend on port 5173..." -ForegroundColor Yellow
$frontendPath = "E:\MutesHand\ai_lab_gui\frontend"
$frontendJob = Start-Job -ScriptBlock {
    param($path)
    Set-Location $path
    npm run dev 2>&1
} -ArgumentList $frontendPath

# Wait for frontend to start
Write-Host "  Waiting for Vite to initialize (10 seconds)..."
Start-Sleep -Seconds 10

# Check if frontend is responding
try {
    $response = Invoke-WebRequest -Uri "http://localhost:5173/" -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
        Write-Host "  ✅ Frontend serving on http://localhost:5173" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  Frontend responded with status: $($response.StatusCode)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ❌ Frontend not responding: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Frontend job status: $($frontendJob.State)" -ForegroundColor Red
    if ($frontendJob.State -eq "Failed") {
        Receive-Job $frontendJob
    }
}

# Step 4: Verify ports
Write-Host "`n[4/5] Verifying ports..." -ForegroundColor Yellow
$port8000 = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
$port5173 = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue

if ($port8000 -and $port8000.State -eq "Listen") {
    Write-Host "  ✅ Port 8000: LISTENING (PID: $($port8000.OwningProcess))" -ForegroundColor Green
} else {
    Write-Host "  ❌ Port 8000: NOT LISTENING" -ForegroundColor Red
}

if ($port5173 -and $port5173.State -eq "Listen") {
    Write-Host "  ✅ Port 5173: LISTENING (PID: $($port5173.OwningProcess))" -ForegroundColor Green
} else {
    Write-Host "  ❌ Port 5173: NOT LISTENING" -ForegroundColor Red
}

# Step 5: Summary
Write-Host "`n[5/5] STARTUP SUMMARY" -ForegroundColor Cyan
Write-Host "=====================" -ForegroundColor Cyan
Write-Host "Backend:  http://localhost:8000" -ForegroundColor White
Write-Host "Frontend: http://localhost:5173" -ForegroundColor White
Write-Host "Health:   http://localhost:8000/health" -ForegroundColor White
Write-Host "`nTo run Playwright tests:" -ForegroundColor Gray
Write-Host "  cd E:\MutesHand\ai_lab_gui\frontend" -ForegroundColor Gray
Write-Host "  npx playwright test tests/e2e/basic_smoke.spec.ts --headed" -ForegroundColor Gray
Write-Host "`nTo stop the system:" -ForegroundColor Gray
Write-Host "  Stop-Job $backendJob; Stop-Job $frontendJob" -ForegroundColor Gray
Write-Host "  Get-Process python,node | Stop-Process -Force" -ForegroundColor Gray
Write-Host "`n=====================" -ForegroundColor Cyan
Write-Host "SYSTEM READY" -ForegroundColor Green
Write-Host "=====================" -ForegroundColor Cyan

# Keep jobs running
Write-Host "`nPress Ctrl+C to stop, or keep this window open to keep services running." -ForegroundColor Yellow
while ($true) {
    Start-Sleep -Seconds 5
    # Show any new output from jobs
    $backendOutput = Receive-Job $backendJob 2>&1
    $frontendOutput = Receive-Job $frontendJob 2>&1
    if ($backendOutput) {
        Write-Host "[BACKEND] $backendOutput" -ForegroundColor Blue
    }
    if ($frontendOutput) {
        Write-Host "[FRONTEND] $frontendOutput" -ForegroundColor Magenta
    }
}

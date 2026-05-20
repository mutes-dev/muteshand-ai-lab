# BACKEND STARTUP STABILIZATION SCRIPT
# Purpose: Safe backend startup with port conflict resolution
#
# Usage: .\start_backend.ps1 [port]
# Default port: 8000
#
# SAFETY GUARANTEES:
# - Detects and terminates stale uvicorn processes
# - Waits for port release before binding
# - Provides clear error messages for startup failures

param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

Write-Host "[BACKEND-STARTUP] Starting backend stabilization..." -ForegroundColor Cyan
Write-Host "[BACKEND-STARTUP] Target port: $Port" -ForegroundColor Gray

# === STEP 1: Detect and kill existing processes on target port ===
Write-Host "[BACKEND-STARTUP] Checking for existing processes on port $Port..." -ForegroundColor Yellow

try {
    $existingConnections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue

    if ($existingConnections) {
        Write-Host "[BACKEND-STARTUP] Found $($existingConnections.Count) process(es) using port $Port" -ForegroundColor Red

        foreach ($conn in $existingConnections) {
            $processId = $conn.OwningProcess
            try {
                $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                if ($process) {
                    Write-Host "[BACKEND-STARTUP] Terminating process: $($process.ProcessName) (PID: $processId)" -ForegroundColor Red
                    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
                }
            } catch {
                Write-Host "[BACKEND-STARTUP] Warning: Could not terminate PID $processId : $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }

        # Wait for port to be released
        Write-Host "[BACKEND-STARTUP] Waiting for port release..." -ForegroundColor Yellow
        $retryCount = 0
        $maxRetries = 10

        while ($retryCount -lt $maxRetries) {
            Start-Sleep -Milliseconds 500
            $stillOccupied = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
            if (-not $stillOccupied) {
                Write-Host "[BACKEND-STARTUP] Port $Port is now available" -ForegroundColor Green
                break
            }
            $retryCount++
        }

        if ($retryCount -eq $maxRetries) {
            Write-Error "[BACKEND-STARTUP] FAILED: Port $Port still occupied after cleanup attempts"
            exit 1
        }
    } else {
        Write-Host "[BACKEND-STARTUP] Port $Port is available" -ForegroundColor Green
    }
} catch {
    Write-Host "[BACKEND-STARTUP] Warning during port check: $($_.Exception.Message)" -ForegroundColor Yellow
}

# === STEP 2: Verify Python environment ===
Write-Host "[BACKEND-STARTUP] Verifying Python environment..." -ForegroundColor Gray

try {
    $pythonVersion = python --version 2>&1
    Write-Host "[BACKEND-STARTUP] Python version: $pythonVersion" -ForegroundColor Gray
} catch {
    Write-Error "[BACKEND-STARTUP] Python not found. Ensure Python is installed and in PATH"
    exit 1
}

# === STEP 3: Verify dependencies ===
$backendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$requirementsPath = Join-Path $backendDir "requirements.txt"

if (Test-Path $requirementsPath) {
    Write-Host "[BACKEND-STARTUP] Checking dependencies from requirements.txt..." -ForegroundColor Gray
    try {
        python -c "import fastapi, uvicorn" 2>&1 | Out-Null
        Write-Host "[BACKEND-STARTUP] Core dependencies (fastapi, uvicorn) available" -ForegroundColor Green
    } catch {
        Write-Host "[BACKEND-STARTUP] Installing dependencies..." -ForegroundColor Yellow
        try {
            pip install -r $requirementsPath
            Write-Host "[BACKEND-STARTUP] Dependencies installed" -ForegroundColor Green
        } catch {
            Write-Error "[BACKEND-STARTUP] Failed to install dependencies: $($_.Exception.Message)"
            exit 1
        }
    }
}

# === STEP 4: Verify api.py exists ===
$apiPath = Join-Path $backendDir "api.py"
if (-not (Test-Path $apiPath)) {
    Write-Error "[BACKEND-STARTUP] api.py not found at: $apiPath"
    exit 1
}
Write-Host "[BACKEND-STARTUP] api.py found: $apiPath" -ForegroundColor Green

# === STEP 5: Start uvicorn ===
Write-Host "[BACKEND-STARTUP] Starting uvicorn on port $Port..." -ForegroundColor Cyan
Write-Host "[BACKEND-STARTUP] Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host "---" -ForegroundColor Gray

try {
    # Use Start-Process to properly handle the uvicorn process
    $uvicornArgs = @(
        "-m", "uvicorn",
        "api:app",
        "--host", "0.0.0.0",
        "--port", $Port.ToString(),
        "--reload"
    )

    # Start uvicorn in the backend directory
    $process = Start-Process -FilePath "python" -ArgumentList $uvicornArgs -WorkingDirectory $backendDir -PassThru -Wait

    Write-Host "---" -ForegroundColor Gray
    Write-Host "[BACKEND-STARTUP] Uvicorn process exited with code: $($process.ExitCode)" -ForegroundColor Cyan

} catch {
    Write-Error "[BACKEND-STARTUP] Failed to start uvicorn: $($_.Exception.Message)"
    exit 1
}

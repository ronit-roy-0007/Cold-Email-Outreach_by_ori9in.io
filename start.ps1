# IntentLead AI Windows PowerShell Startup Script
param (
    [switch]$Poller,
    [switch]$Both
)

$ErrorActionPreference = "Stop"
$workspaceRoot = $PSScriptRoot
$apiDir = Join-Path $workspaceRoot "apps\intelligence-api"

# Check if first-time setup is needed
if (-not (Test-Path "$workspaceRoot\.env") -and -not (Test-Path "$apiDir\.env")) {
    Write-Host "[!] No configuration (.env) detected. Launching setup wizard..." -ForegroundColor Yellow
    python "$workspaceRoot\scripts\setup.py"
    if (-not (Test-Path "$workspaceRoot\.env") -and -not (Test-Path "$apiDir\.env")) {
        Write-Host "Setup was not completed. Exiting." -ForegroundColor Red
        exit 1
    }
}

if ($Poller) {
    Set-Location $workspaceRoot
    $env:PYTHONPATH = "apps/intelligence-api"
    Write-Host "Starting IntentLead AI Telegram Poller Daemon..." -ForegroundColor Cyan
    python -u scripts/telegram_poller.py
    exit 0
}

$apiDir = Join-Path $workspaceRoot "apps\intelligence-api"
Set-Location $apiDir
$env:PYTHONPATH = "."

if (-not $env:DATABASE_URL) {
    if (Test-Path "$workspaceRoot\.env") {
        # Environment is loaded from .env
    } else {
        $env:DATABASE_URL = "sqlite:///./intentlead.db"
    }
}

Write-Host "Applying database migrations..." -ForegroundColor Cyan
python -m alembic upgrade head

if ($Both) {
    Write-Host "Starting API and Telegram Poller..." -ForegroundColor Green
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$workspaceRoot'; `$env:PYTHONPATH='apps/intelligence-api'; python -u scripts/telegram_poller.py"
}

Write-Host "Starting IntentLead AI operator API on http://localhost:8000..." -ForegroundColor Green
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

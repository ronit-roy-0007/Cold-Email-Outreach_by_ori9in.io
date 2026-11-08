# IntentLead AI Windows PowerShell Startup Script
$ErrorActionPreference = "Stop"

$workspaceRoot = $PSScriptRoot
$apiDir = Join-Path $workspaceRoot "apps\intelligence-api"
Set-Location $apiDir

$env:PYTHONPATH = "."

if (-not $env:DATABASE_URL) {
    # Default to PostgreSQL
    $env:DATABASE_URL = "postgresql://intentlead:change-me@localhost:5432/intentlead"
}

if ($env:DATABASE_URL.StartsWith("sqlite:")) {
    if ($env:APP_ENV -ne "development") {
        Write-Error "ERROR: SQLite is only permitted when APP_ENV=development. Current APP_ENV=$($env:APP_ENV)"
        exit 1
    }
    Write-Warning "WARNING: Using SQLite in development mode. PostgreSQL is the production source of truth."
}

Write-Host "Applying Alembic database migrations..." -ForegroundColor Cyan
python -m alembic upgrade head

Write-Host "Starting IntentLead AI operator API on http://localhost:8000..." -ForegroundColor Green
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

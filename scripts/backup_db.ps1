# ==============================================================================
# IntentLead AI — Database Backup Script (Windows PowerShell)
# ==============================================================================
param (
    [string]$BackupDir = ".\backups",
    [string]$ContainerName = "intentlead-db",
    [string]$DbUser = "intentlead",
    [string]$DbName = "intentlead"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

# Check if Docker container is running
$ContainerRunning = docker ps --format '{{.Names}}' 2>$null | Select-String -Pattern "^$ContainerName`$" -SimpleMatch

if ($ContainerRunning) {
    $BackupFile = Join-Path $BackupDir "intentlead_pg_$Timestamp.sql"
    Write-Host "[backup] Backing up PostgreSQL database '$DbName' from container '$ContainerName'..." -ForegroundColor Cyan
    docker exec $ContainerName pg_dump -U $DbUser -d $DbName --clean --if-exists > $BackupFile
    Write-Host "[backup] Backup successfully created at: $BackupFile" -ForegroundColor Green
} elseif (Test-Path ".\intentlead.db") {
    $BackupFile = Join-Path $BackupDir "intentlead_sqlite_$Timestamp.db"
    Write-Host "[backup] Backing up local SQLite database '.\intentlead.db'..." -ForegroundColor Cyan
    Copy-Item -Path ".\intentlead.db" -Destination $BackupFile -Force
    Write-Host "[backup] Backup successfully created at: $BackupFile" -ForegroundColor Green
} else {
    Write-Error "[backup] ERROR: Neither running Docker container '$ContainerName' nor local '.\intentlead.db' found."
}

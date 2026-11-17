# ==============================================================================
# IntentLead AI — Database Restore Script (Windows PowerShell)
# ==============================================================================
param (
    [Parameter(Mandatory=$true, Position=0)]
    [string]$BackupFile,
    [string]$ContainerName = "intentlead-db",
    [string]$DbUser = "intentlead",
    [string]$DbName = "intentlead"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $BackupFile)) {
    Write-Error "ERROR: Backup file '$BackupFile' does not exist."
    exit 1
}

$Confirmation = Read-Host "WARNING: Restoring will overwrite existing data. Proceed? [y/N]"
if ($Confirmation -notmatch "^[yY]$") {
    Write-Host "Restore cancelled." -ForegroundColor Yellow
    exit 0
}

if ($BackupFile -like "*.sql") {
    Write-Host "[restore] Restoring PostgreSQL from '$BackupFile' into container '$ContainerName'..." -ForegroundColor Cyan
    Get-Content $BackupFile | docker exec -i $ContainerName psql -U $DbUser -d $DbName
    Write-Host "[restore] PostgreSQL restore completed successfully." -ForegroundColor Green
} elseif ($BackupFile -like "*.db" -or $BackupFile -like "*.sqlite*") {
    Write-Host "[restore] Restoring SQLite database from '$BackupFile' to '.\intentlead.db'..." -ForegroundColor Cyan
    Copy-Item -Path $BackupFile -Destination ".\intentlead.db" -Force
    Write-Host "[restore] SQLite database restore completed successfully." -ForegroundColor Green
} else {
    Write-Error "ERROR: Unrecognized backup file format. Expected .sql or .db"
}

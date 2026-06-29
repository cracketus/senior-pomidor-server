param(
    [string]$BackupRoot = "backups",
    [string]$ProjectName = "senior-pomidor-server"
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $BackupRoot $timestamp
New-Item -ItemType Directory -Force $backupDir | Out-Null

$dbBackup = Join-Path $backupDir "senior_pomidor.sql"
$photoBackup = Join-Path $backupDir "photo_data.tgz"

docker compose exec -T postgres pg_dump -U senior_pomidor senior_pomidor | Set-Content -Encoding UTF8 $dbBackup
docker run --rm `
    -v "${ProjectName}_photo_data:/data:ro" `
    -v "$((Resolve-Path $backupDir).Path):/backup" `
    alpine tar czf /backup/photo_data.tgz -C /data .

Write-Output "Wrote database backup: $dbBackup"
Write-Output "Wrote photo archive: $photoBackup"

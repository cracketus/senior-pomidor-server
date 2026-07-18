param(
    [string]$BackupRoot = "backups",
    [string]$ProjectName = "senior-pomidor-server",
    [ValidateSet("daily", "migration")]
    [string]$Mode = "daily"
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $BackupRoot "$Mode-$timestamp"
New-Item -ItemType Directory -Force $backupDir | Out-Null
$resolvedBackupDir = (Resolve-Path $backupDir).Path

$postgresId = (docker compose ps -q postgres).Trim()
if (-not $postgresId) {
    throw "PostgreSQL must be running while the other application services are stopped."
}
$postgresUser = (docker exec $postgresId printenv POSTGRES_USER).Trim()
$postgresDb = (docker exec $postgresId printenv POSTGRES_DB).Trim()
if (-not $postgresUser -or -not $postgresDb) {
    throw "Could not read POSTGRES_USER or POSTGRES_DB from the PostgreSQL container."
}

docker exec $postgresId pg_dump --format=custom --no-owner --no-acl `
    --username $postgresUser --file /tmp/senior-pomidor.dump $postgresDb
docker cp "${postgresId}:/tmp/senior-pomidor.dump" (Join-Path $backupDir "database.dump")
docker exec $postgresId pg_dumpall --globals-only --no-role-passwords --username $postgresUser `
    | Set-Content -Encoding utf8 (Join-Path $backupDir "globals-audit.sql")

$countSql = @"
SELECT 'telemetry_events', count(*) FROM telemetry_events
UNION ALL SELECT 'pod_readings', count(*) FROM pod_readings
UNION ALL SELECT 'photos', count(*) FROM photos
UNION ALL SELECT 'state_snapshots', count(*) FROM state_snapshots
UNION ALL SELECT 'sensor_health_snapshots', count(*) FROM sensor_health_snapshots
UNION ALL SELECT 'anomaly_records', count(*) FROM anomaly_records
UNION ALL SELECT 'estimator_diagnostics', count(*) FROM estimator_diagnostics
ORDER BY 1;
"@
docker exec $postgresId psql --username $postgresUser --dbname $postgresDb `
    --tuples-only --no-align --field-separator=, --command $countSql `
    | Set-Content -Encoding utf8 (Join-Path $backupDir "baseline-counts.csv")

docker compose ps --format json | Set-Content -Encoding utf8 (Join-Path $backupDir "compose-services.jsonl")
docker compose images --format json | Set-Content -Encoding utf8 (Join-Path $backupDir "compose-images.jsonl")

function Export-DockerVolume {
    param([string]$VolumeName, [string]$ArchiveName)

    docker volume inspect $VolumeName | Out-Null
    docker run --rm `
        --mount "type=volume,src=$VolumeName,dst=/data,readonly" `
        --mount "type=bind,src=$resolvedBackupDir,dst=/backup" `
        alpine:3.22 tar --numeric-owner -czf "/backup/$ArchiveName" -C /data .
}

if ($Mode -eq "migration") {
    Export-DockerVolume "${ProjectName}_photo_data" "photos.tar.gz"
    Export-DockerVolume "${ProjectName}_estimator_private_data" "estimator-private.tar.gz"
    Export-DockerVolume "${ProjectName}_grafana_data" "grafana.tar.gz"
    Export-DockerVolume "${ProjectName}_mosquitto_data" "mosquitto.tar.gz"

    docker run --rm `
        --mount "type=volume,src=${ProjectName}_photo_data,dst=/data,readonly" `
        alpine:3.22 sh -c "find /data -type f -print | sort | head -n 10 | xargs -r sha256sum" `
        | Set-Content -Encoding utf8 (Join-Path $backupDir "representative-photo-sha256.txt")
}

$manifestPath = Join-Path $backupDir "SHA256SUMS"
$manifestLines = Get-ChildItem -LiteralPath $backupDir -File `
    | Where-Object Name -ne "SHA256SUMS" `
    | Sort-Object Name `
    | ForEach-Object {
        $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        "$hash  $($_.Name)"
    }
$manifestLines | Set-Content -Encoding ascii $manifestPath

Write-Output "Wrote $Mode backup set: $resolvedBackupDir"
Write-Output "Verify every SHA-256 entry after transfer before restoring."

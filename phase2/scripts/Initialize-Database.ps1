[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
if ($env:OS -ne 'Windows_NT') { throw 'This local credential setup uses Windows DPAPI. Configure environment variables explicitly on other hosts.' }
& docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not accessible or not running. This script never starts or restarts Docker Desktop.' }
New-Item -ItemType Directory -Path $script:MasarPrivate -Force | Out-Null
$existing = @(& docker ps -a --filter "name=^/$($script:MasarContainer)$" --format '{{.Names}}')
$ownerPath = Join-Path $script:MasarPrivate 'database-owner.credential.xml'
$appPath = Join-Path $script:MasarPrivate 'database-app.credential.xml'
if ($existing.Count -gt 0 -and (-not (Test-Path -LiteralPath $ownerPath) -or -not (Test-Path -LiteralPath $appPath))) {
    throw 'The container already exists but local encrypted credentials are missing. Restore them; no credentials or data will be reset.'
}
$owner = New-MasarCredential 'masar_bootstrap' $ownerPath
$app = New-MasarCredential 'masar_app' $appPath
if ($existing.Count -eq 0) {
    $volume = @(& docker volume ls --filter "name=^$($script:MasarVolume)$" --format '{{.Name}}')
    if ($volume.Count -gt 0) {
        $label = & docker volume inspect --format '{{index .Labels "com.masar.project"}}' $script:MasarVolume
        if (($label | Out-String).Trim() -ne 'masar-phase2') { throw 'A volume with this name is not owned by this project.' }
    } else {
        & docker volume create --label 'com.masar.project=masar-phase2' $script:MasarVolume | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to create the dedicated data volume.' }
    }
    $env:POSTGRES_PASSWORD = ConvertFrom-MasarSecure $owner.Password
    try {
        & docker run -d --name $script:MasarContainer --label 'com.masar.project=masar-phase2' --restart no --memory 512m --cpus 1 -p '127.0.0.1:55435:5432' -e POSTGRES_USER=masar_bootstrap -e POSTGRES_DB=postgres -e POSTGRES_PASSWORD -v "$($script:MasarVolume):/var/lib/postgresql" postgres:18 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the dedicated PostgreSQL container. Existing workloads were not changed.' }
    } finally { Remove-Item Env:POSTGRES_PASSWORD -ErrorAction SilentlyContinue }
} else {
    Assert-MasarContainer
    $running = & docker inspect --format '{{.State.Running}}' $script:MasarContainer
    if (($running | Out-String).Trim() -ne 'true') { & docker start $script:MasarContainer | Out-Null }
}
Assert-MasarContainer
$ready = $false
for ($attempt=0; $attempt -lt 60; $attempt++) {
    & docker exec $script:MasarContainer pg_isready -h 127.0.0.1 -p 5432 -U masar_bootstrap -d postgres 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) { throw 'The dedicated PostgreSQL TCP endpoint did not become ready.' }
$env:MASAR_APP_PASSWORD = ConvertFrom-MasarSecure $app.Password
try {
    $sql = @'
\getenv app_password MASAR_APP_PASSWORD
SELECT 'CREATE ROLE masar_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='masar_app') \gexec
ALTER ROLE masar_app PASSWORD :'app_password';
SELECT 'CREATE DATABASE masar_phase2 OWNER masar_bootstrap'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='masar_phase2') \gexec
SELECT 'CREATE DATABASE masar_phase2_tests OWNER masar_bootstrap'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='masar_phase2_tests') \gexec
REVOKE CONNECT ON DATABASE masar_phase2, masar_phase2_tests FROM PUBLIC;
GRANT CONNECT ON DATABASE masar_phase2, masar_phase2_tests TO masar_app;
'@
    $sql | & docker exec -i -e MASAR_APP_PASSWORD $script:MasarContainer psql --no-psqlrc -q -U masar_bootstrap -d postgres --set=ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) { throw 'Database or application-role initialization failed.' }
} finally {
    Remove-Item Env:MASAR_APP_PASSWORD -ErrorAction SilentlyContinue
    $owner = $null; $app = $null
}
Write-Host 'PostgreSQL ready: 127.0.0.1:55435; Masar development/test databases created. Credentials remain encrypted locally.'

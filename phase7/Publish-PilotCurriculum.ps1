#Requires -Version 7.0
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Assembly, [switch]$Activate, [switch]$BackupOnly)

$workspace = Split-Path -Parent $PSScriptRoot
. (Join-Path $workspace 'phase2\scripts\Local-Environment.ps1')
$assemblyPath = (Resolve-Path -LiteralPath $Assembly).Path
$bundle = Join-Path $PSScriptRoot 'dist\curriculum.json'
$reviewedSha = 'a66ba6f564d7ce49bbab3afa7aeb7d69452589e1b68a4e315d9da807583000cc'
$database = 'masar_phase5_pilot'
$api = 'http://127.0.0.1:5185/api/v1'
$old = 'phase4-ar-v1'
$new = 'phase7-ar-v1'
$dotnet = (Get-Command dotnet.exe -CommandType Application).Source

if ($Activate -and $BackupOnly) { throw 'Choose activation or backup only.' }
if ((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash -ne $reviewedSha) { throw 'The curriculum differs from the reviewed bundle.' }
& $dotnet $assemblyPath --verify-curriculum $bundle
if ($LASTEXITCODE -ne 0) { throw 'Curriculum verification failed.' }
if (-not $Activate -and -not $BackupOnly) { return }

$health = Invoke-RestMethod -Uri "$api/health" -TimeoutSec 7
$catalog = Invoke-RestMethod -Uri "$api/catalog" -TimeoutSec 7
if ($health.status -ne 'ok' -or $health.database -ne 'available' -or $catalog.activeReleaseId -notin @($old,$new)) {
    throw 'The learner pilot is not serving an expected release from PostgreSQL.'
}
if ($Activate -and $catalog.activeReleaseId -eq $new) {
    Write-Host "The learner pilot already serves $new. No changes made."
    return
}

$native = Get-MasarPortableNativeRoot
$bin = Join-Path $native 'binaries\pgsql\bin'
$control = & (Join-Path $bin 'pg_controldata.exe') (Join-Path $native 'data')
if ($LASTEXITCODE -ne 0 -or ($control -join "`n") -notmatch '(?m)^Database system identifier:\s*([0-9]+)\s*$') {
    throw 'Could not read the original cluster identifier.'
}
$clusterId = $Matches[1]
$onlineId = Invoke-MasarPortableSql -Sql 'SELECT system_identifier FROM pg_control_system();' -TupleOnly
$active = Invoke-MasarPortableSql -Sql "SELECT value FROM public.settings WHERE key='active_release_id';" -Database $database -TupleOnly
if ($onlineId -ne $clusterId -or $active -ne $catalog.activeReleaseId) { throw 'Unexpected PostgreSQL cluster or pilot release.' }

if ($Activate) {
    $lab = Invoke-RestMethod -Uri "$api/lab/exercises/$old/py-02" -TimeoutSec 7
    if (-not $lab.available) { throw 'The learner API does not have an enabled lab.' }
}

$backupRoot = Join-Path $native 'phase7-pilot-backups'
$backupDir = Join-Path $backupRoot ('{0}-{1}' -f [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'),[Guid]::NewGuid().ToString('N'))
$null = [IO.Directory]::CreateDirectory($backupRoot)
if ((Get-Item -LiteralPath $backupRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unexpected pilot backup root.' }
$null = [IO.Directory]::CreateDirectory($backupDir)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
try {
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($identity.User)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity.User,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    Set-Acl -LiteralPath $backupDir -AclObject $acl
} finally { $identity.Dispose() }
$archive = Join-Path $backupDir 'masar_phase5_pilot.dump'
$credential = Import-Clixml -LiteralPath (Join-Path $native 'database-owner.credential.xml')
if ($credential.UserName -ne 'masar_bootstrap') { throw 'Unexpected PostgreSQL owner credential.' }

$previousEnvironment = @{}
if ($Activate) {
    foreach ($name in @('ASPNETCORE_ENVIRONMENT','DOTNET_ENVIRONMENT','ConnectionStrings__Migration',
        'MASAR_CODE_LAB_ENABLED','MASAR_CODE_LAB_RUNNER_URL','MASAR_CODE_LAB_RUNNER_TOKEN')) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
}
try {
    if ($Activate) { & (Join-Path $workspace 'phase3\host\Connect-NexoraRunner.ps1') }
    $processInfo = [Diagnostics.ProcessStartInfo]::new()
    $processInfo.FileName = Join-Path $bin 'pg_dump.exe'
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    foreach ($name in @($processInfo.Environment.Keys | Where-Object { $_ -like 'PG*' })) { $null = $processInfo.Environment.Remove($name) }
    $processInfo.Environment['PGPASSWORD'] = ConvertFrom-MasarSecure $credential.Password
    $processInfo.Environment['PGCONNECT_TIMEOUT'] = '5'
    foreach ($arg in @('--host=127.0.0.1','--port=55436','--username=masar_bootstrap','--no-password',"--dbname=$database",'--format=custom','--lock-wait-timeout=10s',"--file=$archive")) {
        $processInfo.ArgumentList.Add($arg)
    }
    try { $dump = [Diagnostics.Process]::Start($processInfo) }
    finally { $null = $processInfo.Environment.Remove('PGPASSWORD'); $credential = $null }
    try {
        if (-not $dump.WaitForExit(300000)) { $dump.Kill(); throw 'Pilot backup did not finish.' }
        if ($dump.ExitCode -ne 0) { throw 'Pilot backup failed; curriculum was not activated.' }
    } finally { $dump.Dispose() }
    $contents = & (Join-Path $bin 'pg_restore.exe') --list $archive
    $toc = $contents -join "`n"
    if ($LASTEXITCODE -ne 0 -or $toc -notmatch '(?m)^;\s+dbname:\s+masar_phase5_pilot\s*$' -or
        $toc -notmatch 'TABLE DATA public users ' -or $toc -notmatch 'TABLE DATA public learning_plans ' -or
        $toc -notmatch 'TABLE DATA public content_releases ') {
        throw 'Backup failed its archive check; curriculum was not activated.'
    }
    & (Join-Path $bin 'pg_restore.exe') --exit-on-error --file=NUL $archive
    if ($LASTEXITCODE -ne 0) { throw 'The backup archive cannot be fully read; curriculum was not activated.' }
    (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash | Set-Content -LiteralPath "$archive.sha256" -Encoding ascii
    Write-Host "Learner pilot backup verified: $archive"
    if ($BackupOnly) { return }

    $connections = Get-MasarConnections -Database $database -Engine Portable -IncludeMigration
    $env:ConnectionStrings__Migration = $connections.Migration
    $connections = $null
    $env:ASPNETCORE_ENVIRONMENT = 'Development'
    $env:DOTNET_ENVIRONMENT = 'Development'
    & $dotnet $assemblyPath --publish-reviewed-curriculum $bundle $reviewedSha
    if ($LASTEXITCODE -ne 0) { throw 'Reviewed curriculum transaction failed.' }
    $released = Invoke-RestMethod -Uri "$api/catalog" -TimeoutSec 12
    if ($released.activeReleaseId -ne $new) { throw 'The publication command succeeded but the learner API did not confirm the active release. Inspect before retrying.' }
    Write-Host "Learner pilot now serves $new. Confirm the public route and learner login."
} finally {
    $credential = $null
    foreach ($name in $previousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}

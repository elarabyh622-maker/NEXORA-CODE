Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:MasarRoot = Split-Path -Parent $PSScriptRoot
$script:MasarPrivate = Join-Path $script:MasarRoot '.local'
$script:MasarContainer = 'masar-phase2-postgres'
$script:MasarVolume = 'masar-phase2-pgdata'
$script:MasarPort = 55435
$script:MasarPortableRoot = Join-Path $script:MasarPrivate 'portable-postgres'
$script:MasarPortablePort = 55436

function Get-MasarCredentialRoot([ValidateSet('Docker','Portable')][string]$Engine = 'Docker') {
    if ($Engine -eq 'Portable') { return $script:MasarPortableRoot }
    return $script:MasarPrivate
}

function Get-MasarPortableNativeRoot {
    # PostgreSQL's Windows bootstrap uses native paths and may misinterpret non-ASCII directory names.
    # The temporary junction is only an alias: binaries, data and credentials remain in the workspace.
    $target = [IO.Path]::GetFullPath($script:MasarPortableRoot)
    if ($target -notmatch '[^\x00-\x7F]') { return $target }
    # Keep the same alias in Windows PowerShell 5.1 and PowerShell 7.
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try { $digest = $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($target.ToUpperInvariant())) }
    finally { $sha256.Dispose() }
    $identity = [BitConverter]::ToString($digest, 0, 8).Replace('-', '').ToLowerInvariant()
    $alias = Join-Path ([IO.Path]::GetTempPath()) "masar-pg-$identity"
    if ($alias -match '[^\x00-\x7F]') { throw 'An ASCII Windows temporary directory is required for this native path alias.' }
    if (Test-Path -LiteralPath $alias) {
        $item = Get-Item -LiteralPath $alias -Force
        if ($item.LinkType -ne 'Junction' -or -not $item.Target -or
            -not [string]::Equals([IO.Path]::GetFullPath([string]$item.Target),$target,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'The temporary PostgreSQL alias belongs to another target; it will not be replaced.'
        }
    } else { New-Item -ItemType Junction -Path $alias -Target $target | Out-Null }
    return $alias
}

function Assert-LocalDatabaseName([string]$Database, [switch]$PortablePilot) {
    if ($Database -in @('masar_phase2', 'masar_phase2_tests')) { return }
    if ($PortablePilot -and $Database -in @('masar_phase5_pilot', 'masar_phase6_commercial', 'masar_phase6_tests', 'masar_phase6_restore_check')) { return }
    throw 'This helper only permits the dedicated Masar databases.'
}

function ConvertFrom-MasarSecure([Security.SecureString]$Value) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function New-MasarCredential([string]$UserName, [string]$Path) {
    if (Test-Path -LiteralPath $Path) { return Import-Clixml -LiteralPath $Path }
    $bytes = New-Object byte[] 36
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $plain = [Convert]::ToBase64String($bytes)
    $credential = [Management.Automation.PSCredential]::new($UserName, (ConvertTo-SecureString $plain -AsPlainText -Force))
    $credential | Export-Clixml -LiteralPath $Path
    $plain = $null
    return $credential
}

function Get-MasarConnections([string]$Database = 'masar_phase2', [ValidateSet('Docker','Portable')][string]$Engine = 'Docker', [switch]$IncludeMigration) {
    Assert-LocalDatabaseName $Database -PortablePilot:($Engine -eq 'Portable')
    $credentialRoot = Get-MasarCredentialRoot $Engine
    $port = if ($Engine -eq 'Portable') { $script:MasarPortablePort } else { $script:MasarPort }
    $ownerPath = Join-Path $credentialRoot 'database-owner.credential.xml'
    $appPath = Join-Path $credentialRoot 'database-app.credential.xml'
    if (-not (Test-Path -LiteralPath $appPath) -or ($IncludeMigration -and -not (Test-Path -LiteralPath $ownerPath))) {
        throw 'Database credentials are not initialized. Run scripts/Initialize-Masar.ps1 first.'
    }
    $app = Import-Clixml -LiteralPath $appPath
    $appPlain = ConvertFrom-MasarSecure $app.Password
    $ownerPlain = $null
    try {
        if ($IncludeMigration) { $ownerPlain = ConvertFrom-MasarSecure (Import-Clixml -LiteralPath $ownerPath).Password }
        return [PSCustomObject]@{
            Application = "Host=127.0.0.1;Port=$port;Database=$Database;Username=masar_app;Password=$appPlain;Timeout=10;Command Timeout=30;Include Error Detail=false"
            Migration = $(if ($IncludeMigration) { "Host=127.0.0.1;Port=$port;Database=$Database;Username=masar_bootstrap;Password=$ownerPlain;Timeout=10;Command Timeout=30;Include Error Detail=false" } else { $null })
        }
    } finally { $ownerPlain = $null; $appPlain = $null }
}

function Set-MasarProcessEnvironment([string]$Database = 'masar_phase2', [switch]$IncludeMigration, [ValidateSet('Docker','Portable')][string]$Engine='Docker') {
    $connections = Get-MasarConnections -Database $Database -Engine $Engine -IncludeMigration:$IncludeMigration
    $env:ConnectionStrings__Masar = $connections.Application
    if ($IncludeMigration) { $env:ConnectionStrings__Migration = $connections.Migration }
    else { Remove-Item Env:ConnectionStrings__Migration -ErrorAction SilentlyContinue }
    $env:ASPNETCORE_ENVIRONMENT = 'Development'
    $env:ASPNETCORE_URLS = 'http://127.0.0.1:5180'
    $runtime = switch ($Database) {
        'masar_phase2_tests' { 'test-runtime' }
        'masar_phase5_pilot' { 'phase5-pilot-runtime' }
        'masar_phase6_commercial' { 'phase6-commercial-runtime' }
        'masar_phase6_tests' { 'phase6-tests-runtime' }
        default { 'runtime' }
    }
    $env:MASAR_DATA_ROOT = Join-Path (Get-MasarCredentialRoot $Engine) $runtime
    $env:DOTNET_CLI_HOME = Join-Path $script:MasarPrivate 'dotnet'
    $env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
    $env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
    $connections = $null
}

function Clear-MasarProcessSecrets {
    Remove-Item Env:ConnectionStrings__Masar -ErrorAction SilentlyContinue
    Remove-Item Env:ConnectionStrings__Migration -ErrorAction SilentlyContinue
}

function Assert-MasarContainer {
    $label = & docker inspect --format '{{index .Config.Labels "com.masar.project"}}' $script:MasarContainer 2>$null
    if ($LASTEXITCODE -ne 0 -or ($label | Out-String).Trim() -ne 'masar-phase2') {
        throw 'Expected the dedicated Masar container with matching ownership label. No other container will be changed.'
    }
    $binding = & docker port $script:MasarContainer 5432/tcp
    if ($LASTEXITCODE -ne 0 -or ($binding | Out-String).Trim() -ne '127.0.0.1:55435') { throw 'Unexpected database port binding; refusing to reuse this container.' }
}

function Invoke-MasarSql([string]$Sql, [string]$Database = 'postgres') {
    if ($Database -ne 'postgres') { Assert-LocalDatabaseName $Database }
    Assert-MasarContainer
    $Sql | & docker exec -i $script:MasarContainer psql --no-psqlrc -q -U masar_bootstrap -d $Database --set=ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) { throw 'A Masar-only PostgreSQL command failed.' }
}

function Invoke-MasarPortableSql([string]$Sql, [string]$Database = 'postgres', [ValidateSet('Owner','App')][string]$Role='Owner', [switch]$TupleOnly) {
    if ($Database -ne 'postgres') { Assert-LocalDatabaseName $Database -PortablePilot }
    $marker = Join-Path $script:MasarPortableRoot 'masar-portable.json'
    if (-not (Test-Path -LiteralPath $marker)) { throw 'This is not the Masar portable cluster.' }
    $ownership = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($ownership.project -ne 'masar-phase2-portable' -or $ownership.port -ne $script:MasarPortablePort) { throw 'Unexpected portable cluster ownership.' }
    $psql = Join-Path (Get-MasarPortableNativeRoot) 'binaries\pgsql\bin\psql.exe'
    $credential = Import-Clixml -LiteralPath (Join-Path $script:MasarPortableRoot $(if($Role -eq 'Owner'){'database-owner.credential.xml'}else{'database-app.credential.xml'}))
    $env:PGPASSWORD = ConvertFrom-MasarSecure $credential.Password
    $env:PGCLIENTENCODING = 'UTF8'
    $env:PGCONNECT_TIMEOUT = '5'
    try {
        $options = @('--no-psqlrc','-q','-h','127.0.0.1','-p',[string]$script:MasarPortablePort,'-U',$credential.UserName,'-d',$Database,'--set=ON_ERROR_STOP=1')
        if ($TupleOnly) { $options += '-At' }
        $Sql | & $psql @options
        if ($LASTEXITCODE -ne 0) { throw 'A Masar portable PostgreSQL command failed.' }
    } finally { Remove-Item Env:PGPASSWORD,Env:PGCLIENTENCODING,Env:PGCONNECT_TIMEOUT -ErrorAction SilentlyContinue }
}

function Grant-MasarApplicationAccess([string]$Database, [ValidateSet('Docker','Portable')][string]$Engine='Docker') {
    Assert-LocalDatabaseName $Database -PortablePilot:($Engine -eq 'Portable')
    $sql = @'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO masar_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO masar_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO masar_app;
SELECT format('REVOKE ALL ON TABLE public.%I FROM masar_app', tablename)
FROM pg_tables WHERE schemaname='public' AND (tablename LIKE '%migration%' OR tablename LIKE '%schema_version%') \gexec
'@
    if ($Engine -eq 'Portable') { Invoke-MasarPortableSql $sql $Database }
    else { Invoke-MasarSql $sql $Database }
}

[CmdletBinding()]
param(
    [switch]$Initialize,
    [switch]$Test,
    [switch]$WithoutLab,
    [string]$PublicOrigin,
    [string]$ContactUrl,
    [ValidateSet('phase7-ar-v1','phase8-ar-v1')][string]$TargetRelease,
    [ValidateRange(1,10000)][int]$DailyExecutionLimit = 300
)

$workspace = Split-Path -Parent $PSScriptRoot
. (Join-Path $workspace 'phase2\scripts\Local-Environment.ps1')
$private = Join-Path $PSScriptRoot '.local'
$launch = $PSBoundParameters.ContainsKey('PublicOrigin')
$mountPath = ''
$headers = @{}
if ($launch) {
    $publicUri = $null
    if (-not [Uri]::TryCreate($PublicOrigin, [UriKind]::Absolute, [ref]$publicUri) -or
        $publicUri.Scheme -ne 'https' -or $publicUri.AbsolutePath -ne '/' -or
        $publicUri.UserInfo -or $publicUri.Query -or $publicUri.Fragment) {
        throw 'PublicOrigin must be an HTTPS origin without a path, query, fragment, or credentials.'
    }
    $mountPath = '/nexora-commercial'
    $PublicOrigin = $publicUri.GetLeftPart([UriPartial]::Authority)
    $headers = @{ Host = $publicUri.Authority; 'X-Forwarded-Proto' = 'https'; 'X-Forwarded-For' = '127.0.0.1' }
    $private = Join-Path $private 'launch'
}
$candidate = Join-Path $private $(if ($Test) { 'test-app' } else { 'app' })
$database = if ($Test) { 'masar_phase6_tests' } else { 'masar_phase6_commercial' }
$port = if ($launch) { if ($Test) { 5199 } else { 5187 } } elseif ($Test) { 5196 } else { 5186 }
$origin = "http://127.0.0.1:$port"
$backend = "$origin$mountPath"
$displayUrl = if ($launch) { "$PublicOrigin$mountPath/#start" } else { "$origin/#start" }
$assembly = Join-Path $candidate 'Masar.Api.dll'
$dotnet = (Get-Command dotnet.exe -CommandType Application).Source
$releases = @('phase4-ar-v1','phase7-ar-v1','phase8-ar-v1')
if (-not $TargetRelease) { $TargetRelease = if ($Test) { 'phase7-ar-v1' } else { 'phase8-ar-v1' } }
if ($Initialize -or $PSBoundParameters.ContainsKey('TargetRelease')) { $releases = @($TargetRelease) }

function Test-CommercialReady {
    try {
        $health = Invoke-RestMethod -Uri "$backend/api/v1/health" -Headers $headers -TimeoutSec 3
        $catalog = Invoke-RestMethod -Uri "$backend/api/v1/catalog" -Headers $headers -TimeoutSec 3
        $ready = $health.status -eq 'ok' -and $health.database -eq 'available' -and
            $catalog.activeReleaseId -in $releases -and $catalog.accessRequired -eq $true
        return $ready
    } catch { return $false }
}

$listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count) {
    $ids = @($listeners.OwningProcess | Select-Object -Unique)
    $record = Get-CimInstance Win32_Process -Filter ('ProcessId={0}' -f $ids[0])
    $expected = '\A(?:"{0}"|{0})\s+"{1}"\s*\z' -f [regex]::Escape($dotnet), [regex]::Escape($assembly)
    if ($ids.Count -ne 1 -or @($listeners | Where-Object LocalAddress -ne '127.0.0.1').Count -or
        $record.ExecutablePath -ne $dotnet -or $record.CommandLine -notmatch $expected) {
        throw "Port $port belongs to a different service."
    }
    if ($Initialize -or $PSBoundParameters.ContainsKey('ContactUrl') -or
        $PSBoundParameters.ContainsKey('DailyExecutionLimit') -or $WithoutLab) {
        throw 'Stop the owned local candidate before changing its build or startup options.'
    }
    if (-not (Test-CommercialReady)) { throw 'The existing candidate is not ready.' }
    Write-Host "NEXORA CODE commercial candidate: $displayUrl (backend $port)"
    return
}

if (-not $Initialize -and -not (Test-Path -LiteralPath $assembly -PathType Leaf)) {
    throw 'Use -Initialize to build and initialize this commercial instance.'
}
& (Join-Path $workspace 'phase2\scripts\Start-PortableDatabase.ps1') -ProbeTimeoutSeconds 12 -StartupTimeoutSeconds 600

$forwardingVariables = @('DOTNET_ENVIRONMENT', 'MASAR_COMMERCIAL_PUBLIC_ORIGIN', 'MASAR_COMMERCIAL_PUBLIC_PATH')
$savedForwarding = @{}
foreach ($name in $forwardingVariables) { $savedForwarding[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }

try {
    if ($Initialize) {
        $source = Join-Path $workspace 'phase2\src\Masar.Api'
        $frontend = Join-Path $workspace 'phase2\apps\web'
        $env:DOTNET_CLI_HOME = Join-Path $script:MasarPrivate 'dotnet'
        $env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
        & $dotnet build (Join-Path $source 'Masar.Api.csproj') -c Release --no-restore --nologo -o $candidate
        if ($LASTEXITCODE -ne 0) { throw 'Commercial API build failed.' }
        $developmentAssetManifest = Join-Path $candidate 'Masar.Api.staticwebassets.runtime.json'
        if (Test-Path -LiteralPath $developmentAssetManifest -PathType Leaf) { Remove-Item -LiteralPath $developmentAssetManifest }

        $webRoot = Join-Path $candidate 'wwwroot'
        Push-Location -LiteralPath $frontend
        try {
            $nativeCompiler = 'node_modules\@typescript\typescript-win32-x64\lib\tsc.exe'
            if (Test-Path -LiteralPath $nativeCompiler -PathType Leaf) { & ".\$nativeCompiler" --noEmit }
            else { & npm.cmd run typecheck }
            if ($LASTEXITCODE -ne 0) { throw 'Commercial web application type checking failed.' }
            $viteArguments = @('node_modules/vite/bin/vite.js', 'build', '--outDir', $webRoot, '--emptyOutDir')
            if ($launch) { $viteArguments += @('--base', "$mountPath/") }
            & node @viteArguments
            if ($LASTEXITCODE -ne 0) { throw 'Commercial web application build failed.' }
        } finally { Pop-Location }

        $setup = @"
SELECT 'CREATE DATABASE $database OWNER masar_bootstrap'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='$database') \gexec
REVOKE CONNECT ON DATABASE $database FROM PUBLIC;
GRANT CONNECT ON DATABASE $database TO masar_app;
"@
        Invoke-MasarPortableSql -Sql $setup
        Set-MasarProcessEnvironment -Database $database -Engine Portable -IncludeMigration
        & $dotnet $assembly --migrate
        if ($LASTEXITCODE -ne 0) { throw 'Commercial database migration failed.' }
        Grant-MasarApplicationAccess -Database $database -Engine Portable
        & (Join-Path $PSScriptRoot 'Publish-CommercialCurriculum.ps1') -Assembly $assembly -Test:$Test -InitializeContent -TargetRelease $TargetRelease
    }

    Set-MasarProcessEnvironment -Database $database -Engine Portable
    Remove-Item Env:MASAR_PILOT_FUNNEL,Env:MASAR_CODE_LAB_ENABLED,Env:MASAR_CODE_LAB_RUNNER_URL,Env:MASAR_CODE_LAB_RUNNER_TOKEN -ErrorAction SilentlyContinue
    if (-not $WithoutLab) {
        $guest = @(Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 2227 -State Listen -ErrorAction SilentlyContinue)
        if ($guest.Count -eq 0) {
            & python -B (Join-Path $workspace 'phase3\host\prepare-vm.py')
            if ($LASTEXITCODE -ne 0) { throw 'The runner VM did not start.' }
        }
        & (Join-Path $workspace 'phase3\host\Connect-NexoraRunner.ps1')
    }
    $env:ASPNETCORE_URLS = $origin
    $env:MASAR_COMMERCIAL_ENABLED = 'true'
    if ($launch) {
        $env:ASPNETCORE_ENVIRONMENT = 'Production'
        $env:DOTNET_ENVIRONMENT = 'Production'
        $env:MASAR_COMMERCIAL_PUBLIC_ORIGIN = $PublicOrigin
        $env:MASAR_COMMERCIAL_PUBLIC_PATH = $mountPath
    } else {
        Remove-Item Env:DOTNET_ENVIRONMENT,Env:MASAR_COMMERCIAL_PUBLIC_ORIGIN,Env:MASAR_COMMERCIAL_PUBLIC_PATH -ErrorAction SilentlyContinue
    }
    if (-not [string]::IsNullOrWhiteSpace($ContactUrl)) { $env:MASAR_COMMERCIAL_CONTACT_URL = $ContactUrl }
    else { Remove-Item Env:MASAR_COMMERCIAL_CONTACT_URL -ErrorAction SilentlyContinue }
    $env:MASAR_COMMERCIAL_DAILY_EXECUTIONS = [string]$DailyExecutionLimit
    $env:MASAR_COMMERCIAL_SESSION_NAMESPACE = if ($Test) { 'CommercialTest' } else { 'Commercial' }
    $worker = Start-Process -FilePath $dotnet -ArgumentList ('"{0}"' -f $assembly) -WorkingDirectory $candidate `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $candidate 'api.out.log') `
        -RedirectStandardError (Join-Path $candidate 'api.err.log')
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while (-not $worker.HasExited -and [DateTime]::UtcNow -lt $deadline) {
        if (Test-CommercialReady) {
            Write-Host "NEXORA CODE commercial candidate: $displayUrl (backend $port)"
            return
        }
        Start-Sleep -Milliseconds 450
    }
    if (-not $worker.HasExited) { Stop-Process -InputObject $worker }
    throw "Commercial candidate readiness failed. Check $candidate\api.err.log."
} finally {
    Clear-MasarProcessSecrets
    Remove-Item Env:MASAR_COMMERCIAL_ENABLED,Env:MASAR_COMMERCIAL_CONTACT_URL,Env:MASAR_COMMERCIAL_DAILY_EXECUTIONS,Env:MASAR_COMMERCIAL_SESSION_NAMESPACE,Env:MASAR_CODE_LAB_ENABLED,Env:MASAR_CODE_LAB_RUNNER_URL,Env:MASAR_CODE_LAB_RUNNER_TOKEN -ErrorAction SilentlyContinue
    foreach ($name in $forwardingVariables) {
        if ($null -eq $savedForwarding[$name]) { Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue }
        else { [Environment]::SetEnvironmentVariable($name, $savedForwarding[$name], 'Process') }
    }
}

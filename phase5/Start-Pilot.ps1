[CmdletBinding()]
param([switch]$Initialize,[ValidateRange(20,900)][int]$DatabaseStartupTimeoutSeconds = 600)

$workspace = Split-Path -Parent $PSScriptRoot
. (Join-Path $workspace 'phase2\scripts\Local-Environment.ps1')
$private = Join-Path $PSScriptRoot '.local'
$pilotApp = Join-Path $private 'app'
$assembly = Join-Path $pilotApp 'Masar.Api.dll'
$dotnet = (Get-Command dotnet.exe -CommandType Application).Source
$database = 'masar_phase5_pilot'
$origin = 'http://localhost:5185'
$runtimeUrl = 'http://127.0.0.1:5185'

function Test-PilotReady {
    try {
        $health = Invoke-RestMethod -Uri "$runtimeUrl/api/v1/health" -TimeoutSec 3
        $catalog = Invoke-RestMethod -Uri "$runtimeUrl/api/v1/catalog" -TimeoutSec 3
        if ($catalog.activeReleaseId -notin @('phase4-ar-v1','phase7-ar-v1')) { return $false }
        $lab = Invoke-RestMethod -Uri "$runtimeUrl/api/v1/lab/exercises/$($catalog.activeReleaseId)/py-02" -TimeoutSec 3
        return $health.status -eq 'ok' -and $health.database -eq 'available' -and
            $lab.available
    } catch { return $false }
}

$listeners = @(Get-NetTCPConnection -LocalPort 5185 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count) {
    $owners = @($listeners.OwningProcess | Select-Object -Unique)
    $record = Get-CimInstance Win32_Process -Filter ('ProcessId={0}' -f $owners[0])
    $expected = '\A(?:"{0}"|{0})\s+"{1}"\s*\z' -f [regex]::Escape($dotnet), [regex]::Escape($assembly)
    if ($owners.Count -ne 1 -or @($listeners | Where-Object LocalAddress -NotIn @('127.0.0.1','::1')).Count -or
        $record.ExecutablePath -ne $dotnet -or $record.CommandLine -notmatch $expected) {
        throw 'The pilot port is in use by another process.'
    }
    if (-not (Test-PilotReady)) { throw 'The running pilot application is not ready. Check the pilot logs.' }
    Write-Host "NEXORA CODE pilot: $origin/#start"
    return
}

if (-not $Initialize -and -not (Test-Path -LiteralPath $assembly -PathType Leaf)) {
    throw 'Run Start-Pilot.ps1 -Initialize to prepare the dedicated pilot database and application.'
}
& (Join-Path $workspace 'phase2\scripts\Start-PortableDatabase.ps1') -StartupTimeoutSeconds $DatabaseStartupTimeoutSeconds

try {
    if ($Initialize) {
        $reviewedSha = '378ddc4d0405fd978efd6c2a56c8a419da73cecd553d1fef5f011e3b3d397743'
        $curriculum = (Resolve-Path -LiteralPath (Join-Path $workspace 'phase4\dist\curriculum.json')).Path
        if ((Get-FileHash -LiteralPath $curriculum -Algorithm SHA256).Hash -ne $reviewedSha) {
            throw 'The Phase 4 bundle differs from the one accepted for this pilot.'
        }

        $source = Join-Path $workspace 'phase2\src\Masar.Api'
        $binaries = Join-Path $source 'bin\Release\net10.0'
        $webRoot = Join-Path $pilotApp 'wwwroot'
        [void](New-Item -ItemType Directory -Path $webRoot -Force)
        Get-ChildItem -LiteralPath $binaries -File |
            Where-Object { $_.Extension -eq '.dll' -or $_.Name -in @('Masar.Api.deps.json','Masar.Api.runtimeconfig.json') } |
            Copy-Item -Destination $pilotApp -Force
        Copy-Item -Path (Join-Path $source 'wwwroot\*') -Destination $webRoot -Recurse -Force

        $setup = @'
SELECT 'CREATE DATABASE masar_phase5_pilot OWNER masar_bootstrap'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='masar_phase5_pilot') \gexec
REVOKE CONNECT ON DATABASE masar_phase5_pilot FROM PUBLIC;
GRANT CONNECT ON DATABASE masar_phase5_pilot TO masar_app;
'@
        Invoke-MasarPortableSql -Sql $setup
        Set-MasarProcessEnvironment -Database $database -Engine Portable -IncludeMigration
        & $dotnet $assembly --migrate
        if ($LASTEXITCODE -ne 0) { throw 'Pilot database migration failed.' }
        Grant-MasarApplicationAccess -Database $database -Engine Portable

        $initialBundle = Join-Path $private 'initial-bundle.json'
        @{
            sample = Get-Content -LiteralPath (Join-Path $workspace 'phase1\content\sample.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            graph = Get-Content -LiteralPath (Join-Path $workspace 'phase1\content\graph.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        } | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $initialBundle -Encoding UTF8
        & $dotnet $assembly --import-bundle $initialBundle --publish-initial
        if ($LASTEXITCODE -ne 0) { throw 'Pilot prerequisite content could not be imported.' }
        & $dotnet $assembly --publish-reviewed-curriculum $curriculum $reviewedSha
        if ($LASTEXITCODE -ne 0) { throw 'Pilot curriculum could not be activated.' }
    }

    Set-MasarProcessEnvironment -Database $database -Engine Portable
    & python -B (Join-Path $workspace 'phase3\host\prepare-vm.py')
    if ($LASTEXITCODE -ne 0) { throw 'The runner VM did not start.' }
    & (Join-Path $workspace 'phase3\host\Connect-NexoraRunner.ps1')
    $env:ASPNETCORE_URLS = $origin
    $env:MASAR_PILOT_FUNNEL = 'true'
    $worker = Start-Process -FilePath $dotnet -ArgumentList ('"{0}"' -f $assembly) -WorkingDirectory $pilotApp `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $private 'pilot.out.log') `
        -RedirectStandardError (Join-Path $private 'pilot.err.log')
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while (-not $worker.HasExited -and [DateTime]::UtcNow -lt $deadline) {
        if (Test-PilotReady) {
            Write-Host "NEXORA CODE pilot: $origin/#start"
            return
        }
        Start-Sleep -Milliseconds 400
    }
    if (-not $worker.HasExited) { Stop-Process -InputObject $worker }
    throw 'Pilot startup verification failed. Check phase5/.local/pilot.err.log.'
} finally {
    Clear-MasarProcessSecrets
    Remove-Item Env:MASAR_PILOT_FUNNEL,Env:MASAR_CODE_LAB_ENABLED,Env:MASAR_CODE_LAB_RUNNER_URL,Env:MASAR_CODE_LAB_RUNNER_TOKEN -ErrorAction SilentlyContinue
}

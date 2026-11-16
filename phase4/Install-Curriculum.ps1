[CmdletBinding()]
param([Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ReviewedSha256)

$workspace = Split-Path -Parent $PSScriptRoot
. (Join-Path $workspace 'phase2\scripts\Local-Environment.ps1')
$source = Join-Path $PSScriptRoot '.local\api-stage'
$bundle = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'dist\curriculum.json')).Path
if ((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash -ne $ReviewedSha256) {
    throw 'The curriculum bundle differs from the reviewed file.'
}
$webApp = (Resolve-Path -LiteralPath (Join-Path $workspace 'phase2\src\Masar.Api')).Path
$install = Join-Path $webApp 'bin\Release\net10.0'
$assembly = (Resolve-Path -LiteralPath (Join-Path $install 'Masar.Api.dll')).Path
$dotnet = (Get-Command dotnet.exe -CommandType Application).Source
$origin = 'http://127.0.0.1:5180'
$files = @('Masar.Api.dll','Masar.Api.deps.json','Masar.Api.runtimeconfig.json','Masar.Domain.dll')
foreach ($name in $files + @('wwwroot\index.html','wwwroot\projects\web-starter-v1.zip')) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $name) -PathType Leaf)) { throw "Staged file missing: $name" }
}

function Get-OwnedApi {
    $listeners = @(Get-NetTCPConnection -LocalPort 5180 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') { throw 'Unexpected application listener.' }
    $process = Get-Process -Id $listeners[0].OwningProcess
    $null = $process.Handle
    $record = Get-CimInstance Win32_Process -Filter ('ProcessId={0}' -f $process.Id)
    $expected = '\A(?:"{0}"|{0})\s+(?:"{1}"|{1})\s*\z' -f [regex]::Escape($dotnet), [regex]::Escape($assembly)
    if ($process.HasExited -or $record.ExecutablePath -ne $dotnet -or $record.CommandLine -notmatch $expected) {
        throw 'The listener does not match the installed NEXORA CODE API.'
    }
    return $process
}

function Start-LocalApi([string]$LogPrefix) {
    $options = @{
        FilePath = $dotnet
        ArgumentList = ('"{0}"' -f $assembly)
        WorkingDirectory = $webApp
        WindowStyle = 'Hidden'
        PassThru = $true
        RedirectStandardOutput = Join-Path $backup "$LogPrefix.out.log"
        RedirectStandardError = Join-Path $backup "$LogPrefix.err.log"
    }
    Start-Process @options
}

function Wait-LocalApi([System.Diagnostics.Process]$Process) {
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    while (-not $Process.HasExited -and [DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "$origin/api/v1/health" -TimeoutSec 2
            if ($health.status -eq 'ok' -and $health.database -eq 'available' -and (Get-OwnedApi).Id -eq $Process.Id) { return }
        } catch {}
        Start-Sleep -Milliseconds 300
    }
    throw 'Local application readiness failed.'
}

$previous = Get-OwnedApi
$oldCatalog = Invoke-RestMethod -Uri "$origin/api/v1/catalog" -TimeoutSec 4
if ($oldCatalog.activeReleaseId -notin @('phase1-ar-v1','phase4-ar-v1')) { throw 'Unexpected active curriculum.' }
$connect = Join-Path $workspace 'phase3\host\Connect-NexoraRunner.ps1'
$backup = Join-Path $PSScriptRoot ('.local\previous-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss'))
[void](New-Item -ItemType Directory -Path $backup)
$webRoot = Join-Path $webApp 'wwwroot'
foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $install $name) -Destination $backup }
$stageWebRoot = Join-Path $source 'wwwroot'
$webBackup = Join-Path $backup 'wwwroot'
$webFiles = @(Get-ChildItem -LiteralPath $stageWebRoot -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($stageWebRoot.Length + 1)
    $target = Join-Path $webRoot $relative
    $saved = Join-Path $webBackup $relative
    $exists = Test-Path -LiteralPath $target -PathType Leaf
    if ($exists) {
        [void](New-Item -ItemType Directory -Force -Path (Split-Path -Parent $saved))
        Copy-Item -LiteralPath $target -Destination $saved
    }
    [pscustomobject]@{ Source = $_.FullName; Target = $target; Backup = $saved; PreviouslyExisted = $exists }
})

try {
    & $connect
    $busy = Invoke-MasarPortableSql -Database 'masar_phase2' -Role App -TupleOnly -Sql "SELECT EXISTS(SELECT 1 FROM public.code_lab_runs WHERE status IN ('queued','running') AND expires_at > now());"
    if ($busy -ne 'f') { throw 'The code lab has active work. Retry after the current run.' }
    Set-MasarProcessEnvironment -Database 'masar_phase2' -Engine Portable
    if ((Get-OwnedApi).Id -ne $previous.Id) { throw 'The application changed during staging.' }
    $previous.Kill()
    if (-not $previous.WaitForExit(10000)) { throw 'The previous API did not stop.' }
    $replacement = $null
    try {
        foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $source $name) -Destination $install -Force }
        foreach ($asset in $webFiles) {
            [void](New-Item -ItemType Directory -Force -Path (Split-Path -Parent $asset.Target))
            Copy-Item -LiteralPath $asset.Source -Destination $asset.Target -Force
        }
        $replacement = Start-LocalApi 'phase4'
        Wait-LocalApi $replacement
        $legacy = Invoke-RestMethod -Uri "$origin/api/v1/lab/exercises/phase1-ar-v1/what-is-a-program" -TimeoutSec 4
        if (-not $legacy.available -or $legacy.exercises.id -notcontains 'python-greeting') { throw 'The existing code lab did not verify.' }
    } catch {
        if ($null -ne $replacement -and -not $replacement.HasExited) {
            $replacement.Kill()
            [void]$replacement.WaitForExit(10000)
        }
        foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $backup $name) -Destination $install -Force }
        foreach ($asset in $webFiles) {
            if ($asset.PreviouslyExisted) {
                Copy-Item -LiteralPath $asset.Backup -Destination $asset.Target -Force
            } elseif (Test-Path -LiteralPath $asset.Target -PathType Leaf) {
                Remove-Item -LiteralPath $asset.Target
            }
        }
        Wait-LocalApi (Start-LocalApi 'restored')
        throw
    }
    Set-MasarProcessEnvironment -Database 'masar_phase2' -Engine Portable -IncludeMigration
    & $dotnet $assembly --publish-reviewed-curriculum $bundle $ReviewedSha256
    if ($LASTEXITCODE -ne 0) { throw 'The upgraded application is running. Check the publication error, then retry this installer with the same SHA-256.' }
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        try {
            $catalog = Invoke-RestMethod -Uri "$origin/api/v1/catalog" -TimeoutSec 4
            $curriculum = Invoke-RestMethod -Uri "$origin/api/v1/content/phase4-ar-v1" -TimeoutSec 4
            if ($catalog.activeReleaseId -eq 'phase4-ar-v1' -and $catalog.releases.releaseId -contains 'phase1-ar-v1' -and
                $curriculum.sample.lessons.Count -eq 36) {
                Write-Host "NEXORA CODE verified at $origin with $($curriculum.sample.lessons.Count) lessons and the existing sample release."
                return
            }
        } catch {}
        Start-Sleep -Milliseconds 300
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Curriculum publication completed. Local HTTP verification did not respond as expected. Diagnose the upgraded API using the installation logs, then retry with the same SHA-256.'
} finally {
    Clear-MasarProcessSecrets
    Remove-Item Env:MASAR_CODE_LAB_ENABLED,Env:MASAR_CODE_LAB_RUNNER_URL,Env:MASAR_CODE_LAB_RUNNER_TOKEN -ErrorAction SilentlyContinue
}

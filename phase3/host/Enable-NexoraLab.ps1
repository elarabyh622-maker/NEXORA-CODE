[CmdletBinding()]
param([switch]$DisableRunner)

$phaseTwo = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'phase2'
. (Join-Path $phaseTwo 'scripts\Local-Environment.ps1')
$workingDirectory = (Resolve-Path -LiteralPath (Join-Path $phaseTwo 'src\Masar.Api')).Path
$assembly = (Resolve-Path -LiteralPath (Join-Path $workingDirectory 'bin\Release\net10.0\Masar.Api.dll')).Path
$dotnet = (Get-Command dotnet.exe -CommandType Application -ErrorAction Stop).Source
$port = 5180
$origin = "http://127.0.0.1:$port"

function Get-MasarListener {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 1 -or ($listeners.Count -eq 1 -and $listeners[0].LocalAddress -ne '127.0.0.1')) {
        throw "Port $port has an unexpected listener. No process will be stopped."
    }
    if ($listeners.Count -eq 1) { return $listeners[0] }
}

function Get-OwnedMasarApi {
    $listener = Get-MasarListener
    if ($null -eq $listener) { throw "The existing Masar API is not listening on $origin." }

    $process = Get-Process -Id $listener.OwningProcess -ErrorAction Stop
    # Hold a process handle across validation and shutdown so a recycled PID cannot be stopped.
    $null = $process.Handle
    $record = Get-CimInstance Win32_Process -Filter ('ProcessId={0}' -f $process.Id) -ErrorAction Stop
    $dotnetPattern = [regex]::Escape($dotnet)
    $assemblyPattern = [regex]::Escape($assembly)
    $commandPattern = '\A(?:"{0}"|{0})\s+(?:"{1}"|{1})\s*\z' -f $dotnetPattern,$assemblyPattern
    $currentListener = Get-MasarListener
    if ($null -eq $record -or $record.ExecutablePath -ne $dotnet -or $record.CommandLine -notmatch $commandPattern -or
        $process.HasExited -or $null -eq $currentListener -or $currentListener.OwningProcess -ne $process.Id) {
        throw "Port $port does not belong to the expected Masar API Release process. No process will be stopped."
    }
    return $process
}

function Set-RunnerDisabled {
    $env:MASAR_CODE_LAB_ENABLED = 'false'
    Remove-Item Env:MASAR_CODE_LAB_RUNNER_URL,Env:MASAR_CODE_LAB_RUNNER_TOKEN -ErrorAction SilentlyContinue
}

function Start-OwnedMasarApi {
    if ($null -ne (Get-MasarListener)) { throw "Port $port is occupied. No listener will be stopped." }
    $options = @{
        FilePath = $dotnet
        ArgumentList = ('"{0}"' -f $assembly)
        WorkingDirectory = $workingDirectory
        WindowStyle = 'Hidden'
        PassThru = $true
    }
    Start-Process @options
}

function Assert-MasarReady([System.Diagnostics.Process]$Process, [bool]$RunnerAvailable) {
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        if ($Process.HasExited) { throw 'The replacement Masar API exited during startup.' }
        $listener = Get-MasarListener
        if ($null -ne $listener) {
            if ($listener.OwningProcess -ne $Process.Id) { throw "Port $port was taken by a different process." }
            try {
                $health = Invoke-RestMethod -Uri "$origin/api/v1/health" -TimeoutSec 2 -MaximumRedirection 0
                $catalog = Invoke-RestMethod -Uri "$origin/api/v1/lab/exercises/phase1-ar-v1/what-is-a-program" -TimeoutSec 2 -MaximumRedirection 0
                if ($health.status -eq 'ok' -and $health.database -eq 'available' -and
                    $catalog.available -is [bool] -and $catalog.available -eq $RunnerAvailable -and
                    $catalog.exercises.id -contains 'python-greeting') {
                    $verifiedListener = Get-MasarListener
                    if (-not $Process.HasExited -and $null -ne $verifiedListener -and $verifiedListener.OwningProcess -eq $Process.Id) {
                        return
                    }
                }
            } catch {
                # During startup the API or database may not be ready yet.
            }
        }
        Start-Sleep -Milliseconds 300
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'The replacement Masar API did not verify its database and expected lab mode.'
}

function Stop-OwnedMasarApi([System.Diagnostics.Process]$Process) {
    if (-not $Process.HasExited) {
        $Process.Kill()
        if (-not $Process.WaitForExit(10000)) { throw 'The owned Masar API did not stop in time.' }
    }
}

$existing = Get-OwnedMasarApi
try {
    $initialHealth = Invoke-RestMethod -Uri "$origin/api/v1/health" -TimeoutSec 3 -MaximumRedirection 0
    if ($initialHealth.status -ne 'ok' -or $initialHealth.database -ne 'available') { throw 'Unhealthy API.' }
} catch {
    throw 'The existing Masar API database health check failed. The API was left running.'
}

$environmentNames = @(
    'ConnectionStrings__Masar', 'ConnectionStrings__Migration', 'ASPNETCORE_ENVIRONMENT', 'ASPNETCORE_URLS',
    'MASAR_DATA_ROOT', 'DOTNET_CLI_HOME', 'DOTNET_CLI_TELEMETRY_OPTOUT', 'DOTNET_SKIP_FIRST_TIME_EXPERIENCE',
    'MASAR_CODE_LAB_ENABLED', 'MASAR_CODE_LAB_RUNNER_URL', 'MASAR_CODE_LAB_RUNNER_TOKEN'
)
$originalEnvironment = @{}
foreach ($name in $environmentNames) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    if ($DisableRunner) { Set-RunnerDisabled }
    else { & (Join-Path $PSScriptRoot 'Connect-NexoraRunner.ps1') }
    try {
        Set-MasarProcessEnvironment -Database 'masar_phase2' -Engine Portable
    } catch {
        throw 'Could not load the portable Masar database configuration. The API was left running.'
    }
    $env:ASPNETCORE_URLS = $origin

    $verifiedOwner = Get-OwnedMasarApi
    if ($existing.HasExited -or $verifiedOwner.Id -ne $existing.Id) {
        throw 'The original Masar API changed during setup. No process was stopped.'
    }

    $replacement = $null
    try {
        Stop-OwnedMasarApi $existing
        $replacement = Start-OwnedMasarApi
        Assert-MasarReady $replacement (-not $DisableRunner)
    } catch {
        if (-not $existing.HasExited) { throw 'Could not stop the original Masar API. No replacement was started.' }
        try {
            if ($null -ne $replacement) { Stop-OwnedMasarApi $replacement }
            Set-RunnerDisabled
            $fallback = Start-OwnedMasarApi
            Assert-MasarReady $fallback $false
        } catch {
            throw 'The replacement API failed verification and the automatic restart with the runner disabled did not verify.'
        }
        throw "The replacement API failed verification. Masar API was restored at $origin with the runner disabled (PID $($fallback.Id))."
    }

    $mode = if ($DisableRunner) { 'disabled' } else { 'enabled' }
    Write-Host "Masar API verified at $origin (PID $($replacement.Id), runner $mode)."
} finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], 'Process')
    }
}

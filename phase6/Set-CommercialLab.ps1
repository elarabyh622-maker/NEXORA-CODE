[CmdletBinding()]
param(
    [string]$PublicOrigin = 'https://desktop-phkhegp.tail3372f6.ts.net:10000',
    [ValidateRange(1,10000)][int]$DailyExecutionLimit = 300,
    [switch]$WithoutLab
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$app = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '.local/launch/app')).Path
$assembly = Join-Path $app 'Masar.Api.dll'
$dotnet = (Get-Command dotnet.exe -CommandType Application).Source
$parsedOrigin = $null
if (-not [Uri]::TryCreate($PublicOrigin, [UriKind]::Absolute, [ref]$parsedOrigin) -or
    $parsedOrigin.Scheme -ne 'https' -or $parsedOrigin.AbsolutePath -ne '/' -or
    $parsedOrigin.UserInfo -or $parsedOrigin.Query -or $parsedOrigin.Fragment) {
    throw 'PublicOrigin must be an HTTPS origin without a path, query, fragment, or credentials.'
}
$PublicOrigin = $parsedOrigin.GetLeftPart([UriPartial]::Authority)
$base = "$PublicOrigin/nexora-commercial"

function Get-OwnedCommercialWorker {
    $listeners = @(Get-NetTCPConnection -LocalPort 5187 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) { return }
    if ($listeners.Count -ne 1 -or $listeners[0].LocalAddress -ne '127.0.0.1') {
        throw 'Unexpected listener on the commercial port; no process was stopped.'
    }
    $worker = Get-Process -Id $listeners[0].OwningProcess
    $null = $worker.Handle
    if ($worker.HasExited) { throw 'The commercial worker exited before verification.' }
    $created = $worker.StartTime.ToUniversalTime()
    $record = Get-CimInstance Win32_Process -Filter ('ProcessId={0}' -f $worker.Id)
    $expected = '\A(?:"{0}"|{0})\s+"{1}"\s*\z' -f [regex]::Escape($dotnet), [regex]::Escape($assembly)
    if ($record.ExecutablePath -ne $dotnet -or $record.CommandLine -notmatch $expected) {
        throw 'The commercial listener belongs to another process; no process was stopped.'
    }
    $verifiedListeners = @(Get-NetTCPConnection -LocalPort 5187 -State Listen -ErrorAction SilentlyContinue)
    if ($worker.HasExited -or $null -eq $record -or
        [Math]::Abs(($record.CreationDate.ToUniversalTime() - $created).TotalMilliseconds) -ge 1 -or
        $verifiedListeners.Count -ne 1 -or $verifiedListeners[0].OwningProcess -ne $worker.Id -or
        $verifiedListeners[0].LocalAddress -ne '127.0.0.1') {
        throw 'The commercial process identity changed during verification.'
    }
    return $worker
}
function Stop-OwnedCommercialWorker($Worker) {
    if ($Worker -and -not $Worker.HasExited) {
        Stop-Process -InputObject $Worker
        if (-not $Worker.WaitForExit(5000)) { throw 'The commercial worker did not exit.' }
    }
}
function Read-Catalog {
    Invoke-RestMethod -Uri "$base/api/v1/catalog" -TimeoutSec 10 -MaximumRedirection 0
}
$current = Read-Catalog
if (-not $current.accessRequired -or -not $current.activeReleaseId) { throw 'Unexpected commercial profile.' }
$worker = Get-OwnedCommercialWorker
if (-not $worker) { throw 'The current commercial worker was not found.' }
$startArgs = @{ PublicOrigin = $PublicOrigin; DailyExecutionLimit = $DailyExecutionLimit }
if ($current.PSObject.Properties.Name -contains 'contactUrl' -and $current.contactUrl) {
    $startArgs.ContactUrl = $current.contactUrl
}
try {
    # A failed runner probe leaves the commercial application running in its current mode.
    if (-not $WithoutLab) { & (Join-Path $workspace 'phase3/host/Connect-NexoraRunner.ps1') }
    Stop-OwnedCommercialWorker $worker
    try {
        & (Join-Path $PSScriptRoot 'Start-Commercial.ps1') @startArgs -WithoutLab:$WithoutLab
        $after = Read-Catalog
        if ($after.activeReleaseId -ne $current.activeReleaseId -or -not $after.accessRequired) {
            throw 'The restarted commercial profile changed unexpectedly.'
        }
    } catch {
        $failure = $_
        Stop-OwnedCommercialWorker (Get-OwnedCommercialWorker)
        & (Join-Path $PSScriptRoot 'Start-Commercial.ps1') @startArgs -WithoutLab
        throw $failure
    }
    Write-Host ('Commercial application restarted; code execution requested: {0}.' -f (-not $WithoutLab))
} finally {
    Remove-Item Env:MASAR_CODE_LAB_ENABLED,Env:MASAR_CODE_LAB_RUNNER_URL,Env:MASAR_CODE_LAB_RUNNER_TOKEN -ErrorAction SilentlyContinue
}

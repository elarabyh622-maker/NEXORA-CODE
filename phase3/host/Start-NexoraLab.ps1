[CmdletBinding()]
param([switch]$Test)

$ErrorActionPreference = 'Stop'
$phaseThree = Split-Path -Parent $PSScriptRoot
$phaseTwo = Join-Path (Split-Path -Parent $phaseThree) 'phase2'
& python -B (Join-Path $PSScriptRoot 'prepare-vm.py')
if ($LASTEXITCODE -ne 0) { throw 'The runner VM did not start.' }

try {
    & (Join-Path $PSScriptRoot 'Connect-NexoraRunner.ps1')
    if ($Test) {
        & (Join-Path $phaseThree 'Test-CodeLab.ps1') -RealRunner
    } else {
        & (Join-Path $phaseTwo 'Start-Masar.ps1') -Engine Portable
    }
} finally {
    Remove-Item Env:MASAR_CODE_LAB_ENABLED,Env:MASAR_CODE_LAB_RUNNER_URL,Env:MASAR_CODE_LAB_RUNNER_TOKEN -ErrorAction SilentlyContinue
}

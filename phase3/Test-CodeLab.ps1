[CmdletBinding()]
param(
    [string]$ApiPath,
    [switch]$RealRunner
)

$phaseTwo = Join-Path (Split-Path -Parent $PSScriptRoot) 'phase2'
. (Join-Path $phaseTwo 'scripts\Local-Environment.ps1')
if ($RealRunner -and ([string]::IsNullOrWhiteSpace($env:MASAR_CODE_LAB_RUNNER_URL) -or
    [string]::IsNullOrWhiteSpace($env:MASAR_CODE_LAB_RUNNER_TOKEN))) {
    throw 'Real runner acceptance requires MASAR_CODE_LAB_RUNNER_URL and MASAR_CODE_LAB_RUNNER_TOKEN in the process environment.'
}
if (-not $ApiPath) {
    $ApiPath = Join-Path $phaseTwo 'src\Masar.Api\bin\Release\net10.0\Masar.Api.dll'
}
$ApiPath = (Resolve-Path -LiteralPath $ApiPath).Path
& (Join-Path $phaseTwo 'scripts\Update-MasarSchema.ps1') -Engine Portable -Database masar_phase2_tests -ApiPath $ApiPath
try {
    Set-MasarProcessEnvironment -Database 'masar_phase2_tests' -Engine Portable
    $testArguments = @((Join-Path $PSScriptRoot 'test_code_lab_http.py'), $ApiPath)
    if ($RealRunner) { $testArguments += '--real-runner' }
    & python -B @testArguments
    if ($LASTEXITCODE -ne 0) { throw 'Code lab HTTP integration failed.' }
} finally {
    Clear-MasarProcessSecrets
}

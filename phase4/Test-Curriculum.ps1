[CmdletBinding()]
param()

. (Join-Path (Split-Path -Parent $PSScriptRoot) 'phase2\scripts\Local-Environment.ps1')
$assembly = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '.local\api-stage\Masar.Api.dll')).Path
$bundle = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'dist\curriculum.json')).Path
$sha = (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
$connect = Join-Path (Split-Path -Parent $PSScriptRoot) 'phase3\host\Connect-NexoraRunner.ps1'

try {
    & $connect
    & python -B (Join-Path $PSScriptRoot 'validate_execution.py')
    if ($LASTEXITCODE -ne 0) { throw 'One or more curriculum executions did not pass.' }
    Set-MasarProcessEnvironment -Database 'masar_phase2_tests' -Engine Portable -IncludeMigration
    & dotnet $assembly --publish-reviewed-curriculum $bundle $sha
    if ($LASTEXITCODE -ne 0) { throw 'Publication to the dedicated test database did not pass.' }
    Remove-Item Env:ConnectionStrings__Migration -ErrorAction SilentlyContinue
    & python -B (Join-Path $PSScriptRoot 'validate-release.py') $assembly --content-root (Split-Path -Parent $assembly)
    if ($LASTEXITCODE -ne 0) { throw 'Published curriculum acceptance did not pass.' }
    Write-Host "Verified curriculum SHA-256: $sha"
} finally {
    Clear-MasarProcessSecrets
    Remove-Item Env:MASAR_CODE_LAB_ENABLED,Env:MASAR_CODE_LAB_RUNNER_URL,Env:MASAR_CODE_LAB_RUNNER_TOKEN -ErrorAction SilentlyContinue
}

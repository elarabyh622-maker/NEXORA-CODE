[CmdletBinding()]
param([ValidateSet('masar_phase2','masar_phase2_tests')][string]$Database='masar_phase2', [ValidateRange(1024,65535)][int]$Port=5180, [ValidateSet('Docker','Portable')][string]$Engine='Docker')
. (Join-Path $PSScriptRoot 'scripts\Local-Environment.ps1')
$api = Join-Path $script:MasarRoot 'src\Masar.Api\bin\Release\net10.0\Masar.Api.dll'
if (-not (Test-Path -LiteralPath $api)) { throw 'Run scripts/Initialize-Masar.ps1 before starting the application.' }
if ($Engine -eq 'Portable') { & (Join-Path $PSScriptRoot 'scripts\Start-PortableDatabase.ps1') }
Set-MasarProcessEnvironment -Database $Database -Engine $Engine
$env:ASPNETCORE_URLS = "http://127.0.0.1:$Port"
Push-Location (Join-Path $script:MasarRoot 'src\Masar.Api')
try {
    Write-Host "Open http://127.0.0.1:$Port . Stop with Ctrl+C. No migrations or imports run during normal startup."
    & dotnet $api
    if ($LASTEXITCODE -ne 0) { throw 'Masar stopped with an error. Inspect the local server log without exposing connection strings.' }
} finally { Clear-MasarProcessSecrets; Pop-Location }

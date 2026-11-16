[CmdletBinding()]
param([ValidateSet('Docker','Portable')][string]$Engine='Docker')
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
Set-MasarProcessEnvironment -Database 'masar_phase2_tests' -Engine $Engine -IncludeMigration
$env:ASPNETCORE_URLS = 'http://127.0.0.1:5181'
try {
    & python (Join-Path $PSScriptRoot 'http_integration.py') --base 'http://127.0.0.1:5181'
    if ($LASTEXITCODE -ne 0) { throw 'Integration checks failed. Read test-results/http-integration.json; no credentials are included in that report.' }
} finally { Clear-MasarProcessSecrets }

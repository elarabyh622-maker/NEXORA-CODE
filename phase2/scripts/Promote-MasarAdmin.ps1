[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$UserName, [ValidateSet('Docker','Portable')][string]$Engine='Docker')
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$api = Join-Path $script:MasarRoot 'src\Masar.Api\bin\Release\net10.0\Masar.Api.dll'
Set-MasarProcessEnvironment -Engine $Engine -IncludeMigration
Push-Location (Join-Path $script:MasarRoot 'src\Masar.Api')
try {
    & dotnet $api --promote-admin $UserName
    if ($LASTEXITCODE -ne 0) { throw 'No administrator promotion was completed.' }
} finally { Clear-MasarProcessSecrets; Pop-Location }

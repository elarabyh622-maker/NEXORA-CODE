[CmdletBinding()]
param(
    [ValidateSet('masar_phase2','masar_phase2_tests')][string]$Database = 'masar_phase2',
    [ValidateSet('Docker','Portable')][string]$Engine = 'Portable',
    [string]$ApiPath
)

. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
if (-not $ApiPath) {
    $ApiPath = Join-Path $script:MasarRoot 'src\Masar.Api\bin\Release\net10.0\Masar.Api.dll'
}
$ApiPath = (Resolve-Path -LiteralPath $ApiPath).Path
if ($Engine -eq 'Portable') { & (Join-Path $PSScriptRoot 'Start-PortableDatabase.ps1') }

try {
    Set-MasarProcessEnvironment -Database $Database -Engine $Engine -IncludeMigration
    & dotnet $ApiPath --migrate
    if ($LASTEXITCODE -ne 0) { throw 'Schema update failed.' }
    Grant-MasarApplicationAccess -Database $Database -Engine $Engine
} finally {
    Clear-MasarProcessSecrets
}

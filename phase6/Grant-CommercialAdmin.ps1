[CmdletBinding()]
param([Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$UserName)

. (Join-Path (Split-Path -Parent $PSScriptRoot) 'phase2\scripts\Local-Environment.ps1')
$assembly = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '.local\app\Masar.Api.dll')).Path
try {
    Set-MasarProcessEnvironment -Database 'masar_phase6_commercial' -Engine Portable -IncludeMigration
    & dotnet $assembly --promote-admin $UserName
    if ($LASTEXITCODE -ne 0) { throw 'Commercial administrator setup failed.' }
} finally { Clear-MasarProcessSecrets }

[CmdletBinding()]
param([switch]$SkipDatabaseProvisioning, [switch]$SkipBuild, [ValidateSet('Docker','Portable')][string]$Engine='Docker')
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
if (-not $SkipDatabaseProvisioning) {
    $setup = if ($Engine -eq 'Portable') { 'Initialize-PortableDatabase.ps1' } else { 'Initialize-Database.ps1' }
    & (Join-Path $PSScriptRoot $setup)
}
if (-not $SkipBuild) { & (Join-Path $PSScriptRoot 'Build-Masar.ps1') }
$api = Join-Path $script:MasarRoot 'src\Masar.Api\bin\Release\net10.0\Masar.Api.dll'
if (-not (Test-Path -LiteralPath $api)) { throw 'Build the API before initializing the databases.' }
$samplePath = Join-Path (Split-Path -Parent $script:MasarRoot) 'phase1\content\sample.json'
$graphPath = Join-Path (Split-Path -Parent $script:MasarRoot) 'phase1\content\graph.json'
$bundle = @{
    sample = (Get-Content -LiteralPath $samplePath -Raw -Encoding utf8 | ConvertFrom-Json)
    graph = (Get-Content -LiteralPath $graphPath -Raw -Encoding utf8 | ConvertFrom-Json)
}
$bundlePath = Join-Path $script:MasarPrivate 'initial-bundle.json'
$bundle | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $bundlePath -Encoding utf8
Push-Location (Join-Path $script:MasarRoot 'src\Masar.Api')
try {
    foreach ($database in @('masar_phase2', 'masar_phase2_tests')) {
        Set-MasarProcessEnvironment -Database $database -Engine $Engine -IncludeMigration
        & dotnet $api --migrate
        if ($LASTEXITCODE -ne 0) { throw 'Migration failed for the dedicated Masar database.' }
        Grant-MasarApplicationAccess -Database $database -Engine $Engine
        & dotnet $api --import-bundle $bundlePath --publish-initial
        if ($LASTEXITCODE -ne 0) { throw 'Initial content import failed; existing content was not reset.' }
    }
} finally { Clear-MasarProcessSecrets; Pop-Location }
Write-Host 'Masar development and test databases initialized. No default user or administrator password was created.'

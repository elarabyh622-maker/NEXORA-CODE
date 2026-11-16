[CmdletBinding()]
param([switch]$InstallFrontend)
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$env:DOTNET_CLI_HOME = Join-Path $script:MasarPrivate 'dotnet'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
Push-Location $script:MasarRoot
try {
    & dotnet build Masar.slnx -c Release --nologo
    if ($LASTEXITCODE -ne 0) { throw 'The .NET solution build failed.' }
    Push-Location (Join-Path $script:MasarRoot 'apps\web')
    try {
        if ($InstallFrontend -or -not (Test-Path -LiteralPath 'node_modules')) {
            & npm.cmd ci --cache (Join-Path $script:MasarPrivate 'npm') --no-fund --no-audit
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend type checking or build failed.' }
        $webRoot = Join-Path $script:MasarRoot 'src\Masar.Api\wwwroot'
        New-Item -ItemType Directory -Path $webRoot -Force | Out-Null
        Copy-Item -Path '.\dist\*' -Destination $webRoot -Recurse -Force
    } finally { Pop-Location }
} finally { Pop-Location }
Write-Host 'Masar .NET and React builds completed. Static files are served by the API.'

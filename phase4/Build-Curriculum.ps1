[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$web = Join-Path $workspace 'phase2\apps\web'
$project = Join-Path $workspace 'phase2\src\Masar.Api\Masar.Api.csproj'
$stage = Join-Path $PSScriptRoot '.local\api-stage'

& python -B (Join-Path $PSScriptRoot 'build_curriculum.py')
if ($LASTEXITCODE -ne 0) { throw 'Curriculum generation failed.' }

Push-Location -LiteralPath $web
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Web application build failed.' }
} finally {
    Pop-Location
}

& dotnet build $project -c Release --no-restore --nologo -o $stage
if ($LASTEXITCODE -ne 0) { throw 'API build failed.' }
$manifest = Join-Path $stage 'Masar.Api.staticwebassets.runtime.json'
if (Test-Path -LiteralPath $manifest -PathType Leaf) {
    # Serve the staged files rather than resolving static assets from the development checkout.
    Remove-Item -LiteralPath $manifest
}
$stagedWeb = Join-Path $stage 'wwwroot'
[void](New-Item -ItemType Directory -Path $stagedWeb -Force)
Copy-Item -Path (Join-Path $web 'dist\*') -Destination $stagedWeb -Recurse -Force

& dotnet (Join-Path $stage 'Masar.Api.dll') --verify-curriculum (Join-Path $PSScriptRoot 'dist\curriculum.json')
if ($LASTEXITCODE -ne 0) { throw 'Offline curriculum validation failed.' }

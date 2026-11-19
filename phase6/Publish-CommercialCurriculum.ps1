[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Assembly,
    [switch]$Test,
    [switch]$InitializeContent,
    [ValidateSet('phase7-ar-v1','phase8-ar-v1','phase9-ar-v1','phase10-ar-v1','phase11-ar-v1')][string]$TargetRelease = 'phase11-ar-v1'
)

$workspace = Split-Path -Parent $PSScriptRoot
. (Join-Path $workspace 'phase2\scripts\Local-Environment.ps1')
$assemblyPath = (Resolve-Path -LiteralPath $Assembly).Path
if (-not (Test-Path -LiteralPath $assemblyPath -PathType Leaf)) { throw 'Expected a built API assembly.' }
$dotnet = (Get-Command dotnet.exe -CommandType Application).Source
$database = if ($Test) { 'masar_phase6_tests' } else { 'masar_phase6_commercial' }
$TargetRelease = $TargetRelease.ToLowerInvariant()
$releases = @(
    @{ Id = 'phase4-ar-v1'; File = 'phase4\dist\curriculum.json'; Digest = '378ddc4d0405fd978efd6c2a56c8a419da73cecd553d1fef5f011e3b3d397743' }
    @{ Id = 'phase7-ar-v1'; File = 'phase7\dist\curriculum.json'; Digest = 'a66ba6f564d7ce49bbab3afa7aeb7d69452589e1b68a4e315d9da807583000cc' }
    @{ Id = 'phase8-ar-v1'; File = 'phase8\dist\curriculum.json'; Digest = 'e6287e0aac68d5e2b5b9be933ee4dc408e8cd6bfb3b1d8c83d97dd735e62b82a' }
    @{ Id = 'phase9-ar-v1'; File = 'phase9\dist\curriculum.json'; Digest = 'bf66b58d76aaa54bd0d760eecde443cb7c98081b474c0e04ffe92ee9973d525a' }
    @{ Id = 'phase10-ar-v1'; File = 'phase10\dist\curriculum.json'; Digest = 'a418cbb4f6f64fc809716f4fc634ba6b6df50e75e083bdd6925cfbde4d80df62' }
    @{ Id = 'phase11-ar-v1'; File = 'phase11\dist\curriculum.json'; Digest = '9cbf77989eb597c44a6d4bf0011587a52c5a35a23c4a6b8d0792a81c7e171ef7' }
)

$catalogStateQuery = @'
SELECT CASE
    WHEN EXISTS (SELECT 1 FROM public.settings WHERE key = 'active_release_id') THEN
        COALESCE((SELECT r.release_id FROM public.settings s JOIN public.content_releases r ON r.release_id = s.value
                  WHERE s.key = 'active_release_id' AND r.status = 'published'), 'invalid')
    WHEN NOT EXISTS (SELECT 1 FROM public.content_releases WHERE published_at IS NOT NULL OR status IN ('published', 'retired'))
        THEN 'uninitialized'
    ELSE 'invalid'
END;
'@
$active = Invoke-MasarPortableSql -Database $database -Sql $catalogStateQuery -TupleOnly
$releaseIds = @($releases.Id)
$targetIndex = [Array]::IndexOf($releaseIds, $TargetRelease)
$allowedReleases = @($releaseIds[0..$targetIndex])
if ($InitializeContent) { $allowedReleases += 'uninitialized', 'phase1-ar-v1' }
if ($active -notin $allowedReleases) {
    throw 'The commercial database has no supported active release for this operation.'
}

# When the target is already active, recheck its contents through the same publish command.
$firstIndex = [Math]::Min([Array]::IndexOf($releaseIds, $active) + 1, $targetIndex)
$pending = $releases[$firstIndex..$targetIndex]
foreach ($release in $pending) {
    $bundle = Join-Path $workspace $release.File
    if ((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash -ne $release.Digest) {
        throw "The curriculum differs from the reviewed $($release.Id) bundle."
    }
    & $dotnet $assemblyPath --verify-curriculum $bundle
    if ($LASTEXITCODE -ne 0) { throw "The API assembly could not verify $($release.Id)." }
}

$initialFile = $null
$savedEnvironment = @{}
foreach ($name in @('ASPNETCORE_ENVIRONMENT', 'DOTNET_ENVIRONMENT', 'ConnectionStrings__Migration')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $connections = Get-MasarConnections -Database $database -Engine Portable -IncludeMigration
    $env:ConnectionStrings__Migration = $connections.Migration
    $connections = $null
    $env:ASPNETCORE_ENVIRONMENT = 'Development'
    $env:DOTNET_ENVIRONMENT = 'Development'

    if ($active -eq 'uninitialized') {
        $initialFile = New-TemporaryFile
        @{
            sample = Get-Content -LiteralPath (Join-Path $workspace 'phase1\content\sample.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            graph = Get-Content -LiteralPath (Join-Path $workspace 'phase1\content\graph.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        } | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $initialFile.FullName -Encoding UTF8
        & $dotnet $assemblyPath --import-bundle $initialFile.FullName --publish-initial
        if ($LASTEXITCODE -ne 0) { throw 'Commercial sample import failed.' }
    }

    foreach ($release in $pending) {
        $bundle = Join-Path $workspace $release.File
        & $dotnet $assemblyPath --publish-reviewed-curriculum $bundle $release.Digest
        if ($LASTEXITCODE -ne 0) { throw "Commercial activation of $($release.Id) failed." }
    }
    if ((Invoke-MasarPortableSql -Database $database -Sql $catalogStateQuery -TupleOnly) -ne $TargetRelease) {
        throw "Could not verify $TargetRelease as the active commercial release in PostgreSQL."
    }
    Write-Host "Verified $TargetRelease in $database."
} finally {
    foreach ($name in $savedEnvironment.Keys) {
        $value = $savedEnvironment[$name]
        if ($null -eq $value) { Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue }
        else { [Environment]::SetEnvironmentVariable($name, $value, 'Process') }
    }
    if ($initialFile) { Remove-Item -LiteralPath $initialFile.FullName -ErrorAction SilentlyContinue }
}

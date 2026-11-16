[CmdletBinding()]
param([ValidateRange(1,30)][int]$ProbeTimeoutSeconds = 3,
      [ValidateRange(20,900)][int]$StartupTimeoutSeconds = 20)
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$marker = Join-Path $script:MasarPortableRoot 'masar-portable.json'
$nativeRoot = Get-MasarPortableNativeRoot
$data = Join-Path $nativeRoot 'data'
$bin = Join-Path $nativeRoot 'binaries\pgsql\bin'
if (-not (Test-Path -LiteralPath $marker) -or -not (Test-Path -LiteralPath (Join-Path $data 'PG_VERSION'))) {
    throw 'Initialize the separate portable Masar cluster first.'
}
$ownership = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ($ownership.project -ne 'masar-phase2-portable' -or $ownership.port -ne $script:MasarPortablePort -or
    (Get-Content -LiteralPath (Join-Path $data 'PG_VERSION') -Raw).Trim() -ne '18') {
    throw 'Unexpected portable cluster ownership or version; nothing started.'
}
$control = Join-Path $bin 'pg_ctl.exe'
& $control status -D $data | Out-Null
if ($LASTEXITCODE -ne 0) {
    $listeners = @(Get-NetTCPConnection -LocalPort $script:MasarPortablePort -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count) { throw 'The portable Masar port is already in use; nothing started.' }
    $log = Join-Path $nativeRoot 'postgres.log'
    & $control start -D $data -l $log -o "-h 127.0.0.1 -p $($script:MasarPortablePort)" -w -t $StartupTimeoutSeconds
    if ($LASTEXITCODE -ne 0) { throw 'The portable Masar server did not report ready in time. Inspect its local postgres.log before attempting to start it again.' }
}
& (Join-Path $bin 'pg_isready.exe') -h 127.0.0.1 -p $script:MasarPortablePort -U masar_bootstrap -d postgres -t $ProbeTimeoutSeconds
if ($LASTEXITCODE -ne 0) { throw 'The portable Masar PostgreSQL TCP endpoint is not ready.' }

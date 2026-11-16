[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
$marker = Join-Path $script:MasarPortableRoot 'masar-portable.json'
$nativeRoot = Get-MasarPortableNativeRoot
$data = Join-Path $nativeRoot 'data'
$pidFile = Join-Path $data 'postmaster.pid'
if (-not (Test-Path -LiteralPath $marker) -or -not (Test-Path -LiteralPath $pidFile)) { return }
$owner = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
if ($owner.project -ne 'masar-phase2-portable' -or $owner.port -ne $script:MasarPortablePort) { throw 'Unexpected portable cluster marker.' }
$pgProcessId = [int](Get-Content -LiteralPath $pidFile -TotalCount 1)
$pgProcess = Get-Process -Id $pgProcessId -ErrorAction SilentlyContinue
if (-not $pgProcess) { return }
$bin = Join-Path $nativeRoot 'binaries\pgsql\bin'
$expected = [IO.Path]::GetFullPath((Join-Path $bin 'postgres.exe'))
$physical = [IO.Path]::GetFullPath((Join-Path $script:MasarPortableRoot 'binaries\pgsql\bin\postgres.exe'))
if (-not $pgProcess.Path -or $pgProcess.Path -notin @($expected,$physical)) { throw 'PID does not belong to the Masar portable executable; nothing stopped.' }
& (Join-Path $bin 'pg_ctl.exe') stop -D $data -m fast -w -t 20
if ($LASTEXITCODE -ne 0) { throw 'Portable PostgreSQL did not stop cleanly.' }

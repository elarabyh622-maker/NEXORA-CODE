[CmdletBinding()]
param()
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
if ($env:OS -ne 'Windows_NT') { throw 'This portable setup is for Windows x64 and Windows DPAPI.' }
$archive = Join-Path $script:MasarPortableRoot 'postgresql-18.6-windows-x64.zip'
$binaries = Join-Path $script:MasarPortableRoot 'binaries'
$nativeRoot = Get-MasarPortableNativeRoot
$bin = Join-Path $nativeRoot 'binaries\pgsql\bin'
$data = Join-Path $nativeRoot 'data'
$marker = Join-Path $script:MasarPortableRoot 'masar-portable.json'
$init = Join-Path $bin 'initdb.exe'
if (-not (Test-Path -LiteralPath $init)) {
    if (-not (Test-Path -LiteralPath $archive)) { throw 'Download the official EDB Windows x64 PostgreSQL 18.6 binaries archive as described in README.' }
    if (Test-Path -LiteralPath $binaries) { throw 'An incomplete extraction exists; inspect it before retrying. No files were overwritten.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $prefix = [IO.Path]::GetFullPath($binaries).TrimEnd('\') + '\'
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        foreach ($entry in $zip.Entries) {
            $destination = [IO.Path]::GetFullPath((Join-Path $binaries $entry.FullName))
            if (-not $destination.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'The PostgreSQL archive contains an out-of-tree entry.' }
        }
    } finally { $zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $binaries)
}
if (-not (Test-Path -LiteralPath $init)) { throw 'Unexpected PostgreSQL archive layout.' }
$version = & $init --version
if ($LASTEXITCODE -ne 0 -or ($version | Out-String) -notmatch '\b18\.6\b') { throw 'Expected PostgreSQL 18.6 Windows binaries.' }
$ownerPath = Join-Path $script:MasarPortableRoot 'database-owner.credential.xml'
$appPath = Join-Path $script:MasarPortableRoot 'database-app.credential.xml'
if ((Test-Path -LiteralPath $data) -and (-not (Test-Path -LiteralPath $marker) -or -not (Test-Path -LiteralPath $ownerPath) -or -not (Test-Path -LiteralPath $appPath))) {
    throw 'An existing portable data directory has no matching marker or encrypted credentials. It will not be reinitialized.'
}
$owner = New-MasarCredential 'masar_bootstrap' $ownerPath
$app = New-MasarCredential 'masar_app' $appPath
if (-not (Test-Path -LiteralPath $marker)) {
    # A Windows named pipe provides the first line read by initdb --pwfile without a disk file.
    # --pwprompt can open CONIN$ even when standard input is redirected.
    $pipeName = 'MasarInit-' + [Guid]::NewGuid().ToString('N')
    $pipePath = '\\.\pipe\' + $pipeName
    $pipeOptions = [IO.Pipes.PipeOptions]::Asynchronous -bor [IO.Pipes.PipeOptions]::CurrentUserOnly
    $pipe = [IO.Pipes.NamedPipeServerStream]::new($pipeName, [IO.Pipes.PipeDirection]::Out, 1, [IO.Pipes.PipeTransmissionMode]::Byte, $pipeOptions)
    $psi = [Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $init
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    foreach($arg in @('-D',$data,'-U','masar_bootstrap','--encoding=UTF8','--locale=C','--auth=scram-sha-256',"--pwfile=$pipePath")) { $psi.ArgumentList.Add($arg) }
    $process = [Diagnostics.Process]::Start($psi)
    $outTask = $process.StandardOutput.ReadToEndAsync()
    $errTask = $process.StandardError.ReadToEndAsync()
    $initialPassword = ConvertFrom-MasarSecure $owner.Password
    $pipeWait = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(20))
    try {
        $pipe.WaitForConnectionAsync($pipeWait.Token).GetAwaiter().GetResult()
        $writer = [IO.StreamWriter]::new($pipe,[Text.UTF8Encoding]::new($false))
        try { $writer.WriteLine($initialPassword); $writer.Flush() } finally { $writer.Dispose() }
        if (-not $process.WaitForExit(45000)) { throw 'Portable initdb timed out.' }
        if ($process.ExitCode -ne 0) {
            $diagnostic = ($errTask.GetAwaiter().GetResult()).Replace($initialPassword, '[redacted]')
            throw "Portable initdb failed: $diagnostic"
        }
        $null = $outTask.GetAwaiter().GetResult()
    } catch {
        if (-not $process.HasExited) { $process.Kill($true); $process.WaitForExit(5000) | Out-Null }
        $detail = if ($errTask.IsCompletedSuccessfully) { $errTask.Result.Replace($initialPassword,'[redacted]').Trim() } else { '' }
        if ($detail) { throw "Portable initdb failed: $detail" }
        throw
    } finally { $initialPassword = $null; $pipeWait.Dispose(); $pipe.Dispose(); $process.Dispose() }
    [PSCustomObject]@{project='masar-phase2-portable';port=$script:MasarPortablePort;version='18.6';archiveSha256=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash} |
        ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding utf8
}
& (Join-Path $PSScriptRoot 'Start-PortableDatabase.ps1')
$env:MASAR_APP_PASSWORD = ConvertFrom-MasarSecure $app.Password
try {
    $sql = @'
\getenv app_password MASAR_APP_PASSWORD
SELECT 'CREATE ROLE masar_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='masar_app') \gexec
ALTER ROLE masar_app PASSWORD :'app_password';
SELECT 'CREATE DATABASE masar_phase2 OWNER masar_bootstrap'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='masar_phase2') \gexec
SELECT 'CREATE DATABASE masar_phase2_tests OWNER masar_bootstrap'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='masar_phase2_tests') \gexec
REVOKE CONNECT ON DATABASE masar_phase2, masar_phase2_tests FROM PUBLIC;
GRANT CONNECT ON DATABASE masar_phase2, masar_phase2_tests TO masar_app;
'@
    Invoke-MasarPortableSql $sql
} finally { Remove-Item Env:MASAR_APP_PASSWORD -ErrorAction SilentlyContinue; $owner=$null; $app=$null }
Write-Host 'Portable Masar PostgreSQL ready on 127.0.0.1:55436. Docker data was not used or modified.'

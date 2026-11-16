#Requires -Version 7.0
[CmdletBinding()]
param()

$workspace = Split-Path -Parent $PSScriptRoot
. (Join-Path $workspace 'phase2\scripts\Local-Environment.ps1')
$sourceDatabase = 'masar_phase6_commercial'
$scratchDatabase = 'masar_phase6_restore_check'
$nativeRoot = Get-MasarPortableNativeRoot
$bin = Join-Path $nativeRoot 'binaries\pgsql\bin'
$marker = Get-Content -LiteralPath (Join-Path $nativeRoot 'masar-portable.json') -Raw | ConvertFrom-Json
if ($marker.project -ne 'masar-phase2-portable' -or $marker.port -ne 55436 -or $script:MasarPortablePort -ne 55436) {
    throw 'The dedicated Masar portable cluster is required on 127.0.0.1:55436.'
}

$credential = Import-Clixml -LiteralPath (Join-Path $nativeRoot 'database-owner.credential.xml')
if ($credential.UserName -ne 'masar_bootstrap') { throw 'Unexpected portable cluster owner credential.' }
$ownerPassword = ConvertFrom-MasarSecure $credential.Password
$credential = $null

function Start-RecoveryClient([string]$Tool, [string[]]$Options, [switch]$LocalOnly) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = Join-Path $bin "$Tool.exe"
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
    $info.StandardOutputEncoding = [Text.Encoding]::UTF8
    $info.Environment['LC_ALL'] = 'C'
    foreach ($name in @($info.Environment.Keys | Where-Object { $_ -like 'PG*' })) {
        [void]$info.Environment.Remove($name)
    }
    if (-not $LocalOnly) {
        $info.Environment['PGPASSWORD'] = $ownerPassword
        $info.Environment['PGCONNECT_TIMEOUT'] = '5'
        $info.Environment['PGCLIENTENCODING'] = 'UTF8'
        foreach ($arg in @('--host=127.0.0.1','--port=55436','--username=masar_bootstrap','--no-password')) {
            $info.ArgumentList.Add($arg)
        }
    }
    foreach ($arg in $Options) { $info.ArgumentList.Add($arg) }
    try { return [Diagnostics.Process]::Start($info) }
    finally { [void]$info.Environment.Remove('PGPASSWORD') }
}

function Close-RecoveryClient([Diagnostics.Process]$Process) {
    try {
        if (-not $Process.HasExited) { $Process.Kill($true); [void]$Process.WaitForExit(5000) }
    } finally { $Process.Dispose() }
}

function Invoke-RecoveryClient([string]$Tool, [string[]]$Options, [string]$Step, [string]$Sql, [switch]$LocalOnly) {
    $process = Start-RecoveryClient -Tool $Tool -Options $Options -LocalOnly:$LocalOnly
    try {
        $output = $process.StandardOutput.ReadToEndAsync()
        $diagnostics = $process.StandardError.BaseStream.CopyToAsync([IO.Stream]::Null)
        if ($Sql) { $process.StandardInput.WriteLine($Sql) }
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(300000)) { throw "$Step timed out." }
        if ($process.ExitCode -ne 0) { throw "$Step failed with exit code $($process.ExitCode)." }
        $null = $diagnostics.GetAwaiter().GetResult()
        return $output.GetAwaiter().GetResult().Trim()
    } finally { Close-RecoveryClient $process }
}

$psqlOptions = @('--no-psqlrc','--quiet','--no-align','--tuples-only','--set=ON_ERROR_STOP=1')
function Invoke-RecoverySql([string]$Database, [string]$Step, [string]$Sql) {
    Invoke-RecoveryClient -Tool psql -Options ($psqlOptions + "--dbname=$Database") -Step $Step -Sql $Sql
}

$fingerprintSql = @'
SET LOCAL search_path TO pg_catalog, public;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL DateStyle TO 'ISO, YMD';
SET LOCAL IntervalStyle TO 'postgres';
SET LOCAL extra_float_digits TO 3;
SET LOCAL bytea_output TO 'hex';
SET LOCAL row_security TO off;
SELECT 'ready|' || (
    to_regclass('public.commercial_access') IS NOT NULL
    AND to_regclass('public.audit') IS NOT NULL
    AND to_regclass('public.masar_schema_migrations') IS NOT NULL
    AND NOT has_table_privilege('masar_app', 'public.masar_schema_migrations', 'SELECT')
    AND EXISTS (SELECT FROM public.settings s JOIN public.content_releases r ON r.release_id = s.value
                WHERE s.key = 'active_release_id' AND r.status = 'published')
)::text;

WITH definitions(item) AS (
    SELECT jsonb_build_array('column', table_name, ordinal_position, column_name, udt_schema, udt_name,
                             is_nullable, column_default, is_identity, identity_generation)
    FROM information_schema.columns WHERE table_schema = 'public'
    UNION ALL
    SELECT jsonb_build_array('constraint', c.relname, k.conname, pg_get_constraintdef(k.oid), k.convalidated)
    FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
    WHERE c.relnamespace = 'public'::regnamespace
    UNION ALL
    SELECT jsonb_build_array('index', indexdef) FROM pg_indexes WHERE schemaname = 'public'
    UNION ALL
    SELECT jsonb_build_array('sequence', sequencename, data_type, start_value, min_value, max_value,
                             increment_by, cycle, cache_size)
    FROM pg_sequences WHERE schemaname = 'public'
    UNION ALL
    SELECT jsonb_build_array('trigger', c.relname, pg_get_triggerdef(t.oid), t.tgenabled)
    FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
    WHERE c.relnamespace = 'public'::regnamespace AND NOT t.tgisinternal
    UNION ALL
    SELECT jsonb_build_array('function', pg_get_functiondef(p.oid)) FROM pg_proc p
    WHERE p.pronamespace = 'public'::regnamespace AND p.prokind IN ('f', 'p')
    UNION ALL
    SELECT jsonb_build_array('table', c.relname, pg_get_userbyid(c.relowner), c.relrowsecurity, c.relforcerowsecurity,
                             has_table_privilege('masar_app', c.oid, 'SELECT'),
                             has_table_privilege('masar_app', c.oid, 'INSERT'),
                             has_table_privilege('masar_app', c.oid, 'UPDATE'),
                             has_table_privilege('masar_app', c.oid, 'DELETE'))
    FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
)
SELECT 'schema|' || encode(sha256(convert_to(string_agg(item::text, '' ORDER BY item::text COLLATE "C"), 'UTF8')), 'hex')
FROM definitions;

SELECT format($fingerprint$
    SELECT %L || '|' || count(*) || '|' ||
        encode(sha256(convert_to(COALESCE(string_agg(row_hash, '' ORDER BY row_hash COLLATE "C"), ''), 'UTF8')), 'hex')
    FROM (SELECT encode(sha256(convert_to(to_jsonb(row_data)::text, 'UTF8')), 'hex') AS row_hash
          FROM public.%I AS row_data) AS row_hashes
$fingerprint$, tablename, tablename)
FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename COLLATE "C" \gexec
'@

$holder = $null
$scratchOid = ''
$archivePath = $null
$archiveCreated = $false
$checksum = $null
$failure = $null
try {
    $control = Invoke-RecoveryClient -Tool pg_controldata -Options @((Join-Path $nativeRoot 'data')) -Step 'Local cluster identity' -LocalOnly
    if ($control -notmatch '(?m)^Database system identifier:\s*([0-9]+)\s*$') { throw 'The local cluster identity could not be read.' }
    $controlId = $Matches[1]
    $serverId = Invoke-RecoverySql -Database postgres -Step 'TCP cluster identity' -Sql 'SELECT system_identifier FROM pg_control_system();'
    if ($controlId -cne $serverId) { throw 'The TCP endpoint does not belong to the expected portable cluster.' }
    $existingScratch = Invoke-RecoverySql -Database postgres -Step 'Scratch availability' -Sql "SELECT 1 FROM pg_database WHERE datname = '$scratchDatabase';"
    if ($existingScratch) { throw 'The restore-check database already exists. Leave it in place and review it before retrying.' }

    $holder = Start-RecoveryClient -Tool psql -Options ($psqlOptions + "--dbname=$sourceDatabase")
    $holderDiagnostics = $holder.StandardError.BaseStream.CopyToAsync([IO.Stream]::Null)
    $holder.StandardInput.WriteLine('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();')
    $holder.StandardInput.Flush()
    $snapshotTask = $holder.StandardOutput.ReadLineAsync()
    if (-not $snapshotTask.Wait(15000) -or $snapshotTask.Result -notmatch '^[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+$') {
        throw 'The candidate snapshot could not be opened.'
    }
    $snapshot = $snapshotTask.Result
    $sourceFingerprint = Invoke-RecoverySql -Database $sourceDatabase -Step 'Candidate schema and data check' -Sql @"
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET TRANSACTION SNAPSHOT '$snapshot';
$fingerprintSql
COMMIT;
"@
    if ($sourceFingerprint -notmatch '(?m)^ready\|true\r?$' -or $sourceFingerprint -notmatch '(?m)^commercial_access\|\d+\|[a-f0-9]{64}\r?$') {
        throw 'The commercial schema or published active release is missing, or migration privileges are incorrect.'
    }

    $runName = '{0}-{1}' -f [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'), [Guid]::NewGuid().ToString('N')
    $backupRoot = [IO.Directory]::CreateDirectory((Join-Path $script:MasarPortableRoot 'phase6-backups'))
    if ($backupRoot.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'The backup directory must be a local directory.' }
    $runDirectory = Join-Path $backupRoot.FullName $runName
    New-Item -ItemType Directory -Path $runDirectory | Out-Null
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    try {
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $acl.SetAccessRuleProtection($true, $false)
        $acl.SetOwner($identity.User)
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity.User, 'FullControl',
            'ContainerInherit, ObjectInherit', 'None', 'Allow'))
        Set-Acl -LiteralPath $runDirectory -AclObject $acl
    } finally { $identity.Dispose() }
    $archivePath = Join-Path $runDirectory 'masar_phase6_commercial.dump'
    $nativeArchive = Join-Path (Join-Path $nativeRoot "phase6-backups\$runName") 'masar_phase6_commercial.dump'
    $null = Invoke-RecoveryClient -Tool pg_dump -Options @("--dbname=$sourceDatabase", '--format=custom', '--compress=gzip:6',
        "--snapshot=$snapshot", "--file=$nativeArchive.partial") -Step 'Compressed snapshot backup'
    [IO.File]::Move("$archivePath.partial", $archivePath)
    $archiveCreated = $true
    $holder.StandardInput.WriteLine('COMMIT;')
    $holder.StandardInput.Close()
    if (-not $holder.WaitForExit(15000) -or $holder.ExitCode -ne 0) { throw 'The candidate snapshot could not be closed.' }
    $null = $holderDiagnostics.GetAwaiter().GetResult()
    Close-RecoveryClient $holder
    $holder = $null

    $scratchOwnership = "datname = '$scratchDatabase' AND pg_get_userbyid(datdba) = 'masar_bootstrap' AND shobj_description(oid, 'pg_database') = '$runName'"
    $scratchOid = Invoke-RecoverySql -Database postgres -Step 'Create and identify fresh restore-check database' -Sql @"
CREATE DATABASE $scratchDatabase OWNER masar_bootstrap TEMPLATE template0 ALLOW_CONNECTIONS false;
COMMENT ON DATABASE $scratchDatabase IS '$runName';
SELECT oid FROM pg_database WHERE $scratchOwnership;
"@
    if ($scratchOid -notmatch '^[0-9]+$') { throw 'The new restore-check database identity could not be verified.' }
    $null = Invoke-RecoverySql -Database postgres -Step 'Enable isolated scratch connections' -Sql @"
BEGIN;
REVOKE CONNECT ON DATABASE $scratchDatabase FROM PUBLIC;
ALTER DATABASE $scratchDatabase ALLOW_CONNECTIONS true;
COMMIT;
"@
    $null = Invoke-RecoveryClient -Tool pg_restore -Options @("--dbname=$scratchDatabase", '--exit-on-error', '--single-transaction', $nativeArchive) -Step 'Isolated archive restore'
    $restoredFingerprint = Invoke-RecoverySql -Database $scratchDatabase -Step 'Restored schema and data check' -Sql @"
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
$fingerprintSql
COMMIT;
"@
    if ($sourceFingerprint -cne $restoredFingerprint) { throw 'Restored schema, privileges, row counts or content differ from the source snapshot.' }
    $sequenceReady = Invoke-RecoverySql -Database $scratchDatabase -Step 'Restored audit identity check' -Sql @'
SELECT format($check$
    SELECT COALESCE((SELECT max(id) FROM public.audit), 0) < last_value + is_called::int FROM %s
$check$, pg_get_serial_sequence('public.audit', 'id')) \gexec
'@
    if ($sequenceReady -cne 't') { throw 'The restored audit sequence cannot safely issue the next identity.' }
    $checksum = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
} catch {
    $failure = $_
} finally {
    try {
        if ($holder) { Close-RecoveryClient $holder }
        if ($scratchOid -match '^[0-9]+$') {
            $remaining = Invoke-RecoverySql -Database postgres -Step 'Remove this run''s scratch database' -Sql @"
SELECT format('DROP DATABASE %I', datname) FROM pg_database WHERE oid = $scratchOid AND $scratchOwnership \gexec
SELECT 1 FROM pg_database WHERE datname = '$scratchDatabase';
"@
            if ($remaining) { throw 'The restore-check database identity changed. Scratch cleanup was halted.' }
        }
    } catch {
        if ($failure) { Write-Warning "Scratch cleanup also failed: $($_.Exception.Message)" }
        else { $failure = $_ }
    } finally {
        $ownerPassword = $null
    }
}
if ($failure) {
    if ($archiveCreated) { Write-Warning "A compressed archive was retained after the failed drill at $archivePath" }
    throw $failure
}

$checkedTableCount = @($restoredFingerprint -split '\r?\n' | Where-Object { $_ -match '^[^|]+\|[0-9]+\|[a-f0-9]{64}$' }).Count
Write-Host "PASS: commercial backup restored; schema and $checkedTableCount table fingerprints matched, including commercial access and audit."
Write-Host "Archive: $archivePath"
Write-Host "SHA-256: $checksum"

[CmdletBinding()]
param([ValidateSet('Docker','Portable')][string]$Engine='Docker')
. (Join-Path $PSScriptRoot 'Local-Environment.ps1')
if ($Engine -eq 'Docker') { Assert-MasarContainer }
New-Item -ItemType Directory -Path (Join-Path $script:MasarRoot 'test-results') -Force | Out-Null
$credential = $null
try {
    $sql = @'
SELECT json_build_object(
    'database',current_database(),
    'user',current_user,
    'serverVersion',current_setting('server_version'),
    'isSuperuser',(SELECT rolsuper FROM pg_roles WHERE rolname=current_user),
    'canCreateDatabase',(SELECT rolcreatedb FROM pg_roles WHERE rolname=current_user),
    'canCreateRole',(SELECT rolcreaterole FROM pg_roles WHERE rolname=current_user),
    'canCreatePublicTable',has_schema_privilege('public','CREATE'),
    'migrationLedgerWritable',COALESCE((SELECT bool_or(has_table_privilege(current_user,format('%I.%I',schemaname,tablename),'INSERT,UPDATE,DELETE'))
       FROM pg_tables WHERE schemaname='public' AND (tablename LIKE '%migration%' OR tablename LIKE '%schema_version%')),false),
    'usersPersisted',(SELECT count(*) FROM public.users),
    'passwordHashesHaveIdentityFormat',(SELECT COALESCE(bool_and(password_hash LIKE 'AQAAAA%' AND char_length(password_hash)>80),true) FROM public.users),
    'plansPersisted',(SELECT count(*) FROM public.learning_plans),
    'attemptsPersisted',(SELECT count(*) FROM public.attempts),
    'auditEvents',(SELECT count(*) FROM public.audit)
);
'@
    if ($Engine -eq 'Portable') {
        $result = Invoke-MasarPortableSql -Sql $sql -Database 'masar_phase2_tests' -Role App -TupleOnly
    } else {
        $credential = Import-Clixml -LiteralPath (Join-Path $script:MasarPrivate 'database-app.credential.xml')
        $env:PGPASSWORD = ConvertFrom-MasarSecure $credential.Password
        $result = $sql | & docker exec -i -e PGPASSWORD $script:MasarContainer psql --no-psqlrc -qAt -h 127.0.0.1 -p 5432 -U masar_app -d masar_phase2_tests --set=ON_ERROR_STOP=1
        if ($LASTEXITCODE -ne 0) { throw 'The application-role PostgreSQL probe failed.' }
    }
    $record = ($result | Out-String).Trim() | ConvertFrom-Json
    if ($record.isSuperuser -or $record.canCreateDatabase -or $record.canCreateRole -or $record.canCreatePublicTable -or $record.migrationLedgerWritable -or -not $record.passwordHashesHaveIdentityFormat) {
        throw 'Unexpected application privileges or persisted credential format.'
    }
    $record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $script:MasarRoot 'test-results\database-probe.json') -Encoding utf8
    $record | ConvertTo-Json -Depth 4
} finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue; $credential = $null }

[CmdletBinding()]
param()

. (Join-Path (Split-Path -Parent $PSScriptRoot) 'phase2\scripts\Local-Environment.ps1')
$origin = 'http://127.0.0.1:5186'
$health = Invoke-RestMethod -Uri "$origin/api/v1/health" -TimeoutSec 6
$catalog = Invoke-RestMethod -Uri "$origin/api/v1/catalog" -TimeoutSec 6
if ($health.status -ne 'ok' -or $health.database -ne 'available' -or
    $catalog.activeReleaseId -ne 'phase4-ar-v1' -or $catalog.accessRequired -ne $true) {
    throw 'Commercial candidate failed readiness.'
}

$sql = @'
SELECT json_build_object(
    'queued', count(*) FILTER (WHERE status='queued' AND expires_at > now()),
    'running', count(*) FILTER (WHERE status='running' AND expires_at > now()),
    'executionUnitsLast24h', COALESCE(sum(GREATEST(1,jsonb_array_length(test_cases))),0),
    'infrastructureErrorsLast24h', count(*) FILTER (WHERE status='infrastructure_error'),
    'timeLimitsLast24h', count(*) FILTER (WHERE status='timed_out')
) FROM public.code_lab_runs WHERE created_at > now() - interval '24 hours';
'@
$lab = Invoke-MasarPortableSql -Database masar_phase6_commercial -Role App -TupleOnly -Sql $sql | ConvertFrom-Json
[pscustomobject]@{ status = 'ready'; database = $health.database; activeRelease = $catalog.activeReleaseId; codeLab = $lab } |
    ConvertTo-Json -Depth 3

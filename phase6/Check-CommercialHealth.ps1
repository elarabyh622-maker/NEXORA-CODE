[CmdletBinding()]
param(
    [ValidateSet('phase4-ar-v1','phase7-ar-v1','phase8-ar-v1','phase9-ar-v1','phase10-ar-v1','phase11-ar-v1','phase12-ar-v1','phase13-ar-v1')][string]$ExpectedRelease,
    [string]$BaseUrl,
    [switch]$Test
)

. (Join-Path (Split-Path -Parent $PSScriptRoot) 'phase2\scripts\Local-Environment.ps1')
$database = if ($Test) { 'masar_phase6_tests' } else { 'masar_phase6_commercial' }
if (-not $ExpectedRelease) { $ExpectedRelease = if ($Test) { 'phase7-ar-v1' } else { 'phase13-ar-v1' } }
if (-not $BaseUrl) {
    $BaseUrl = if ($Test) { 'http://127.0.0.1:5196' } else { 'https://desktop-phkhegp.tail3372f6.ts.net:10000/nexora-commercial' }
}
$origin = $BaseUrl.TrimEnd('/')
$health = Invoke-RestMethod -Uri "$origin/api/v1/health" -TimeoutSec 6
$catalog = Invoke-RestMethod -Uri "$origin/api/v1/catalog" -TimeoutSec 6
if ($health.status -ne 'ok' -or $health.database -ne 'available' -or
    $catalog.activeReleaseId -ne $ExpectedRelease -or $catalog.accessRequired -ne $true) {
    throw 'Commercial candidate failed readiness.'
}
$requiredGoals = switch ($ExpectedRelease) {
    'phase7-ar-v1' { 'data-analysis' }
    'phase8-ar-v1' { 'data-analysis', 'sql', 'web-data', 'git-workshop' }
    'phase9-ar-v1' { 'data-analysis', 'sql', 'web-data', 'git-workshop', 'python-projects', 'sql-write', 'backend', 'fullstack' }
    'phase10-ar-v1' { 'data-analysis', 'sql', 'web-data', 'git-workshop', 'python-projects', 'sql-write', 'backend', 'fullstack', 'javascript-projects', 'react', 'react-fullstack', 'typescript-react' }
    'phase11-ar-v1' { 'data-analysis', 'sql', 'web-data', 'git-workshop', 'python-projects', 'sql-write', 'backend', 'fullstack', 'javascript-projects', 'react', 'react-fullstack', 'typescript-react', 'algorithms', 'oop', 'problem-solving' }
    'phase12-ar-v1' { 'data-analysis', 'sql', 'web-data', 'git-workshop', 'python-projects', 'sql-write', 'backend', 'fullstack', 'javascript-projects', 'react', 'react-fullstack', 'typescript-react', 'algorithms', 'oop', 'problem-solving', 'applied-data' }
    'phase13-ar-v1' { 'data-analysis', 'sql', 'web-data', 'git-workshop', 'python-projects', 'sql-write', 'backend', 'fullstack', 'javascript-projects', 'react', 'react-fullstack', 'typescript-react', 'algorithms', 'oop', 'problem-solving', 'applied-data', 'machine-learning' }
}
foreach ($id in $requiredGoals) {
    if ($catalog.goals.id -notcontains $id) { throw "The active commercial catalog is missing the reviewed track $id." }
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
$lab = Invoke-MasarPortableSql -Database $database -Role App -TupleOnly -Sql $sql | ConvertFrom-Json
[pscustomobject]@{ status = 'ready'; database = $health.database; activeRelease = $catalog.activeReleaseId; codeLab = $lab } |
    ConvertTo-Json -Depth 3

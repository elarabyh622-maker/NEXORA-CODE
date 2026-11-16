[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$vmDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\.local\runner-vm')).Path
$stateFile = Join-Path $vmDirectory 'tunnel.json'
$ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
$transport = @(
    '-F', 'NUL', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20',
    '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=known_hosts',
    '-o', 'GlobalKnownHostsFile=NUL', '-o', 'IdentitiesOnly=yes',
    '-p', '2227', '-i', 'vm-operator'
)
$remote = 'nexora-operator@127.0.0.1'
$port = 18787
$origin = "http://127.0.0.1:$port"

function Get-NexoraTunnelListener {
    Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $port -State Listen -ErrorAction SilentlyContinue
}

function Test-NexoraTunnelOwner($Listener, $State) {
    if ($null -eq $Listener -or $null -eq $State -or $Listener.OwningProcess -ne $State.pid) { return $false }
    $owner = Get-Process -Id $State.pid -ErrorAction SilentlyContinue
    return $null -ne $owner -and $owner.Path -eq $ssh -and
        $owner.StartTime.ToUniversalTime().Ticks.ToString() -eq [string]$State.started
}

Push-Location -LiteralPath $vmDirectory
try {
    $readToken = 'sudo -n sed -n "s/^NEXORA_RUNNER_BEARER_TOKEN=//p" /etc/nexora-code-runner/runner.env'
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $tokenLines = @(& $ssh @transport $remote $readToken)
        if ($LASTEXITCODE -eq 0 -or $attempt -eq 3) { break }
        Start-Sleep -Seconds 1
    }
    if ($LASTEXITCODE -ne 0 -or $tokenLines.Count -ne 1 -or $tokenLines[0] -cnotmatch '^[A-Za-z0-9_-]{32,128}$') {
        throw 'The pinned VM did not provide a valid runner credential. Check guest provisioning.'
    }
    $token = $tokenLines[0]
    $listener = Get-NexoraTunnelListener
    if ($null -ne $listener) {
        $state = if (Test-Path -LiteralPath $stateFile -PathType Leaf) {
            Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        } else { $null }
        if (-not (Test-NexoraTunnelOwner $listener $state)) { throw "Port $port is already used by another process." }
    } else {
        $tunnelArgs = $transport + @(
            '-N', '-T', '-o', 'ExitOnForwardFailure=yes',
            '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=3',
            '-L', ('127.0.0.1:{0}:127.0.0.1:8787' -f $port), $remote
        )
        $startOptions = @{
            FilePath = $ssh
            ArgumentList = $tunnelArgs
            WorkingDirectory = $vmDirectory
            WindowStyle = 'Hidden'
            PassThru = $true
            RedirectStandardError = Join-Path $vmDirectory 'tunnel.log'
        }
        $tunnel = Start-Process @startOptions
        $state = @{
            pid = $tunnel.Id
            started = $tunnel.StartTime.ToUniversalTime().Ticks.ToString()
        }
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if ($tunnel.HasExited) { throw 'The SSH tunnel did not start. Check tunnel.log.' }
            if (Test-NexoraTunnelOwner (Get-NexoraTunnelListener) $state) { break }
            Start-Sleep -Milliseconds 300
        }
        if (-not (Test-NexoraTunnelOwner (Get-NexoraTunnelListener) $state)) {
            if (-not $tunnel.HasExited) { Stop-Process -InputObject $tunnel }
            throw 'The SSH tunnel did not open its project loopback port.'
        }
        $state | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(75)
    $ready = $false
    while (-not $ready -and [DateTime]::UtcNow -lt $deadline) {
        try {
            $null = Invoke-WebRequest -Uri "$origin/v1/execute" -Method Post -UseBasicParsing -TimeoutSec 8 -MaximumRedirection 0
        } catch {
            $response = $_.Exception.PSObject.Properties['Response']
            $ready = $null -ne $response -and $null -ne $response.Value -and [int]$response.Value.StatusCode -eq 401
        }
        if (-not $ready) { Start-Sleep -Milliseconds 800 }
    }
    if (-not $ready) { throw 'The runner did not finish its startup checks.' }

    $payload = @{ language = 'python'; code = "print('nexora-runner-ready')"; stdin = '' } | ConvertTo-Json -Compress
    try {
        $request = @{
            Uri = "$origin/v1/execute"
            Method = 'Post'
            ContentType = 'application/json'
            Headers = @{ Authorization = "Bearer $token" }
            Body = $payload
            TimeoutSec = 25
            MaximumRedirection = 0
        }
        $probe = Invoke-RestMethod @request
    } catch {
        throw 'The runner did not respond through the authenticated SSH tunnel.'
    }
    if ($probe.status -ne 'completed' -or $probe.stdout.Trim() -ne 'nexora-runner-ready') {
        $knownStatus = $probe.status -in @('completed', 'code_error', 'timed_out', 'output_limit', 'infrastructure_error')
        $reason = if ($knownStatus) { $probe.status } else { 'unknown' }
        throw "The runner did not pass its execution readiness probe (status: $reason)."
    }
    $env:MASAR_CODE_LAB_ENABLED = 'true'
    $env:MASAR_CODE_LAB_RUNNER_URL = $origin
    $env:MASAR_CODE_LAB_RUNNER_TOKEN = $token
    Write-Host "Runner ready through the project SSH tunnel ($origin)."
} finally {
    $token = $null
    $tokenLines = $null
    Pop-Location
}

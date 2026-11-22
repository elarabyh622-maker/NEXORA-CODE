param(
    [Parameter(Mandatory)]
    [string] $Executable,
    [switch] $Starter
)

$ErrorActionPreference = 'Stop'
$program = (Resolve-Path -LiteralPath $Executable).ProviderPath
$testFolder = Join-Path ([IO.Path]::GetTempPath()) ("cpp-expenses-" + [Guid]::NewGuid().ToString('N'))
$dataName = 'expenses.tsv'
$dataPath = Join-Path $testFolder $dataName

function Assert-Command {
    param(
        [string[]] $Command,
        [string] $Output = '',
        [string] $ErrorMessage = ''
    )

    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $program
    $info.Arguments = "$dataName $($Command -join ' ')"
    $info.WorkingDirectory = $testFolder
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($info)
    try {
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (!$process.WaitForExit(10000)) {
            $process.Kill()
            throw "Command timed out: $Command"
        }
        $actual = $stdout.GetAwaiter().GetResult().Replace("`r`n", "`n")
        $diagnostic = $stderr.GetAwaiter().GetResult()
        if ($actual -cne $Output) {
            throw "Unexpected output for $($Command -join ' '): $actual"
        }
        if ($ErrorMessage) {
            if ($process.ExitCode -eq 0 -or !$diagnostic.Contains($ErrorMessage)) {
                throw "Expected an error containing '$ErrorMessage': $diagnostic"
            }
        } elseif ($process.ExitCode -ne 0 -or $diagnostic) {
            throw "Command failed: $Command. $diagnostic"
        }
    } finally {
        $process.Dispose()
    }
}

[void] [IO.Directory]::CreateDirectory($testFolder)
try {
    Assert-Command @('list')
    if ([IO.File]::Exists($dataPath)) { throw 'List created a data file.' }
    if (!$Starter) { Assert-Command @('summary') -Output "total`t0`n" }
    Assert-Command @('add', 'transport', '1200')
    Assert-Command @('add', 'food', '3250')
    Assert-Command @('add', 'food', '750')
    $rows = "transport`t1200`nfood`t3250`nfood`t750`n"
    Assert-Command @('list') -Output $rows
    Assert-Command @('add', 'food', '1.25') -ErrorMessage 'Invalid category or amount'
    if ($Starter) {
        Assert-Command @('summary') -ErrorMessage 'Summary is incomplete'
    } else {
        Assert-Command @('summary') -Output "food`t4000`ntransport`t1200`ntotal`t5200`n"
    }
    if ([IO.File]::ReadAllText($dataPath) -cne $rows) { throw 'The data file changed.' }
    $corrupt = $rows + "food,100`n"
    [IO.File]::WriteAllText($dataPath, $corrupt)
    Assert-Command @('add', 'food', '100') -ErrorMessage 'line 4'
    if ([IO.File]::ReadAllText($dataPath) -cne $corrupt) { throw 'The invalid file changed.' }
    Write-Output 'PASSED: expense tracker checks'
} finally {
    [IO.File]::Delete($dataPath)
    if ([IO.Directory]::GetFileSystemEntries($testFolder).Length -eq 0) {
        [IO.Directory]::Delete($testFolder)
    }
}

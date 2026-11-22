Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)
$script:passed = 0
$script:failed = 0

function Assert-That {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Assert-Report {
    param([object[]]$Rows)
    $keys = @($Rows | ForEach-Object { "$($_.Sku)=$($_.TotalQuantity)" }) -join ','
    Assert-That ($keys -ceq 'P-101=8,P-102=5,P-103=7') 'Report rows, totals, or order differed from the fixture.'
}

function Invoke-Case {
    param([string]$Name, [scriptblock]$Check)
    $scratch = Join-Path $tempBase ('nexora-report-test-' + [Guid]::NewGuid().ToString('N'))
    try {
        $dataDirectory = Join-Path $scratch 'data'
        [void][IO.Directory]::CreateDirectory($dataDirectory)
        $reportScript = Join-Path $scratch 'New-InventoryReport.ps1'
        $sourcePath = Join-Path $dataDirectory 'orders.csv'
        $outputPath = Join-Path $scratch 'output/inventory-summary.csv'
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'New-InventoryReport.ps1') -Destination $reportScript
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'data/orders.csv') -Destination $sourcePath
        & $Check $reportScript $sourcePath $outputPath
        $script:passed++
        Write-Host "PASS $Name"
    } catch {
        $script:failed++
        Write-Host "FAIL $Name ($($_.Exception.Message))"
    } finally {
        if (Test-Path -LiteralPath $scratch) {
            $target = (Resolve-Path -LiteralPath $scratch).ProviderPath
            Assert-That ([IO.Path]::GetDirectoryName($target) -eq $tempBase) 'The fixture cleanup must stay under the temporary folder.'
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
}

Invoke-Case 'Preview does not write' {
    param($run, $source, $destination)
    Assert-Report @(& $run -Preview)
    $outputDirectory = Split-Path -Parent $destination
    Assert-That (-not (Test-Path -LiteralPath $outputDirectory)) 'Preview created an output directory.'

    [void][IO.Directory]::CreateDirectory($outputDirectory)
    Set-Content -LiteralPath $destination -Value 'existing report' -Encoding Ascii
    $before = Get-FileHash -LiteralPath $destination
    $beforeTime = (Get-Item -LiteralPath $destination).LastWriteTimeUtc
    Assert-Report @(& $run -Preview)
    Assert-That ((Get-FileHash -LiteralPath $destination).Hash -eq $before.Hash) 'Preview changed the report bytes.'
    Assert-That ((Get-Item -LiteralPath $destination).LastWriteTimeUtc -eq $beforeTime) 'Preview rewrote the report.'
    Assert-That (@(Get-ChildItem -LiteralPath $outputDirectory -Force).Count -eq 1) 'Preview created an extra file.'
}

Invoke-Case 'Writes sorted totals and reruns idempotently' {
    param($run, $source, $destination)
    $inputHash = (Get-FileHash -LiteralPath $source).Hash
    & $run | Out-Null
    $rows = @(Import-Csv -LiteralPath $destination -Encoding UTF8)
    Assert-That (($rows[0].PSObject.Properties.Name -join ',') -ceq 'Sku,TotalQuantity') 'Wrong CSV headers.'
    Assert-Report $rows
    $first = (Get-FileHash -LiteralPath $destination).Hash
    & $run | Out-Null
    Assert-That ((Get-FileHash -LiteralPath $destination).Hash -eq $first) 'Rerun wrote different bytes.'
    Assert-That ((Get-FileHash -LiteralPath $source).Hash -eq $inputHash) 'Source CSV changed.'
    Assert-That (@(Get-ChildItem -LiteralPath (Split-Path -Parent $destination) -Force).Count -eq 1) 'Unexpected output files.'
}

Invoke-Case 'Invalid quantity preserves prior report' {
    param($run, $source, $destination)
    & $run | Out-Null
    $first = (Get-FileHash -LiteralPath $destination).Hash
    Set-Content -LiteralPath $source -Value 'OrderId,Sku,Quantity', 'ORD-001,P-101,0' -Encoding Ascii

    $message = ''
    try { & $run | Out-Null } catch { $message = $_.Exception.Message }
    Assert-That ($message -like 'Quantity must be a positive integer*') 'Invalid quantity was not reported.'
    Assert-That ((Get-FileHash -LiteralPath $destination).Hash -eq $first) 'Invalid source overwrote the report.'
}

Invoke-Case 'Invalid header and duplicates block writes' {
    param($run, $source, $destination)
    Set-Content -LiteralPath $source -Value 'OrderId,Sku,Value', 'ORD-001,P-101,2' -Encoding Ascii
    $message = ''
    try { & $run | Out-Null } catch { $message = $_.Exception.Message }
    Assert-That ($message -like 'Expected at least one order*') 'Invalid header was not reported.'

    Set-Content -LiteralPath $source -Value 'OrderId,Sku,Quantity', 'ORD-001,P-101,2', 'ORD-001,P-102,5' -Encoding Ascii
    $message = ''
    try { & $run | Out-Null } catch { $message = $_.Exception.Message }
    Assert-That ($message -like 'Duplicate order ID*') 'Duplicate order was not reported.'
    Assert-That (-not (Test-Path -LiteralPath (Split-Path -Parent $destination))) 'Invalid source created an output directory.'
}

Write-Host "$passed/$($passed + $failed) passed."
if ($failed -gt 0) { throw "$failed test group(s) failed." }

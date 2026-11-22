[CmdletBinding()]
param([switch]$Preview)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$sourcePath = Join-Path $PSScriptRoot 'data/orders.csv'
$orders = @(Import-Csv -LiteralPath $sourcePath -Encoding UTF8)
if ($orders.Count -eq 0 -or ($orders[0].PSObject.Properties.Name -join ',') -cne 'OrderId,Sku,Quantity') {
    throw 'Expected at least one order and these CSV headers: OrderId,Sku,Quantity.'
}

$seenOrderIds = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
$totals = @{}
foreach ($order in $orders) {
    if ($order.OrderId -cnotmatch '^ORD-[0-9]{3}$' -or $order.Sku -cnotmatch '^P-[0-9]{3}$') {
        throw 'Expected an order ID such as ORD-001 and a SKU such as P-101.'
    }
    if (-not $seenOrderIds.Add($order.OrderId)) {
        throw "Duplicate order ID $($order.OrderId)."
    }

    $quantity = 0
    if (-not [int]::TryParse($order.Quantity, [Globalization.NumberStyles]::None,
            [Globalization.CultureInfo]::InvariantCulture, [ref]$quantity) -or $quantity -lt 1) {
        throw "Quantity must be a positive integer for order $($order.OrderId)."
    }

    $totals[$order.Sku] = [long]$totals[$order.Sku] + $quantity
}

$report = foreach ($sku in ($totals.Keys | Sort-Object)) {
    [pscustomobject]@{ Sku = $sku; TotalQuantity = $totals[$sku] }
}

if ($Preview) {
    $report
    return
}

$outputDirectory = Join-Path $PSScriptRoot 'output'
$outputPath = Join-Path $outputDirectory 'inventory-summary.csv'
[void][IO.Directory]::CreateDirectory($outputDirectory)

# Prepare a complete file in the same directory before replacing the report.
$temporaryPath = Join-Path $outputDirectory ('inventory-' + [Guid]::NewGuid().ToString('N') + '.tmp')
try {
    $lines = $report | ConvertTo-Csv -NoTypeInformation
    [IO.File]::WriteAllLines($temporaryPath, [string[]]$lines, [Text.UTF8Encoding]::new($false))
    if ([IO.File]::Exists($outputPath)) {
        [IO.File]::Replace($temporaryPath, $outputPath, [NullString]::Value)
    } else {
        [IO.File]::Move($temporaryPath, $outputPath)
    }
} finally {
    [IO.File]::Delete($temporaryPath)
}

Write-Output "Report written to $outputPath"

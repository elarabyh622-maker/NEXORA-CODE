$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host 'Node.js 22 أو أحدث مطلوب لتشغيل العينة المحلية.'
    exit 1
}
Write-Host 'افتح http://127.0.0.1:4173 في المتصفح. لإيقاف العينة اضغط Ctrl+C.'
node scripts/serve.mjs

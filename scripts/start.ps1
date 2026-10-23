param([ValidateSet('platform', 'import', 'query', 'worker', 'settlement-worker')][string]$Service = 'platform')
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw '先运行 uv sync --locked'
}
& '.venv\Scripts\python.exe' -m atguigu.cli $Service
exit $LASTEXITCODE

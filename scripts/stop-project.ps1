$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $projectRoot 'var\logs\project-processes.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { Write-Output '没有启动脚本登记的进程。'; exit 0 }
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($record in $manifest.processes) {
    $running = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)" -ErrorAction SilentlyContinue
    $process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    $recordedStart = if ($record.started -is [datetime]) { $record.started.ToUniversalTime() } else { [datetime]::Parse($record.started).ToUniversalTime() }
    if ($running -and $process -and $running.ExecutablePath -eq $manifest.python -and $running.CommandLine -like '*atguigu.cli*' -and [Math]::Abs(($process.StartTime.ToUniversalTime() - $recordedStart).TotalSeconds) -lt 2) {
        Stop-Process -Id $record.pid
        Write-Output "已停止 $($record.service) ($($record.pid))"
    }
}

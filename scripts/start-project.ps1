param([int]$Port = 8105, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath '.env')) { throw '请先根据 .env.example 配置 .env 和存储服务。' }
& uv sync --locked
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败' }
if (-not $SkipBuild) {
    $lockedBuilder = Join-Path $projectRoot 'frontend\node_modules\@esbuild\win32-x64\esbuild.exe'
    if (Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $lockedBuilder }) {
        throw '请先停止本项目的 Vite/preview 开发进程，再安装前端依赖；或使用已有构建并传入 -SkipBuild。'
    }
    & npm --prefix frontend ci
    if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
    & npm --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
}
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw '缺少前端构建，请去掉 -SkipBuild' }
& $python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败，请先检查存储服务' }
$logDir = Join-Path $projectRoot 'var\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$manifestPath = Join-Path $logDir 'project-processes.json'
if (Test-Path -LiteralPath $manifestPath) {
    $previous = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($record in $previous.processes) {
        $running = Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)" -ErrorAction SilentlyContinue
        if ($running -and $running.ExecutablePath -eq $python -and $running.CommandLine -like '*atguigu.cli*') {
            throw "已有项目进程 $($record.pid) 正在运行。请使用既有入口，或先运行 scripts/stop-project.ps1。"
        }
    }
}
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { throw "端口 $Port 已被占用，请使用现有服务或指定 -Port。" }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$processes = @()
foreach ($service in @('platform','worker','settlement-worker')) {
    $arguments = @('-m','atguigu.cli',$service)
    if ($service -eq 'platform') { $arguments += @('--port', "$Port") }
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir "$service-$stamp.out.log") -RedirectStandardError (Join-Path $logDir "$service-$stamp.err.log")
    $processes += @{service=$service;pid=$process.Id;started=$process.StartTime.ToUniversalTime().ToString('o')}
    @{port=$Port;python=$python;processes=$processes} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
}
Write-Output "项目已启动：http://127.0.0.1:$Port；API 文档：http://127.0.0.1:$Port/docs"
Write-Output '账号密码见 var/setup/stage2-accounts.json；首次环境使用 scripts/init_stage2.py 初始化。'

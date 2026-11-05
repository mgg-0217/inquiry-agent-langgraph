# Mailpit 启动/停止脚本
# 用法：
#   .\scripts\start-mailpit.ps1          启动
#   .\scripts\start-mailpit.ps1 -Stop    停止
#   .\scripts\start-mailpit.ps1 -Status  查看状态

param(
    [switch]$Stop,
    [switch]$Status
)

$ErrorActionPreference = "Stop"

$ExePath  = "D:\dshWorkspace\tools\mailpit\mailpit.exe"
$DataDir  = Join-Path $PSScriptRoot "..\backend\data"
$DbPath   = Join-Path $DataDir "mailpit.db"
$SmtpPort = 1025
$WebPort  = 8025

function Test-Port {
    param([int]$Port, [int]$TimeoutMs = 800)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait($TimeoutMs) -and $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Get-MailpitProcess {
    Get-Process -Name "mailpit" -ErrorAction SilentlyContinue
}

# ---------- Status ----------
if ($Status) {
    Write-Host "=== Mailpit 状态 ===" -ForegroundColor Cyan
    $proc = Get-MailpitProcess
    if ($proc) {
        Write-Host ("进程: 运行中 (PID " + ($proc.Id -join ", ") + ")") -ForegroundColor Green
    } else {
        Write-Host "进程: 未运行" -ForegroundColor Yellow
    }
    foreach ($p in @($SmtpPort, $WebPort)) {
        $ok = Test-Port -Port $p
        $color = if ($ok) { "Green" } else { "DarkGray" }
        Write-Host ("端口 " + $p + ": " + $(if ($ok) { "监听中" } else { "未监听" })) -ForegroundColor $color
    }
    if ($proc) {
        Write-Host ""
        Write-Host ("Web UI: http://localhost:" + $WebPort) -ForegroundColor Cyan
    }
    return
}

# ---------- Stop ----------
if ($Stop) {
    $proc = Get-MailpitProcess
    if (-not $proc) {
        Write-Host "Mailpit 未在运行。" -ForegroundColor Yellow
        return
    }
    $proc | Stop-Process -Force
    Write-Host ("已停止 Mailpit (PID " + ($proc.Id -join ", ") + ")") -ForegroundColor Green
    return
}

# ---------- Start ----------
if (-not (Test-Path $ExePath)) {
    Write-Host "找不到 mailpit.exe：" -ForegroundColor Red
    Write-Host "  $ExePath"
    Write-Host ""
    Write-Host "请从 https://github.com/axllent/mailpit/releases 下载 mailpit-windows-amd64.zip" -ForegroundColor Yellow
    Write-Host "解压到 D:\dshWorkspace\tools\mailpit\ 后重试。"
    exit 1
}

if (Get-MailpitProcess) {
    Write-Host "Mailpit 已在运行，无需重复启动。" -ForegroundColor Yellow
    Write-Host ("Web UI: http://localhost:" + $WebPort) -ForegroundColor Cyan
    return
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

Write-Host "启动 Mailpit ..." -ForegroundColor Cyan
$process = Start-Process -FilePath $ExePath -ArgumentList @(
    "--smtp",    "127.0.0.1:$SmtpPort",
    "--listen",  "127.0.0.1:$WebPort",
    "--database", $DbPath
) -PassThru -WindowStyle Hidden

# 等待端口就绪
$ready = $false
for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Milliseconds 300
    if ((Test-Port -Port $SmtpPort) -and (Test-Port -Port $WebPort)) {
        $ready = $true
        break
    }
}

if ($ready) {
    Write-Host ""
    Write-Host "Mailpit 已启动 (PID $($process.Id))" -ForegroundColor Green
    Write-Host "  SMTP : 127.0.0.1:$SmtpPort"
    Write-Host "  Web  : http://localhost:$WebPort"
    Write-Host "  API  : http://localhost:$WebPort/api/v1"
    Write-Host "  数据 : $DbPath"
    Write-Host ""
    Write-Host "停止：.\scripts\start-mailpit.ps1 -Stop" -ForegroundColor DarkGray
} else {
    Write-Host "启动超时，请检查端口是否被占用。" -ForegroundColor Red
    Write-Host "  netstat -ano | findstr `":$SmtpPort`"" -ForegroundColor DarkGray
    exit 1
}

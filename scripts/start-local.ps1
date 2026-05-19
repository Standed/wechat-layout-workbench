param(
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LogFile = Join-Path $Root "output\wechat-layout-workbench.log"

New-Item -ItemType Directory -Force -Path (Join-Path $Root "output") | Out-Null

Write-Host "检查 Python..."
python --version

Write-Host "检查 lark-cli..."
$LarkCli = Get-Command lark-cli -ErrorAction SilentlyContinue
if (-not $LarkCli) {
  Write-Host "未找到 lark-cli。请先执行：npm install -g @larksuite/cli" -ForegroundColor Red
  Write-Host "安装后关闭并重新打开 PowerShell，再运行本脚本。" -ForegroundColor Yellow
  exit 1
}
lark-cli --version

Write-Host "检查飞书登录态..."
$Auth = lark-cli auth status --verify 2>&1
if ($LASTEXITCODE -ne 0) {
  Write-Host $Auth -ForegroundColor Yellow
  Write-Host "飞书登录态不可用。请先执行：lark-cli auth login" -ForegroundColor Red
  exit 1
}

Write-Host "清理旧端口 $Port..."
$Connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($Connections) {
  $Connections | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Milliseconds 500
}

Write-Host "启动公众号排版工作台..."
$Process = Start-Process -FilePath "python" `
  -ArgumentList @("web/server.py", "$Port") `
  -WorkingDirectory $Root `
  -RedirectStandardOutput $LogFile `
  -RedirectStandardError $LogFile `
  -PassThru

Start-Sleep -Seconds 1

try {
  Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/" | Out-Null
  Write-Host "已启动：http://127.0.0.1:$Port/" -ForegroundColor Green
  Write-Host "PID: $($Process.Id)"
  Write-Host "日志：$LogFile"
} catch {
  Write-Host "进程已启动，但页面暂时不可访问。日志如下：" -ForegroundColor Red
  Get-Content $LogFile -Tail 80 -ErrorAction SilentlyContinue
  exit 1
}

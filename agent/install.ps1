# Stella Agent 安装脚本（Windows，PowerShell 管理员运行）
# 用法：iwr http://<stella>/agent/install.ps1 -UseBasicParsing | iex
# 或手动：powershell -File install.ps1 -Url http://<stella> -Token <token> [-Deps | -NoDeps]
param(
    [string]$Url = "http://127.0.0.1:12031",
    [string]$Token = "",
    [switch]$Deps,      # 自动安装缺失依赖（不询问）
    [switch]$NoDeps     # 跳过依赖安装
)

if (-not $Token) {
    Write-Error "缺少 -Token"
    exit 1
}

$InstallDir = "C:\stella-agent"
Write-Host "==> Stella Agent 安装中..." -ForegroundColor Cyan
Write-Host "    中心: $Url"

# 询问是否安装（-Deps 恒 true，-NoDeps 恒 false，否则 Read-Host 交互）
function Ask-Yn {
    param([string]$Prompt, [string]$Default = "y")
    if ($Deps) { return $true }
    if ($NoDeps) { return $false }
    $suffix = if ($Default -eq "y") { "[Y/n]" } else { "[y/N]" }
    $ans = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($ans)) { return ($Default -eq "y") }
    return ($ans.Trim() -match '^[Yy]')
}

# ── 1. 检测 Python（硬依赖，缺失则询问安装） ──
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "    [缺] Python（Stella Agent 必需）" -ForegroundColor Yellow
    if (Ask-Yn "    是否自动安装 Python？" "y") {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            winget install -e --id Python.Python.3.13 --silent --accept-source-agreements --accept-package-agreements
            # 刷新 PATH（winget 安装后当前进程 PATH 不自动更新）
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        } else {
            Write-Host "    未检测到 winget，请手动安装 Python：https://www.python.org/downloads/" -ForegroundColor Yellow
            exit 1
        }
    } else {
        Write-Error "已取消，退出"
        exit 1
    }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Error "Python 安装后未在 PATH 中找到，请重新打开终端后重试"
        exit 1
    }
}
Write-Host "    python: $(python --version)"

# ── 2. 检测可选依赖 httpx / psutil ──
Write-Host "==> 检查依赖..."
$missing = @()
python -c "import httpx" 2>$null
if ($LASTEXITCODE -ne 0) { $missing += "httpx" }
python -c "import psutil" 2>$null
if ($LASTEXITCODE -ne 0) { $missing += "psutil" }

if ($missing.Count -eq 0) {
    Write-Host "    httpx / psutil 已就绪"
} elseif ($NoDeps) {
    Write-Host "    [缺] $($missing -join ' / ')，-NoDeps 跳过（agent 将降级运行）" -ForegroundColor Yellow
} elseif (Ask-Yn "    缺少 $($missing -join ' / ')，是否安装？" "y") {
    python -m pip install --quiet $missing
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    [warn] pip 安装失败，将降级运行" -ForegroundColor Yellow
    }
} else {
    Write-Host "    已跳过，agent 将降级运行"
}

# ── 3. 下载 agent 主程序 ──
Write-Host "==> 下载 agent..."
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
try {
    Invoke-WebRequest "$Url/agent/script" -OutFile "$InstallDir\stella_agent.py" -UseBasicParsing
} catch {
    Write-Host "    [warn] 中心未提供 /agent/script，请手动放置 stella_agent.py 到 $InstallDir\" -ForegroundColor Yellow
}

# ── 4. 校验 token（提前发现 token 错误，避免装完一直离线） ──
Write-Host "==> 校验 token..."
try {
    Invoke-WebRequest "$Url/agent/config?token=$Token" -UseBasicParsing -ErrorAction Stop | Out-Null
    Write-Host "    token 校验通过"
} catch {
    $code = 0
    if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
    if ($code -eq 401) {
        Write-Host "⚠️  token 校验失败（HTTP 401）—— token 无效或已失效！" -ForegroundColor Red
        Write-Host "    请回到 Stella 服务器页，重新打开该节点的 agent 弹窗复制最新安装命令。"
        Write-Host "    否则 agent 装上后无法上报，会一直显示「离线」。"
        if (-not $Deps) {
            $go = Read-Host "    是否仍要继续安装？（token 错误会导致离线）[y/N]"
            if ($go -notmatch '^[Yy]') { Write-Host "    已取消安装"; exit 1 }
        }
    } else {
        Write-Host "    [warn] token 校验请求失败（中心可能不可达），跳过校验" -ForegroundColor Yellow
    }
}

# ── 5. 注册为计划任务（开机自启 + 崩溃重启） ──
Write-Host "==> 配置计划任务..."
$action = New-ScheduledTaskAction -Execute "python" `
    -Argument "`"$InstallDir\stella_agent.py`" --url $Url --token $Token"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "StellaAgent" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "StellaAgent"

Write-Host "==> 安装完成。计划任务 StellaAgent 已启动。" -ForegroundColor Green

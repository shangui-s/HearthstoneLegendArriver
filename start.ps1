# HSLegendArriver 一键启动脚本（由 start.bat 双击调用，也可直接右键「使用 PowerShell 运行」）
<#
  它做四件事：
    1. 需要管理员权限时自动弹 UAC 提权（鼠标/键盘点击必须管理员才生效）；
    2. 自动找 Python 3.12（64 位）：HS_PYTHON 环境变量 → py -3.12 → PATH → 常见安装路径 → conda HTL 环境；
    3. 缺依赖时用清华镜像一键 pip install -r requirements.txt；
    4. 启动 web_ui.py（浏览器会自动打开控制台，端口 8765 起自动顺延）。

  参数：
    -CheckOnly   只体检不启动（找 Python + 查依赖，方便排错）
    -NoElevate   不提权，直接用当前权限启动
    -NoBrowser   启动时不自动开浏览器（等价 web_ui.py --no-browser）
    -PauseAlways 结束时/失败时停住窗口（提权后的新窗口会自动带上，避免一闪而过）
#>
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$NoElevate,
    [switch]$NoBrowser,
    [switch]$PauseAlways
)

$ErrorActionPreference = 'Continue'   # 原生 exe 往 stderr 输出时不至于中断脚本
$Root = $PSScriptRoot
if (-not $Root) { $Root = Split-Path -Parent $MyInvocation.MyCommand.Path }
$Entry = Join-Path $Root 'web_ui.py'
$ReqFile = Join-Path $Root 'requirements.txt'
$TunaMirror = 'https://pypi.tuna.tsinghua.edu.cn/simple'

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Tip([string]$msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }

function Stop-WithError([string]$msg, [string]$hint = '') {
    Write-Host ""
    Write-Host "[X] $msg" -ForegroundColor Red
    if ($hint) { Write-Host "    $hint" -ForegroundColor Yellow }
    if ($PauseAlways -and -not $CheckOnly) { Write-Host ""; Read-Host "按回车关闭窗口" | Out-Null }
    exit 1
}

function Test-Admin {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($id)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

try { $Host.UI.RawUI.WindowTitle = 'HSLegendArriver 一键启动' } catch { }

Write-Host ""
Write-Host "  HSLegendArriver 一键启动" -ForegroundColor White
Write-Host "  ----------------------------------------" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 0. 环境检查
if (-not (Test-Path -LiteralPath $Entry)) {
    Stop-WithError "没找到 web_ui.py：$Entry" "请把 start.bat / start.ps1 放在项目根目录（和 web_ui.py 同一层）。"
}

# ---------------------------------------------------------------- 1. 提权
$isAdmin = Test-Admin
if (-not $isAdmin -and -not $NoElevate -and -not $CheckOnly) {
    Write-Step '需要管理员权限，正在请求提权（UAC 弹窗请点「是」）'
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $PSCommandPath), '-PauseAlways')
    if ($NoBrowser) { $argList += '-NoBrowser' }
    try {
        Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $argList -WorkingDirectory $Root -ErrorAction Stop | Out-Null
        Write-Ok '已在新的管理员窗口中启动，本窗口可以关闭了。'
    } catch {
        Stop-WithError '提权失败（可能在 UAC 弹窗里点了「否」）。' '可以右键 start.bat → 以管理员身份运行。'
    }
    exit 0
}
if ($isAdmin) { Write-Ok '管理员权限：已具备' } else { Write-Tip '当前不是管理员：鼠标/键盘点击可能无效（去掉 -NoElevate 重新运行会自动提权）' }

# ---------------------------------------------------------------- 2. 找 Python 3.12
Write-Step '查找 Python 3.12（64 位）'

# 注意：PowerShell 5.1 调原生 exe 会吞掉参数里的双引号（print("%d.%d") 会变成
# print(%d.%d)），所以探测代码一律写成「不含空格、不含双引号」的单行，或者走 stdin。
$versionProbe = 'import sys;print(sys.version_info[0],sys.version_info[1],sys.maxsize>2**32)'

function Get-PythonInfo([string]$exe, [string[]]$extraArgs = @()) {
    if ([string]::IsNullOrWhiteSpace($exe)) { return $null }
    if (-not (Test-Path -LiteralPath $exe) -and -not (Get-Command $exe -ErrorAction SilentlyContinue)) { return $null }
    try {
        $out = @(& $exe @extraArgs '-c' $versionProbe 2>$null | Where-Object { $_ -match '\S' })
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0 -or $out.Count -lt 1) { return $null }
    $parts = ([string]$out[0]).Trim() -split '\s+'
    if ($parts.Count -lt 3) { return $null }
    return [pscustomobject]@{
        Path    = $exe
        Version = ('{0}.{1}' -f $parts[0], $parts[1])
        Bits    = $(if ($parts[2] -eq 'True') { 64 } else { 32 })
    }
}

$candidates = New-Object System.Collections.ArrayList
if ($env:HS_PYTHON) {
    [void]$candidates.Add(@{ exe = $env:HS_PYTHON; args = @(); label = 'HS_PYTHON 环境变量' })
}
if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        $real = @(& py -3.12 -c 'import sys;print(sys.executable)' 2>$null | Where-Object { $_ })
        if ($LASTEXITCODE -eq 0 -and $real.Count -gt 0) {
            [void]$candidates.Add(@{ exe = ([string]$real[0]).Trim(); args = @(); label = 'py -3.12 启动器' })
        }
    } catch { }
}
[void]$candidates.Add(@{ exe = 'python'; args = @(); label = 'PATH 里的 python' })

$commonPaths = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    'C:\Python312\python.exe',
    'C:\Program Files\Python312\python.exe',
    (Join-Path $env:USERPROFILE 'anaconda3\envs\HTL\python.exe'),
    (Join-Path $env:USERPROFILE 'miniconda3\envs\HTL\python.exe'),
    (Join-Path $env:USERPROFILE '.conda\envs\HTL\python.exe'),
    'C:\ProgramData\anaconda3\envs\HTL\python.exe',
    'C:\ProgramData\miniconda3\envs\HTL\python.exe'
)
foreach ($p in $commonPaths) { [void]$candidates.Add(@{ exe = $p; args = @(); label = '常见安装路径' }) }

$python = $null
$otherVersions = New-Object System.Collections.ArrayList
foreach ($c in $candidates) {
    $info = Get-PythonInfo $c.exe $c.args
    if ($null -eq $info) { continue }
    if ($info.Version -eq '3.12' -and $info.Bits -eq 64) {
        $python = $info
        Write-Ok ("Python {0}（{1} 位）：{2}" -f $info.Version, $info.Bits, $info.Path)
        break
    }
    $desc = "Python {0}（{1} 位）" -f $info.Version, $info.Bits
    if (-not $otherVersions.Contains($desc)) { [void]$otherVersions.Add($desc) }
}

if ($null -eq $python) {
    $found = if ($otherVersions.Count -gt 0) { "找到的是：" + ($otherVersions -join '、') + "。" } else { '' }
    $hint = @"
$found OCR 后端 paddlepaddle 2.6.2 只有 3.12 及以下的 64 位轮子，装 3.13/3.14 会跑不起来。
    两个办法：
      1) 装 3.12：https://www.python.org/downloads/（务必 64 位，勾选 Add python.exe to PATH）
      2) 用 conda：conda create -n HTL python=3.12 -y && conda activate HTL
    装完重新双击 start.bat 即可。
"@
    Stop-WithError '没有找到可用的 Python 3.12（64 位）。' $hint
}

# ---------------------------------------------------------------- 3. 依赖
Write-Step '检查依赖包'

$missingProbe = @'
import importlib.util as u
mods = ["cv2", "numpy", "PIL", "psutil", "keyboard", "pynput", "requests", "win32gui", "paddleocr", "paddle"]
print(",".join([m for m in mods if u.find_spec(m) is None]))
'@

function Get-MissingModules([string]$exe) {
    try {
        # 走 stdin（python -），彻底避开 PowerShell 的原生参数引号问题
        $out = @($missingProbe | & $exe '-' 2>$null | Where-Object { $_ -match '\S' })
        if ($LASTEXITCODE -ne 0) { return @('无法读取依赖状态') }
        if ($out.Count -eq 0) { return @() }
        $text = ([string]$out[0]).Trim()
        if ([string]::IsNullOrWhiteSpace($text)) { return @() }
        return @($text -split ',')
    } catch {
        return @('无法读取依赖状态')
    }
}

$missing = @(Get-MissingModules $python.Path)
if ($missing.Count -eq 0) {
    Write-Ok '依赖齐全'
} else {
    Write-Tip ("缺少依赖：" + ($missing -join '、'))
    if ($CheckOnly) {
        Write-Tip ("需要时执行：`"$($python.Path)`" -m pip install -r requirements.txt -i $TunaMirror")
    } else {
        $answer = Read-Host "  现在用清华镜像安装依赖吗？[Y/n]"
        if ([string]::IsNullOrWhiteSpace($answer) -or $answer -match '^[Yy]') {
            Write-Step '安装依赖（耗时较长，请耐心等待）'
            & $python.Path -m pip install -r $ReqFile -i $TunaMirror
            if ($LASTEXITCODE -ne 0) {
                Stop-WithError 'pip 安装失败。' "可以手动执行：`"$($python.Path)`" -m pip install -r requirements.txt -i $TunaMirror"
            }
            $missing = @(Get-MissingModules $python.Path)
            if ($missing.Count -eq 0) { Write-Ok '依赖已就绪' }
            else { Write-Tip ("仍缺少：" + ($missing -join '、') + "，先尝试启动，页面「环境自检」里会标出来") }
        } else {
            Write-Tip '跳过安装，先尝试启动'
        }
    }
}

if ($CheckOnly) {
    Write-Host ""
    Write-Host "  体检完成：可以正常启动。" -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------- 4. 启动
$runArgs = @('web_ui.py')
if ($NoBrowser) { $runArgs += '--no-browser' }

Write-Step '启动 Web 控制台'
Write-Host ("  解释器：{0}" -f $python.Path) -ForegroundColor DarkGray
Write-Host '  保持本窗口打开；关掉窗口 = 退出控制台（Ctrl+C 也可以）' -ForegroundColor DarkGray

Push-Location $Root
$exitCode = 0
try {
    & $python.Path @runArgs
    $exitCode = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "[X] 控制台已退出，退出码：$exitCode" -ForegroundColor Red
    Write-Host '    往上翻一点看报错信息；也可以双击 start.bat 后加 -CheckOnly 做体检。' -ForegroundColor Yellow
    if ($PauseAlways) { Write-Host ""; Read-Host '按回车关闭窗口' | Out-Null }
    exit $exitCode
}

Write-Host ""
Write-Host '  控制台已正常退出。' -ForegroundColor Green
if ($PauseAlways) { Read-Host '按回车关闭窗口' | Out-Null }
exit 0

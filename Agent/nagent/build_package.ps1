<#
.SYNOPSIS
  NAgent 一键打包脚本：PyInstaller 构建 exe + Inno Setup 6 编译安装包。
  之后每次想打包，直接运行本脚本即可：
      powershell -ExecutionPolicy Bypass -File .\build_package.ps1
.DESCRIPTION
  步骤：
    1) 用 PyInstaller 按 Nagent.spec 构建，产物在 dist\Nagent\Nagent.exe
    2) 用 Inno Setup 6 的 ISCC.exe 编译 installer\NAgent.iss
       ，生成安装包 installer\NAgent-setup-<版本>.exe
.NOTES
  版本号默认 1.0.0，如需改版：
      powershell -ExecutionPolicy Bypass -File .\build_package.ps1 -Version 1.1.0
#>
[CmdletBinding()]
param(
    # 安装包版本号，会同时用于安装包文件名与 Inno 脚本
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = (Get-Location).Path }

Write-Host "=== NAgent 打包脚本 ===" -ForegroundColor Cyan
Write-Host "项目目录 : $ProjectRoot"
Write-Host "版本     : $Version"

# ---------- 1. 定位工具 ----------
function Get-PyInstaller {
    try {
        $v = & pyinstaller --version 2>$null
        if ($LASTEXITCODE -eq 0) { return "pyinstaller" }
    } catch {}
    return $null
}

function Find-ISCC {
    $candidates = @(
        "D:\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$pyinstaller = Get-PyInstaller
if (-not $pyinstaller) {
    Write-Host "[错误] 未找到 pyinstaller，请先: pip install pyinstaller" -ForegroundColor Red
    exit 1
}
$iscc = Find-ISCC
if (-not $iscc) {
    Write-Host "[错误] 未找到 ISCC.exe（Inno Setup 6），请确认已安装并核对安装路径" -ForegroundColor Red
    exit 1
}
Write-Host "PyInstaller : $pyinstaller"
Write-Host "ISCC       : $iscc"

# ---------- 2. PyInstaller 构建 ----------
$spec = Join-Path $ProjectRoot "Nagent.spec"
if (-not (Test-Path -LiteralPath $spec)) {
    Write-Host "[错误] 找不到 Nagent.spec" -ForegroundColor Red
    exit 1
}
Write-Host "`n[1/2] PyInstaller 构建中..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    & pyinstaller --noconfirm --clean $spec
    if ($LASTEXITCODE -ne 0) { throw "pyinstaller 构建失败 (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$exe = Join-Path $ProjectRoot "dist\Nagent\Nagent.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Host "[错误] 构建产物缺失: $exe" -ForegroundColor Red
    exit 1
}
Write-Host "构建完成: $exe" -ForegroundColor Green

# ---------- 3. Inno Setup 编译安装包 ----------
$iss = Join-Path $ProjectRoot "installer\NAgent.iss"
if (-not (Test-Path -LiteralPath $iss)) {
    Write-Host "[错误] 找不到 installer\NAgent.iss" -ForegroundColor Red
    exit 1
}
Write-Host "`n[2/2] Inno Setup 编译安装包中..." -ForegroundColor Yellow
# /D 把版本号传给 .iss（.iss 中 #ifndef 已设默认值）
& $iscc "/DMyAppVersion=$Version" "/Qp" $iss
if ($LASTEXITCODE -ne 0) { throw "ISCC 编译失败 (exit $LASTEXITCODE)" }

# ---------- 4. 结果 ----------
$out = Join-Path $ProjectRoot "installer\NAgent-setup-$Version.exe"
if (Test-Path -LiteralPath $out) {
    Write-Host "`n=== 打包成功 ===" -ForegroundColor Green
    Write-Host "安装包: $out" -ForegroundColor Green
} else {
    Write-Host "[警告] 未在预期路径找到安装包，请查看 ISCC 输出" -ForegroundColor Red
}

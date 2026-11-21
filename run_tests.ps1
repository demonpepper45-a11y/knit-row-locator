$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "未找到 .venv；请先运行 .\run.ps1 或按 README 安装依赖。"
}

Set-Location $root
& $python -m pytest -q

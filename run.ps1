param(
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "未找到 .venv，正在创建并安装依赖..."
    python -m venv (Join-Path $root ".venv")
    & $python -m pip install --upgrade pip
    & $python -m pip install -r (Join-Path $root "requirements.txt")
}

if (-not (Test-Path (Join-Path $root "examples\case1_unique\photo.png"))) {
    Write-Host "正在生成演示样例..."
    & $python (Join-Path $root "examples\build_examples.py")
}

Write-Host "启动应用：http://127.0.0.1:$Port"
& $python -m streamlit run (Join-Path $root "app.py") --server.port $Port

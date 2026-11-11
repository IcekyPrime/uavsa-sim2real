# ============================================================
# 创建 conda 环境并安装依赖
# 用法（PowerShell）：
#   powershell -ExecutionPolicy Bypass -File setup_conda_env.ps1
# 可选环境变量：CONDA_EXE（conda 可执行文件路径）、UAVSA_ENV_NAME（环境名）
# ============================================================
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$conda = if ($env:CONDA_EXE) { $env:CONDA_EXE } else { "conda" }
$envName = if ($env:UAVSA_ENV_NAME) { $env:UAVSA_ENV_NAME } else { "uavsa" }

Write-Host "[1/3] 创建 conda 环境 $envName ..."
& $conda create -n $envName python=3.10 -y

Write-Host "[2/3] 安装核心依赖..."
& $conda run -n $envName python -m pip install -r (Join-Path $repo "requirements.txt")

Write-Host "[3/3] 安装 GUI 依赖（pywebview / pyinstaller）..."
& $conda run -n $envName python -m pip install -r (Join-Path $repo "gui\requirements-gui.txt")

Write-Host "完成。启动方式："
Write-Host "  conda activate $envName"
Write-Host "  cd docker1"
Write-Host "  python -m agent.main --mock"

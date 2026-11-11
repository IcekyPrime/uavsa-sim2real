# Mock 演示：无需 Docker，本地启动内置 Mock Agent（GUI 可连 http://127.0.0.1:8000）
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py = if ($env:UAVSA_PYTHON) { $env:UAVSA_PYTHON } else { "python" }

$env:PYTHONPATH = Join-Path $repo "docker1"
Set-Location (Join-Path $repo "docker1")
& $py -m agent.main --mock

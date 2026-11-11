# 启动双容器（docker1 仿真+Agent，docker2 算法）
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "已生成 .env，请填写 LLM_API_KEY" }
docker compose up -d
Write-Host "Agent: http://127.0.0.1:8000   sim_bridge: http://127.0.0.1:8001"
docker compose ps

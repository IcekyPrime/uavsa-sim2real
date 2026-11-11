# 构建双容器镜像（需先启动 Docker Desktop）
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "已生成 .env，请填写 LLM_API_KEY" }
docker compose build

# 快速开始

## 1. 环境要求

| 项 | 要求 |
|----|------|
| Python | 3.10 及以上 |
| Docker | 可选，仅在双容器模式下需要 |
| 操作系统 | Windows / Linux / macOS 均可 |
| 集群 SSH | 可选，仅在使用集群仿真时填写 |

## 2. 安装依赖

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
pip install -r gui/requirements-gui.txt
```

也可以使用脚本（Windows）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_conda_env.ps1
```

## 3. 配置

```bash
copy .env.example .env   # Windows
cp .env.example .env     # Linux / macOS
```

打开 `.env`，至少填写：

```ini
LLM_API_KEY=你的密钥
```

其余配置按需填写。`.env` 已被 `.gitignore` 排除，不会进入仓库。

## 4. Mock 模式（无需 Docker 与集群）

```bash
cd docker1
python -m agent.main --mock
```

服务监听 `http://127.0.0.1:8000`。Mock 后端用内存数据模拟仿真与算法，
用于验证 Agent 闭环和前端流程。

## 5. 集群模式（真实 PX4 + EGO-Planner）

在 `.env` 中填写：

```ini
CLUSTER_SSH_HOST=
CLUSTER_SSH_PORT=22
CLUSTER_SSH_USER=
CLUSTER_SSH_PASSWORD=
CLUSTER_SSH_NODE=
CLUSTER_PRP_DOCKER=
CLUSTER_SIM_CONTAINER=uavsa-sim22
CLUSTER_EGO_CONTAINER=uavsa-ego4
```

说明：

- `CLUSTER_SSH_NODE` 是登录后进入的计算节点名。
- `CLUSTER_PRP_DOCKER` 是宿主机上存放 `advanced_param_px4.xml`、`run_px4.launch` 的目录绝对路径。
- 容器需要提前启动，并保证 ROS master 在 `localhost:11311`。

启动：

```bash
cd docker1
python -m agent.main --cluster
```

## 6. Docker 双容器模式（可选）

```bash
docker compose up -d --build
```

- `docker1`：仿真平台 + Agent + `sim_bridge`（8001）
- `docker2`：EGO-Planner + `algo_bridge`（8002）

当前 `sim_bridge` 的 Gazebo 控制与 ROS1↔ROS2 桥接是骨架实现，
真实仿真请使用第 5 节的集群模式。

## 7. 启动 GUI

```bash
cd gui
python main.py
```

首次打开后，在「设置」中填写 API Key。
如果连接外部 Agent 服务，把 Agent 地址填为 `http://127.0.0.1:8000`；
留空则使用内置 Mock Agent。

## 8. 打包 exe（Windows）

```bash
cd gui
build.bat
```

产物在 `gui/dist/UAVSA.exe`。

## 9. 常见问题

| 问题 | 处理 |
|------|------|
| `docker` 连不上 daemon | 先启动 Docker Desktop |
| `未配置集群 SSH` | 检查 `.env` 中的 `CLUSTER_SSH_*` |
| LLM 返回 401 | 检查 `LLM_API_KEY` 是否有效 |
| GUI 显示「已结束」且没有事件 | 确认后端已启动，且 `uvicorn[standard]` 已安装 |
| 任务一直悬停 | 参考 `shared/knowledge/02-flight-state-diagnosis.md` |

# UAVSA：无人机算法 sim2real 平台

UAVSA 是一个用于无人机算法仿真评测与参数调优的平台。用户输入任务目标，Agent 调用大模型，
按 ReAct 循环调用工具，完成检索、编译、仿真、运行、评测、参数补丁、重跑和报告生成。

当前支持的算法是 EGO-Planner，仿真环境是 Gazebo + PX4 SITL + MAVROS。

## 主要功能

- Agent 闭环：读指标、分析、改参数、重跑，最多执行 5 轮补丁
- 真实飞行数据：10 Hz 采样位置、速度、规划指令和跟踪误差
- 分相位统计：起飞、巡航、悬停分别统计，避免悬停数据造成误判
- 知识库：参数地图、诊断树、补丁配方、故障案例
- 参数补丁：支持整文件覆盖和参数覆盖，自动备份原文件
- 评测报告：Markdown 报告，包含分相位指标和补丁记录
- 桌面 GUI：pywebview 窗口，实时显示 Agent 的思考和工具调用

## 系统架构

```
GUI（pywebview）
   │ HTTP + WebSocket
Agent（FastAPI，:8000）
   ├─ Mock 后端        内存数据，无需集群
   ├─ HTTP 后端        sim_bridge :8001 / algo_bridge :8002
   └─ SSH 后端         集群容器 uavsa-sim22 / uavsa-ego4
```

| 组件 | 位置 | 职责 |
|------|------|------|
| `agent` | docker1 | ReAct 循环、工具、知识库、报告 |
| `sim_bridge` | docker1 | 仿真控制与指标接口 |
| `algo_bridge` | docker2 | 算法编译、运行、补丁接口 |
| `shared/` | 共享目录 | 知识库、评测报告、算法工作区 |

## 目录结构

```
UAVSA-v1.0/
├── docker1/
│   ├── agent/            Agent 主体
│   │   ├── backends/     Mock / HTTP / SSH 三种后端
│   │   ├── tools/        工具、知识库、时序分析、报告
│   │   ├── loop.py       ReAct 循环
│   │   └── main.py       FastAPI 入口
│   └── sim_bridge/       仿真桥
├── docker2/algo_bridge/  算法桥
├── gui/                  pywebview 前端
├── shared/
│   ├── knowledge/        知识库文档
│   ├── results/          评测报告
│   └── workspace/        算法参数工作区
├── docs/                 架构、快速开始、Agent 设计、API
└── scripts/              启动与构建脚本
```

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
pip install -r gui/requirements-gui.txt
```

### 2. 配置

```bash
copy .env.example .env        # Windows
cp .env.example .env          # Linux / macOS
```

编辑 `.env`，至少填写 `LLM_API_KEY`。没有 Key 时 Agent 会退回到固定的基线流程。

### 3. 启动 Agent（Mock 模式）

```bash
cd docker1
python -m agent.main --mock
```

服务地址为 `http://127.0.0.1:8000`。

### 4. 启动 GUI

```bash
cd gui
python main.py
```

在「设置」中填写 API Key。Agent 地址留空时使用内置 Mock Agent，
填写 `http://127.0.0.1:8000` 时连接外部 Agent 服务。

## 集群模式

在 `.env` 中填写以下配置：

| 变量 | 说明 |
|------|------|
| `CLUSTER_SSH_HOST` | SSH 入口主机 |
| `CLUSTER_SSH_PORT` | SSH 端口，默认 22 |
| `CLUSTER_SSH_USER` | 登录用户名 |
| `CLUSTER_SSH_PASSWORD` | 登录密码 |
| `CLUSTER_SSH_NODE` | 登录后进入的计算节点 |
| `CLUSTER_PRP_DOCKER` | 宿主机上 `docker/` 目录的绝对路径 |
| `CLUSTER_SIM_CONTAINER` | 仿真容器名，默认 `uavsa-sim22` |
| `CLUSTER_EGO_CONTAINER` | 算法容器名，默认 `uavsa-ego4` |

启动：

```bash
cd docker1
python -m agent.main --cluster
```

集群模式要求两个容器已经运行，并且 ROS master 在 `localhost:11311`。
具体话题、路径和重启约定见 `shared/knowledge/06-cluster-conventions.md`。

## Docker 双容器模式

```bash
docker compose up -d --build
```

`docker1` 包含 Gazebo/PX4、`sim_bridge` 和 Agent，`docker2` 包含 EGO-Planner 和 `algo_bridge`。
当前双容器的 Gazebo 控制和 ROS1↔ROS2 桥接是骨架实现，真实仿真请使用集群模式。

## Agent 工具

| 工具 | 作用 |
|------|------|
| `search_algorithm` | 检索算法与调参经验 |
| `retrieve_knowledge` | 检索知识库片段 |
| `run_simulation` / `stop_simulation` | 启动、停止仿真 |
| `read_metrics` | 读取指标并做诊断 |
| `build_algorithm` | 编译被测算法 |
| `run_algorithm` | 运行算法并返回 10 Hz 飞行时序 |
| `patch_algorithm` | 应用参数或文件补丁 |
| `analyze_time_series` | 分相位分析轨迹时序 |
| `generate_report` | 生成 Markdown 评测报告 |

## 评测指标

| 指标 | 含义 |
|------|------|
| `tracking_error_m` | 巡航段跟踪误差均值 |
| `convergence_time_s` | 巡航段首次稳定跟踪所需时间 |
| `success_rate` | 窗口内完成至少一个航点且无碰撞 |
| `collision_count` | 距墙面小于 0.15 m 的连续段数 |
| `overshoot` | 巡航段最大跟踪误差 |
| `smoothness` | 巡航段加速度 RMS |
| `energy` | 巡航段速度平方均值 |
| `safety_violations` | 距墙面小于 0.35 m 的连续段数 |
| `anomaly_score` | 综合异常分，范围 0 到 1 |

主指标只在 `cruise` 相位统计。悬停时误差会变小，不能当作优化效果。

## 知识库

`shared/knowledge/` 包含 6 篇文档：

1. 指标语义与阈值
2. 飞行状态诊断树
3. 参数地图
4. 补丁配方
5. 故障案例
6. 集群拓扑与约定

Agent 在会话结束时会把「症状、补丁、结果」写入 `shared/knowledge/cases/auto-cases.md`，
并按签名去重。

## 已知限制

- 目前只支持 EGO-Planner 和 Gazebo Classic 9
- Docker 双容器的 ROS1↔ROS2 桥接尚未完整实现
- mock 墙没有物理碰撞体，碰撞指标是几何近似
- 没有自动化测试
- 集群模式需要自备容器和 ROS 环境

## 安全说明

- `.env` 和 GUI 本地配置已加入 `.gitignore`
- `.env.example` 中的 API Key 和集群连接信息均为空
- 评测报告、日志、知识库自动案例不会提交到仓库

本项目用于学习和研究。

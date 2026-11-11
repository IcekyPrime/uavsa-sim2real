# Agent 设计

## 1. 角色定位

Agent 是 UAVSA 的「大脑」，运行在 docker1 内，通过 API 调用大模型（默认 DeepSeek），
编排工具完成「检索 → 封装 → 仿真 → 评测 → 分析 → 补丁 → 重跑」的自适应闭环，
最终目标是缩小算法从仿真到实机的表现差异（sim2real）。

## 2. 运行模式

| 模式 | 后端 | 说明 |
|------|------|------|
| Mock | `agent/backends/mock.py` | 内存假数据，无需 Docker，用于演示 / 单测 / 封装逻辑验证 |
| Docker | `agent/backends/http.py` | 通过 HTTP 调用 `sim_bridge`(8001) 与 `algo_bridge`(8002) |

## 3. 决策范式

Agent 使用 **ReAct（推理-行动）** 循环：

1. 系统提示词声明角色、可用工具（含参数 schema）与输出格式。
2. 用户消息注入任务目标 + 算法 + 建议流程。
3. 每轮调用 LLM，解析出 `{"action": ..., "input": {...}}`（调用工具）或 `{"answer": ...}`（结束）。
4. 工具结果作为「观察」追加进对话，供下一轮决策引用。

无 `LLM_API_KEY` 时回退到确定性基线循环（跑一轮 + 占位补丁 + 报告），保证平台始终可运行。

## 4. 工具清单与职责边界

工具在 `agent/tools/builder.py` 中构建，绑定后端与会话：

| 工具 | 职责 | 边界 |
|------|------|------|
| `search_algorithm` / `retrieve_knowledge` | 知识库检索 | 只检索，不修改 |
| `run_simulation` / `stop_simulation` | 仿真控制 | 通过 `sim_bridge`，不直接操作 ROS |
| `read_metrics` | 读取标准化指标 | 同时做一次时序判别诊断 |
| `build_algorithm` / `run_algorithm` / `patch_algorithm` | 算法控制 | 通过 `algo_bridge`；补丁自动备份 |
| `analyze_time_series` | 时序质量/异常判别 | 对应 Plan.md 判别器设想，预留模型插槽 |
| `generate_report` | 报告生成 | 汇总迭代历史，落盘 `shared/results/` |

> **职责边界**：LLM 只做「编排 + 解读 + 生成补丁」，一切结论必须锚定工具输出，
> 不得凭空猜测指标或篡改原始数据。

## 5. 知识库（RAG）

- **单一事实源**：`UAVSA-v1.0/shared/knowledge/`；`docker1/shared` 是指向 `../shared` 的目录链接，
  `SHARED_DIR` 的相对路径统一按仓库根解析，避免本地 / Docker 读到不同副本。
- 文档按主题拆分：指标语义、飞行状态诊断、参数地图、补丁配方、故障案例、集群约定。
- 索引：哈希 n-gram + **语料级 IDF** + 余弦相似度（纯 Python/numpy，无重依赖）；
  正文与标题分别向量化，标题命中加权；参数名（含 `/`、`_`）精确匹配额外加权。
- 过滤：查询实词覆盖率 + 最低相关度阈值，低分噪声直接丢弃；未命中返回空并附文档目录。
- 文档变更按 mtime 自动重建索引；会话结束时若有「≥1 次补丁 + ≥2 轮指标」，
  自动把「症状 / 补丁 / 结果 / 结论」追加到 `knowledge/cases/auto-cases.md`（按签名去重）。

## 6. 时序判别器

`agent/tools/time_series.py` 提供可插拔判别器：

- v1.0：规则 + 统计（均值 / 标准差 / RMS / z-score 尖峰检测 / 异常分）。
- 预留 `model_path` 插槽，后续可加载 Plan.md 设想的自回归判别器替换。
- v1.1：新增 `analyze_trajectory(rows, field)`，输入单次飞行的 10 Hz 真实时序，
  按 `takeoff` / `cruise` / `hover` 分相位统计，支持 `err` / `speed` / `accel` / `x` / `y` / `z`。

## 6.1 观测时序化（v1.1）

SSH 后端的观测层不再只返回聚合标量，而是注入 ROS 脚本按 10 Hz 采样：

| 数据 | 说明 |
|------|------|
| `trajectory` | `t` / 实际位置 `x,y,z` / 实际速度 `vx,vy,vz` / 指令位置 `cmd_*` / 跟踪误差 `err` / 相位 `phase` |
| `phase_summary` | `takeoff`/`cruise`/`hover` 各自的采样数、时长、跟踪误差、最大误差、平均速度、加速度 RMS |
| `_flight_state` | 本次窗口的主相位：`cruise` / `hover` / `takeoff_only` / `no_data` |

指标语义同步校正：

| 指标 | 修正后含义 |
|------|-----------|
| `tracking_error_m` / `smoothness` / `energy` / `overshoot` | 只在 `cruise` 相位统计；悬停不再自动得高分 |
| `convergence_time_s` | 巡航段内首次 `|err|<0.2` 且持续 1 s 的时刻（相对巡航起点）；无则 `null` |
| `success_rate` | 窗口内至少完成 1 个航点且无碰撞记 1.0，否则 0.0（短窗口不按全程到达率计算） |
| `collision_count` | 遍历 `mock_cloud` 全部墙面，按连续侵入段计（机体半径 0.15 m） |
| `safety_violations` | 距墙面 < 0.35 m 的连续近距段数（真实安全裕度，不再用跟踪误差代替） |
| `anomaly_score` | 跟踪误差 / 平滑度 / 超调 / 安全告警的有界加权，避免长期饱和到 1.0 |

> 采样窗口默认 12 s；若无人机处于悬停态，会先重启 ego 重新触发航点任务，
> 使窗口覆盖 `takeoff → cruise`，保证改前/改后可按相同相位比较。

## 7. 会话记忆

`agent/memory.py` 记录任务全生命周期：步骤、指标历史、补丁历史、飞行时序（`trajectories`），
供报告与后续决策引用；每次会话独立，互不污染。

# API 参考

## 端口总览

| 服务 | 端口 | 位置 |
|------|------|------|
| `agent` | 8000 | docker1（GUI 连接此端口） |
| `sim_bridge` | 8001 | docker1 |
| `algo_bridge` | 8002 | docker2 |

## 1. Agent（8000）

### POST /session — 开始任务

```json
{
  "goal": "改善 EGO-Planner 轨迹平滑度",
  "algorithm": "ego-planner",
  "llm_api_key": "sk-...（可选，覆盖全局）",
  "llm_model": "deepseek-v4-pro（可选）"
}
```
返回：`{"session_id": "sess-..."}`

### GET /session/{sid} — 查询会话状态

返回事件列表、是否完成、最终结果。

### WS /session/{sid}/stream — 事件流

事件类型：`start` / `action` / `observation` / `log` / `final` / `done`。

### GET /health · GET /config · POST /config

健康检查；读取（脱敏）/ 更新运行期 LLM 配置。

## 2. sim_bridge（8001）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 后端类型 |
| POST | `/scenario/start` | 启动场景，body：`{obstacle_density, wind_m_s, duration_s}` |
| POST | `/scenario/stop` | 停止场景 |
| GET | `/metrics` | 读取标准化指标 |
| GET | `/metric_keys` | 指标键名列表 |

标准化指标键：`tracking_error_m`、`convergence_time_s`、`success_rate`、
`collision_count`、`overshoot`、`smoothness`、`energy`、`safety_violations`、`anomaly_score`。

## 3. algo_bridge（8002）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 后端类型 |
| GET | `/status` | 工作区 / 后端状态 |
| POST | `/build` | 编译被测算法 |
| POST | `/run` | 运行算法，body：`{duration_s}` |
| POST | `/patch` | 应用补丁，body：`{files:[{path,content}], message}` |
| POST | `/ingest` | 接收 sim_bridge 推送的传感器数据（预留） |

## 4. 补丁格式约定

`patch_algorithm` / `algo_bridge /patch` 使用统一补丁格式：

```json
{
  "files": [
    {"path": "src/plan_manage/advanced_param.xml", "content": "<xml>...</xml>"}
  ],
  "message": "上调 w_smooth 抑制抖振"
}
```

`path` 为相对 `shared/workspace/` 的路径；原文件自动备份到 `shared/workspace/.bak/`。

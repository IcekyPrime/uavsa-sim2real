# UAVSA 知识库

本目录是 Agent 的唯一知识事实源（RAG 数据源）。只支持 `.md` / `.txt`，新增或修改后
下一次会话自动重建索引；Agent 也可在会话结束自动追加案例（`cases/auto-cases.md`）。

> 单一事实源：`UAVSA-v1.0/shared/knowledge/`。
> `docker1/shared` 已改为指向 `../shared` 的目录链接，不再单独维护副本。

## 文档索引

| 文档 | 主题 | 什么时候用 |
|------|------|-----------|
| `01-metrics-semantics.md` | 指标定义、阈值、相位口径、墙面几何 | 解读 `read_metrics` / `run_algorithm` 的数值前必读 |
| `02-flight-state-diagnosis.md` | 飞行状态诊断树（hover / 卡 FSM / 起飞失败 / 碰撞） | 遇到「飞行器不动」、`_flight_state` 异常时 |
| `03-parameter-map.md` | 参数地图：谁真正生效、谁无效、任务参数在哪 | 决定改哪个参数之前 |
| `04-patch-recipes.md` | 症状→参数→方向→步长→风险、安全区间 | 生成补丁时 |
| `05-failure-cases.md` | 真实故障案例（C01–C13） | 排查相似现象时 |
| `06-cluster-conventions.md` | 容器、路径、话题、生命周期、常用命令 | 需要确认环境细节时 |
| `cases/auto-cases.md` | Agent 自动沉淀的「症状/补丁/结果」 | 参考历史调参效果 |

## 检索约定

- 查询优先使用**具体术语**：参数名（如 `optimization/lambda_smooth`）、指标名（如 `tracking_error_m`）、
  飞行态（如 `hover`、`WAIT_TARGET`）、工具名（如 `run_algorithm`）。
- 检索会做标题加权与参数名精确匹配加权；低于相关度阈值的结果会被丢弃。
- 若返回 `results: []`，工具会附带 `available_docs` 文档列表，换关键词再查，不要凭猜测补参数。

## 新增知识

1. 单主题成篇，标题用 `#`，正文用二级标题分段（检索按标题与段落切块）。
2. 参数名、指标名用反引号包裹，便于精确匹配。
3. 结论必须可验证：写清「现象 / 根因 / 修复 / 教训」，不要只写结论。
4. 与源码冲突时以源码为准，并同步修正本知识库。

## 自动案例格式

`cases/auto-cases.md` 由 Agent 在会话结束时追加，格式：

```markdown
## 2026-11-11 10:30 · <任务目标摘要>
- 症状：flight_state=cruise；巡航跟踪误差 0.88 m；碰撞 2；安全告警 2
- 补丁：advanced_param_px4.xml ← optimization/lambda_smooth=2.2, grid_map/obstacles_inflation=0.16
- 结果：跟踪误差 0.88 → 0.64 m；碰撞 2 → 0（相位均为 cruise）
- 结论：部分有效
```

仅当「至少 1 次补丁 + 至少 2 次指标」时才记录，并按签名去重。

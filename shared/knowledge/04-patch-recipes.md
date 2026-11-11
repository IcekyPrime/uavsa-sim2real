# 补丁配方：症状 → 参数 → 方向 → 步长 → 风险

补丁原则：**一次只验证一个假设**，每轮改 1–3 个参数，幅度 20%–30%；
改完必须重跑并只看 `cruise` 相位指标。若目标指标没有变化，先怀疑参数是否真正生效（见 `03-parameter-map`）。

## 优先级

1. 先消碰撞/安全告警（安全底线）
2. 再降巡航跟踪误差
3. 再降平滑度（抖振）
4. 最后才考虑提速/节能

## 配方表

### R1 巡航跟踪误差大、平滑度正常（表现为「滞后」）

| 项 | 内容 |
|----|------|
| 判据 | `tracking_error_m > 0.35` 且 `smoothness < 0.6`；实际轨迹整体滞后于 `cmd` |
| 参数 | `optimization/lambda_smooth` ↑、`manager/max_acc` ↓ |
| 步长 | lambda_smooth 1.0 → 1.5 → 2.0；max_acc 1.5 → 1.2 |
| 风险 | 更保守，到达变慢；`convergence_time_s` 可能上升 |
| 预期 | tracking_error 下降，smoothness 略降 |

### R2 平滑度大 / 明显抖振

| 项 | 内容 |
|----|------|
| 判据 | `smoothness > 0.6`（或加速度 RMS 持续偏高） |
| 参数 | `optimization/lambda_smooth` ↑、`optimization/lambda_feasibility` ↑、`manager/max_acc` ↓ |
| 步长 | lambda_smooth 1.0 → 1.8；lambda_feasibility 0.1 → 0.2；max_acc 1.5 → 1.2 |
| 风险 | 过度平滑会削弱避障锐度，碰撞风险上升 |
| 预期 | smoothness 下降，若碰撞上升则回到 R3 补膨胀 |

### R3 碰撞 / 安全告警（尤其内拐角切角）

| 项 | 内容 |
|----|------|
| 判据 | `collision_count ≥ 1` 或 `safety_violations ≥ 2`；`walls` 指向 wallA/wallB |
| 参数 | `grid_map/obstacles_inflation` ↑、`optimization/lambda_collision` ↑、`optimization/dist0` ↑ |
| 步长 | inflation 0.10 → 0.15 → 0.20；lambda_collision 0.5 → 0.8；dist0 0.5 → 0.7 |
| 风险 | 通道变窄可能无解，FSM 卡 `GEN_NEW_TRAJ` |
| 预期 | collision/safety 下降；若规划失败则回调 inflation |

### R4 超调大

| 项 | 内容 |
|----|------|
| 判据 | `overshoot > 1.0`，且 tracking_error 主要由少数峰值拉高 |
| 参数 | `manager/max_acc` ↓、`optimization/lambda_feasibility` ↑、`optimization/dist0` ↑ |
| 步长 | max_acc 1.5 → 1.2；lambda_feasibility 0.1 → 0.2；dist0 0.5 → 0.7 |
| 风险 | 转弯变钝、到达变慢 |
| 预期 | overshoot 下降，smoothness 略降 |

### R5 到达慢 / 收敛时间长

| 项 | 内容 |
|----|------|
| 判据 | `convergence_time_s > 5` 或 `null`，且平均速度明显低于 `manager/max_vel` |
| 参数 | `manager/max_vel` ↑（同步 `optimization/max_vel` ↑）、`optimization/lambda_smooth` ↓（不低于 1.0） |
| 步长 | max_vel 1.0 → 1.2 → 1.5 |
| 风险 | 跟踪误差与超调上升，碰撞风险上升 |
| 预期 | convergence_time 下降，tracking_error 可能上升；需权衡 |

### R6 能耗偏高

| 项 | 内容 |
|----|------|
| 判据 | `energy` 明显高于同场景历史，且不是因为速度更高 |
| 参数 | `manager/max_vel` ↓、`optimization/lambda_smooth` ↑ |
| 步长 | max_vel 1.0 → 0.8 |
| 风险 | 到达变慢 |
| 预期 | energy 下降 |

## 参数安全区间

| 参数 | 建议区间 |
|------|----------|
| `optimization/lambda_smooth` | 1.0 – 3.0 |
| `optimization/lambda_collision` | 0.5 – 1.5 |
| `optimization/lambda_feasibility` | 0.1 – 0.5 |
| `optimization/lambda_fitness` | 0.8 – 1.5（过大易贴障碍） |
| `optimization/dist0` | 0.3 – 0.8 |
| `grid_map/obstacles_inflation` | 0.10 – 0.25 |
| `manager/max_vel` / `optimization/max_vel` | 0.5 – 1.5（两者保持一致） |
| `manager/max_acc` / `optimization/max_acc` | 0.8 – 2.0（两者保持一致） |

## 每轮补丁的固定动作

```json
{"action": "patch_algorithm",
 "input": {"files": [{"path": "advanced_param_px4.xml",
                      "params": {"optimization/lambda_smooth": "1.8"}}],
           "message": "假设：巡航滞后由平滑权重不足导致，上调 lambda_smooth 1.0→1.8"}}
```

1. `patch_algorithm` → `run_algorithm`（12 s）→ 看 `phase_summary.cruise`
2. 若 `_flight_state` 不是 `cruise`，本次作废，重新触发任务再测
3. 目标指标改善 ≥5% 视为有效；无变化先查参数是否生效；变差则回滚
4. 最多 5 轮；收敛条件：`collision=0`、`safety≤1`、`tracking_error` 下降且 `success_rate=1`

## 明确禁止

- 改 `fsm/waypoint_num`、`fsm/waypoint*`、`fsm/flight_type` 来「让飞行器动起来」
- 改 `bspline/limit_*`（不生效）
- 一次性改 5 个以上参数，导致无法归因
- 在 `hover` 窗口下宣布优化成功
- 把 `lambda_smooth` 或 `lambda_collision` 设为 0

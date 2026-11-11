# 参数地图：谁真正生效

本平台的规划参数分布在两个文件：`advanced_param_px4.xml`（节点参数）与 `run_px4.launch`（launch 参数）。
补丁前先确认参数**确实被源码读取**，否则补丁是空操作。

## 1. 真正生效的参数（已核对源码）

| 参数 | 默认值 | 读取位置 | 作用 | 调参影响 |
|------|--------|----------|------|----------|
| `fsm/flight_type` | 2 | `ego_replan_fsm.cpp` | 1=手动目标，2=PRESET 航点 | 不要改 |
| `fsm/thresh_replan` | 1.5 | 同上 | 距起点超过该距离触发重规划 | 调小更频繁重规划 |
| `fsm/thresh_no_replan` | 2.0 | 同上 | 距终点小于该距离不再重规划 | 调大更早停止重规划 |
| `fsm/planning_horizon` | 3.0 | 同上 | 局部规划距离 | 调大看得更远、耗时增加 |
| `fsm/planning_horizen_time` | 3.0 | 同上 | 局部规划时间窗 | 影响重规划频率 |
| `fsm/emergency_time_` | 1.0 | 同上 | 紧急停止判定时间 | 一般不动 |
| `fsm/waypoint_num` | 4 | 同上 | PRESET 航点数量 | **任务结构参数，禁止调参** |
| `fsm/waypoint{i}_x/y/z` | 见 launch | 同上 | PRESET 航点坐标 | **任务结构参数，禁止调参** |
| `manager/max_vel` | 1.0 | `planner_manager.cpp` | 时间分配用的最大速度 | 下调→更保守、跟踪误差降低但更慢 |
| `manager/max_acc` | 1.5 | 同上 | 时间分配用的最大加速度 | 下调→更平滑 |
| `manager/feasibility_tolerance` | 0.05 | 同上 | 物理限幅容差 | 调大→允许更激进 |
| `manager/control_points_distance` | 0.4 | 同上 | 控制点间距 | 调大→轨迹更粗、计算更快 |
| `manager/planning_horizon` | 3.0 | 同上 | 规划距离（与 fsm 同名不同层） | 一般与 `fsm/planning_horizon` 保持一致 |
| `optimization/lambda_smooth` | 1.0 | `bspline_optimizer.cpp` | 平滑项权重 | **上调→更平滑、可跟踪性更好** |
| `optimization/lambda_collision` | 0.5 | 同上 | 碰撞项权重 | 上调→更远离障碍 |
| `optimization/lambda_feasibility` | 0.1 | 同上 | 动力学可行性权重 | 上调→抑制速度/加速度超限 |
| `optimization/lambda_fitness` | 1.0 | 同上 | 航点拟合权重 | 上调→更贴航点；过大易撞障碍 |
| `optimization/dist0` | 0.5 | 同上 | 碰撞代价作用距离 | 上调→更早开始避障 |
| `optimization/max_vel` | 1.0 | 同上 | **优化器内部**的速度可行性阈值 | 上调→允许更快；与 `manager/max_vel` 建议一致 |
| `optimization/max_acc` | 1.5 | 同上 | **优化器内部**的加速度可行性阈值 | 同上 |
| `optimization/order` | 3 | 同上 | B 样条阶数 | 不要改 |
| `grid_map/obstacles_inflation` | 0.099 | `grid_map.cpp` | 障碍膨胀半径 | **上调→安全裕度更大、通道更窄** |
| `grid_map/resolution` | 0.1 | 同上 | 栅格分辨率 | 调大→更快更粗 |
| `grid_map/local_update_range_x/y/z` | 5.5/5.5/4.5 | 同上 | 局部地图更新范围 | 一般不动 |
| `grid_map/virtual_ceil_height` | 2.5 | 同上 | 虚拟天花板高度 | 影响可飞高度 |

> `optimization/max_vel` / `optimization/max_acc` **不是无效参数**：它们在 `BsplineOptimizer` 的
> 可行性惩罚中被直接使用（速度/加速度越界项）。它们与 `manager/max_vel` / `manager/max_acc`
> 分工不同：`manager/*` 用于轨迹时间分配与 `setPhysicalLimits`，`optimization/*` 用于优化器惩罚阈值。
> 调参时建议保持两者一致，或让 `optimization/*` 不大于 `manager/*`。

## 2. 看起来有效、实际无效的参数

| 参数 | 实际情况 |
|------|----------|
| `bspline/limit_vel` | XML 里声明了，但 `UniformBspline::setPhysicalLimits` 由 `manager/max_vel` 传入，**该参数无人读取** |
| `bspline/limit_acc` | 同上，实际来自 `manager/max_acc` |
| `bspline/limit_ratio` | 同上，源码中 `limit_ratio_` 硬编码为 1.1 |
| `manager/max_jerk` | 被读入 `pp_.max_jerk_`，但规划/优化代码中**没有使用** |

结论：想改物理限速/限加速度，改 `manager/max_vel` / `manager/max_acc`（或它们对应的 launch 参数），
不要改 `bspline/limit_*`。

## 3. 任务结构参数（禁止当调参对象）

这些参数由 `run_px4.launch` 的 `<arg>` 注入：

| launch arg | 注入的节点参数 | 说明 |
|------------|----------------|------|
| `flight_type` | `fsm/flight_type` | 2 = PRESET |
| `point_num` | `fsm/waypoint_num` | 航点数量 |
| `point{i}_x/y/z` | `fsm/waypoint{i}_x/y/z` | 第 i 个航点 |

改动方式（二选一）：

1. **推荐**：patch `run_px4.launch` 的 `<arg>`，保持 XML 里的 `$(arg ...)` 引用不变。
2. 在 XML 中直接写死 `fsm/waypoint*` 数值（会绕过 launch arg，必须整组一致修改）。

任务必须**开环**：最后一个航点不要与第一个航点相同，否则 FSM 会在首点就判定「near end」。

## 4. 补丁目标与路径

| 文件 | 容器内路径 | 宿主机路径 |
|------|-----------|-----------|
| `advanced_param_px4.xml` | `/host/advanced_param_px4.xml` | `PRP/docker/advanced_param_px4.xml` |
| `run_px4.launch` | `/host/run_px4.launch` | `PRP/docker/run_px4.launch` |

`patch_algorithm` 的相对路径会自动映射到 `/host/`。参数覆盖形式（`params`）比整文件覆盖更稳，
且会做 XML 合法性校验；原文件会备份为 `<file>.bak`。

## 5. 依赖关系速记

- 想「更平滑 / 跟踪更好」→ `optimization/lambda_smooth` ↑，必要时 `manager/max_acc` ↓
- 想「离墙更远」→ `grid_map/obstacles_inflation` ↑，`optimization/lambda_collision` ↑
- 想「抑制超速/超加速」→ `optimization/lambda_feasibility` ↑，`optimization/max_vel/acc` 与 `manager/*` 对齐
- 想「更快到达」→ `manager/max_vel` ↑（同时 `optimization/max_vel` ↑），风险是跟踪误差上升

# 飞行状态诊断树

当 `_flight_state` 异常或轨迹位移接近 0 时，按下面的顺序排查。**先判状态，再谈调参**；
绝大多数「飞行器不动」不是参数问题。

## 0. no_data（没有采样）

按顺序确认：

```bash
docker ps --format '{{.Names}}|{{.Status}}' | grep ai_<user>_
# 期望：uavsa-sim22、uavsa-ego4 都是 Up
docker exec <ego容器ID> bash -lc 'source /opt/ros/noetic/setup.bash && source /ego_ws/ego/devel/setup.bash && export ROS_MASTER_URI=http://localhost:11311 && rosnode list'
# 期望：/ego_planner_node /traj_server /pos_cmd_to_px4 /mock_cloud /setpoint_holder /mavros
```

若节点缺失，重启 ego 容器（见 `06-cluster-conventions`）。

## 1. hover / 位移 ≈ 0

依次排除下面 5 种原因，**不要直接调 max_vel**：

| 子情况 | 判定方法 | 结论 |
|--------|----------|------|
| 任务已正常结束 | `pos_cmd` 恒定且等于最后一个航点；FSM 日志为 `WAIT_TARGET` | 正常终态，重新触发任务才能继续评测 |
| 只有一个航点 | `rosparam get /ego_planner_node/fsm/waypoint_num` 返回 1 | 任务被削弱，恢复 launch 的 `point_num` |
| 航点闭环 | 最后一个航点坐标 == 第一个（如都是 `(0,0,1)`） | FSM 的 `end_pt_` 与首点重合，`near end` 提前触发；改成开环 |
| FSM 卡 WAIT_TARGET | 日志长期只有 `[FSM]: state: WAIT_TARGET`，且 `have_target_=false` | 没有有效目标：检查航点数量/坐标与 `fsm/flight_type` |
| FSM 卡 GEN_NEW_TRAJ | 日志反复 `GEN_NEW_TRAJ`，无 `EXEC_TRAJ` | 规划失败：检查点云是否发布、`grid_map` 是否建起来、目标是否在障碍内 |

常用检查命令：

```bash
docker exec <egoID> bash -lc 'source /opt/ros/noetic/setup.bash && source /ego_ws/ego/devel/setup.bash && export ROS_MASTER_URI=http://localhost:11311 && rosparam get /ego_planner_node/fsm/waypoint_num'
docker exec <egoID> bash -lc '... && timeout 5 rostopic echo -n 1 /planning/pos_cmd'
docker exec <egoID> bash -lc '... && timeout 5 rostopic echo -n 1 /planning/bspline'
docker logs --tail 60 <egoID>
```

判断「已到终点」还是「卡死」的关键：看 `/planning/pos_cmd` 是否在变。
若 `pos_cmd` 恒定且等于终点 → 正常悬停；若 `pos_cmd` 完全不变但离终点很远 → 卡死。

## 2. takeoff_only（高度起不来）

| 检查 | 期望 | 异常处理 |
|------|------|----------|
| `/mavros/state` 的 `armed` | True | 未解锁：桥接脚本是否完成 OFFBOARD + ARM |
| `/mavros/state` 的 `mode` | OFFBOARD | 不在 OFFBOARD：检查 `pos_cmd_to_px4` 是否在发 setpoint |
| `/mavros/setpoint_raw/local` 频率 | ≥ 2 Hz（实际 50 Hz） | 断流会触发 failsafe |
| 目标高度 | ≥ 0.5 m | 低于 0.5 会被桥接 clamp |

注意：这不是算法参数问题，先修复控制链路，再谈规划调参。

## 3. cruise 但跟踪误差大

按可能性排序：

1. **轨迹过于激进**：`manager/max_vel` / `manager/max_acc` 过大，或 `optimization/lambda_smooth` 过低。
2. **可行性权重不足**：`optimization/lambda_feasibility` 过低，B 样条速度/加速度超限。
3. **坐标系或桥接问题**：`pos_cmd` 与实际位置存在固定偏移（观察 `cmd_*` 与 `x/y/z` 的差值是否恒定）。
4. **控制延迟**：实际轨迹整体滞后于指令，误差随速度增大而增大。

若误差呈「恒定偏移」而非「滞后」，优先怀疑坐标系；若误差随速度增长，优先怀疑动力学超限。

## 4. collision / safety_violations 非 0

1. 看 `walls` 字段定位是哪一面墙：`wallA`（x=2.5）或 `wallB`（y=2.5）。
2. 两墙内拐角在 (2.5, 2.5)，切角是最常见原因。
3. 处理顺序：先增大 `grid_map/obstacles_inflation`，再增大 `optimization/lambda_collision`，最后才考虑降速。

## 5. 判定流程速查

```
采样 →
  no_data        → 查容器 / ROS master / 节点
  takeoff_only   → 查 armed / OFFBOARD / setpoint
  hover          → 查任务是否结束 / 航点数量 / 是否闭环 / FSM 状态
  cruise + 高误差 → 先看误差是「滞后」还是「恒定偏移」，再调平滑/限速
  collision      → 先加膨胀，再加碰撞权重，最后降速
```

## 绝对不要做的事

- 不要为了「让飞行器动起来」把 `fsm/waypoint_num` 改成 1。
- 不要修改 `fsm/flight_type`（2 = PRESET 航点模式）。
- 不要在 `hover` 窗口下得出「跟踪误差下降 = 优化成功」的结论。
- 不要用 `optimization/max_vel = 0` 之类的极端值试探；参数有合理区间，见 `04-patch-recipes`。

# 故障案例库

按「现象 → 根因 → 修复 → 教训」记录本项目真实踩过的坑。新坑请追加到 `cases/auto-cases.md`（Agent 也会自动沉淀）。

## C01 飞行器一直悬停不动（单航点）

- **现象**：`/planning/pos_cmd` 恒定、`travel_m≈0`，但无人机已在空中。
- **根因**：补丁把 `fsm/waypoint_num` 改成了 1，任务只剩一个航点，飞到后自然悬停。
- **修复**：恢复为 `$(arg point_num)`（launch 注入 4 个航点）。
- **教训**：`fsm/waypoint_num` 是任务结构参数，不是调参对象；排查「不动」先看航点数量。

## C02 飞到第一个航点就停（航点闭环）

- **现象**：明明有 5 个航点，无人机到第一个点后不再前进。
- **根因**：最后一个航点坐标与第一个相同（都是 `(0,0,1)`）。FSM 的 `end_pt_` 取最后一个航点，
  `near end` 判定在首点就成立，提前结束。
- **修复**：航点改为开环（删除重复的末点，`point_num=4`）。
- **教训**：PRESET 航点必须开环，末点不要等于首点。

## C03 「跟踪误差 0.63 → 0.01」的假改善

- **现象**：补丁后指标大幅变好，但无人机只是在终点悬停。
- **根因**：旧指标没有相位区分，悬停时 `odom≈pos_cmd`，误差自然接近 0。
- **修复**：v1.1 起主指标只在 `cruise` 相位统计，并输出 `phase_summary` / `_flight_state`。
- **教训**：比较必须在同一相位；`hover` 数据不参与优化结论。

## C04 Agent 误判「飞行器在爬行」

- **现象**：Agent 反复说「轨迹是直线、点几乎不变、可能在爬」，进而乱调参。
- **根因**：旧 `run_algorithm` 固定只取 12 帧 `pos_cmd`（约 0.12 s），且无时间戳、无 z、无实际位置。
- **修复**：v1.1 改为 10 Hz、3–15 s 的真实时序（含实际位置/速度/指令/误差/相位）。
- **教训**：观测分辨率不足会让 Agent 产生幻觉式诊断；先修观测，再谈调参。

## C05 把 `optimization/max_vel` 当无效参数

- **现象**：知识库曾标注该参数「ego-planner 不读取」，导致 Agent 不敢调、或改错方向。
- **根因**：早期只核对了 `manager/*`，漏看了 `bspline_optimizer.cpp` 的可行性惩罚。
- **事实**：`optimization/max_vel` / `optimization/max_acc` **会被优化器读取并用于越界惩罚**；
  真正无效的是 `bspline/limit_vel` / `bspline/limit_acc` / `bspline/limit_ratio`（源码未读取）与
  `manager/max_jerk`（读入但未使用）。
- **修复**：本知识库 v2 已更正，详见 `03-parameter-map`。
- **教训**：参数有效性必须对照源码，不能凭命名或旧笔记推断。

## C06 补丁写了但不生效

- **现象**：`patch_algorithm` 返回 `patched`，但指标毫无变化。
- **根因**：参数文件在启动时加载，未重启 ego 容器。
- **修复**：补丁后 `docker restart uavsa-ego4`，重启会重新触发 PRESET 任务。
- **教训**：参数补丁 = 写文件 + 重启；两者缺一不可。

## C07 重启 ego 后容器直接退出

- **现象**：执行 `docker exec ... pkill roslaunch` 后容器变成 Exited。
- **根因**：ego 容器的 entrypoint 是前台 `roslaunch`，PID 1 退出即容器退出。
- **修复**：用 `docker restart <容器ID>`，让 entrypoint 重新拉起 mock_cloud、桥接与规划链。
- **教训**：不要在 ego 容器里杀 roslaunch。

## C08 无人机物理趴地无法起飞（历史）

- **现象**：MAVROS 进入 OFFBOARD 但无人机不动，电机推力不足。
- **根因**：`pos_cmd_to_px4.py` 手动做了一次 ENU→NED 取反，MAVROS `setpoint_raw/local` 又自动转换一次，
  高度被二次取反为负。
- **修复**：桥接直接发布 ENU 位置与 `FRAME_LOCAL_NED`，由 MAVROS 完成转换。
- **教训**：坐标转换只做一次；排查时先看 `setpoint_raw/local` 的 z 符号。

## C09 `setpoint_holder` 启动失败（历史）

- **现象**：ego 重启瞬间 `pos_cmd` 断流，PX4 触发「no offboard」failsafe。
- **根因**：防断流脚本依赖 `quadrotor_msgs`，在 sim 容器内不可用。
- **修复**：改用 `rospy.AnyMsg` 订阅 `/planning/pos_cmd`，只判断新鲜度。
- **教训**：跨容器脚本尽量减少消息类型依赖。

## C10 知识库双目录漂移

- **现象**：同一份 `egoplanner-cheatsheet.md` 在 `shared/knowledge` 与 `docker1/shared/knowledge` 内容不同，
  Docker 模式读到旧版。
- **根因**：`.env` 的 `SHARED_DIR=./shared` 是相对路径，按启动目录解析，导致本地与 Docker 指向不同目录。
- **修复**：v2 起 `SHARED_DIR` 相对路径统一按仓库根解析；`docker1/shared` 改为指向 `../shared` 的链接。
- **教训**：共享目录必须单一事实源。

## C11 API Key 失效导致「没有思考过程」

- **现象**：GUI 立即结束，事件流只有 `start` + 一条 `LLM 循环异常：401` 日志，随后是基线循环。
- **根因**：LLM Key 过期/无效，Agent 捕获异常后回退到确定性基线。
- **修复**：更新 `.env` / GUI 设置中的 Key，并重启服务。
- **教训**：看到「思考」全是写死的固定句，先查 401 与 Key。

## C12 切内拐角导致碰撞（当前基线仍存在）

- **现象**：`collision_count=1~2`、`safety_violations=1~2`，`walls` 指向 wallA/wallB。
- **根因**：航点 `(5,0) → (0,5)` 的直线正好穿过两墙交点 `(2.5, 2.5)`，规划轨迹贴角切过。
- **处理**：按 R3 配方先增大 `grid_map/obstacles_inflation`，再增大 `optimization/lambda_collision`。
- **教训**：碰撞不一定表现为「撞墙停下」，几何贴角也会被计入；先看 `walls` 定位。

## C13 巡航跟踪误差偏大（当前基线仍存在）

- **现象**：真实集群实测 cruise `tracking_error_m ≈ 0.64–0.88`，`smoothness ≈ 0.41–0.51`。
- **可能原因**：`lambda_smooth` 偏低、`max_acc` 偏大、或轨迹本身过于激进。
- **处理**：按 R1/R2 配方调 `optimization/lambda_smooth` 与 `manager/max_acc`。
- **教训**：先建立基线（不改参数跑一轮），再评估补丁是否真的改善。
